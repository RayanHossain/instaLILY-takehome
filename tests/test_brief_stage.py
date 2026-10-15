"""The brief stage against a fake Gemini API: which leads it picks, what it skips, and how it checks briefs."""

import json
import time
from functools import partial
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import scoring
from app.ai import client as ai
from app.db.models import AiCall, Contractor, ContractorBrief, Fact, Run, StageRun
from app.pipeline.brief import brief, lead_input, pick_leads
from app.pipeline.score import score
from app.services.leads import get_lead
from app.settings import Settings, load_selling_points, load_territory

TERRITORY = load_territory()
# _env_file=None: never read the developer's .env. The key only ever reaches a mock transport.
SETTINGS = Settings(
    _env_file=None,
    database_url="unused",
    coveo_org_id="test-org",
    coveo_api_key="test-key",
    gemini_api_key="test-key",
    top_leads_per_preset=1,
)
VALID_BRIEF: dict[str, Any] = {
    "why_this_contractor": "It installs roofs near the branch.",
    "first_touch": {"opener": "Call to introduce the branch and its stock.", "reason": "It is close by."},
    "follow_ups": [{"step": "Offer introductory pricing on a first order.", "reason": "A low-risk way to start."}],
    "questions": ["What jobs are you bidding next month?", "Which shingle lines do you install most?"],
    "selling_points": ["introductory_pricing"],
    "ask_for": None,
    "cited_fact_ids": [],
}


def add_scored_contractors(session: Session) -> None:
    """Score three contractors: a big established account 20 miles out, a new business at the branch,
    and a steady mid-size one 10 miles out with no facts.

    Top 1 by preset: Balanced and Quick wins pick "new", Big accounts picks "big".
    Top 2 adds "mid" (second under Balanced and Quick wins).
    """
    run = Run(territory_zip="10013", radius_miles=25)
    session.add(run)
    session.flush()
    seen = {"first_seen_run": run.id, "last_seen_run": run.id, "lng": TERRITORY["lng"], "city": "Wayne", "state": "NJ"}
    session.add_all(
        [
            Contractor(
                gaf_id="big",
                name="Big Roofing",
                certifications=["President's Club - Award"],
                review_count=312,
                rating=4.8,
                in_business_since=1990,
                lat=TERRITORY["lat"] + 0.29,
                postal_code="07470",
                **seen,
            ),
            Contractor(
                gaf_id="new",
                name="New Roofing",
                certifications=["GAF Certified Plus™ - Certification"],
                review_count=3,
                rating=5.0,
                lat=TERRITORY["lat"],
                postal_code="10013",
                **seen,
            ),
            Contractor(
                gaf_id="mid",
                name="Mid Roofing",
                certifications=["GAF Certified™ - Certification"],
                review_count=40,
                rating=4.6,
                in_business_since=2015,
                lat=TERRITORY["lat"] + 0.145,
                postal_code="07470",
                **seen,
            ),
        ]
    )
    session.flush()
    for contractor_id, field, value, evidence in [
        ("big", "other_trades", "Siding", "We also install siding"),
        ("big", "services", "Roof replacement", "full roof replacements"),
        ("big", "owner_names", "Dana Reyes (Owner)", "Dana Reyes, owner"),
        ("new", "founded_year", "2025", "Founded in 2025"),
    ]:
        session.add(
            Fact(
                contractor_id=contractor_id,
                field=field,
                value=value,
                evidence=evidence,
                source="homepage",
                model="test",
                prompt_version="test",
            )
        )
    session.commit()
    score(session, 2026)


