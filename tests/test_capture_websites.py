"""Homepage capture: the real adapter against a mock transport, run by the real stage."""

from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Contractor, RawResponse, Run, utc_now
from app.pipeline.capture_websites import capture_websites
from app.sources import websites


def test_capture_follows_redirects_records_refusals_and_skips_non_html(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_run, latest_run = Run(territory_zip="10013", radius_miles=25), Run(territory_zip="10013", radius_miles=25)
    session.add_all([old_run, latest_run])
    session.flush()
    for gaf_id, website_url, website_status, run in [
        ("1", "https://redirects.example/", 301, latest_run),
        ("2", "https://refuses.example/", 403, latest_run),
        ("3", "https://brochure.example/", 200, latest_run),
        ("4", "https://down.example/", None, latest_run),  # the website check got no answer
        ("5", "https://gone.example/", 200, old_run),  # not in the latest discover
    ]:
        session.add(
            Contractor(
                gaf_id=gaf_id,
                name=f"Roofer {gaf_id}",
                website_url=website_url,
                website_status=website_status,
                first_seen_run=run.id,
                last_seen_run=run.id,
            )
        )
    session.commit()

    requests: list[httpx.Request] = []

    def sites(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "redirects.example":
            return httpx.Response(301, headers={"location": "https://www.redirects.example/home"})
        if request.url.host == "www.redirects.example":
            return httpx.Response(200, html="<html><body>Roofing since 1999</body></html>")
        if request.url.host == "refuses.example":
            return httpx.Response(403, html="<html><body>Access denied</body></html>")
        return httpx.Response(200, content=b"%PDF-1.7", headers={"content-type": "application/pdf"})

    real_fetch_homepages = websites.fetch_homepages
    monkeypatch.setattr(
        websites, "fetch_homepages", lambda urls: real_fetch_homepages(urls, transport=httpx.MockTransport(sites))
    )

    assert capture_websites(session) == 1

    pages = {page.contractor_id: page for page in session.scalars(select(RawResponse))}
    assert set(pages) == {"1", "2"}  # the PDF is skipped, and 4 and 5 are never asked for
    assert (pages["1"].url, pages["1"].status_code) == ("https://www.redirects.example/home", 200)  # redirect followed
    assert pages["1"].body == "<html><body>Roofing since 1999</body></html>"
    assert (pages["1"].source, pages["1"].run_id) == ("contractor_website", latest_run.id)
    assert pages["2"].status_code == 403  # recorded, not worked around
    assert [str(request.url) for request in requests] == [
        "https://redirects.example/",
        "https://www.redirects.example/home",
        "https://refuses.example/",  # asked once: no retry after the 403
        "https://brochure.example/",
    ]
    assert requests[0].headers["user-agent"].startswith("instaLILY-takehome-lead-research")

    # A rerun skips the homepage saved, and the site that refused, less than 7 days ago; the PDF is tried again.
    requests.clear()
    capture_websites(session)
    assert [str(request.url) for request in requests] == ["https://brochure.example/"]

    # Once the refusal is more than 7 days old, the site is asked again.
    pages["2"].fetched_at = utc_now() - timedelta(days=8)
    session.commit()
    requests.clear()
    capture_websites(session)
    assert [str(request.url) for request in requests] == ["https://refuses.example/", "https://brochure.example/"]


def test_html_is_cut_to_2_mb() -> None:
    big_page = "<html>" + "a" * (3 * 1024 * 1024) + "</html>"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, html=big_page))

    [(gaf_id, homepage)] = websites.fetch_homepages({"1": "https://big.example/"}, transport=transport)

    assert (gaf_id, homepage.status_code) == ("1", 200)
    assert homepage.html == big_page[: 2 * 1024 * 1024]
