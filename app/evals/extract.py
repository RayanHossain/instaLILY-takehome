"""Extraction eval: each extracted field's precision and recall against hand-checked gold facts.

The gold file is evals/extract_gold.yaml. Each gold contractor's input is built exactly as
the extract stage builds it, so its answer comes from the AI cache when the stage has
already asked; the AI is called only on a cache miss. That exact input is also written to
evals/inputs/<GAF ID>.txt, to check the gold file against the source text. The answer
goes through the stage's grounding check, then each field's values are compared with
the gold values, ignoring case, punctuation, spacing, and a trailing plural "s".
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.ai import client as ai
from app.db.models import Contractor, StageRun, utc_now
from app.pipeline import extract
from app.settings import Settings

GOLD = Path("evals/extract_gold.yaml")
INPUTS = Path("evals/inputs")  # each gold contractor's exact input, rewritten on every run
FIELDS =["founded_year", "services", "other_trades", "building_types", "service_areas", "owner_names"]


@dataclass
class FieldScore:
    """One field's counts over the gold contractors, and the precision and recall they give."""

    field: str
    gold: int = 0  # values in the gold file
    found: int = 0  # values the model found, after the grounding check
    right: int = 0  # found values that are also in the gold file

    @property
    def precision(self) -> float | None:
        """The share of found values that are right; None when nothing was found."""
        return self.right / self.found if self.found else None

    @property
    def recall(self) -> float | None:
        """The share of gold values that were found; None when the gold file has none."""
        return self.right / self.gold if self.gold else None


def evaluate_extract(
    session: Session, settings: Settings, gold_path: Path = GOLD, inputs_dir: Path = INPUTS
) -> list[FieldScore]:
    """Score the extract prompt's answers for the gold contractors, field by field.

    The eval is a stage_runs row ("extract eval"), so its AI calls are in ai_calls and
    python -m app.pipeline stats shows how many came from the cache.

    Args:
        session: An open session on the database holding the contractors' saved text.
        settings: The model whose answers are scored, and the key for a cache miss.
        gold_path: The gold file.
        inputs_dir: Where each gold contractor's exact input is written, as <GAF ID>.txt.

    Returns:
        One FieldScore per field, in the order of the extract stage's output model.

    Raises:
        SystemExit: A gold contractor isn't in the database.
    """
    gold = yaml.safe_load(gold_path.read_text(encoding="utf-8"))
    homepages = extract.latest_homepages(session)
    inputs_dir.mkdir(parents=True, exist_ok=True)
    run = StageRun(stage="extract eval", model=settings.gemini_model)
    session.add(run)
    session.commit()

    scores = {field: FieldScore(field) for field in FIELDS}
    try:
        for gaf_id, gold_facts in gold.items():
            contractor = session.get(Contractor, str(gaf_id))
            if contractor is None:
                raise SystemExit(f"{gold_path}: no contractor with GAF ID {gaf_id}")
            texts = extract.source_texts(contractor.about_text, homepages.get(contractor.gaf_id, (None, None))[1])
            facts = None
            if texts:
                (inputs_dir / f"{contractor.gaf_id}.txt").write_text(extract.model_input(texts), encoding="utf-8")
                facts = ai.generate(
                    session,
                    settings,
                    extract.PROMPT,
                    extract.model_input(texts),
                    extract.ContractorFacts,
                    run=run,
                    contractor_id=contractor.gaf_id,
                )
            rows, _ = extract.ground(facts, texts) if facts else ([], 0)

            for field in FIELDS:
                found = {_normalize(row["value"]) for row in rows if row["field"] == field}
                expected = {_normalize(str(value)) for value in gold_facts.get(field) or []}
                scores[field].gold += len(expected)
                scores[field].found += len(found)
                scores[field].right += len(found & expected)
        run.status = "finished"
    except BaseException:  # includes SystemExit, and Ctrl-C
        session.rollback()
        run.status = "failed"
        raise
    finally:
        run.finished_at = utc_now()
        run.totals = {**ai.totals(session, run), "contractors": len(gold)}
        session.commit()
    return list(scores.values())


def _normalize(value: str) -> str:
    """How gold and found values are compared: lowercase, without punctuation, whitespace
    collapsed, and without a trailing plural "s", so "Roof Replacements." matches "roof replacement".
    """
    return " ".join(re.sub(r"[^\w\s]", "", value.lower()).split()).removesuffix("s")
