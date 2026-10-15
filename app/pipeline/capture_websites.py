"""Homepage capture stage: save the homepage of every contractor whose website answered.

Each homepage is saved to raw_responses (source "contractor_website") before anything
parses it. One saved in the last 7 days is skipped, so a rerun after a crash picks up
where the last run stopped.
"""

import hashlib
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Contractor, RawResponse, utc_now
from app.sources import websites

FRESH_FOR = timedelta(days=7)


def capture_websites(session: Session) -> int:
    """Save the homepage of each contractor in the latest discover whose website check got an HTTP response.

    A page that comes back with any status other than 200 is saved too, with its status
    code, and counted as failed; a 403 or 429 is recorded this way and never worked
    around. A request that gets no response is saved with its error instead. Both are
    retried next run. A 200 that isn't HTML (a PDF, say) is skipped and nothing is saved.

    Args:
        session: An open session. Each page is committed as soon as it is saved.

    Returns:
        The number of homepages saved with HTTP 200.
    """
    # Discover sets last_seen_run, so the highest one is the most recent discover run.
    latest_run = session.scalar(select(func.max(Contractor.last_seen_run)))
    saved_recently = (
        select(RawResponse.id)
        .where(
            RawResponse.contractor_id == Contractor.gaf_id,
            RawResponse.source == websites.HOMEPAGE_SOURCE,
            RawResponse.status_code == 200,
            RawResponse.fetched_at >= utc_now() - FRESH_FOR,
        )
        .exists()
    )
    website_urls = dict(
        session.execute(
            select(Contractor.gaf_id, Contractor.website_url)
            .where(
                Contractor.last_seen_run == latest_run,
                Contractor.website_url.is_not(None),
                Contractor.website_status.is_not(None),  # the website check got an HTTP response
                ~saved_recently,
            )
            .order_by(Contractor.gaf_id)
        ).all()
    )
    print(f"capture_websites: {len(website_urls)} homepages to fetch")

    saved = failed = skipped = 0
    for number, (gaf_id, homepage) in enumerate(websites.fetch_homepages(website_urls), start=1):
        if homepage.status_code == 200 and homepage.html is None:
            skipped += 1
            print(f"capture_websites: {number}/{len(website_urls)} {gaf_id} skipped, not HTML ({homepage.content_type})")
            continue

        # Save it before anything else: a good page is kept for extraction, a failure as a record.
        body = homepage.html or ""
        session.add(
            RawResponse(
                run_id=latest_run,
                contractor_id=gaf_id,
                source=websites.HOMEPAGE_SOURCE,
                url=homepage.url,
                status_code=homepage.status_code,
                error=homepage.error,
                content_type=homepage.content_type,
                body=body,
                content_hash=hashlib.sha256(body.encode()).hexdigest(),
            )
        )
        session.commit()
        if homepage.status_code == 200:
            saved += 1
        else:
            failed += 1
        outcome = f"no response ({homepage.error})" if homepage.error else f"HTTP {homepage.status_code}"
        print(f"capture_websites: {number}/{len(website_urls)} {gaf_id} {outcome}")

    print(f"capture_websites: done, {saved} homepages saved, {failed} failed, {skipped} skipped as not HTML")
    return saved
