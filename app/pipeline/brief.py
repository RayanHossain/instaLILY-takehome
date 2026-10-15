"""Brief stage: a short touch plan for each preset's top leads, written by the AI from the facts it's given.

The leads are the union of every preset's top N by total (N is TOP_LEADS_PER_PRESET,
10 by default), ranked by the same list_leads the services use, so the two can't drift
apart. Each lead's input is its name, city, tier, reviews and rating, years in business,
distance, facts with their ids and quotes, and matched selling points: the evidence
behind its scores in plain words, never a score component's name, and never its total,
rank, or preset. A lead whose input is unchanged since its brief was written is
skipped, so a rerun makes no AI calls and a weight change only briefs newcomers.
"""

import hashlib
from collections import Counter
from dataclasses import dataclass
from functools import partial

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import briefs, scoring
from app.ai import client as ai
from app.db.models import Contractor, ContractorBrief, Fact, Score, StageRun, utc_now
from app.db.upsert import upsert
from app.services.leads import list_leads, tier
from app.settings import Settings, load_selling_points

PROMPT = "write_brief_v2"  # v2 describes the evidence in plain words and never names a score component


@dataclass
class LeadInput:
    """What the AI is told about one lead, and what checking its brief needs."""

    text: str
    fact_ids: set[int]
    matched: dict[str, str]  # selling point id -> why it fits
    owners: list[str]


def pick_leads(session: Session, top_n: int) -> list[str]:
    """The GAF IDs in any preset's top_n by total, each once, in the order first met.

    Ranked by the services' own list_leads, so the briefs and the lead list can't drift apart.
    """
    picked: list[str] = []
    for preset in scoring.load_scoring_config().presets:
        for lead in list_leads(session, preset=preset, sort="total")[:top_n]:
            if lead.score is not None and lead.gaf_id not in picked:
                picked.append(lead.gaf_id)
    return picked


def lead_input(session: Session, gaf_id: str, selling_points: dict[str, str]) -> LeadInput:
    """Everything the brief may use about one scored lead, as text in plain words.

    The evidence behind its scores is written as a rep would say it ("103 GAF reviews
    averaging 5.0"), never under a score component's name, and its total, rank, and
    preset are never given.
    """
    contractor = session.get(Contractor, gaf_id)
    score = session.get(Score, gaf_id)
    facts = session.scalars(select(Fact).where(Fact.contractor_id == gaf_id).order_by(Fact.id)).all()
    contractor_tier = tier(contractor.certifications)
    matched = briefs.match_selling_points(
        tier=contractor_tier,
        other_trades=[fact.value for fact in facts if fact.field == "other_trades"],
        services=[fact.value for fact in facts if fact.field == "services"],
        postal_code=contractor.postal_code,
        stability=score.stability,
        flags=score.flags,
    )
    owners = [fact.value for fact in facts if fact.field == "owner_names"]
    # The evidence behind its scores, in plain words; other trades come through its facts.
    reviews = contractor.review_count or 0
    rating = f"{reviews} GAF review{'s' if reviews != 1 else ''} averaging {contractor.rating:.1f}" if contractor.rating else "no GAF reviews yet"
    years = next(signal["input"] for signal in score.reasons["winnability"] if signal["signal"] == "years in business")
    distance = score.reasons["distance"][0]["input"]  # e.g. "6.1 miles from the branch"

    lines = [
        f"Contractor: {contractor.name}, {contractor.city}, {contractor.state}",
        f"GAF tier: {contractor_tier or 'none'}",
        f"Reviews: {rating}",
        f"Years in business: {years}",
        f"Distance: {distance}",
        "",
        "Facts from its GAF profile and website, each with its id and the quote it comes from:"
        if facts
        else "No facts are known about this contractor beyond the lines above.",
        *[f'[{fact.id}] {fact.field}: {fact.value} (quote: "{fact.evidence}")' for fact in facts],
        "",
        "Selling points that fit it (use only these):",
        *[f"- {point}: {selling_points[point]} It fits because {reason}." for point, reason in matched.items()],
        "",
        f"Owner: {'; '.join(owners)}" if owners else "No owner name is known.",
    ]
    return LeadInput(text="\n".join(lines), fact_ids={fact.id for fact in facts}, matched=matched, owners=owners)


def brief(session: Session, settings: Settings) -> int:
    """Write a brief for each lead in a preset's top N, unless its input is unchanged since its last one.

    A brief that fails its checks gets the AI client's one retry with the problems shown;
    if it fails again, or the API keeps failing, the lead is counted and skipped, and the
    next run tries again. The run is a stage_runs row whose totals add leads picked,
    briefs written, leads unchanged, leads skipped, and how often each selling point matched.

    Args:
        session: An open session. Each brief is committed as soon as it is written.
        settings: The AI settings, and TOP_LEADS_PER_PRESET.

    Returns:
        The number of briefs written.
    """
    selling_points = load_selling_points()
    lead_ids = pick_leads(session, settings.top_leads_per_preset)
    run = StageRun(stage="brief", model=settings.gemini_model)
    session.add(run)
    session.commit()

    written = unchanged = skipped = 0
    matches: Counter[str] = Counter()
    try:
        for number, gaf_id in enumerate(lead_ids, start=1):
            lead = lead_input(session, gaf_id, selling_points)
            matches.update(lead.matched.keys())
            input_hash = hashlib.sha256(lead.text.encode()).hexdigest()
            stored = session.get(ContractorBrief, gaf_id)
            if stored and (stored.input_hash, stored.model, stored.prompt_version) == (input_hash, settings.gemini_model, PROMPT):
                unchanged += 1
                print(f"brief: {number}/{len(lead_ids)} {gaf_id} unchanged, skipped")
                continue

            check = partial(briefs.check_brief, fact_ids=lead.fact_ids, matched_points=set(lead.matched), owners=lead.owners)
            result = ai.generate(session, settings, PROMPT, lead.text, briefs.Brief, run=run, contractor_id=gaf_id, check=check)
            if result is None:
                skipped += 1
                print(f"brief: {number}/{len(lead_ids)} {gaf_id} no valid brief, so skipped (its attempts are in ai_calls)")
                continue
            row = {
                "contractor_id": gaf_id,
                "content": result.model_dump(),
                "input_hash": input_hash,
                "model": settings.gemini_model,
                "prompt_version": PROMPT,
                "created_at": utc_now(),
            }
            upsert(session, ContractorBrief, [row], key_column="contractor_id", keep_on_conflict=[])
            session.commit()
            written += 1
            print(f"brief: {number}/{len(lead_ids)} {gaf_id} written, citing {len(result.cited_fact_ids)} facts")
        run.status = "finished"
    except BaseException:  # includes SystemExit when the AI client stops the stage, and Ctrl-C
        session.rollback()
        run.status = "failed"
        raise
    finally:
        run.finished_at = utc_now()
        run.totals = {
            **ai.totals(session, run),
            "leads picked": len(lead_ids),
            "briefs written": written,
            "leads unchanged": unchanged,
            "leads skipped": skipped,
            **{f"matched {point}": matches[point] for point in selling_points},
        }
        session.commit()
        print(f"brief: {run.status}: " + ", ".join(f"{name} {value}" for name, value in run.totals.items()))
    return written
