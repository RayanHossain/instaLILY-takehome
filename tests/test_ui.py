"""Smoke test: the Streamlit page renders against a temporary database."""

from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from streamlit.testing.v1 import AppTest

from app.db.models import Contractor, Run
from app.settings import load_territory

ENTRY_POINT = Path(__file__).parent.parent / "streamlit_app.py"  # what `streamlit run` runs
TERRITORY = load_territory()


def test_page_renders_the_leads_with_the_nearest_one_selected(
    engine: Engine, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = Run(territory_zip="10013", radius_miles=25)
    session.add(run)
    session.flush()
    shared = {"certifications": ["GAF Master Elite® - Certification"], "first_seen_run": run.id, "last_seen_run": run.id}
    session.add(Contractor(gaf_id="2", name="Far Roofing", lat=TERRITORY["lat"] + 0.1, lng=TERRITORY["lng"], **shared))
    session.add(
        Contractor(gaf_id="1", name="Near Roofing", lat=TERRITORY["lat"], lng=TERRITORY["lng"], rating=4.9, review_count=312, **shared)
    )
    session.commit()
    # Environment variables win over .env, so the app opens the test database, never data/leads.db.
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    monkeypatch.setenv("COVEO_ORG_ID", "test-org")
    monkeypatch.setenv("COVEO_API_KEY", "test-key")

    app = AppTest.from_file(str(ENTRY_POINT), default_timeout=30).run()

    assert not app.exception
    assert app.header[0].value == f"2 contractors within {TERRITORY['radius_miles']} miles of {TERRITORY['zip']}"
    table = app.dataframe[0].value
    assert list(table.columns) == ["Name", "City", "Miles", "Tier", "Rating"]
    assert table["Name"].tolist() == ["Near Roofing", "Far Roofing"]
    assert table["Rating"][0] == "4.9 (312)"
    assert app.subheader[0].value == "Near Roofing"  # the nearest row starts selected
    lines = [markdown.value for markdown in app.markdown]
    assert "**Rating:** 4.9 (312 reviews)" in lines
    assert "**GAF Leads:** Unknown" in lines
    assert "**Website:** —" in lines
    assert any(line.startswith("**Notes and status:**") for line in lines)

    app.sidebar.text_input[0].input("near").run()

    assert app.header[0].value == f"1 contractor within {TERRITORY['radius_miles']} miles of {TERRITORY['zip']}"
