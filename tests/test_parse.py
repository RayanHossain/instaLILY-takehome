"""The parse stage, reading saved profile pages from the database."""

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Contractor, RawResponse, Run
from app.pipeline.parse import parse

FIXTURES = Path(__file__).parent / "fixtures"


def save_page(session: Session, run: Run, gaf_id: str, status_code: int, body: str) -> None:
    """Save a profile page for a contractor, as the fetch stage would."""
    session.add(
        RawResponse(
            run_id=run.id,
            contractor_id=gaf_id,
            source="gaf_profile",
            url=f"https://www.gaf.com/en-us/roofing-contractors/roofer-{gaf_id}",
            status_code=status_code,
            body=body,
            content_hash=hashlib.sha256(body.encode()).hexdigest(),
        )
    )
    session.flush()  # flush one at a time, so ids follow the order pages were saved


def test_parse_uses_each_contractors_latest_good_page(session: Session) -> None:
    run = Run(territory_zip="10013", radius_miles=25)
    session.add(run)
    session.flush()
    for gaf_id in ["1113654", "1000002"]:
        session.add(Contractor(gaf_id=gaf_id, name=f"Roofer {gaf_id}", first_seen_run=run.id, last_seen_run=run.id))
    session.flush()

    # An older page, then a newer one, then a failed fetch. The newer 200 page wins.
    save_page(session, run, "1113654", 200, (FIXTURES / "gaf_profile_7158181.html").read_text(encoding="utf-8"))
    save_page(session, run, "1113654", 200, (FIXTURES / "gaf_profile_1113654.html").read_text(encoding="utf-8"))
    save_page(session, run, "1113654", 500, "Internal Server Error")
    session.commit()

    assert parse(session) == 1
    assert parse(session) == 1  # parsing is local, so a rerun parses everything again

    contractor = session.get(Contractor, "1113654")
    assert contractor.street_address == "50 Galesi Dr, Wayne NJ, 07470 USA"
    assert contractor.website_domain == "matuteroofing.com"
    assert (contractor.google_rating, contractor.google_review_count) == (5.0, 501)
    assert contractor.in_business_since == 2009
    assert contractor.name == "Roofer 1113654"  # columns the profile doesn't cover are left alone

    no_profile = session.get(Contractor, "1000002")
    assert no_profile.street_address is None
