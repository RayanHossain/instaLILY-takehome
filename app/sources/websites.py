"""Contractor websites: one GET to each, to see whether anything answers."""

import socket
import ssl
from collections.abc import Iterator

import httpx

from app.sources import USER_AGENT


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
