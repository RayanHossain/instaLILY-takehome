"""Command line entry point for evals: score the AI's output against hand-checked gold data.

Usage (from the repo root):
    python -m app.evals extract
"""

import argparse

from sqlalchemy.orm import Session

from app.db.engine import make_engine
from app.evals.extract import GOLD, INPUTS, FieldScore, evaluate_extract
from app.settings import Settings


def main() -> None:
    """Parse the command line, run the requested eval, and print its scores."""
    parser = argparse.ArgumentParser(prog="python -m app.evals", description="Score the AI's output against gold data.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("extract", help=f"each extracted field's precision and recall against {GOLD}")
    parser.parse_args()

    settings = Settings()
    with Session(make_engine(settings.database_url)) as session:
        scores = evaluate_extract(session, settings)

    overall = FieldScore(
        "all fields",
        gold=sum(score.gold for score in scores),
        found=sum(score.found for score in scores),
        right=sum(score.right for score in scores),
    )
    print(f"extract eval: model {settings.gemini_model}, gold {GOLD} (AI calls behind it: python -m app.pipeline stats)")
    print(f"each contractor's exact input: {INPUTS}/<GAF ID>.txt")
    print(f"{'field':<16}{'gold':>6}{'found':>7}{'right':>7}{'precision':>11}{'recall':>8}")
    for score in [*scores, overall]:
        precision = "-" if score.precision is None else f"{score.precision:.2f}"
        recall = "-" if score.recall is None else f"{score.recall:.2f}"
        print(f"{score.field:<16}{score.gold:>6}{score.found:>7}{score.right:>7}{precision:>11}{recall:>8}")


if __name__ == "__main__":
    main()
