"""Lead services: contractors from the latest discover, shaped for the rep UI.

Each function takes an open session and returns Pydantic models. Distance and tier
are worked out on every call from stored columns, and so is a preset's total, from
the stored component scores; none of them is stored.
"""

import math
import re
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import scoring
from app.briefs import Brief
from app.db.models import Contractor, ContractorBrief, Fact, Score
from app.settings import load_territory

# GAF's contractor tiers, highest first.
TIERS = ["President's Club", "Master Elite", "Certified Plus", "Certified"]
# The tags a lead can carry besides the preset names, rarest first, so a narrow column cuts off
# the common ones. Tags name only exceptions, so "Certified", the most common tier, gets none.
OTHER_TAGS = ["New business", "Low rating", "President's Club", "Master Elite", "Certified Plus"]

EARTH_RADIUS_MILES = 3958.8


class LeadScore(BaseModel):
    """A lead's scores under one preset: the total, its four components (0-100), and its flags."""

    preset: str
    total: float  # the preset's weighted sum of the components, worked out when read, never stored
    value: float
    winnability: float
    stability: float
    distance: float
    flags: list[dict[str, str]]  # e.g. {"flag": "Low rating", "kind": "risk", "reason": "rated 3.2 from 41 reviews"}


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
    score: LeadScore | None  # None until the score stage has scored the contractor
    tags: list[str] = []  # in the order of all_tags()


class Signal(BaseModel):
    """One signal behind a component score, from the score stage's reasons."""

    signal: str  # e.g. "reviews"
    input: str  # in plain words, e.g. "312 reviews" or "founding year unknown"
    points: float
    weight: float
    guess: bool = False  # its data was missing, so it scored the neutral middle


class LeadFact(BaseModel):
    """One fact the AI extracted about a contractor, with the exact quote it rests on."""

    id: int
    field: str  # e.g. "services" or "owner_names"
    value: str
    quote: str  # an exact quote from the source text
    source: str  # "about_text" (the GAF profile) or "homepage"
    source_url: str | None


class LeadDetail(BaseModel):
    """Everything the detail panel shows about one contractor."""

    gaf_id: str
    name: str
    street_address: str | None
    city: str | None
    state: str | None
    phone: str | None
    website_url: str | None
    profile_url: str | None
    distance_miles: float | None
    tier: str | None
    certifications: list[str]
    rating: float | None
    review_count: int | None
    # The year the score uses: GAF's "In business since" (scoring.founding_year).
    founded_year: int | None
    enrolled_in_gaf_leads: bool | None
    about_text: str | None
    score: LeadScore | None
    reasons: dict[str, list[Signal]] | None  # each component's signals; None until scored
    top_presets: list[str]  # the presets whose top N it's in under the current scores, shown as tags
    totals: dict[str, float]  # its total under each preset, by name; empty until scored
    brief: Brief | None  # its latest brief, only while it's in a preset's top N
    facts: list[LeadFact]  # every fact extracted about it; a brief cites some of them by id


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


def distance_miles(lat: float | None, lng: float | None, territory: dict[str, Any]) -> float | None:
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
    preset: str | None = None,
    sort: Literal["distance", "total"] = "distance",
    top_n: int = 10,
) -> list[LeadRow]:
    """List the contractors from the most recent discover, nearest first or highest total first.

    Args:
        session: An open session.
        search: Keeps contractors whose name contains it, in any case. A search with no
            letters also matches phone numbers by digits only, so "9735583045" finds
            "(973) 558-3045". None or blank keeps everyone.
        tiers: Keeps contractors in these tiers. None or empty keeps every tier.
        max_miles: Keeps contractors at most this far from the territory center.
        preset: The scoring preset whose weights make each lead's total, e.g. "Quick wins".
            None uses the default, Balanced.
        sort: "distance" for nearest first, or "total" for highest total first. Leads not
            scored yet sort last.
        top_n: How many leads each preset's top takes, for the preset tags. The UI passes
            TOP_LEADS_PER_PRESET, the number the brief stage uses.

    Returns:
        One LeadRow per matching contractor, with its tags.

    Raises:
        ValueError: The preset isn't one in config/scoring.yaml.
    """
    top = top_leads(session, top_n)
    leads = _rows(session, search, tiers, max_miles, preset, sort)
    for lead in leads:
        lead.tags = _tags(lead, top)
    return leads


def briefed_top_leads(session: Session, top_n: int) -> list[LeadRow]:
    """Every lead in any preset's top_n that has a brief, with its tags: the leads Top leads steps through.

    Leads in the most presets' tops come first, so the ones every preset picks lead the
    list. Among leads in as many tops, the best place in any of its presets' rankings
    comes first (1st before 3rd), and ties stay nearest first. Places, not totals, because
    some presets' weights give higher totals than others. A top lead whose brief hasn't
    been written yet is left out.
    """
    top = top_leads(session, top_n)
    briefed = set(session.scalars(select(ContractorBrief.contractor_id)))
    ranked = []  # (how many tops it's in, its best place in them, counting from 0, the lead)
    for lead in _rows(session):  # nearest first, so the sort below keeps ties nearest first
        places = [ids.index(lead.gaf_id) for ids in top.values() if lead.gaf_id in ids]
        if places and lead.gaf_id in briefed:
            lead.tags = _tags(lead, top)
            ranked.append((len(places), min(places), lead))
    ranked.sort(key=lambda entry: (-entry[0], entry[1]))
    return [lead for _, _, lead in ranked]


