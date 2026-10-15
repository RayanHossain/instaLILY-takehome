"""The Streamlit page, run headless against a temporary database."""

from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from streamlit.testing.v1 import AppTest

from app.db.models import Contractor, ContractorBrief, Fact, Rep, Run, Score
from app.settings import load_territory

ENTRY_POINT = Path(__file__).parent.parent / "streamlit_app.py"  # what `streamlit run` runs
TERRITORY = load_territory()


@pytest.fixture
def app(engine: Engine, session: Session, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    """The page, not yet run, on a database with three scored contractors.

    Balanced ranks them Alpha, Beta, Gamma; Quick wins ranks them Beta, Gamma, Alpha.
    Alpha has a brief; Gamma has none, but has one fact.
    """
    run = Run(territory_zip="10013", radius_miles=25)
    session.add(run)
    session.flush()
    shared = {"certifications": ["GAF Master Elite® - Certification"], "first_seen_run": run.id, "last_seen_run": run.id}
    for gaf_id, name, lat_offset in [("1", "Alpha Roofing", 0.0), ("2", "Beta Roofing", 0.05), ("3", "Gamma Roofing", 0.1)]:
        session.add(Contractor(gaf_id=gaf_id, name=name, lat=TERRITORY["lat"] + lat_offset, lng=TERRITORY["lng"], **shared))
    session.flush()
    for gaf_id, value, winnability, distance in [("1", 90, 20, 100), ("2", 20, 95, 80), ("3", 60, 60, 60)]:
        session.add(
            Score(
                contractor_id=gaf_id,
                value=value,
                winnability=winnability,
                stability=50,
                distance=distance,
                flags=[],
                reasons={},
                rules_version="test",
            )
        )
    brief = {
        "why_this_contractor": "Alpha replaces roofs across Brooklyn.",
        "first_touch": {"opener": "Saw your slate work on Atlantic Ave.", "reason": "It names a job they're proud of."},
        "follow_ups": [{"step": "Send the rooftop delivery sheet.", "reason": "They work on tight streets."}],
        "questions": ["What's next on your board?", "Who supplies you now?"],
        "selling_points": [],
        "cited_fact_ids": [],
    }
    session.add(ContractorBrief(contractor_id="1", content=brief, input_hash="0" * 64, model="test", prompt_version="test"))
    session.add(
        Fact(
            contractor_id="3",
            field="services",
            value="Slate roof repair",
            evidence="We repair slate roofs.",
            source="homepage",
            source_url="https://gamma.example",
            model="test",
            prompt_version="test",
        )
    )
    session.commit()
    # Environment variables win over .env, so the app opens the test database, never data/leads.db.
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    monkeypatch.setenv("COVEO_ORG_ID", "test-org")
    monkeypatch.setenv("COVEO_API_KEY", "test-key")
    return AppTest.from_file(str(ENTRY_POINT), default_timeout=30)


def shown_lead(app: AppTest) -> str:
    """The name in the detail panel's header."""
    return app.subheader[0].value


def test_page_lists_the_leads_and_selects_the_first(app: AppTest) -> None:
    app.run()

    assert not app.exception
    assert len(app.dataframe[0].value) == 3
    assert shown_lead(app) == "Alpha Roofing"
    assert [tab.label for tab in app.tabs] == ["Why", "Brief", "Notes"]


def test_the_selected_lead_survives_a_filter_change(app: AppTest) -> None:
    app.session_state["lead_id"] = "3"
    app.run()
    assert shown_lead(app) == "Gamma Roofing"

    # Gamma moves from the third row to the first; the panel stays on Gamma.
    app.sidebar.text_input[0].input("gamma").run()
    assert shown_lead(app) == "Gamma Roofing"
    assert app.session_state["lead_table"]["selection"]["rows"] == [0]

    app.sidebar.text_input[0].input("").run()
    assert shown_lead(app) == "Gamma Roofing"
    assert app.session_state["lead_table"]["selection"]["rows"] == [2]


def test_a_lead_filtered_out_hands_the_panel_to_the_top_lead(app: AppTest) -> None:
    app.session_state["lead_id"] = "3"
    app.run()

    app.sidebar.text_input[0].input("beta").run()

    assert shown_lead(app) == "Beta Roofing"


def test_the_selected_lead_survives_a_preset_switch_that_re_sorts_the_table(app: AppTest) -> None:
    app.session_state["lead_id"] = "3"
    app.run()
    assert app.session_state["lead_table"]["selection"]["rows"] == [2]  # Balanced: Alpha, Beta, Gamma

    app.segmented_control(key="preset").set_value("Quick wins").run()

    assert shown_lead(app) == "Gamma Roofing"
    assert app.session_state["lead_table"]["selection"]["rows"] == [1]  # Quick wins: Beta, Gamma, Alpha


def test_a_link_with_a_preset_opens_the_page_ranked_by_it(app: AppTest) -> None:
    app.query_params["preset"] = "Quick wins"
    app.run()

    assert app.segmented_control(key="preset").value == "Quick wins"
    assert shown_lead(app) == "Beta Roofing"  # the top lead under Quick wins


def test_a_lead_without_a_brief_shows_brief_none_and_its_facts(app: AppTest) -> None:
    app.session_state["lead_id"] = "3"
    app.run()

    assert app.tabs[1].label == "Brief (none)"
    assert any("Slate roof repair" in markdown.value for markdown in app.tabs[1].markdown)


def test_a_lead_with_a_brief_shows_its_opener(app: AppTest) -> None:
    app.run()  # Alpha, the top lead, is selected

    assert app.tabs[1].label == "Brief"
    assert any("Atlantic Ave" in markdown.value for markdown in app.tabs[1].markdown)


def save_status(app: AppTest, status: str, note: str) -> None:
    """Fill in the Notes tab's form and save it."""
    gaf_id = app.session_state["lead_id"]
    app.segmented_control(key=f"status_{gaf_id}").set_value(status)
    app.text_area(key=f"note_{gaf_id}").set_value(note)
    app.form_submit_button[0].click().run()


def test_the_selected_lead_survives_a_saved_status(app: AppTest) -> None:
    app.session_state["lead_id"] = "3"
    app.run()
    app.segmented_control(key="status_group").set_value("All").run()

    save_status(app, "Contacted", "Left a voicemail.")

    assert shown_lead(app) == "Gamma Roofing"
    assert [toast.value for toast in app.toast] == ["Saved: Gamma Roofing"]
    assert any("Left a voicemail" in markdown.value for markdown in app.tabs[2].markdown)


def test_a_save_that_moves_the_lead_out_of_the_filter_moves_the_panel_to_the_top_lead(app: AppTest) -> None:
    app.session_state["lead_id"] = "3"
    app.run()  # To contact: every lead is New

    save_status(app, "Considering us", "Asked for a quote.")

    assert shown_lead(app) == "Alpha Roofing"
    assert [toast.value for toast in app.toast] == ["Saved: Gamma Roofing is now In progress"]
    assert len(app.dataframe[0].value) == 2


def test_the_preset_is_saved_for_the_rep_and_restored_next_visit(app: AppTest, session: Session) -> None:
    app.run()
    assert app.sidebar.caption[0].value == "Signed in as **Demo Rep**"

    app.segmented_control(key="preset").set_value("Big accounts").run()

    session.expire_all()
    assert session.get(Rep, 1).preset == "Big accounts"
    next_visit = AppTest.from_file(str(ENTRY_POINT), default_timeout=30).run()
    assert next_visit.segmented_control(key="preset").value == "Big accounts"
