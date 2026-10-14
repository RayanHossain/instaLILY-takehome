"""Session factory for the app's database."""

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.engine import make_engine


def make_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    """Return a factory that opens sessions on the given engine (default: DATABASE_URL).

    Open sessions with a `with` block so they always close:

        SessionFactory = make_session_factory()
        with SessionFactory() as session:
            ...
            session.commit()
    """
    return sessionmaker(bind=engine or make_engine())
