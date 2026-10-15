"""GAF contractor profile pages (gaf.com/en-us/roofing-contractors/...).

The search results link to one profile page per contractor. The page has details
the search doesn't return, such as the street address and website.
"""

import time
from collections.abc import Iterator

import httpx

from app.sources import USER_AGENT


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
