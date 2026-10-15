"""Score stage: four component scores, flags, and reasons for every contractor in the latest discover.

Rules only, no AI: every number is in config/scoring.yaml, and app/scoring.py applies
them. Scoring is cheap, so every run rescores everyone and upserts; the same data and
rules always give the same scores, flags, and reasons.
"""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import scoring
from app.db.models import Contractor, Fact, Score, utc_now
from app.db.upsert import upsert
from app.services.leads import distance_miles, tier
from app.settings import load_territory


def score(session: Session, current_year: int) -> int:
    """Score every contractor in the latest discover, and upsert its row in scores.

    The founding year is the earliest the GAF profile and the extracted facts give; the
    reasons record which source it came from.

    Args:
        session: An open session. All rows are committed together.
        current_year: The year to count years in business up to, passed in so that tests
            don't depend on the clock.

    Returns:
        The number of contractors scored.
    """
    config = scoring.load_scoring_config()
    territory = load_territory()
    # Discover sets last_seen_run, so the highest one is the most recent discover run.
    latest_run = session.scalar(select(func.max(Contractor.last_seen_run)))
    contractors = session.scalars(
        select(Contractor).where(Contractor.last_seen_run == latest_run).order_by(Contractor.gaf_id)
    ).all()

    # The facts the rules use: other trades, and the founding year the contractor's own text gives.
    other_trades: defaultdict[str, set[str]] = defaultdict(set)
    founded_facts: dict[str, int] = {}
    for contractor_id, field, value in session.execute(
        select(Fact.contractor_id, Fact.field, Fact.value).where(Fact.field.in_(["other_trades", "founded_year"]))
    ):
        if field == "other_trades":
            other_trades[contractor_id].add(value)
        else:
            founded_facts[contractor_id] = int(value)

    rows = []
    for contractor in contractors:
        founded_year, founded_from = scoring.founding_year(contractor.in_business_since, founded_facts.get(contractor.gaf_id))
        scored = scoring.score_contractor(
            config,
            review_count=contractor.review_count,
            rating=contractor.rating,
            tier=tier(contractor.certifications),
            other_trades=sorted(other_trades[contractor.gaf_id]),  # sorted, so a rerun gives the same reasons
            founded_year=founded_year,
            founded_from=founded_from,
            distance_miles=distance_miles(contractor.lat, contractor.lng, territory),
            radius_miles=territory["radius_miles"],
            current_year=current_year,
        )
        rows.append({"contractor_id": contractor.gaf_id, **scored, "scored_at": utc_now()})

    upsert(session, Score, rows, key_column="contractor_id", keep_on_conflict=[])
    session.commit()
    print(f"score: {len(rows)} contractors scored with rules version {config.rules_version}")
    return len(rows)
