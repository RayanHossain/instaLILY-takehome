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
    pages = session.execute(
        select(RawResponse.contractor_id, RawResponse.body).where(RawResponse.id.in_(latest_page_ids))
    )
    rows = [
        {"gaf_id": contractor_id, **gaf_profile.parse_profile(body), "updated_at": utc_now()}
        for contractor_id, body in pages
    ]

    # The upsert helper can't do this: its INSERT needs every NOT NULL column (name,
    # first_seen_run, ...), even when the row exists. These rows only update, by primary key.
    if rows:
        session.execute(update(Contractor), rows)
    session.commit()
    print(f"parse: {len(rows)} profiles parsed")
    return len(rows)
