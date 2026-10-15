"""Discover stage: find every GAF contractor in the territory and store them.

Each run opens a runs row, saves every Coveo response before parsing it, and
upserts the contractors keyed on GAF's ID. Rerunning is safe: a contractor seen
again is updated in place and keeps the run it was first seen in.
"""

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Contractor, RawResponse, Run, utc_now
from app.db.upsert import upsert
from app.settings import Settings
from app.sources import coveo


def discover(session: Session, territory: dict[str, Any], settings: Settings) -> Run:
    """Fetch every contractor near the territory from GAF's search and upsert them.

    Args:
        session: An open session. Work is committed page by page.
        territory: The territory from config/distributor.yaml (zip, lat, lng, radius_miles).
        settings: App settings, for the Coveo org ID and API key.

    Returns:
        The closed run, with status "finished" and the number of contractors seen.
        If anything fails, the run is closed as "failed" and the error is re-raised.
        Without a Coveo key it exits before opening a run.
    """
    # .env.example ships "replace-me", so a copied placeholder counts as no key.
    if not settings.coveo_api_key or settings.coveo_api_key.get_secret_value() == "replace-me":
        raise SystemExit("COVEO_API_KEY is not set. Put a Coveo API key in .env to run discover.")

    run = Run(territory_zip=territory["zip"], radius_miles=territory["radius_miles"])
    session.add(run)
    session.commit()

    seen_ids: set[str] = set()
    try:
        pages = coveo.fetch_pages(
            settings.coveo_org_id,
            settings.coveo_api_key.get_secret_value(),  # checked above
            territory["lat"],
            territory["lng"],
            territory["radius_miles"],
        )
        for page_number, response in enumerate(pages, start=1):
            # Save the raw body first, so it's kept even if parsing fails.
            session.add(
                RawResponse(
                    run_id=run.id,
                    source="coveo",
                    url=str(response.url),
                    status_code=response.status_code,
                    content_type=response.headers.get("content-type"),
                    request_body=json.loads(response.request.content),  # holds firstResult, the page offset
                    body=response.text,
                    content_hash=hashlib.sha256(response.content).hexdigest(),
                )
            )
            session.commit()

            rows = []
            for result in response.json()["results"]:
                row = coveo.parse_result(result)
                row.update(first_seen_run=run.id, last_seen_run=run.id, updated_at=utc_now())
                rows.append(row)
            upsert(session, Contractor, rows, key_column="gaf_id", keep_on_conflict=["first_seen_run"])
            session.commit()
            seen_ids.update(row["gaf_id"] for row in rows)  # count only what was stored
            print(f"discover: page {page_number} saved, {len(rows)} contractors upserted")

        run.status = "finished"
    except BaseException:  # includes SystemExit from a rejected key and Ctrl-C
        session.rollback()
        run.status = "failed"
        raise
    finally:
        run.finished_at = utc_now()
        run.contractors_seen = len(seen_ids)
        session.commit()

    return run
