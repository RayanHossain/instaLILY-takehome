"""ORM models for the lead database.

Only SQLAlchemy's generic column types are used, so the same models run on
SQLite locally and on Postgres in production.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """Return the current time in UTC. Used for timestamp defaults."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """The base class SQLAlchemy requires for typed ORM models."""


class Run(Base):
    """One execution of the pipeline for a territory."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, default="running")
    territory_zip: Mapped[str] = mapped_column(String)
    radius_miles: Mapped[float] = mapped_column(Float)
    contractors_seen: Mapped[int] = mapped_column(Integer, default=0)


class Contractor(Base):
    """A roofing contractor listed in GAF's contractor locator."""

    __tablename__ = "contractors"

    # GAF IDs can have leading zeros, so they are stored as text, never as integers.
    gaf_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    phone: Mapped[str | None] = mapped_column(String)
    city: Mapped[str | None] = mapped_column(String)
    state: Mapped[str | None] = mapped_column(String)
    postal_code: Mapped[str | None] = mapped_column(String)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    profile_url: Mapped[str | None] = mapped_column(String)
    rating: Mapped[float | None] = mapped_column(Float)
    review_count: Mapped[int | None] = mapped_column(Integer)
    certifications: Mapped[list[str]] = mapped_column(JSON, default=list)
    designations: Mapped[list[str]] = mapped_column(JSON, default=list)
    specialties: Mapped[list[str]] = mapped_column(JSON, default=list)
    # None means GAF didn't say, which is different from "not enrolled".
    enrolled_in_gaf_leads: Mapped[bool | None] = mapped_column(Boolean)
    first_seen_run: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    last_seen_run: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RawResponse(Base):
    """An HTTP response body exactly as received, saved before it is parsed."""

    __tablename__ = "raw_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    # Empty for responses that cover many contractors, like a search results page.
    contractor_id: Mapped[str | None] = mapped_column(ForeignKey("contractors.gaf_id"))
    source: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    content_type: Mapped[str | None] = mapped_column(String)
    body: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))  # sha256 hex digest of body


class Rep(Base):
    """A sales rep and the territory they cover."""

    __tablename__ = "reps"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    territory_zip: Mapped[str] = mapped_column(String)
    radius_miles: Mapped[float] = mapped_column(Float)
