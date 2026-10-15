"""Parse stage: read each contractor's latest saved GAF profile and store its details.

Parsing reads saved pages only, never the network, so it reruns on every profile
each time. Fixing the parser and rerunning this stage updates every contractor.
"""

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.db.models import Contractor, RawResponse, utc_now
from app.sources import gaf_profile


def parse(session: Session) -> int:
    """Parse the latest saved profile (HTTP 200) of every contractor into its row.

    Args:
        session: An open session. All rows are committed together at the end.

    Returns:
        The number of contractors updated.
    """
    # Ids grow as pages are saved, so the highest id per contractor is its latest page.
    latest_page_ids = (
        select(func.max(RawResponse.id))
        .where(RawResponse.source == gaf_profile.SOURCE, RawResponse.status_code == 200)
        .group_by(RawResponse.contractor_id)
    )
    stored_website_urls = dict(session.execute(select(Contractor.gaf_id, Contractor.website_url)).all())
    pages = session.execute(
        select(RawResponse.contractor_id, RawResponse.body).where(RawResponse.id.in_(latest_page_ids))
    )

    rows = []
    for contractor_id, body in pages:
        row = {"gaf_id": contractor_id, **gaf_profile.parse_profile(body), "updated_at": utc_now()}
        if row["website_url"] != stored_website_urls.get(contractor_id):
            # The website changed or went away, so the last check was of another URL: clear it,
            # and check_websites will check the new one on its next run.
            row.update(website_status=None, website_error=None, website_checked_at=None)
        rows.append(row)

    # The upsert helper can't do this: its INSERT needs every NOT NULL column (name,
    # first_seen_run, ...), even when the row exists. These rows only update, by primary key.
    if rows:
        session.execute(update(Contractor), rows)
    session.commit()
    print(f"parse: {len(rows)} profiles parsed")
    return len(rows)
