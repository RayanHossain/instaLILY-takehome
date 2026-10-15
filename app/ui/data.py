"""The UI's only way to the data: opens a database session and calls the services.

main.py imports this module and nothing else from app, so every read the UI makes
goes through a service.
"""

import streamlit as st
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.db.engine import make_engine
from app.scoring import Preset, load_scoring_config
from app.services import leads
from app.services.leads import TAGS, TIERS, LeadDetail, LeadFact, LeadRow
from app.settings import Settings, load_territory

# What main.py may use. The constants, the models (for type hints), load_scoring_config,
# and load_territory are passed through unchanged.
__all__ = [
    "TAGS",
    "TIERS",
    "LeadDetail",
    "LeadFact",
    "Preset",
    "get_lead",
    "list_leads",
    "load_scoring_config",
    "load_territory",
    "top_leads_per_preset",
]


@st.cache_resource
def _engine(database_url: str) -> Engine:
    """Create one engine per database URL, shared by every rerun and browser tab."""
    return make_engine(database_url)


def _open_session() -> Session:
    """Open a session on the database DATABASE_URL names (the environment wins over .env)."""
    return Session(_engine(Settings().database_url))


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


def get_lead(gaf_id: str, preset: str) -> LeadDetail:
    """The detail panel's data for one contractor, scored under the preset."""
    with _open_session() as session:
        return leads.get_lead(session, gaf_id, preset=preset, top_n=Settings().top_leads_per_preset)


def top_leads_per_preset() -> int:
    """How many leads each preset's top takes: the ones the brief stage writes briefs for."""
    return Settings().top_leads_per_preset
