"""The extract stage with a fake model returning fixture output, and the grounding check on its own."""

from functools import partial
from pathlib import Path

import httpx
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import client as ai
from app.db.models import AiCall, Contractor, Fact, RawResponse, Run, StageRun
from app.pipeline.extract import ContractorFacts, FoundedYear, Item, Owner, extract, ground
from app.settings import Settings
from app.sources.gaf_profile import parse_profile

FIXTURES = Path(__file__).parent / "fixtures"
ABOUT = parse_profile((FIXTURES / "gaf_profile_1113654.html").read_text(encoding="utf-8"))["about_text"]
HOMEPAGE = (FIXTURES / "homepage_1113654.html").read_text(encoding="utf-8")
ANSWER_JSON = (FIXTURES / "facts_1113654.json").read_text(encoding="utf-8")  # 13 items, 1 of them invented
ANSWER = ContractorFacts.model_validate_json(ANSWER_JSON)
PROFILE_URL = "https://www.gaf.com/en-us/roofing-contractors/residential/usa/nj/wayne/matute-roofing-1113654"
# _env_file=None: never read the developer's .env. The key only ever reaches a mock transport.
SETTINGS = Settings(
    _env_file=None, database_url="unused", coveo_org_id="test-org", coveo_api_key="test-key", gemini_api_key="test-key"
)


def normalize(text: str) -> str:
    """Lowercase, with whitespace collapsed: how the grounding check compares text."""
    return " ".join(text.lower().split())


