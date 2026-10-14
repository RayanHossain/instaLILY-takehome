"""Shared pytest fixtures: a fresh, fully migrated SQLite database for each test."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.engine import make_engine


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """Run `alembic upgrade head` on a new SQLite file in this test's temp folder."""
    database_url = f"sqlite:///{tmp_path / 'test.db'}"
    alembic_config = Config(str(Path(__file__).parent.parent / "alembic.ini"))
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
