"""GAF contractor profile pages (gaf.com/en-us/roofing-contractors/...).

The search results link to one profile page per contractor. The page has details
the search doesn't return, such as the street address and website.
"""

import re
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from bs4 import BeautifulSoup

from app.sources import USER_AGENT

SOURCE = "gaf_profile"  # raw_responses.source for saved profile pages


def fetch_profiles(
    profile_urls: dict[str, str],
    *,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[tuple[str, httpx.Response | httpx.RequestError]]:
    """Yield (gaf_id, response) for each profile page, about one request per second.

    The caller should save each response before parsing it. A request that gets no
    response at all (timeout, DNS, connection) yields the error instead, so the
    caller can record it and move on.

    GAF's CDN answers a new session's first request with a 403 that sets a cookie,
    then serves pages to a client that sends the cookie back. So when the very first
    request gets a 403 that sets a cookie, it is retried once, and that is logged.
    Any other 403, or any 429, exits with a message: GAF is refusing us, so we stop.

    Args:
        profile_urls: GAF contractor ID -> profile URL, in the order to fetch them.
        transport: Tests pass an httpx.MockTransport; None uses the real network.
    """
    # One client for the whole run, so its cookie jar keeps the cookie GAF sets.
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True, transport=transport
    ) as client:
        for number, (gaf_id, url) in enumerate(profile_urls.items()):
            if number > 0:
                time.sleep(1)  # about one request per second, to be polite to GAF
            try:
                response = client.get(url)
                if number == 0 and response.status_code == 403 and response.cookies:
                    print(
                        "fetch: cookie handshake: GAF answered the first request with a 403 and set "
                        f"{', '.join(response.cookies.keys())}; retrying once with the cookie"
                    )
                    time.sleep(1)
                    response = client.get(url)
            except httpx.RequestError as error:
                yield gaf_id, error
                continue

            if response.status_code in (403, 429):
                raise SystemExit(
                    f"GAF refused the profile for {gaf_id} (HTTP {response.status_code}), so the fetch stopped. "
                    "Profiles saved so far are kept, and a later rerun skips them."
                )
            yield gaf_id, response


def parse_profile(html: str) -> dict[str, Any]:
    """Map one saved profile page to contractor column values.

    A value the page doesn't show is None. The Google figures are read from the
    "Google Reviews" section; the masthead at the top of the page repeats them.
    """
    soup = BeautifulSoup(html, "html.parser")

    address = soup.select_one("address.image-masthead-carousel__address")
    website = soup.find("a", string=lambda text: text is not None and text.strip() == "Visit Website")
    place_link = soup.select_one('section.contractor-reviews a[href*="placeid="]')  # the "See All Reviews" button
    rating = soup.select_one("section.contractor-reviews span.rating-stars__average")  # e.g. "4.9"
    review_count = soup.select_one("section.contractor-reviews span.rating-stars__total")  # e.g. "(1846)"
    # The page holds the whole About text; "Expand to read more" only un-hides it with CSS.
    about = soup.select_one("section.about-us-block .about-us-block__description")
    details = soup.select_one("section.contractor-details")
    founded = re.search(r"In business since (\d{4})", details.get_text()) if details else None

    website_url = website.get("href", "").strip() if website else ""
    website_host = urlsplit(website_url).hostname if website_url else None  # hostname is lowercased
    about_text = " ".join(about.get_text(" ").split()) if about else ""  # collapse the page's line breaks

    return {
        "street_address": address.get_text(strip=True) if address else None,
        "website_url": website_url or None,
        "website_domain": website_host.removeprefix("www.") if website_host else None,
        "google_place_id": parse_qs(urlsplit(place_link["href"]).query)["placeid"][0] if place_link else None,
        "google_rating": float(rating.get_text(strip=True)) if rating else None,
        "google_review_count": int(re.sub(r"\D", "", review_count.get_text())) if review_count else None,
        "about_text": about_text or None,
        "in_business_since": int(founded.group(1)) if founded else None,
    }
