"""Command line entry point for the lead pipeline.

Usage (from the repo root):
    python -m app.pipeline run --stages discover
    python -m app.pipeline run --stages fetch,parse,check_websites
    python -m app.pipeline run --stages capture_websites,extract
"""

import argparse

from sqlalchemy.orm import Session

from app.db.engine import make_engine
from app.pipeline.capture_websites import capture_websites
from app.pipeline.check_websites import check_websites
from app.pipeline.discover import discover
from app.pipeline.extract import extract
from app.pipeline.fetch import fetch
from app.pipeline.parse import parse
from app.settings import Settings, load_territory

STAGES = ["discover", "fetch", "parse", "check_websites", "capture_websites", "extract"]


def main() -> None:
    """Parse the command line and run the requested stages in order."""
    parser = argparse.ArgumentParser(prog="python -m app.pipeline", description="Run lead pipeline stages.")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--stages", required=True, help=f"comma-separated stages to run in order, from: {','.join(STAGES)}")
    args = parser.parse_args()

    stages = args.stages.split(",")
    unknown = [stage for stage in stages if stage not in STAGES]
    if unknown:
        parser.error(f"unknown stage {', '.join(unknown)}; choose from {','.join(STAGES)}")

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


if __name__ == "__main__":
    main()
