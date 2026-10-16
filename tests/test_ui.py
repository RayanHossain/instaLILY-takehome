"""The Streamlit page, run headless against a temporary database."""

from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import Button

from app.db.models import Contractor, ContractorBrief, Fact, Rep, Run, Score
from app.services.notes import add_note, lead_notes
from app.settings import load_territory

ENTRY_POINT = Path(__file__).parent.parent / "streamlit_app.py"  # what `streamlit run` runs
ALL_LEADS = "app_pages/all_leads.py"  # the All leads page, relative to ENTRY_POINT
TERRITORY = load_territory()


@pytest.fixture
def app(engine: Engine, session: Session, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    """The app, not yet run, on a database with three scored contractors.

    Balanced ranks them Alpha, Beta, Gamma; Quick wins ranks them Beta, Gamma, Alpha.
    Alpha and Beta have briefs, so they're the Top leads; Gamma has none, but has one fact
    and the only website.
    """
    run = Run(territory_zip="10013", radius_miles=25)
    session.add(run)
    session.flush()
    shared = {"certifications": ["GAF Master Elite® - Certification"], "first_seen_run": run.id, "last_seen_run": run.id}
    for gaf_id, name, lat_offset in [("1", "Alpha Roofing", 0.0), ("2", "Beta Roofing", 0.05), ("3", "Gamma Roofing", 0.1)]:
        session.add(Contractor(gaf_id=gaf_id, name=name, lat=TERRITORY["lat"] + lat_offset, lng=TERRITORY["lng"], **shared))
    session.get(Contractor, "3").website_url = "https://gamma.example"
    for contractor in session.query(Contractor):
        contractor.profile_url = f"https://www.gaf.com/en-us/roofing-contractors/{contractor.gaf_id}"
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
    for gaf_id in ["1", "2"]:
        session.add(ContractorBrief(contractor_id=gaf_id, content=brief, input_hash="0" * 64, model="test", prompt_version="test"))
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
    """The name in the lead's header."""
    return app.main.subheader[0].value


def selected_row(app: AppTest) -> int:
    """The All leads table row the page selected: the row of the outlined name cell, which it also tints."""
    return app.session_state["lead_table"]["selection"]["cells"][0][0]


def open_all_leads(app: AppTest) -> AppTest:
    """Run the app, then open the All leads page. AppTest switches pages only after a first run."""
    return app.run().switch_page(ALL_LEADS).run()


def labelled(app: AppTest, label: str) -> Button:
    """The button with this label."""
    return next(button for button in app.button if button.label == label)


def test_the_landing_page_shows_one_top_lead_with_its_brief(app: AppTest) -> None:
    app.run()

    assert not app.exception
    assert app.header[0].value == "Top leads"
    assert not app.dataframe  # no table: one lead at a time
    assert shown_lead(app) == "Alpha Roofing"
    assert app.caption[0].value == "Lead 1 of 2 · :gray-badge[New]"
    assert "**Notes**" not in [markdown.value for markdown in app.markdown]  # notes live on the call sheet
    assert any("Atlantic Ave" in markdown.value for markdown in app.markdown)  # the brief, no tab to click
    with pytest.raises(KeyError):
        app.segmented_control(key="preset")  # no preset picker: the list covers every preset's top
    # The Why box gives the total under each preset that picked the lead.
    assert "Out of 100: **65** Balanced · **75** Big accounts · **58** Quick wins" in [markdown.value for markdown in app.markdown]
    # Alpha is in every preset's top 10, so it carries every preset's name as a tag.
    assert [markdown.value for markdown in app.markdown if "orange-badge" in markdown.value] == [
        ":orange-badge[Balanced]",
        ":orange-badge[Big accounts]",
        ":orange-badge[Quick wins]",
    ]


def test_next_and_previous_step_through_the_top_leads_and_stop_at_the_ends(app: AppTest) -> None:
    app.run()
    assert labelled(app, "Previous").disabled

    labelled(app, "Next").click().run()
    assert shown_lead(app) == "Beta Roofing"
    assert app.caption[0].value.startswith("Lead 2 of 2")
    assert labelled(app, "Next").disabled  # Gamma has no brief, so Beta is the last

    labelled(app, "Previous").click().run()
    assert shown_lead(app) == "Alpha Roofing"


def test_logging_a_call_on_the_landing_page_opens_the_next_top_lead(app: AppTest, session: Session) -> None:
    app.run()
    labelled(app, "Call").click().run()

    app.segmented_control(key="outcome_1").set_value("Contacted")
    labelled(app, "Log call").click().run()

    assert [note.status for note in lead_notes(session, 1, "1")] == ["Contacted"]
    assert shown_lead(app) == "Beta Roofing"
    assert any(button.label == "Log call" for button in app.button)  # Beta's call sheet is open
    # Alpha stays on the page, now Contacted.
    labelled(app, "Previous").click().run()
    assert app.caption[0].value.startswith("Lead 1 of 2 · :blue-badge[Contacted] · last logged")


def test_the_all_leads_page_lists_the_leads_and_selects_the_first(app: AppTest) -> None:
    open_all_leads(app)

    assert not app.exception
    assert app.header[0].value == "All leads"
    assert len(app.dataframe[0].value) == 3
    assert list(app.dataframe[0].value["Brief"]) == ["✓", "✓", ""]  # Alpha and Beta have briefs
    assert shown_lead(app) == "Alpha Roofing"
    assert [tab.label for tab in app.tabs] == ["Why", "Brief", "Notes"]


def test_the_selected_lead_survives_a_filter_change(app: AppTest) -> None:
    app.session_state["lead_id"] = "3"
    open_all_leads(app)
    assert shown_lead(app) == "Gamma Roofing"

    # Gamma moves from the third row to the first; the panel stays on Gamma.
    app.sidebar.text_input[0].input("gamma").run()
    assert shown_lead(app) == "Gamma Roofing"
    assert selected_row(app) == 0

    app.sidebar.text_input[0].input("").run()
    assert shown_lead(app) == "Gamma Roofing"
    assert selected_row(app) == 2


def test_a_lead_filtered_out_hands_the_panel_to_the_top_lead(app: AppTest) -> None:
    app.session_state["lead_id"] = "3"
    open_all_leads(app)

    app.sidebar.text_input[0].input("beta").run()

    assert shown_lead(app) == "Beta Roofing"


def test_the_selected_lead_survives_a_preset_switch_that_re_sorts_the_table(app: AppTest) -> None:
    app.session_state["lead_id"] = "3"
    open_all_leads(app)
    assert selected_row(app) == 2  # Balanced: Alpha, Beta, Gamma

    app.segmented_control(key="preset").set_value("Quick wins").run()

    assert shown_lead(app) == "Gamma Roofing"
    assert selected_row(app) == 1  # Quick wins: Beta, Gamma, Alpha


def test_a_link_with_a_preset_opens_all_leads_ranked_by_it(app: AppTest) -> None:
    app.query_params["preset"] = "Quick wins"
    open_all_leads(app)

    assert app.segmented_control(key="preset").value == "Quick wins"
    assert shown_lead(app) == "Beta Roofing"  # the top lead under Quick wins


def test_a_lead_without_a_brief_shows_brief_none_and_its_facts(app: AppTest) -> None:
    app.session_state["lead_id"] = "3"
    open_all_leads(app)

    assert app.tabs[1].label == "Brief (none)"
    assert any("Slate roof repair" in markdown.value for markdown in app.tabs[1].markdown)


def test_a_lead_with_a_brief_shows_its_opener(app: AppTest) -> None:
    open_all_leads(app)  # Alpha, the top lead, is selected

    assert app.tabs[1].label == "Brief"
    assert any("Atlantic Ave" in markdown.value for markdown in app.tabs[1].markdown)


def test_the_notes_tab_shows_each_status_change_in_color(app: AppTest, session: Session) -> None:
    add_note(session, 1, "3", "Contacted", "Left a voicemail.")
    add_note(session, 1, "3", "Considering us", "Asked for a quote.")
    session.commit()
    open_all_leads(app)
    app.segmented_control(key="status_group").set_value("All").run()
    app.session_state["lead_id"] = "3"  # Gamma is In progress now, so pick it once All shows it
    app.run()

    history = [markdown.value for markdown in app.tabs[2].markdown]

    # Newest first: each note's change of status as colored badges, then its text.
    assert history[0].startswith(":blue-badge[Contacted] → :violet-badge[Considering us]")
    assert "Asked for a quote" in history[1]
    assert history[2].startswith(":gray-badge[New] → :blue-badge[Contacted]")
    assert "Left a voicemail" in history[3]


def test_the_preset_is_saved_for_the_rep_and_restored_next_visit(app: AppTest, session: Session) -> None:
    open_all_leads(app)
    assert app.sidebar.caption[0].value == "Signed in as **Demo Rep**"

    app.segmented_control(key="preset").set_value("Big accounts").run()

    session.expire_all()
    assert session.get(Rep, 1).preset == "Big accounts"
    next_visit = open_all_leads(AppTest.from_file(str(ENTRY_POINT), default_timeout=30))
    assert next_visit.segmented_control(key="preset").value == "Big accounts"


def test_first_orders_and_leads_not_a_fit_each_have_their_own_filter(app: AppTest, session: Session) -> None:
    add_note(session, 1, "1", "First order", "Ordered shingles for a Park Slope job.")
    add_note(session, 1, "3", "Not a fit", "Commercial work only.")
    session.commit()
    open_all_leads(app)

    app.segmented_control(key="status_group").set_value("First order").run()
    assert list(app.dataframe[0].value["Contractor"]) == ["Alpha Roofing"]

    app.segmented_control(key="status_group").set_value("Not a fit").run()
    assert list(app.dataframe[0].value["Contractor"]) == ["Gamma Roofing"]


def test_the_header_links_the_website_only_when_there_is_one(app: AppTest) -> None:
    open_all_leads(app)  # Alpha: no website
    assert [button.label for button in app.main.get("link_button")] == ["GAF profile"]

    app.session_state["lead_id"] = "3"
    app.run()  # Gamma
    assert [button.label for button in app.main.get("link_button")] == ["Website", "GAF profile"]


def test_logging_a_call_saves_the_outcome_and_opens_the_next_lead(app: AppTest, session: Session) -> None:
    open_all_leads(app)  # Alpha, the top lead, is selected
    labelled(app, "Call").click().run()

    app.segmented_control(key="outcome_1").set_value("Contacted")
    app.text_area(key="call_note_1").set_value("Left a voicemail.")
    labelled(app, "Log call").click().run()

    assert [(note.status, note.text) for note in lead_notes(session, 1, "1")] == [("Contacted", "Left a voicemail.")]
    assert shown_lead(app) == "Beta Roofing"  # the next lead, and its call sheet opens
    assert any(button.label == "Log call" for button in app.button)
    assert len(app.dataframe[0].value) == 2  # Alpha left To contact


def test_next_and_previous_move_down_and_up_the_table(app: AppTest) -> None:
    open_all_leads(app)
    labelled(app, "Next").click().run()
    assert shown_lead(app) == "Beta Roofing"

    labelled(app, "Previous").click().run()
    assert shown_lead(app) == "Alpha Roofing"


def test_the_call_sheet_starts_on_the_leads_current_status(app: AppTest, session: Session) -> None:
    add_note(session, 1, "3", "Considering us", "Asked for a quote.")
    session.commit()
    open_all_leads(app)
    app.segmented_control(key="status_group").set_value("All").run()
    app.session_state["lead_id"] = "3"  # Gamma is In progress now, so pick it once All shows it
    app.run()

    labelled(app, "Call").click().run()

    assert app.segmented_control(key="outcome_3").value == "Considering us"


def test_a_missing_database_shows_the_seed_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "leads.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{missing}")
    monkeypatch.setenv("COVEO_ORG_ID", "test-org")

    app = AppTest.from_file(str(ENTRY_POINT), default_timeout=30).run()

    assert not app.exception
    assert "cp seed/leads.db data/leads.db" in app.error[0].value
    assert not missing.exists()  # checked before connecting, so no empty file is left behind


def test_the_header_shows_the_founding_year_the_score_uses(app: AppTest, session: Session) -> None:
    # GAF says 2015 and the contractor's own text says 2004: the score uses only GAF's year, so the header must too.
    session.get(Contractor, "1").in_business_since = 2015
    session.add(
        Fact(
            contractor_id="1",
            field="founded_year",
            value="2004",
            evidence="Family-owned since 2004.",
            source="about_text",
            source_url="https://www.gaf.com/en-us/roofing-contractors/1",
            model="test",
            prompt_version="test",
        )
    )
    session.commit()

    app.run()  # Alpha, the top lead, is selected

    captions = [caption.value for caption in app.caption]
    assert any("since 2015" in caption for caption in captions)
    assert not any("since 2004" in caption for caption in captions)
