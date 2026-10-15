"""The extract stage with a fake model returning fixture output, and the grounding check on its own."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import client as ai
from app.db.models import Contractor, Fact, RawResponse, Run
from app.pipeline.extract import ContractorFacts, FoundedYear, Item, Owner, extract, ground
from app.settings import Settings
from app.sources.gaf_profile import parse_profile

FIXTURES = Path(__file__).parent / "fixtures"
ABOUT = parse_profile((FIXTURES / "gaf_profile_1113654.html").read_text(encoding="utf-8"))["about_text"]
HOMEPAGE = (FIXTURES / "homepage_1113654.html").read_text(encoding="utf-8")
ANSWER = ContractorFacts.model_validate_json((FIXTURES / "facts_1113654.json").read_bytes())  # 13 items, 1 invented
PROFILE_URL = "https://www.gaf.com/en-us/roofing-contractors/residential/usa/nj/wayne/matute-roofing-1113654"
# _env_file=None: never read the developer's .env. The AI client is replaced, so no key is needed.
SETTINGS = Settings(_env_file=None, database_url="unused", coveo_org_id="test-org", coveo_api_key="test-key")


def normalize(text: str) -> str:
    """Lowercase, with whitespace collapsed: how the grounding check compares text."""
    return " ".join(text.lower().split())


def test_extract_stores_grounded_facts_and_replaces_them(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    run = Run(territory_zip="10013", radius_miles=25)
    session.add(run)
    session.flush()
    session.add_all(
        [
            Contractor(
                gaf_id="1113654",
                name="Matute Roofing",
                about_text=ABOUT,
                profile_url=PROFILE_URL,
                first_seen_run=run.id,
                last_seen_run=run.id,
            ),
            Contractor(gaf_id="7158181", name="Golovin Roofing LLC", first_seen_run=run.id, last_seen_run=run.id),
        ]
    )
    session.flush()
    session.add(
        RawResponse(
            run_id=run.id,
            contractor_id="1113654",
            source="contractor_website",
            url="https://matuteroofing.com/",
            status_code=200,
            body=HOMEPAGE,
            content_hash="0" * 64,
        )
    )
    session.commit()

    inputs: list[str] = []
    answers = [ANSWER, ANSWER, ContractorFacts(service_areas=[Item(value="Wayne, NJ", evidence="our home base in Wayne, NJ")])]

    def fake_generate(
        session: Session, settings: Settings, prompt_name: str, input_text: str, output_model: type[ContractorFacts]
    ) -> ContractorFacts:
        inputs.append(input_text)
        return answers.pop(0)

    monkeypatch.setattr(ai, "generate", fake_generate)

    assert extract(session, SETTINGS) == 12  # the invented quote is dropped

    assert len(inputs) == 1  # Golovin has no About text or homepage, so no call
    assert ABOUT in inputs[0]
    assert "Over 20 years serving North Jersey" in inputs[0]  # the homepage's visible text...
    assert "dataLayer" not in inputs[0]  # ...without its scripts
    facts = {fact.value: fact for fact in session.scalars(select(Fact))}
    assert "Solar panels" not in facts
    assert (facts["Roofing"].source, facts["Roofing"].source_url) == ("about_text", PROFILE_URL)
    assert (facts["Metal roofing"].source, facts["Metal roofing"].source_url) == ("homepage", "https://matuteroofing.com/")
    assert {(fact.model, fact.prompt_version) for fact in facts.values()} == {("gemma-4-26b-a4b-it", "extract_facts_v1")}
    source_texts = {"about_text": normalize(ABOUT), "homepage": normalize(BeautifulSoup(HOMEPAGE, "html.parser").get_text(" "))}
    assert all(normalize(fact.evidence) in source_texts[fact.source] for fact in facts.values())

    # A rerun replaces the facts instead of adding to them.
    extract(session, SETTINGS)
    assert session.scalar(select(func.count()).select_from(Fact)) == 12

    # When the input changes, the new answer's facts replace the old ones.
    session.get(Contractor, "1113654").about_text = "Matute Roofing is based in Wayne, NJ."
    session.commit()
    extract(session, SETTINGS)
    assert inputs[2] != inputs[0]
    assert [(fact.field, fact.value) for fact in session.scalars(select(Fact))] == [("service_areas", "Wayne, NJ")]


def test_grounding_drops_an_invented_quote() -> None:
    facts = ContractorFacts(
        founded_year=FoundedYear(value=1998, evidence="Founded in 1998"),
        services=[
            Item(value="Roof repair", evidence="we   REPAIR roofs"),  # case and spacing don't matter
            Item(value="Solar", evidence="we install solar panels"),  # invented: in neither text
        ],
        service_areas=[Item(value="Everywhere", evidence=" ")],  # an empty quote would match any text
        owner_names=[Owner(name="Dana Reyes", role="Owner", evidence="Dana Reyes, Owner")],
    )
    texts = {"about_text": "Founded in 1998 by Dana Reyes, Owner.", "homepage": "Since then we repair roofs across Morris County."}

    rows, dropped = ground(facts, texts)

    assert rows == [
        {"field": "founded_year", "value": "1998", "evidence": "Founded in 1998", "source": "about_text"},
        {"field": "services", "value": "Roof repair", "evidence": "we   REPAIR roofs", "source": "homepage"},
        {"field": "owner_names", "value": "Dana Reyes (Owner)", "evidence": "Dana Reyes, Owner", "source": "about_text"},
    ]
    assert dropped == 2