def add_contractors(session: Session) -> None:
    """Add Matute Roofing, with About text and a saved homepage, and Golovin Roofing, with neither."""
    run = Run(territory_zip="10013", radius_miles=25)
    session.add(run)
    session.flush()
    session.add_all(
        [
            Contractor(
                gaf_id="1113654",
                name="Matute Roofing",
                about_text=ABOUT,
                profile_url=PROFILE_URL,
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Contractor(gaf_id="7158181", name="Golovin Roofing LLC", first_seen_run=run.id, last_seen_run=run.id),
        ]
    )
    session.flush()
    session.add(
        RawResponse(
            run_id=run.id,
            contractor_id="1113654",
            source="contractor_website",
            url="https://matuteroofing.com/",
            status_code=200,
            body=HOMEPAGE,
            content_hash="0" * 64,
        )
    )
    session.commit()


def test_extract_stores_grounded_facts_and_replaces_them(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    add_contractors(session)
    inputs: list[str] = []
    answers = [ANSWER, ANSWER, ContractorFacts(service_areas=[Item(value="Wayne, NJ", evidence="our home base in Wayne, NJ")])]

    def fake_generate(
        session: Session,
        settings: Settings,
        prompt_name: str,
        input_text: str,
        output_model: type[ContractorFacts],
        *,
        run: StageRun,
        contractor_id: str | None = None,
    ) -> ContractorFacts:
        inputs.append(input_text)
        return answers.pop(0)

    monkeypatch.setattr(ai, "generate", fake_generate)

    assert extract(session, SETTINGS) == 12  # the invented quote is dropped

    run = session.scalars(select(StageRun)).one()
    assert (run.stage, run.status, run.model) == ("extract", "finished", SETTINGS.gemini_model)
    assert {name: run.totals[name] for name in ["contractors with text", "About text and homepage", "facts kept", "grounding drops"]} == {
        "contractors with text": 1,
        "About text and homepage": 1,
        "facts kept": 12,
        "grounding drops": 1,
    }

    assert len(inputs) == 1  # Golovin has no About text or homepage, so no call
    assert ABOUT in inputs[0]
    assert "Over 20 years serving North Jersey" in inputs[0]  # the homepage's visible text...
    assert "dataLayer" not in inputs[0]  # ...without its scripts
    facts = {fact.value: fact for fact in session.scalars(select(Fact))}
    assert "Solar panels" not in facts
    assert (facts["Roofing"].source, facts["Roofing"].source_url) == ("about_text", PROFILE_URL)
    assert (facts["Metal roofing"].source, facts["Metal roofing"].source_url) == ("homepage", "https://matuteroofing.com/")
    assert {(fact.model, fact.prompt_version) for fact in facts.values()} == {(SETTINGS.gemini_model, "extract_facts_v1")}
    source_texts = {"about_text": normalize(ABOUT), "homepage": normalize(BeautifulSoup(HOMEPAGE, "html.parser").get_text(" "))}
    assert all(normalize(fact.evidence) in source_texts[fact.source] for fact in facts.values())

    # A rerun replaces the facts instead of adding to them.
    extract(session, SETTINGS)
    assert session.scalar(select(func.count()).select_from(Fact)) == 12

    # When the input changes, the new answer's facts replace the old ones.
    session.get(Contractor, "1113654").about_text = "Matute Roofing is based in Wayne, NJ."
    session.commit()
    extract(session, SETTINGS)
    assert inputs[2] != inputs[0]
    assert [(fact.field, fact.value) for fact in session.scalars(select(Fact))] == [("service_areas", "Wayne, NJ")]


def test_extract_logs_its_calls_and_a_rerun_makes_none(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    add_contractors(session)
    requests: list[httpx.Request] = []

    def gemini(request: httpx.Request) -> httpx.Response:
        """A fake Gemini API that answers with the fixture's facts."""
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "candidates": [{"content": {"role": "model", "parts": [{"text": ANSWER_JSON}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 1500, "candidatesTokenCount": 400},
            },
        )

    # The real AI client, talking to the fake API.
    monkeypatch.setattr(ai, "generate", partial(ai.generate, transport=httpx.MockTransport(gemini)))
    monkeypatch.setattr(ai, "_last_request_at", 0.0)  # no pacing pause before the first request

    extract(session, SETTINGS)
    extract(session, SETTINGS)

    assert len(requests) == 1  # the second run is answered from the cache
    first, second = session.scalars(select(StageRun).order_by(StageRun.id)).all()
    assert [first.totals[name] for name in ["requests to the model", "ok", "cache hits", "facts kept", "grounding drops"]] == [1, 1, 0, 12, 1]
    assert [second.totals[name] for name in ["requests to the model", "ok", "cache hits", "facts kept", "grounding drops"]] == [0, 0, 1, 12, 1]
    call = session.scalars(select(AiCall).where(AiCall.run_id == first.id)).one()
    assert (call.stage, call.contractor_id, call.prompt_name, call.model) == (
        "extract",
        "1113654",
        "extract_facts_v1",
        SETTINGS.gemini_model,
    )
    assert (call.outcome, call.input_tokens, call.output_tokens) == ("ok", 1500, 400)


def test_grounding_drops_an_invented_quote() -> None:
    facts = ContractorFacts(
        founded_year=FoundedYear(value=1998, evidence="Founded in 1998"),
        services=[
            Item(value="Roof repair", evidence="we   REPAIR roofs"),  # case and spacing don't matter
            Item(value="Solar", evidence="we install solar panels"),  # invented: in neither text
        ],
        service_areas=[Item(value="Everywhere", evidence=" ")],  # an empty quote would match any text
        owner_names=[Owner(name="Dana Reyes", role="Owner", evidence="Dana Reyes, Owner")],
    )
    texts = {"about_text": "Founded in 1998 by Dana Reyes, Owner.", "homepage": "Since then we repair roofs across Morris County."}

    rows, dropped = ground(facts, texts)

    assert rows == [
        {"field": "founded_year", "value": "1998", "evidence": "Founded in 1998", "source": "about_text"},
        {"field": "services", "value": "Roof repair", "evidence": "we   REPAIR roofs", "source": "homepage"},
        {"field": "owner_names", "value": "Dana Reyes (Owner)", "evidence": "Dana Reyes, Owner", "source": "about_text"},
    ]
    assert dropped == 2
