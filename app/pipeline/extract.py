"""Extract stage: structured facts about each contractor, each tied to an exact quote.

The input is the contractor's About text (from its GAF profile) and the visible text of
its saved homepage. The model answers through app/ai, and the grounding check here
keeps only the items whose quote is in that input. Every run rebuilds each contractor's
facts from its current input; an unchanged input is answered from the AI cache, so a
rerun makes no calls.
"""

from collections import Counter

from bs4 import BeautifulSoup
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ai import client as ai
from app.db.models import Contractor, Fact, RawResponse, StageRun, utc_now
from app.settings import Settings
from app.sources import websites

PROMPT = "extract_facts_v1"
HOMEPAGE_CHARS = 4000  # the homepage's visible text is cut to this many characters
# How each source's text is introduced to the model.
HEADINGS = {
    "about_text": "About text, from the contractor's GAF profile:",
    "homepage": "Text of the contractor's homepage:",
}
# How a contractor is counted in the run's totals, by the sources its input had.
INPUT_KINDS = {
    ("about_text",): "About text only",
    ("homepage",): "homepage only",
    ("about_text", "homepage"): "About text and homepage",
}


class Item(BaseModel):
    """One extracted value and the exact quote it rests on."""

    value: str
    evidence: str


class FoundedYear(BaseModel):
    """The year the business started and the exact quote that gives it."""

    value: int
    evidence: str


class Owner(BaseModel):
    """An owner, founder, president, or CEO named in the text, and the exact quote."""

    name: str
    role: str | None = None
    evidence: str


class ContractorFacts(BaseModel):
    """What the text states about one contractor; empty or null where it says nothing."""

    founded_year: FoundedYear | None = None
    services: list[Item] = []
    other_trades: list[Item] = []
    building_types: list[Item] = []
    service_areas: list[Item] = []
    owner_names: list[Owner] = []