def all_tags() -> list[str]:
    """Every tag a lead can carry, in the order they show: the preset names, then OTHER_TAGS.

    A preset's name tags the leads in its top N. The names come from config/scoring.yaml,
    so a new preset gets its own tag.
    """
    return [*scoring.load_scoring_config().presets, *OTHER_TAGS]


def top_leads(session: Session, top_n: int) -> dict[str, list[str]]:
    """Each preset's top_n scored leads, highest total first, as GAF IDs.

    Ranked by the same function that sorts the lead table, so the table, its tags, and
    the brief stage can't drift apart.
    """
    return {
        preset: [lead.gaf_id for lead in _rows(session, preset=preset, sort="total") if lead.score][:top_n]
        for preset in scoring.load_scoring_config().presets
    }


def _rows(
    session: Session,
    search: str | None = None,
    tiers: list[str] | None = None,
    max_miles: float | None = None,
    preset: str | None = None,
    sort: Literal["distance", "total"] = "distance",
) -> list[LeadRow]:
    """The lead table's rows without their tags: list_leads does the filtering and sorting here."""
    territory = load_territory()
    preset_name, weights = _preset(preset)
    scores = {score.contractor_id: score for score in session.scalars(select(Score))}
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

        distance = distance_miles(contractor.lat, contractor.lng, territory)
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
                score=_lead_score(scores.get(contractor.gaf_id), preset_name, weights),
            )
        )

    # A contractor without coordinates sorts last.
    leads.sort(key=lambda lead: math.inf if lead.distance_miles is None else lead.distance_miles)
    if sort == "total":
        # The sort is stable, so equal totals stay nearest first.
        leads.sort(key=lambda lead: -lead.score.total if lead.score else math.inf)
    return leads


def _tags(lead: LeadRow, top: dict[str, list[str]]) -> list[str]:
    """The lead's exceptions, in the order of all_tags(): each preset whose top N it's in, its flags, and its tier unless plain Certified."""
    top_presets = [preset for preset, ids in top.items() if lead.gaf_id in ids]
    others = [lead.tier] if lead.tier in OTHER_TAGS else []
    others += [flag["flag"] for flag in lead.score.flags] if lead.score else []
    return top_presets + sorted(others, key=OTHER_TAGS.index)


def get_lead(session: Session, gaf_id: str, preset: str | None = None, top_n: int = 10) -> LeadDetail:
    """Return the details of one contractor: its scores under the preset, its total under every preset, their reasons, its brief, and its facts.

    A brief is written for each preset's top_n leads. One written under older rules stays
    stored, but is returned only while its lead is in a top_n under the current scores.

    Raises:
        LookupError: No contractor has this GAF ID.
        ValueError: The preset isn't one in config/scoring.yaml.
    """
    contractor = session.get(Contractor, gaf_id)
    if contractor is None:
        raise LookupError(f"No contractor with GAF ID {gaf_id}")
    preset_name, weights = _preset(preset)
    score = session.get(Score, gaf_id)
    stored_brief = session.get(ContractorBrief, gaf_id)
    top_presets = [name for name, ids in top_leads(session, top_n).items() if gaf_id in ids]
    presets = scoring.load_scoring_config().presets
    totals = {name: scoring.total(score, preset_weights) for name, preset_weights in presets.items()} if score else {}
    facts = session.scalars(select(Fact).where(Fact.contractor_id == gaf_id).order_by(Fact.id))
    founded_year, _ = scoring.founding_year(contractor.in_business_since)

    return LeadDetail(
        gaf_id=contractor.gaf_id,
        name=contractor.name,
        street_address=contractor.street_address,
        city=contractor.city,
        state=contractor.state,
        phone=contractor.phone,
        website_url=contractor.website_url,
        profile_url=contractor.profile_url,
        distance_miles=distance_miles(contractor.lat, contractor.lng, load_territory()),
        tier=tier(contractor.certifications),
        certifications=contractor.certifications,
        rating=contractor.rating,
        review_count=contractor.review_count,
        founded_year=founded_year,
        enrolled_in_gaf_leads=contractor.enrolled_in_gaf_leads,
        about_text=contractor.about_text,
        score=_lead_score(score, preset_name, weights),
        reasons={component: [Signal(**signal) for signal in signals] for component, signals in score.reasons.items()} if score else None,
        top_presets=top_presets,
        totals=totals,
        brief=Brief.model_validate(stored_brief.content) if stored_brief and top_presets else None,
        facts=[
            LeadFact(id=fact.id, field=fact.field, value=fact.value, quote=fact.evidence, source=fact.source, source_url=fact.source_url)
            for fact in facts
        ],
    )


def _preset(name: str | None) -> tuple[str, scoring.Preset]:
    """The named scoring preset, or the default one when name is None, with its weights."""
    config = scoring.load_scoring_config()
    name = name or config.default_preset
    if name not in config.presets:
        raise ValueError(f"Unknown preset {name!r}; choose from {', '.join(config.presets)}")
    return name, config.presets[name]


def _lead_score(score: Score | None, preset_name: str, weights: scoring.Preset) -> LeadScore | None:
    """A stored score's total under the preset, with its components and flags; None if not scored yet."""
    if score is None:
        return None
    return LeadScore(
        preset=preset_name,
        total=scoring.total(score, weights),
        value=score.value,
        winnability=score.winnability,
        stability=score.stability,
        distance=score.distance,
        flags=score.flags,
    )
