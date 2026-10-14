"""The discover stage, run against a saved Coveo page instead of the network."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Contractor, RawResponse, Run
from app.pipeline.discover import discover
from app.settings import Settings
from app.sources import coveo

FIXTURE = Path(__file__).parent / "fixtures" / "coveo_page.json"
TERRITORY = {"zip": "10013", "lat": 40.7217861, "lng": -74.0094471, "radius_miles": 25}
# _env_file=None: never read the developer's .env. discover only uses the Coveo fields,
# and fetch_pages is replaced below, so these values never leave the test.
SETTINGS = Settings(_env_file=None, database_url="unused", coveo_org_id="test-org", coveo_api_key="test-key")


def test_second_run_adds_no_duplicates_and_moves_last_seen_run(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    def saved_page(*args: object) -> Iterator[httpx.Response]:
        request = httpx.Request(
            "POST",
            "https://test-org.org.coveo.com/rest/search/v2?organizationId=test-org",
            json=coveo.build_search_body(TERRITORY["lat"], TERRITORY["lng"], TERRITORY["radius_miles"]),
        )
        yield httpx.Response(200, content=FIXTURE.read_bytes(), headers={"content-type": "application/json"}, request=request)

    monkeypatch.setattr(coveo, "fetch_pages", saved_page)
    fixture_count = len(json.loads(FIXTURE.read_bytes())["results"])

    first = discover(session, TERRITORY, SETTINGS)
    second = discover(session, TERRITORY, SETTINGS)

    assert (first.status, first.contractors_seen) == ("finished", fixture_count)
    assert (second.status, second.contractors_seen) == ("finished", fixture_count)
    contractors = session.scalars(select(Contractor)).all()
    assert len(contractors) == fixture_count
    assert {c.first_seen_run for c in contractors} == {first.id}
    assert {c.last_seen_run for c in contractors} == {second.id}

    raw_responses = session.scalars(select(RawResponse)).all()
    assert [r.run_id for r in raw_responses] == [first.id, second.id]
    assert raw_responses[0].body == FIXTURE.read_bytes().decode()
    assert raw_responses[0].request_body["firstResult"] == 0  # the page offset is saved with the page


def test_rejected_key_marks_the_run_failed(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    def rejected_key(*args: object) -> NoReturn:
        raise SystemExit("Coveo rejected the API key (HTTP 401).")

    monkeypatch.setattr(coveo, "fetch_pages", rejected_key)

    with pytest.raises(SystemExit):
        discover(session, TERRITORY, SETTINGS)

    run = session.scalars(select(Run)).one()
    assert run.status == "failed"
    assert run.finished_at is not None
    assert session.scalar(select(func.count()).select_from(Contractor)) == 0
