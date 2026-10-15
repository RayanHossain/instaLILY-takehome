"""The website check: one GET per site against a mock transport, and the stage that records it."""

import socket
import ssl
from collections.abc import Iterator
from datetime import timedelta

import httpx
import pytest
from sqlalchemy.orm import Session

from app.db.models import Contractor, Run, utc_now
from app.pipeline.check_websites import check_websites
from app.sources import websites


def test_any_http_response_is_recorded_as_is() -> None:
    statuses = {"https://ok.example/": 200, "https://blocked.example/": 403, "https://moved.example/": 301}
    requests = []

    def site(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(statuses[str(request.url)], headers={"location": "https://elsewhere.example/"})

    results = list(websites.check(dict(zip("abc", statuses)), transport=httpx.MockTransport(site)))

    assert results == [("a", 200, None), ("b", 403, None), ("c", 301, None)]
    assert len(requests) == 3  # one request per site: the 301 is not followed
    assert requests[0].headers["user-agent"].startswith("instaLILY-takehome-lead-research")


def failed_connection(cause: Exception) -> httpx.ConnectError:
    """An httpx.ConnectError wrapping the socket or SSL error behind it, as httpx raises them."""
    error = httpx.ConnectError(str(cause))
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    ("failure", "expected_error"),
    [
        (httpx.ConnectTimeout("timed out"), "timeout"),
        (httpx.ReadTimeout("timed out"), "timeout"),
        (failed_connection(socket.gaierror(8, "nodename nor servname provided, or not known")), "dns"),
        (failed_connection(ssl.SSLCertVerificationError(1, "certificate verify failed")), "ssl"),
        (failed_connection(ConnectionRefusedError(61, "Connection refused")), "connection"),
    ],
)
def test_no_response_is_recorded_as_an_error_kind(failure: Exception, expected_error: str) -> None:
    def fails(request: httpx.Request) -> httpx.Response:
        raise failure

    results = list(websites.check({"a": "https://roofer.example/"}, transport=httpx.MockTransport(fails)))

    assert results == [("a", None, expected_error)]


def test_stage_records_outcomes_and_skips_recent_checks(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run(territory_zip="10013", radius_miles=25)
    session.add(run)
    session.flush()
    for gaf_id, website_url in [("1", "https://up.example/"), ("2", "https://down.example/"), ("3", None)]:
        session.add(
            Contractor(gaf_id=gaf_id, name=f"Roofer {gaf_id}", website_url=website_url, first_seen_run=run.id, last_seen_run=run.id)
        )
    session.commit()

    checked: list[list[str]] = []

    def canned(website_urls: dict[str, str]) -> Iterator[tuple[str, int | None, str | None]]:
        checked.append(list(website_urls))
        for gaf_id in website_urls:
            yield (gaf_id, 200, None) if gaf_id == "1" else (gaf_id, None, "dns")

    monkeypatch.setattr(websites, "check", canned)

    assert check_websites(session) == 2  # contractor 3 has no website
    up, down = session.get(Contractor, "1"), session.get(Contractor, "2")
    assert (up.website_status, up.website_error) == (200, None)
    assert (down.website_status, down.website_error) == (None, "dns")
    assert up.website_checked_at is not None

    assert check_websites(session) == 0  # both were checked less than 7 days ago

    up.website_checked_at = utc_now() - timedelta(days=8)
    session.commit()
    assert check_websites(session) == 1
    assert checked[-1] == ["1"]
