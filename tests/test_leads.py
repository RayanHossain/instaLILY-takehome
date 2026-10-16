"""The lead services, against a migrated temporary database."""

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.db.models import Contractor, ContractorBrief, Fact, Run, Score
from app.services.leads import LeadRow, briefed_top_leads, get_lead, list_leads, tier, top_leads
from app.settings import load_territory
from app.sources import coveo

COVEO_PAGE = Path(__file__).parent / "fixtures" / "coveo_page.json"
TERRITORY = load_territory()

# GAF's labels, as they appear in the search results.
CERTIFIED = "GAF Certified™ - Certification"
CERTIFIED_PLUS = "GAF Certified Plus™ - Certification"
MASTER_ELITE = "GAF Master Elite® - Certification"
PRESIDENTS_CLUB = "President's Club - Award"


def make_run(session: Session) -> Run:
    """Add a discover run."""
    run = Run(territory_zip="10013", radius_miles=25)
    session.add(run)
    session.flush()
    return run


def add_contractor(session: Session, run: Run, gaf_id: str, **columns: Any) -> None:
    """Add a Certified contractor last seen in run, at the territory center unless columns say otherwise."""
    values = {
        "name": f"Roofer {gaf_id}",
        "lat": TERRITORY["lat"],
        "lng": TERRITORY["lng"],
        "certifications": [CERTIFIED],
        "first_seen_run": run.id,
        "last_seen_run": run.id,
    }
    session.add(Contractor(gaf_id=gaf_id, **(values | columns)))
    session.flush()


def add_score(session: Session, gaf_id: str, points: float, flags: list[dict[str, str]] | None = None, **reasons: Any) -> None:
    """Score a contractor with the same points in every component, and the given reasons."""
    session.add(
        Score(
            contractor_id=gaf_id,
            value=points,
            winnability=points,
            stability=points,
            distance=points,
            flags=flags or [],
            reasons=reasons,
            rules_version="test",
        )
    )
    session.flush()


# A valid brief's content, as the brief stage stores it.
BRIEF = {
    "why_this_contractor": "It does replacements.",
    "first_touch": {"opener": "Hi.", "reason": "It fits."},
    "follow_ups": [{"step": "Call back.", "reason": "To follow up."}],
    "questions": ["Any jobs?", "When?"],
    "selling_points": [],
    "cited_fact_ids": [],
}


def add_brief(session: Session, gaf_id: str, content: dict[str, Any] = BRIEF) -> None:
    """Store a brief for a contractor."""
    session.add(ContractorBrief(contractor_id=gaf_id, content=content, input_hash="0" * 64, model="test", prompt_version="test"))
    session.flush()


def ids(leads: list[LeadRow]) -> list[str]:
    """The GAF IDs of the leads, in order."""
    return [lead.gaf_id for lead in leads]


def test_distance_matches_coveos_own_and_sorts_nearest_first(session: Session) -> None:
    run = make_run(session)
    results = json.loads(COVEO_PAGE.read_bytes())["results"]
    for result in reversed(results):  # stored farthest first, to show the sort
        session.add(Contractor(**coveo.parse_result(result), first_seen_run=run.id, last_seen_run=run.id))
    session.flush()

    leads = list_leads(session)

    # Coveo measured these from the same territory center when the fixture was saved.
    assert ids(leads) == ["7158181", "1150334", "1138492"]
    assert [lead.distance_miles for lead in leads] == [
        pytest.approx(result["raw"]["distanceinmiles"], abs=0.01) for result in results
    ]


@pytest.mark.parametrize(
    ("certifications", "expected"),
    [
        ([CERTIFIED], "Certified"),
        ([CERTIFIED_PLUS], "Certified Plus"),
        ([MASTER_ELITE], "Master Elite"),
        ([MASTER_ELITE, PRESIDENTS_CLUB], "President's Club"),
        ([], None),
    ],
)
def test_tier_is_the_highest_level_named(certifications: list[str], expected: str | None) -> None:
    assert tier(certifications) == expected


def test_search_matches_the_name_in_any_case(session: Session) -> None:
    run = make_run(session)
    add_contractor(session, run, "1", name="Summit Roofing LLC")
    add_contractor(session, run, "2", name="Top Roofing")

    assert ids(list_leads(session, search="summit")) == ["1"]
    assert sorted(ids(list_leads(session, search=" ROOFING "))) == ["1", "2"]
    assert list_leads(session, search="gutters") == []


def test_search_matches_the_phone_by_digits_only(session: Session) -> None:
    run = make_run(session)
    add_contractor(session, run, "1", name="Summit Roofing", phone="(973) 558-3045")
    add_contractor(session, run, "2", name="A1 Roofing", phone="(201) 466-2534")
    add_contractor(session, run, "3", name="Best Roofing", phone="(718) 111-0000")

    assert ids(list_leads(session, search="9735583045")) == ["1"]
    assert ids(list_leads(session, search="558-3045")) == ["1"]
    # A search with letters only matches names, so "A1" doesn't find Best Roofing's 1s.
    assert ids(list_leads(session, search="A1")) == ["2"]


def test_tier_filter_keeps_only_the_chosen_tiers(session: Session) -> None:
    run = make_run(session)
    add_contractor(session, run, "certified", certifications=[CERTIFIED])
    add_contractor(session, run, "elite", certifications=[MASTER_ELITE])
    add_contractor(session, run, "club", certifications=[MASTER_ELITE, PRESIDENTS_CLUB])

    assert ids(list_leads(session, tiers=["Master Elite"])) == ["elite"]
    assert sorted(ids(list_leads(session, tiers=["Master Elite", "President's Club"]))) == ["club", "elite"]
    assert len(list_leads(session, tiers=[])) == 3


