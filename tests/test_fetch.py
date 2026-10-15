"""The fetch stage, with the profile adapter replaced by canned responses."""

from collections.abc import Iterator
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Contractor, RawResponse, Run, utc_now
from app.pipeline.fetch import fetch
from app.sources import gaf_profile


def add_contractor(session: Session, gaf_id: str, run: Run) -> None:
    """Add a contractor last seen in the given discover run."""
    session.add(
        Contractor(
            gaf_id=gaf_id,
            name=f"Roofer {gaf_id}",
            profile_url=f"https://www.gaf.com/en-us/roofing-contractors/roofer-{gaf_id}",
            first_seen_run=run.id,
            last_seen_run=run.id,
        )
    )


def test_fetch_saves_pages_records_failures_and_skips_fresh_profiles(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_run, latest_run = Run(territory_zip="10013", radius_miles=25), Run(territory_zip="10013", radius_miles=25)
    session.add_all([old_run, latest_run])
    session.flush()
    add_contractor(session, "0000001", old_run)  # not in the latest discover, so never fetched
    for gaf_id in ["1000001", "1000002", "1000003"]:
        add_contractor(session, gaf_id, latest_run)
    session.commit()

    requested: list[list[str]] = []

    def canned(profile_urls: dict[str, str]) -> Iterator[tuple[str, httpx.Response | httpx.RequestError]]:
        requested.append(list(profile_urls))
        for gaf_id, url in profile_urls.items():
            request = httpx.Request("GET", url)
            if gaf_id == "1000001":
                yield gaf_id, httpx.Response(200, text="<html>profile</html>", request=request)
            elif gaf_id == "1000002":
                yield gaf_id, httpx.Response(404, text="Not Found", request=request)
            else:
                yield gaf_id, httpx.ConnectTimeout("timed out", request=request)

    monkeypatch.setattr(gaf_profile, "fetch_profiles", canned)

    assert fetch(session) == 1
    saved = {r.contractor_id: r for r in session.scalars(select(RawResponse))}
    assert {gaf_id: r.status_code for gaf_id, r in saved.items()} == {"1000001": 200, "1000002": 404}
    assert saved["1000001"].source == "gaf_profile"
    assert saved["1000001"].body == "<html>profile</html>"
    assert saved["1000001"].run_id == latest_run.id

    # A rerun retries only the failures: the good profile was saved less than 7 days ago.
    fetch(session)
    assert requested[1] == ["1000002", "1000003"]

    # Once the good profile is more than 7 days old, it is fetched again.
    saved["1000001"].fetched_at = utc_now() - timedelta(days=8)
    session.commit()
    fetch(session)
    assert requested[2] == ["1000001", "1000002", "1000003"]
