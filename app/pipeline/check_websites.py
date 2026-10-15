"""Website check stage: one GET to each contractor's website, recording what came back.

The outcome is recorded, not interpreted: any HTTP status means the site exists.
"""

from datetime import timedelta

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.db.models import Contractor, utc_now
from app.sources import websites

RECHECK_AFTER = timedelta(days=7)


def check_websites(session: Session) -> int:
    """Check each contractor's website_url once and store the status or error.

    Skips websites checked in the last 7 days, so a rerun resumes after a crash
    instead of calling every site again.

    Args:
        session: An open session. Each result is committed as soon as it is known.

    Returns:
        The number of websites checked.
    """
    website_urls = dict(
        session.execute(
            select(Contractor.gaf_id, Contractor.website_url)
            .where(
                Contractor.website_url.is_not(None),
                or_(
                    Contractor.website_checked_at.is_(None),
                    Contractor.website_checked_at < utc_now() - RECHECK_AFTER,
                ),
            )
            .order_by(Contractor.gaf_id)
        ).all()
    )
    print(f"check_websites: {len(website_urls)} websites to check")

    checked = 0
    for gaf_id, status_code, error in websites.check(website_urls):
        # Bulk UPDATE by primary key, as in parse: the upsert helper can't update part of a row.
        session.execute(
            update(Contractor),
            [
                {
                    "gaf_id": gaf_id,
                    "website_status": status_code,
                    "website_error": error,
                    "website_checked_at": utc_now(),
                    "updated_at": utc_now(),
                }
            ],
        )
        session.commit()
        checked += 1
        print(f"check_websites: {checked}/{len(website_urls)} {gaf_id} {status_code or error}")

    print(f"check_websites: done, {checked} websites checked")
    return checked
