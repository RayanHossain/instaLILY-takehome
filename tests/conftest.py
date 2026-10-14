"""Shared pytest fixtures: a fresh, fully migrated SQLite database for each test."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.engine import make_engine

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def database_url(tmp_path: Path) -> str:
    """A SQLite file in pytest's temporary folder, deleted after the test run."""
    return f"sqlite:///{tmp_path / 'test.db'}"


@pytest.fixture
def engine(database_url: str) -> Iterator[Engine]:
    """Run `alembic upgrade head` on a new database and return an engine for it."""
    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(alembic_config, "head")

    engine = make_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """An open session on the migrated test database."""
    with Session(engine) as session:
        yield session
