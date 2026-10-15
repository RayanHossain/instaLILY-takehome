"""Lead services: contractors from the latest discover, shaped for the rep UI.

Each function takes an open session and returns Pydantic models. Distance and tier
are worked out on every call from stored columns; neither is stored.
"""

import math
import re
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Contractor
from app.settings import load_territory

# GAF's contractor tiers, highest first.
TIERS = ["President's Club", "Master Elite", "Certified Plus", "Certified"]

EARTH_RADIUS_MILES = 3958.8


class LeadRow(BaseModel):
    """One contractor in the lead table."""

    gaf_id: str
    name: str
    city: str | None
    state: str | None
    distance_miles: float | None  # None when GAF gave no coordinates
    tier: str | None  # None when no certification names a tier
    rating: float | None  # None when there are no reviews
    review_count: int | None
    phone: str | None
    enrolled_in_gaf_leads: bool | None  # None means GAF didn't say


class LeadDetail(BaseModel):
    """Everything the detail panel shows about one contractor."""

    gaf_id: str
    name: str
    street_address: str | None
    phone: str | None
    website_url: str | None
    profile_url: str | None
    distance_miles: float | None
    tier: str | None
    certifications: list[str]
    rating: float | None
    review_count: int | None
    in_business_since: int | None
    enrolled_in_gaf_leads: bool | None
    about_text: str | None


def tier(certifications: list[str]) -> str | None:
    """Return the highest tier that any of the contractor's certifications names, or None.

    GAF's labels wrap the tier name, e.g. "GAF Master Elite® - Certification" or
    "President's Club - Award". Tiers are checked highest first, which also keeps
    "Certified" from matching a "Certified Plus" label.
    """
    for level in TIERS:
        if any(level in certification for certification in certifications):
            return level
    return None


def _distance_miles(lat: float | None, lng: float | None, territory: dict[str, Any]) -> float | None:
    """Great-circle (haversine) distance in miles from the territory center, or None without coordinates."""
    if lat is None or lng is None:
        return None
    lat1, lng1, lat2, lng2 = map(math.radians, (territory["lat"], territory["lng"], lat, lng))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def list_leads(
    session: Session,
    search: str | None = None,
    tiers: list[str] | None = None,
    max_miles: float | None = None,
) -> list[LeadRow]:
    """List the contractors from the most recent discover, nearest first.

    Args:
        session: An open session.
        search: Keeps contractors whose name contains it, in any case. A search with no
            letters also matches phone numbers by digits only, so "9735583045" finds
            "(973) 558-3045". None or blank keeps everyone.
        tiers: Keeps contractors in these tiers. None or empty keeps every tier.
        max_miles: Keeps contractors at most this far from the territory center.

    Returns:
        One LeadRow per matching contractor, sorted by distance.
    """
    territory = load_territory()
    # Discover sets last_seen_run, so the highest one is the most recent discover run.
    latest_run = select(func.max(Contractor.last_seen_run)).scalar_subquery()
    contractors = session.scalars(select(Contractor).where(Contractor.last_seen_run == latest_run))

    search = (search or "").strip()
    # Only a search with no letters is tried against phones, so "A1 Roofing" doesn't
    # match every phone number that has a 1 in it.
    search_digits = "" if re.search(r"[A-Za-z]", search) else re.sub(r"\D", "", search)

    leads = []
    for contractor in contractors:
        if search:
            name_matches = search.lower() in contractor.name.lower()
            phone_matches = bool(search_digits) and search_digits in re.sub(r"\D", "", contractor.phone or "")
            if not (name_matches or phone_matches):
                continue

        contractor_tier = tier(contractor.certifications)
        if tiers and contractor_tier not in tiers:
            continue

        distance = _distance_miles(contractor.lat, contractor.lng, territory)
        if max_miles is not None and (distance is None or distance > max_miles):
            continue

        leads.append(
            LeadRow(
                gaf_id=contractor.gaf_id,
                name=contractor.name,
                city=contractor.city,
                state=contractor.state,
                distance_miles=distance,
                tier=contractor_tier,
                rating=contractor.rating,
                review_count=contractor.review_count,
                phone=contractor.phone,
                enrolled_in_gaf_leads=contractor.enrolled_in_gaf_leads,
            )
        )

    # A contractor without coordinates sorts last.
    leads.sort(key=lambda lead: math.inf if lead.distance_miles is None else lead.distance_miles)
    return leads


def get_lead(session: Session, gaf_id: str) -> LeadDetail:
    """Return the details of one contractor.

    Raises:
        LookupError: No contractor has this GAF ID.
    """
    contractor = session.get(Contractor, gaf_id)
    if contractor is None:
        raise LookupError(f"No contractor with GAF ID {gaf_id}")

    return LeadDetail(
        gaf_id=contractor.gaf_id,
        name=contractor.name,
        street_address=contractor.street_address,
        phone=contractor.phone,
        website_url=contractor.website_url,
        profile_url=contractor.profile_url,
        distance_miles=_distance_miles(contractor.lat, contractor.lng, load_territory()),
        tier=tier(contractor.certifications),
        certifications=contractor.certifications,
        rating=contractor.rating,
        review_count=contractor.review_count,
        in_business_since=contractor.in_business_since,
        enrolled_in_gaf_leads=contractor.enrolled_in_gaf_leads,
        about_text=contractor.about_text,
    )
