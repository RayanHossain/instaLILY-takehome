"""Command line entry point for the lead pipeline.

Usage (from the repo root):
    python -m app.pipeline run --stages discover
"""

import argparse
from pathlib import Path

import yaml
from sqlalchemy.orm import Session

from app.db.engine import make_engine
from app.pipeline.discover import discover
from app.settings import Settings


def main() -> None:
    """Parse the command line and run the requested stages in order."""
    parser = argparse.ArgumentParser(prog="python -m app.pipeline", description="Run lead pipeline stages.")
    parser.add_argument("command", choices=["run"])
    parser.add_argument("--stages", nargs="+", choices=["discover"], required=True, help="stages to run, in order")
    args = parser.parse_args()

    settings = Settings()
    territory = yaml.safe_load(Path("config/distributor.yaml").read_text())["territory"]

    with Session(make_engine(settings.database_url)) as session:
        for stage in args.stages:
            if stage == "discover":
                run = discover(session, territory, settings)
                print(f"discover: run {run.id} {run.status}, {run.contractors_seen} contractors seen")


if __name__ == "__main__":
    main()