def test_max_miles_keeps_only_contractors_that_close(session: Session) -> None:
    run = make_run(session)
    add_contractor(session, run, "center")
    add_contractor(session, run, "near", lat=TERRITORY["lat"] + 0.1)  # 0.1 degree of latitude is 6.9 miles
    add_contractor(session, run, "unplaced", lat=None, lng=None)

    assert ids(list_leads(session)) == ["center", "near", "unplaced"]  # no coordinates sorts last
    assert ids(list_leads(session, max_miles=7)) == ["center", "near"]
    assert ids(list_leads(session, max_miles=5)) == ["center"]


def test_only_the_latest_discovers_contractors_appear(session: Session) -> None:
    old_run = make_run(session)
    add_contractor(session, old_run, "dropped")
    new_run = make_run(session)
    add_contractor(session, new_run, "current")

    assert ids(list_leads(session)) == ["current"]


def test_get_lead_returns_the_details_or_raises(session: Session) -> None:
    run = make_run(session)
    add_contractor(
        session,
        run,
        "1",
        name="Summit Roofing",
        lat=TERRITORY["lat"] + 0.1,
        street_address="1 Main St, Summit NJ, 07901 USA",
        website_url="https://summit-roofing.example",
        certifications=[MASTER_ELITE, PRESIDENTS_CLUB],
        rating=4.8,
        review_count=120,
        in_business_since=1998,
        enrolled_in_gaf_leads=True,
    )

    lead = get_lead(session, "1")

    assert lead.name == "Summit Roofing"
    assert lead.street_address == "1 Main St, Summit NJ, 07901 USA"
    assert lead.distance_miles == pytest.approx(6.909, abs=0.001)
    assert lead.tier == "President's Club"
    assert lead.certifications == [MASTER_ELITE, PRESIDENTS_CLUB]
    assert lead.about_text is None
    with pytest.raises(LookupError):
        get_lead(session, "no-such-id")


def test_tags_name_only_the_exceptions(session: Session) -> None:
    run = make_run(session)
    add_contractor(session, run, "star", certifications=[MASTER_ELITE])
    add_contractor(session, run, "other")  # plain Certified: no tier tag
    add_score(session, "star", 90)
    add_score(session, "other", 50, flags=[{"flag": "New business", "kind": "opportunity", "reason": "founded 2025"}])

    assert top_leads(session, 1) == {"Balanced": ["star"], "Big accounts": ["star"], "Quick wins": ["star"]}
    tags = {lead.gaf_id: lead.tags for lead in list_leads(session, top_n=1)}
    assert tags == {"star": ["Balanced", "Big accounts", "Quick wins", "Master Elite"], "other": ["New business"]}

    # In every preset's top 2, the other lead carries every preset's name too.
    tags = {lead.gaf_id: lead.tags for lead in list_leads(session, top_n=2)}
    assert tags["other"] == ["Balanced", "Big accounts", "Quick wins", "New business"]


def test_a_preset_tag_names_only_the_presets_whose_top_n_the_lead_is_in(session: Session) -> None:
    run = make_run(session)
    add_contractor(session, run, "big")
    add_contractor(session, run, "quick")
    # Totals: big scores 35 Balanced, 55 Big accounts, 15 Quick wins; quick scores 30, 15, 45.
    for gaf_id, value, winnability in [("big", 100, 0), ("quick", 0, 100)]:
        session.add(
            Score(contractor_id=gaf_id, value=value, winnability=winnability, stability=0, distance=0, flags=[], reasons={}, rules_version="test")
        )
    session.flush()

    tags = {lead.gaf_id: lead.tags for lead in list_leads(session, top_n=1)}

    assert tags == {"big": ["Balanced", "Big accounts"], "quick": ["Quick wins"]}


def test_briefed_top_leads_keeps_the_presets_top_n_that_have_a_brief(session: Session) -> None:
    run = make_run(session)
    for gaf_id, points in [("first", 90), ("unbriefed", 80), ("third", 70), ("outside", 60)]:
        add_contractor(session, run, gaf_id)
        add_score(session, gaf_id, points)
    add_brief(session, "first")
    add_brief(session, "third")
    add_brief(session, "outside")  # written under older rules, when it was in a top N

    leads = briefed_top_leads(session, "Quick wins", top_n=3)

    # unbriefed is in the top 3 but has no brief; outside has a brief but isn't in the top 3.
    assert ids(leads) == ["first", "third"]
    assert leads[0].tags == ["Balanced", "Big accounts", "Quick wins"]


def test_a_brief_shows_only_while_its_lead_is_in_a_top_n(session: Session) -> None:
    run = make_run(session)
    add_contractor(session, run, "star")
    add_contractor(session, run, "fallen")  # briefed under older rules, now out of every top 1
    add_score(session, "star", 90)
    add_score(session, "fallen", 50)
    add_brief(session, "star")
    add_brief(session, "fallen")
    session.add(Fact(contractor_id="fallen", field="services", value="Roof replacement", evidence="We replace roofs.", source="homepage", source_url="https://fallen.example", model="test", prompt_version="test"))
    session.flush()

    star = get_lead(session, "star", top_n=1)
    assert star.brief is not None
    assert star.top_presets == ["Balanced", "Big accounts", "Quick wins"]
    fallen = get_lead(session, "fallen", top_n=1)
    assert fallen.brief is None
    assert fallen.top_presets == []
    assert [(fact.value, fact.quote) for fact in fallen.facts] == [("Roof replacement", "We replace roofs.")]
    assert get_lead(session, "fallen", top_n=2).brief is not None  # back in a top 2
