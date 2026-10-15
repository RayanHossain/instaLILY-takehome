"""ORM models for the lead database.

Only SQLAlchemy's generic column types are used, so the same models run on
SQLite locally and on Postgres in production.
"""

from datetime import datetime, timezone
from typing import Any

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
    # From the contractor's GAF profile page (parse stage). None when the page doesn't show it.
    street_address: Mapped[str | None] = mapped_column(String)
    website_url: Mapped[str | None] = mapped_column(String)
    website_domain: Mapped[str | None] = mapped_column(String)  # lowercase, without "www."
    google_place_id: Mapped[str | None] = mapped_column(String)
    google_rating: Mapped[float | None] = mapped_column(Float)
    google_review_count: Mapped[int | None] = mapped_column(Integer)
    about_text: Mapped[str | None] = mapped_column(Text)
    in_business_since: Mapped[int | None] = mapped_column(Integer)
    # From one GET to website_url (check_websites stage): the HTTP status if anything
    # answered, else the error ("timeout", "dns", "ssl", or "connection").
    website_status: Mapped[int | None] = mapped_column(Integer)
    website_error: Mapped[str | None] = mapped_column(String)
    website_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_run: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    last_seen_run: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RawResponse(Base):
    """One outgoing request and what came back, saved before anything parses it.

    A response's body is kept exactly as received. A request that got no response
    at all (a timeout, say) has no status_code, an empty body, and the error instead.
    """

    __tablename__ = "raw_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id"))
    # Empty for responses that cover many contractors, like a search results page.
    contractor_id: Mapped[str | None] = mapped_column(ForeignKey("contractors.gaf_id"))
    source: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(String)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    # The HTTP status. Only 200s are parsed; other statuses are kept as a record of the failure.
    status_code: Mapped[int | None] = mapped_column(Integer)
    # Only when nothing came back: the httpx error name, e.g. "ConnectTimeout".
    error: Mapped[str | None] = mapped_column(String)
    content_type: Mapped[str | None] = mapped_column(String)
    # The JSON body we sent, for POST requests like a search page (its offset is in here).
    # Must never hold secrets; credentials go in headers, which are not saved.
    request_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    body: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))  # sha256 hex digest of body


class AiCache(Base):
    """One answer from an AI model, saved before it is parsed.

    An answer that passed validation is reused: the next request with the same
    cache_key gets the newest valid answer without calling the model.
    """

    __tablename__ = "ai_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    # sha256 hex digest of the model, the prompt (its name carries its version), and the input.
    cache_key: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String)
    prompt_name: Mapped[str] = mapped_column(String)  # e.g. "extract_facts_v1"
    response: Mapped[str] = mapped_column(Text)  # the answer exactly as received
    valid: Mapped[bool] = mapped_column(Boolean, default=False)  # True once it passed validation
    error: Mapped[str | None] = mapped_column(Text)  # why it failed validation
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class StageRun(Base):
    """One run of a pipeline stage that calls the AI, with its totals once it ends."""

    __tablename__ = "stage_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    stage: Mapped[str] = mapped_column(String)  # e.g. "extract"
    model: Mapped[str] = mapped_column(String)  # the AI model the run used (GEMINI_MODEL)
    status: Mapped[str] = mapped_column(String, default="running")  # then "finished" or "failed"
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Written when the run ends: its AI attempts counted by outcome, tokens, and latency,
    # then the stage's own numbers (for extract: facts kept and grounding drops).
    totals: Mapped[dict[str, float] | None] = mapped_column(JSON)


class AiCall(Base):
    """One attempt by generate() to get an answer: a cache hit, or one request to the model."""

    __tablename__ = "ai_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("stage_runs.id"), index=True)
    stage: Mapped[str] = mapped_column(String)
    contractor_id: Mapped[str | None] = mapped_column(ForeignKey("contractors.gaf_id"))
    prompt_name: Mapped[str] = mapped_column(String)  # carries its version, e.g. "extract_facts_v1"
    model: Mapped[str] = mapped_column(String)
    cache_hit: Mapped[bool] = mapped_column(Boolean)
    # "ok"; "ok after a retry" (valid only on the validation retry); "invalid"; "rate-limited"
    # (HTTP 429); "overloaded" (HTTP 503); or "error" (any other API error, or a timeout).
    outcome: Mapped[str] = mapped_column(String)
    latency_seconds: Mapped[float | None] = mapped_column(Float)  # None for a cache hit
    input_tokens: Mapped[int | None] = mapped_column(Integer)  # when the API reports them
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)  # what went wrong, for invalid and failed attempts
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Fact(Base):
    """One fact the AI extracted about a contractor, with the exact quote it rests on.

    A contractor's facts are replaced together each time the extract stage runs.
    """

    __tablename__ = "facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    contractor_id: Mapped[str] = mapped_column(ForeignKey("contractors.gaf_id"), index=True)
    field: Mapped[str] = mapped_column(String)  # e.g. "services" or "owner_names"
    value: Mapped[str] = mapped_column(String)  # an owner's role, when stated, follows in parentheses
    evidence: Mapped[str] = mapped_column(Text)  # an exact quote from the source text
    source: Mapped[str] = mapped_column(String)  # "about_text" or "homepage"
    source_url: Mapped[str | None] = mapped_column(String)  # the GAF profile or the homepage
    model: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)  # e.g. "extract_facts_v1"
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Score(Base):
    """A contractor's four component scores (0-100), flags, and reasons, from the score stage.

    A preset's total combines the components when leads are read; it is never stored.
    """

    __tablename__ = "scores"

    contractor_id: Mapped[str] = mapped_column(ForeignKey("contractors.gaf_id"), primary_key=True)
    value: Mapped[float] = mapped_column(Float)
    winnability: Mapped[float] = mapped_column(Float)
    stability: Mapped[float] = mapped_column(Float)
    distance: Mapped[float] = mapped_column(Float)
    # e.g. [{"flag": "New business", "kind": "opportunity", "reason": "founded 2025"}]
    flags: Mapped[list[dict[str, str]]] = mapped_column(JSON)
    # Per component, its signals: {"value": [{"signal": "reviews", "input": "312 reviews", "points": 90, "weight": 50}, ...], ...}
    reasons: Mapped[dict[str, list[dict[str, Any]]]] = mapped_column(JSON)
    rules_version: Mapped[str] = mapped_column(String)  # config/scoring.yaml's rules_version
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ContractorBrief(Base):
    """A contractor's latest brief: the AI's touch plan, written for a lead in a preset's top N.

    input_hash covers everything the AI was told; a brief whose input, model, and prompt
    version are unchanged is never written again.
    """

    __tablename__ = "briefs"

    contractor_id: Mapped[str] = mapped_column(ForeignKey("contractors.gaf_id"), primary_key=True)
    content: Mapped[dict[str, Any]] = mapped_column(JSON)  # the validated app.briefs.Brief, as a dict
    input_hash: Mapped[str] = mapped_column(String(64))  # sha256 hex digest of the input text
    model: Mapped[str] = mapped_column(String)
    prompt_version: Mapped[str] = mapped_column(String)  # e.g. "write_brief_v1"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Rep(Base):
    """A sales rep and the territory they cover."""

    __tablename__ = "reps"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    territory_zip: Mapped[str] = mapped_column(String)
    radius_miles: Mapped[float] = mapped_column(Float)
