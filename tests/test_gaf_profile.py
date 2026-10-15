"""The GAF profile adapter: polite fetching (mock transport) and parsing (saved, trimmed real pages)."""

import time
from pathlib import Path

import httpx
import pytest

from app.sources.gaf_profile import fetch_profiles, parse_profile

FIXTURES = Path(__file__).parent / "fixtures"

PROFILE_URLS = {
    "1000001": "https://www.gaf.com/en-us/roofing-contractors/residential/usa/ny/a/a-roofing-1000001",
    "1000002": "https://www.gaf.com/en-us/roofing-contractors/residential/usa/ny/b/b-roofing-1000002",
}


@pytest.fixture(autouse=True)
def no_pauses(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the one-second politeness pauses."""
    monkeypatch.setattr(time, "sleep", lambda seconds: None)


def test_cookie_setting_403_then_200_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    requests = []

    def gaf(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "ak_geo=US" not in request.headers.get("cookie", ""):
            return httpx.Response(403, headers={"set-cookie": "ak_geo=US; path=/"}, text="Access Denied")
        return httpx.Response(200, text="<html>profile</html>")

    results = list(fetch_profiles(PROFILE_URLS, transport=httpx.MockTransport(gaf)))

    assert [(gaf_id, response.status_code) for gaf_id, response in results] == [("1000001", 200), ("1000002", 200)]
    assert len(requests) == 3  # the handshake 403, its one retry, then the second profile
    assert capsys.readouterr().out.count("cookie handshake") == 1  # logged once per run


def test_second_403_stops_the_run() -> None:
    requests = []

    def always_refuses(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(403, headers={"set-cookie": "ak_geo=US; path=/"}, text="Access Denied")

    with pytest.raises(SystemExit, match="HTTP 403"):
        list(fetch_profiles(PROFILE_URLS, transport=httpx.MockTransport(always_refuses)))

    assert len(requests) == 2  # the first request and its one retry; the second profile is never asked for


def test_first_403_without_a_cookie_stops_without_retrying() -> None:
    requests = []

    def refuses_without_cookie(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(403, text="Access Denied")

    with pytest.raises(SystemExit, match="HTTP 403"):
        list(fetch_profiles(PROFILE_URLS, transport=httpx.MockTransport(refuses_without_cookie)))

    assert len(requests) == 1


@pytest.mark.parametrize("status", [403, 429])
def test_403_or_429_after_the_first_request_stops_the_run(status: int) -> None:
    requested_paths = []

    def refuses_second(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path.endswith("1000002"):
            return httpx.Response(status, headers={"set-cookie": "ak_geo=US; path=/"})
        return httpx.Response(200, text="<html>profile</html>")

    results = fetch_profiles(PROFILE_URLS, transport=httpx.MockTransport(refuses_second))

    assert next(results)[1].status_code == 200
    with pytest.raises(SystemExit, match=f"HTTP {status}"):
        next(results)
    assert len(requested_paths) == 2  # the refused profile was asked for once: no retry after the first request


def test_parse_profile_with_google_reviews_website_about_and_founding_year() -> None:
    html = (FIXTURES / "gaf_profile_1113654.html").read_text(encoding="utf-8")

    assert parse_profile(html) == {
        "street_address": "50 Galesi Dr, Wayne NJ, 07470 USA",
        "website_url": "https://www.matuteroofing.com/",
        "website_domain": "matuteroofing.com",  # lowercase, without "www."
        "google_place_id": "ChIJqzpJ3dYDw4kR2EdOcYM3L2w",
        "google_rating": 5.0,
        "google_review_count": 501,
        # The whole About text, with the page's line breaks and double spaces collapsed.
        "about_text": (
            "Matute Roofing is a family owned and operated roofing company with over 20 years experience "
            "Matute Roofing is Licensed and fully insured Matute Roofing is committed to providing you with "
            "the finest products ,skilled workmanship and courteous service We are the honest dependable and "
            "reliable you can TRUST"
        ),
        "in_business_since": 2009,
    }


def test_parse_profile_without_reviews_website_about_or_founding_year() -> None:
    html = (FIXTURES / "gaf_profile_7158181.html").read_text(encoding="utf-8")

    assert parse_profile(html) == {
        "street_address": "36-20 168th St, Flushing NY, 11358 USA",
        "website_url": None,
        "website_domain": None,
        "google_place_id": None,  # "See All Reviews" links to "#"
        "google_rating": None,  # the page says "No Google Verified Reviews"
        "google_review_count": None,
        "about_text": None,
        "in_business_since": None,
    }
