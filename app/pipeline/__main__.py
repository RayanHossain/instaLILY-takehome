"""Command line entry point for the lead pipeline.

Usage (from the repo root):
    python -m app.pipeline run --stages discover
    python -m app.pipeline run --stages fetch,parse,check_websites
    python -m app.pipeline run --stages capture_websites,extract
    python -m app.pipeline run --stages score
    python -m app.pipeline stats
"""

import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.engine import make_engine
from app.db.models import StageRun, utc_now
from app.pipeline.capture_websites import capture_websites
from app.pipeline.check_websites import check_websites
from app.pipeline.discover import discover
from app.pipeline.extract import extract
from app.pipeline.fetch import fetch
from app.pipeline.parse import parse
from app.pipeline.score import score
from app.settings import Settings, load_territory

STAGES = ["discover", "fetch", "parse", "check_websites", "capture_websites", "extract", "score"]


def main() -> None:
    """Parse the command line, then run the requested stages in order or print the latest AI run's numbers."""
    parser = argparse.ArgumentParser(prog="python -m app.pipeline", description="Run lead pipeline stages.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_command = commands.add_parser("run", help="run stages in order")
    run_command.add_argument("--stages", required=True, help=f"comma-separated stages to run in order, from: {','.join(STAGES)}")
    commands.add_parser("stats", help="print the numbers of the latest run of a stage that calls the AI")
    args = parser.parse_args()

    if args.command == "stats":
        with Session(make_engine(Settings().database_url)) as session:
            show_stats(session)
        return

    stages = args.stages.split(",")
    unknown = [stage for stage in stages if stage not in STAGES]
    if unknown:
        run_command.error(f"unknown stage {', '.join(unknown)}; choose from {','.join(STAGES)}")

    settings = Settings()
    territory = load_territory()

    with Session(make_engine(settings.database_url)) as session:
        for stage in stages:
            if stage == "discover":
                run = discover(session, territory, settings)
                print(f"discover: run {run.id} {run.status}, {run.contractors_seen} contractors seen")
            elif stage == "fetch":
                fetch(session)
            elif stage == "parse":
                parse(session)
            elif stage == "check_websites":
                check_websites(session)
            elif stage == "capture_websites":
                capture_websites(session)
            elif stage == "extract":
                extract(session, settings)
            elif stage == "score":
                score(session, current_year=utc_now().year)


def show_stats(session: Session) -> None:
    """Print the latest run of a stage that calls the AI: its status, model, timing, and totals."""
    run = session.scalar(select(StageRun).order_by(StageRun.id.desc()).limit(1))
    if run is None:
        print("No stage that calls the AI has run yet.")
        return
    took = f", took {(run.finished_at - run.started_at).total_seconds() / 60:.1f} min" if run.finished_at else ""
    print(f"{run.stage} run {run.id}: {run.status}, model {run.model}, started {run.started_at:%Y-%m-%d %H:%M} UTC{took}")
    for name, value in (run.totals or {}).items():
        print(f"  {name}: {value}")


if __name__ == "__main__":
    main()