def extract(session: Session, settings: Settings) -> int:
    """Rebuild the facts of every contractor in the latest discover from its About text and homepage.

    A contractor with neither gets no AI call and keeps no facts. One whose answer is
    still invalid after the AI client's retry is counted and keeps no facts. The run is
    a stage_runs row; when it ends, finished or not, it gets its totals: the AI client's
    counts from ai_calls, then contractors by input, facts kept, and grounding drops.

    Args:
        session: An open session. Each contractor's facts are committed together.
        settings: For the AI client: the Gemini key, model, and requests per minute.

    Returns:
        The number of facts stored.
    """
    # Discover sets last_seen_run, so the highest one is the most recent discover run.
    latest_run = session.scalar(select(func.max(Contractor.last_seen_run)))
    contractors = session.execute(
        select(Contractor.gaf_id, Contractor.about_text, Contractor.profile_url)
        .where(Contractor.last_seen_run == latest_run)
        .order_by(Contractor.gaf_id)
    ).all()
    # Ids grow as pages are saved, so the highest id per contractor is its latest homepage.
    latest_homepage_ids = (
        select(func.max(RawResponse.id))
        .where(RawResponse.source == websites.HOMEPAGE_SOURCE, RawResponse.status_code == 200)
        .group_by(RawResponse.contractor_id)
    )
    homepages = {
        contractor_id: (url, html)
        for contractor_id, url, html in session.execute(
            select(RawResponse.contractor_id, RawResponse.url, RawResponse.body).where(
                RawResponse.id.in_(latest_homepage_ids)
            )
        )
    }

    run = StageRun(stage="extract", model=settings.gemini_model)
    session.add(run)
    session.commit()

    inputs: Counter[str] = Counter()  # contractors by the sources their input had
    stored = dropped = failed = 0
    try:
        for number, (gaf_id, about_text, profile_url) in enumerate(contractors, start=1):
            texts: dict[str, str] = {}  # source -> its text, as the model sees it
            urls: dict[str, str | None] = {}  # source -> where that text came from
            if about_text:
                texts["about_text"], urls["about_text"] = about_text, profile_url
            homepage_url, html = homepages.get(gaf_id, (None, None))
            homepage_text = " ".join(BeautifulSoup(html, "html.parser").get_text(" ").split()) if html else ""
            if homepage_text:
                texts["homepage"], urls["homepage"] = homepage_text[:HOMEPAGE_CHARS], homepage_url

            rows: list[dict[str, str]] = []
            if texts:
                inputs[INPUT_KINDS[tuple(texts)]] += 1
                input_text = "\n\n".join(f"{HEADINGS[source]}\n{text}" for source, text in texts.items())
                facts = ai.generate(session, settings, PROMPT, input_text, ContractorFacts, run=run, contractor_id=gaf_id)
                if facts is None:
                    failed += 1
                    outcome = "answer still invalid after the retry, so no facts"
                else:
                    rows, drops = ground(facts, texts)
                    dropped += drops
                    outcome = f"{len(rows)} facts" + (f", {drops} dropped by the grounding check" if drops else "")
                print(f"extract: {number}/{len(contractors)} {gaf_id} {outcome}")

            # Replace the contractor's facts. No text, or an answer still invalid, leaves none.
            # "fetch" also drops the deleted facts from the session, so a new fact that reuses
            # a deleted one's id can't clash with a stale copy the caller still holds.
            session.execute(delete(Fact).where(Fact.contractor_id == gaf_id).execution_options(synchronize_session="fetch"))
            extracted_at = utc_now()
            session.add_all(
                Fact(
                    contractor_id=gaf_id,
                    **row,
                    source_url=urls[row["source"]],
                    model=settings.gemini_model,
                    prompt_version=PROMPT,
                    extracted_at=extracted_at,
                )
                for row in rows
            )
            session.commit()
            stored += len(rows)
        run.status = "finished"
    except BaseException:  # includes SystemExit when the AI client stops the stage, and Ctrl-C
        session.rollback()
        run.status = "failed"
        raise
    finally:
        run.finished_at = utc_now()
        run.totals = {
            **ai.totals(session, run),
            "contractors with text": sum(inputs.values()),
            **{kind: inputs[kind] for kind in INPUT_KINDS.values()},
            "facts kept": stored,
            "grounding drops": dropped,
            "answers still invalid": failed,
        }
        session.commit()
        print(f"extract: {run.status}: " + ", ".join(f"{name} {value}" for name, value in run.totals.items()))
    return stored


def ground(facts: ContractorFacts, texts: dict[str, str]) -> tuple[list[dict[str, str]], int]:
    """Keep each extracted item whose evidence quote appears in one of the texts, and count the others.

    Quotes and texts are compared after lowercasing and collapsing whitespace. An empty
    quote is dropped too: it would appear in any text.

    Args:
        facts: The model's answer.
        texts: Source ("about_text" or "homepage") -> the text the model was given.

    Returns:
        A row per kept item, like {"field": "services", "value": "Roof repair",
        "evidence": "we repair roofs", "source": "homepage"}, and the number dropped.
    """
    items: list[tuple[str, str, str]] = []  # (field, value, evidence)
    if facts.founded_year:
        items.append(("founded_year", str(facts.founded_year.value), facts.founded_year.evidence))
    for field, values in [
        ("services", facts.services),
        ("other_trades", facts.other_trades),
        ("building_types", facts.building_types),
        ("service_areas", facts.service_areas),
    ]:
        items += [(field, item.value, item.evidence) for item in values]
    # The facts table has no role column, so an owner's role follows the name in parentheses.
    items += [
        ("owner_names", f"{owner.name} ({owner.role})" if owner.role else owner.name, owner.evidence)
        for owner in facts.owner_names
    ]

    normalized = {source: " ".join(text.lower().split()) for source, text in texts.items()}
    rows, dropped = [], 0
    for field, value, evidence in items:
        quote = " ".join(evidence.lower().split())
        # The first source that contains the quote: the About text is checked first.
        source = next((source for source, text in normalized.items() if quote and quote in text), None)
        if source is None:
            dropped += 1
        else:
            rows.append({"field": field, "value": value, "evidence": evidence, "source": source})
    return rows, dropped
