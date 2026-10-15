"""Command line entry point for the lead pipeline.

Usage (from the repo root):
    python -m app.pipeline run --stages discover
    python -m app.pipeline run --stages fetch,parse,check_websites
"""

import argparse
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.db.engine import make_engine
from app.pipeline.discover import discover
from app.pipeline.fetch import fetch
from app.settings import Settings

STAGES = ["discover", "fetch"]


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
    territory = yaml.safe_load(Path("config/distributor.yaml").read_text())["territory"]

    with Session(make_engine(settings.database_url)) as session:
        for stage in stages:
            if stage == "discover":
                run = discover(session, territory, settings)
                print(f"discover: run {run.id} {run.status}, {run.contractors_seen} contractors seen")
            elif stage == "fetch":
                fetch(session)


if __name__ == "__main__":
    main()
