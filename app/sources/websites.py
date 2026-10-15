"""Contractor websites: one GET to each, to see whether anything answers, and their homepages."""

import socket
import ssl
from collections.abc import Iterator
from dataclasses import dataclass

import httpx

from app.sources import USER_AGENT

HOMEPAGE_SOURCE = "contractor_website"  # raw_responses.source for saved homepages
MAX_HTML_BYTES = 2 * 1024 * 1024  # a homepage's HTML is kept up to 2 MB
HTML_TYPES = {"text/html", "application/xhtml+xml"}


def check(
    website_urls: dict[str, str],
    *,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[tuple[str, int | None, str | None]]:
    """Yield (gaf_id, status_code, error) after one GET to each website, one site at a time.

    Any HTTP response, even a 403 or a 500, means the site exists: its status code
    is yielded as is, with error None. Redirects are not followed, so each site gets
    exactly one request. If nothing answers, status_code is None and error is
    "timeout", "dns", "ssl", or "connection".

    Args:
        website_urls: GAF contractor ID -> website URL.
        transport: Tests pass an httpx.MockTransport; None uses the real network.
    """
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=5, transport=transport) as client:
        for gaf_id, url in website_urls.items():
            try:
                # Streaming reads only the status line and headers, not the whole page.
                with client.stream("GET", url) as response:
                    status_code = response.status_code
            except httpx.TimeoutException:
                yield gaf_id, None, "timeout"
            except (httpx.RequestError, httpx.InvalidURL) as error:
                # httpx wraps the socket or SSL error underneath; walk down the chain to name it.
                chain = []
                cause: BaseException | None = error
                while cause is not None:
                    chain.append(cause)
                    cause = cause.__cause__ or cause.__context__
                if any(isinstance(cause, socket.gaierror) for cause in chain):
                    yield gaf_id, None, "dns"
                elif any(isinstance(cause, ssl.SSLError) for cause in chain):
                    yield gaf_id, None, "ssl"
                else:
                    yield gaf_id, None, "connection"
            else:
                yield gaf_id, status_code, None


@dataclass
class Homepage:
    """What one GET to a contractor's website brought back."""

    url: str  # where the answer came from, after any redirects
    status_code: int | None  # None when nothing answered
    content_type: str | None
    html: str | None  # the HTML, cut to 2 MB; None when the answer wasn't HTML
    error: str | None  # when nothing answered: the httpx error name, e.g. "ConnectTimeout"


def fetch_homepages(
    website_urls: dict[str, str],
    *,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[tuple[str, Homepage]]:
    """Yield (gaf_id, homepage) after one GET to each website, one site at a time.

    Up to 5 redirects are followed. Only an HTML body is downloaded, and only its first
    2 MB. A 403 or 429 is yielded like any other answer, for the caller to record: it
    is never retried or worked around.

    Args:
        website_urls: GAF contractor ID -> website URL.
        transport: Tests pass an httpx.MockTransport; None uses the real network.
    """
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=10,
        follow_redirects=True,
        max_redirects=5,
        transport=transport,
    ) as client:
        for gaf_id, url in website_urls.items():
            try:
                with client.stream("GET", url) as response:
                    content_type = response.headers.get("content-type")
                    html = None
                    if content_type and content_type.split(";")[0].strip().lower() in HTML_TYPES:
                        body = b""
                        for chunk in response.iter_bytes():
                            body += chunk
                            if len(body) >= MAX_HTML_BYTES:
                                break  # the rest of the page is never downloaded
                        # errors="replace": the cut can split a character, and some sites mislabel their charset.
                        html = body[:MAX_HTML_BYTES].decode(response.encoding or "utf-8", errors="replace")
                    homepage = Homepage(
                        url=str(response.url),
                        status_code=response.status_code,
                        content_type=content_type,
                        html=html,
                        error=None,
                    )
            except (httpx.RequestError, httpx.InvalidURL) as error:
                homepage = Homepage(url=url, status_code=None, content_type=None, html=None, error=type(error).__name__)
            yield gaf_id, homepage
