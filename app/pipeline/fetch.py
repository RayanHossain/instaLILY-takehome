"""Fetch stage: download the GAF profile page of every contractor in the latest discover.

Each page is saved to raw_responses (source "gaf_profile") before anything parses it.
A contractor whose profile was saved in the last 7 days is skipped, so a rerun after
a crash or a block picks up where the last run stopped, with no progress table.
"""

import hashlib
from datetime import timedelta

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Contractor, RawResponse, utc_now
from app.sources import gaf_profile

FRESH_FOR = timedelta(days=7)


def fetch(session: Session) -> int:
    """Save the profile page of each contractor seen in the most recent discover.

    A page that comes back with any status other than 200 is saved too, with its
    status code, and counted as failed. A request that gets no response (timeout,
    DNS, connection) is saved with its error instead. Both are retried next run.

    Args:
        session: An open session. Each page is committed as soon as it is saved.

    Returns:
        The number of profiles saved with HTTP 200.
    """
    # Discover sets last_seen_run, so the highest one is the most recent discover run.
    latest_run = session.scalar(select(func.max(Contractor.last_seen_run)))
    saved_recently = (
        select(RawResponse.id)
        .where(
            RawResponse.contractor_id == Contractor.gaf_id,
            RawResponse.source == gaf_profile.SOURCE,
            RawResponse.status_code == 200,
            RawResponse.fetched_at >= utc_now() - FRESH_FOR,
        )
        .exists()
    )
    profile_urls = dict(
        session.execute(
            select(Contractor.gaf_id, Contractor.profile_url)
            .where(Contractor.last_seen_run == latest_run, Contractor.profile_url.is_not(None), ~saved_recently)
            .order_by(Contractor.gaf_id)
        ).all()
    )
    print(f"fetch: {len(profile_urls)} profiles to fetch for discover run {latest_run}")

    saved = failed = 0
    for number, (gaf_id, result) in enumerate(gaf_profile.fetch_profiles(profile_urls), start=1):
        page = RawResponse(run_id=latest_run, contractor_id=gaf_id, source=gaf_profile.SOURCE)
        if isinstance(result, httpx.RequestError):
            # Nothing came back, so the error is recorded in place of a response.
            page.url = profile_urls[gaf_id]
            page.error = type(result).__name__
            page.body = ""
            outcome = f"no response ({page.error})"
        else:
            page.url = str(result.url)
            page.status_code = result.status_code
            page.content_type = result.headers.get("content-type")
            page.body = result.text
            outcome = f"HTTP {result.status_code}"
        page.content_hash = hashlib.sha256(page.body.encode()).hexdigest()

        # Save it before anything else: a good page is kept for parsing, a failure as a record.
        session.add(page)
        session.commit()
        if page.status_code == 200:
            saved += 1
        else:
            failed += 1
        print(f"fetch: {number}/{len(profile_urls)} {gaf_id} {outcome}")

    print(f"fetch: done, {saved} profiles saved, {failed} failed")
    return saved