def use_fake_gemini(monkeypatch: pytest.MonkeyPatch, *briefs: dict[str, Any]) -> list[httpx.Request]:
    """Run the real AI client against a fake Gemini API that answers with these briefs in turn (the last repeats).

    Returns the list the requests are kept in.
    """
    requests: list[httpx.Request] = []
    answers = list(briefs)

    def answer(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        text = json.dumps(answers.pop(0) if len(answers) > 1 else answers[0])
        return httpx.Response(200, json={"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}]})

    monkeypatch.setattr(ai, "generate", partial(ai.generate, transport=httpx.MockTransport(answer)))
    monkeypatch.setattr(ai, "_last_request_at", 0.0)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)  # no pacing pauses
    return requests


def outcomes(session: Session, contractor_id: str) -> list[str]:
    """The outcomes of the AI calls for one contractor, in order."""
    return [call.outcome for call in session.scalars(select(AiCall).where(AiCall.contractor_id == contractor_id).order_by(AiCall.id))]


def test_the_leads_are_the_union_of_each_presets_top_n(session: Session) -> None:
    add_scored_contractors(session)

    assert pick_leads(session, 1) == ["new", "big"]
    assert pick_leads(session, 2) == ["new", "mid", "big"]


def test_a_lead_input_has_its_facts_and_selling_points_but_never_its_standing(session: Session) -> None:
    add_scored_contractors(session)

    big = lead_input(session, "big", load_selling_points())

    assert 'other_trades: Siding (quote: "We also install siding")' in big.text
    assert list(big.matched) == ["one_stop_supply", "full_gaf_systems", "rooftop_delivery", "credit_terms", "introductory_pricing"]
    assert big.owners == ["Dana Reyes (Owner)"]
    assert len(big.fact_ids) == 3
    for word in ["total", "rank", "Balanced", "Big accounts", "Quick wins"]:
        assert word not in big.text


def test_a_rerun_makes_no_calls_and_a_weight_change_briefs_only_the_newcomer(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    add_scored_contractors(session)
    requests = use_fake_gemini(monkeypatch, VALID_BRIEF)

    assert brief(session, SETTINGS) == 2  # "new" and "big"
    assert brief(session, SETTINGS) == 0
    assert len(requests) == 2  # the rerun made no AI calls
    rerun = session.scalars(select(StageRun).order_by(StageRun.id.desc())).first()
    assert (rerun.totals["leads unchanged"], rerun.totals["requests to the model"]) == (2, 0)

    # Weighting stability alone puts "mid" (rated 4.6, nearer than "big") on top of Quick wins.
    config = scoring.load_scoring_config()
    config.presets["Quick wins"] = scoring.Preset(value=0, winnability=0, stability=100, distance=0)
    monkeypatch.setattr(scoring, "load_scoring_config", lambda: config)

    assert brief(session, SETTINGS) == 1  # only the newcomer
    assert len(requests) == 3
    assert {row.contractor_id for row in session.scalars(select(ContractorBrief))} == {"new", "big", "mid"}


def test_a_brief_failing_its_checks_gets_one_retry_then_is_recorded(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    add_scored_contractors(session)
    unknown_fact = VALID_BRIEF | {"cited_fact_ids": [999]}
    mentions_rank = VALID_BRIEF | {"why_this_contractor": "It is ranked first under every preset."}
    # "new" is briefed first: its first answer cites an unknown fact, its retry is valid. "big" mentions its rank twice.
    requests = use_fake_gemini(monkeypatch, unknown_fact, VALID_BRIEF, mentions_rank)

    assert brief(session, SETTINGS) == 1

    assert outcomes(session, "new") == ["invalid", "ok after a retry"]
    assert "cited_fact_ids [999] are not among the facts given" in json.loads(requests[1].content)["contents"][2]["parts"][0]["text"]
    assert outcomes(session, "big") == ["invalid", "invalid"]
    assert [row.contractor_id for row in session.scalars(select(ContractorBrief))] == ["new"]
    run = session.scalars(select(StageRun)).one()
    assert (run.totals["briefs written"], run.totals["leads skipped"]) == (1, 1)


def test_a_lead_with_few_facts_gets_a_valid_brief(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    add_scored_contractors(session)
    use_fake_gemini(monkeypatch, VALID_BRIEF)

    assert "No facts are known about this contractor" in lead_input(session, "mid", load_selling_points()).text
    brief(session, SETTINGS.model_copy(update={"top_leads_per_preset": 2}))

    mid = get_lead(session, "mid")
    assert mid.brief is not None
    assert mid.brief.questions == VALID_BRIEF["questions"]
    assert get_lead(session, "big").brief.cited_fact_ids == []
