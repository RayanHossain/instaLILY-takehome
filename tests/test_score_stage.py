"""The score stage on a migrated test database, and the services' totals and ranking by preset."""

from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Contractor, Fact, Run, Score
from app.pipeline.score import score
from app.services.leads import get_lead, list_leads
from app.settings import load_territory

TERRITORY = load_territory()
YEAR = 2026


def add_fact(session: Session, contractor_id: str, field: str, value: str, evidence: str) -> None:
    """Add one extracted fact, as the extract stage would."""
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


def add_contractors(session: Session) -> None:
    """A big established account 20 miles out, a new business at the branch, and one from an older discover.

    "big" gives its founding year on its GAF profile; "new" only in its extracted facts.
    """
    old_run, latest_run = Run(territory_zip="10013", radius_miles=25), Run(territory_zip="10013", radius_miles=25)
    session.add_all([old_run, latest_run])
    session.flush()
    big: dict[str, Any] = {
        "name": "Big Roofing",
        "certifications": ["President's Club - Award", "GAF Master Elite® - Certification"],
        "review_count": 312,
        "rating": 4.8,
        "in_business_since": 1990,
        "lat": TERRITORY["lat"] + 0.29,  # about 20 miles north
        "lng": TERRITORY["lng"],
    }
    new: dict[str, Any] = {
        "name": "New Roofing",
        "certifications": ["GAF Certified Plus™ - Certification"],
        "review_count": 3,
        "rating": 5.0,
        "lat": TERRITORY["lat"],
        "lng": TERRITORY["lng"],
    }
    session.add_all(
        [
            Contractor(gaf_id="big", **big, first_seen_run=latest_run.id, last_seen_run=latest_run.id),
            Contractor(gaf_id="new", **new, first_seen_run=latest_run.id, last_seen_run=latest_run.id),
            Contractor(gaf_id="gone", name="Gone Roofing", first_seen_run=old_run.id, last_seen_run=old_run.id),
        ]
    )
    session.flush()
    add_fact(session, "big", "other_trades", "Siding", "We also install siding")
    add_fact(session, "new", "founded_year", "2025", "Founded in 2025")
    session.commit()


def test_score_scores_the_latest_discover_and_a_rerun_changes_nothing(session: Session) -> None:
    add_contractors(session)

    assert score(session, YEAR) == 2

    scores = {row.contractor_id: row for row in session.scalars(select(Score))}
    assert set(scores) == {"big", "new"}  # "gone" isn't in the latest discover
    assert (scores["big"].value, scores["big"].winnability, scores["big"].stability) == (91.0, 30.0, 90.0)
    assert (scores["new"].value, scores["new"].winnability, scores["new"].stability, scores["new"].distance) == (53.0, 90.0, 50.0, 100.0)
    years = {contractor_id: row.reasons["winnability"][0] for contractor_id, row in scores.items()}
    assert (years["big"]["founded_from"], years["new"]["founded_from"]) == ("the GAF profile", "its extracted facts")
    assert years["new"]["input"] == "1 year in business (founded 2025, per its extracted facts)"
    assert scores["new"].flags == [{"flag": "New business", "kind": "opportunity", "reason": "founded 2025"}]
    assert scores["big"].flags == []
    before = {row.contractor_id: (row.value, row.winnability, row.stability, row.distance, row.flags, row.reasons) for row in scores.values()}

    score(session, YEAR)
    session.expire_all()

    after = {row.contractor_id: (row.value, row.winnability, row.stability, row.distance, row.flags, row.reasons) for row in session.scalars(select(Score))}
    assert after == before


def test_presets_rank_the_same_contractors_differently(session: Session) -> None:
    add_contractors(session)
    score(session, YEAR)

    big_accounts = list_leads(session, preset="Big accounts", sort="total")
    quick_wins = list_leads(session, preset="Quick wins", sort="total")

    assert [lead.gaf_id for lead in big_accounts] == ["big", "new"]
    assert [lead.gaf_id for lead in quick_wins] == ["new", "big"]
    assert big_accounts[0].score.preset == "Big accounts"
    assert [lead.gaf_id for lead in list_leads(session)] == ["new", "big"]  # the UI's sort is still nearest first


def test_get_lead_returns_the_total_flags_and_reasons(session: Session) -> None:
    add_contractors(session)
    assert get_lead(session, "new").score is None  # not scored yet

    score(session, YEAR)
    lead = get_lead(session, "new", preset="Quick wins")

    assert lead.score.total == 83.5  # (53*15 + 90*45 + 50*10 + 100*30) / 100, rounded to one decimal
    assert lead.score.flags[0]["flag"] == "New business"
    assert [signal["input"] for signal in lead.reasons["value"]] == ["3 reviews", "Certified Plus", "no other trades found"]
    assert get_lead(session, "new").score.preset == "Balanced"  # the default
    with pytest.raises(ValueError, match="Unknown preset"):
        get_lead(session, "new", preset="Nope")
