"""The UI's only way to the data: opens a database session and calls the services.

main.py imports this module and nothing else from app, so every read and write the UI
makes goes through a service. Writes touch only the rep's own data: notes, statuses,
and their chosen preset.
"""

from pathlib import Path

import streamlit as st
from sqlalchemy import Engine, make_url
from sqlalchemy.orm import Session

from app.db.engine import make_engine
from app.scoring import Preset, load_scoring_config
from app.services import leads, notes, reps
from app.services.leads import TIERS, LeadDetail, LeadFact, LeadRow, all_tags
from app.services.notes import STATUS_GROUPS, STATUSES, Note, status_group
from app.services.reps import RepInfo
from app.settings import Settings, load_territory

# What main.py may use. The constants, the models (for type hints), all_tags,
# load_scoring_config, load_territory, and status_group are passed through unchanged.
__all__ = [
    "STATUSES",
    "STATUS_GROUPS",
    "TIERS",
    "LeadDetail",
    "LeadFact",
    "Note",
    "Preset",
    "RepInfo",
    "add_note",
    "all_tags",
    "briefed_top_leads",
    "current_rep",
    "current_statuses",
    "database_missing",
    "get_lead",
    "lead_notes",
    "list_leads",
    "load_scoring_config",
    "load_territory",
    "save_preset",
    "status_group",
    "top_leads_per_preset",
]

DEMO_REP_ID = 1  # the rep the initial migration seeds


@st.cache_resource
def _engine(database_url: str) -> Engine:
    """Create one engine per database URL, shared by every rerun and browser tab."""
    return make_engine(database_url)


def _open_session() -> Session:
    """Open a session on the database DATABASE_URL names (the environment wins over .env)."""
    return Session(_engine(Settings().database_url))


def database_missing() -> bool:
    """True when DATABASE_URL names a SQLite file that doesn't exist yet, as in a fresh clone.

    Checked before connecting, because connecting would create an empty file.
    """
    url = make_url(Settings().database_url)
    return url.get_backend_name() == "sqlite" and not Path(url.database or "").exists()


def current_rep() -> RepInfo:
    """The signed-in rep. For now that's always the seeded demo rep; login later replaces only this function."""
    with _open_session() as session:
        return reps.get_rep(session, DEMO_REP_ID)


def save_preset(rep_id: int, preset: str) -> None:
    """Remember the rep's chosen preset, so their next visit starts on it."""
    with _open_session() as session:
        reps.save_preset(session, rep_id, preset)
        session.commit()


def list_leads(search: str, tiers: list[str], max_miles: float, preset: str) -> list[LeadRow]:
    """The lead table's rows for the sidebar's search and filters, highest total under the preset first."""
    with _open_session() as session:
        return leads.list_leads(
            session,
            search=search,
            tiers=tiers,
            max_miles=max_miles,
            preset=preset,
            sort="total",
            top_n=Settings().top_leads_per_preset,
        )


def briefed_top_leads(preset: str) -> list[LeadRow]:
    """The Top leads page's leads: the preset's top N that have a brief, highest total first."""
    with _open_session() as session:
        return leads.briefed_top_leads(session, preset, Settings().top_leads_per_preset)


def get_lead(gaf_id: str, preset: str) -> LeadDetail:
    """The detail panel's data for one contractor, scored under the preset."""
    with _open_session() as session:
        return leads.get_lead(session, gaf_id, preset=preset, top_n=Settings().top_leads_per_preset)


def top_leads_per_preset() -> int:
    """How many leads each preset's top takes: the ones the brief stage writes briefs for."""
    return Settings().top_leads_per_preset


def current_statuses(rep_id: int, gaf_ids: list[str]) -> dict[str, str]:
    """Each lead's current status for the rep: its newest note's, or New."""
    with _open_session() as session:
        return notes.current_statuses(session, rep_id, gaf_ids)


def lead_notes(rep_id: int, gaf_id: str) -> list[Note]:
    """The rep's notes on one lead, newest first."""
    with _open_session() as session:
        return notes.lead_notes(session, rep_id, gaf_id)


def add_note(rep_id: int, gaf_id: str, status: str, text: str) -> None:
    """Save a note that sets the lead's status for the rep."""
    with _open_session() as session:
        notes.add_note(session, rep_id, gaf_id, status, text)
        session.commit()
