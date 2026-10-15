"""The parse stage, reading saved profile pages from the database."""

import hashlib
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Contractor, RawResponse, Run, utc_now
from app.pipeline.parse import parse

FIXTURES = Path(__file__).parent / "fixtures"
WITH_EVERYTHING = (FIXTURES / "gaf_profile_1113654.html").read_text(encoding="utf-8")
WITH_NOTHING = (FIXTURES / "gaf_profile_7158181.html").read_text(encoding="utf-8")


def save_page(session: Session, run: Run, gaf_id: str | None, status_code: int, body: str, source: str = "gaf_profile") -> None:
    """Save a page as the fetch stage would (or, with source="coveo", as discover would)."""
    session.add(
        RawResponse(
            run_id=run.id,
            contractor_id=gaf_id,
            source=source,
            url=f"https://www.gaf.com/en-us/roofing-contractors/roofer-{gaf_id}",
            status_code=status_code,
            body=body,
            content_hash=hashlib.sha256(body.encode()).hexdigest(),
        )
    )
    session.flush()  # flush one at a time, so ids follow the order pages were saved


def make_run_with_contractors(session: Session, *gaf_ids: str) -> Run:
    """Add a discover run and contractors last seen in it."""
    run = Run(territory_zip="10013", radius_miles=25)
    session.add(run)
    session.flush()
    for gaf_id in gaf_ids:
        session.add(Contractor(gaf_id=gaf_id, name=f"Roofer {gaf_id}", first_seen_run=run.id, last_seen_run=run.id))
    session.flush()
    return run


def test_parse_uses_each_contractors_latest_good_page(session: Session) -> None:
    run = make_run_with_contractors(session, "1113654", "7158181", "1000003")
    # For 1113654: an older page, a newer one, then a failed fetch. The newer 200 page wins.
    save_page(session, run, "1113654", 200, WITH_NOTHING)
    save_page(session, run, "1113654", 200, WITH_EVERYTHING)
    save_page(session, run, "1113654", 500, "Internal Server Error")
    save_page(session, run, "7158181", 200, WITH_NOTHING)
    save_page(session, run, None, 200, '{"results": []}', source="coveo")  # a search page is not a profile
    session.commit()

    assert parse(session) == 2
    assert parse(session) == 2  # parsing is local, so a rerun parses everything again

    full = session.get(Contractor, "1113654")
    assert full.street_address == "50 Galesi Dr, Wayne NJ, 07470 USA"
    assert full.website_domain == "matuteroofing.com"
    assert (full.google_rating, full.google_review_count) == (5.0, 501)
    assert full.in_business_since == 2009
    assert full.name == "Roofer 1113654"  # columns the profile doesn't cover are left alone

    sparse = session.get(Contractor, "7158181")
    assert sparse.street_address == "36-20 168th St, Flushing NY, 11358 USA"
    assert sparse.website_url is None

    assert session.get(Contractor, "1000003").street_address is None  # never fetched


def test_parse_clears_the_website_check_when_the_website_changes(session: Session) -> None:
    run = make_run_with_contractors(session, "1113654")
    save_page(session, run, "1113654", 200, WITH_EVERYTHING)
    session.commit()
    parse(session)
    contractor = session.get(Contractor, "1113654")
    contractor.website_status, contractor.website_checked_at = 200, utc_now()
    session.commit()

    parse(session)  # same website: the check still applies
    assert contractor.website_status == 200

    save_page(session, run, "1113654", 200, WITH_EVERYTHING.replace("www.matuteroofing.com", "www.new-roofer.example"))
    session.commit()
    parse(session)  # new website: the old check was of another URL
    assert contractor.website_domain == "new-roofer.example"
    assert (contractor.website_status, contractor.website_checked_at) == (None, None)
