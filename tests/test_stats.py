"""python -m app.pipeline stats: the numbers of the latest run of a stage that calls the AI."""

import sys
from datetime import datetime, timezone

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.models import StageRun
from app.pipeline.__main__ import main


def test_stats_prints_the_latest_runs_numbers(
    engine: Engine, session: Session, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Environment variables win over .env, so the command opens the test database, never data/leads.db.
    monkeypatch.setenv("DATABASE_URL", str(engine.url))
    monkeypatch.setenv("COVEO_ORG_ID", "test-org")
    monkeypatch.setenv("COVEO_API_KEY", "test-key")
    monkeypatch.setattr(sys, "argv", ["python -m app.pipeline", "stats"])

    main()
    assert capsys.readouterr().out == "No stage that calls the AI has run yet.\n"

    session.add_all(
        [
            StageRun(
                stage="extract",
                model="gemma-4-26b-a4b-it",
                status="failed",
                started_at=datetime(2026, 10, 14, 23, 0, tzinfo=timezone.utc),
                finished_at=datetime(2026, 10, 14, 23, 9, tzinfo=timezone.utc),
                totals={"requests to the model": 16},
            ),
            StageRun(
                stage="extract",
                model="gemma-4-31b-it",
                status="finished",
                started_at=datetime(2026, 10, 15, 0, 10, tzinfo=timezone.utc),
                finished_at=datetime(2026, 10, 15, 0, 55, 30, tzinfo=timezone.utc),
                totals={"requests to the model": 128, "rate-limited": 0, "facts kept": 2104, "grounding drops": 97},
            ),
        ]
    )
    session.commit()

    main()
    assert capsys.readouterr().out.splitlines() == [
        "extract run 2: finished, model gemma-4-31b-it, started 2026-10-15 00:10 UTC, took 45.5 min",
        "  requests to the model: 128",
        "  rate-limited: 0",
        "  facts kept: 2104",
        "  grounding drops: 97",
    ]
