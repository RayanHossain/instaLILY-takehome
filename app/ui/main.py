"""The rep's lead list: a table of contractors and the selected one's details.

streamlit_app.py at the repo root calls main() on every rerun:
    streamlit run streamlit_app.py
Every read goes through app/ui/data.py. The page fits one 1440x900 laptop screen: the
table and the detail tabs scroll on their own, so the page never does.
"""

import streamlit as st

from app.ui import data

DASH = "—"  # shown for a missing value


def remember_pick() -> None:
    """Store the clicked lead's id. Row positions change with every filter, sort, and preset; ids don't."""
    rows, ids = st.session_state.lead_table["selection"]["rows"], st.session_state.shown_ids
    if rows and rows[0] < len(ids):
        st.session_state.lead_id = ids[rows[0]]


def main() -> None:
    """Draw the page: sidebar filters, the lead table, and the selected lead's details."""
    st.set_page_config(page_title="Roofing leads", layout="wide")
    territory = data.load_territory()
    radius = float(territory["radius_miles"])

    search = st.sidebar.text_input("Search", placeholder="Name or phone")
    tiers = st.sidebar.multiselect("Tier", data.TIERS, placeholder="All tiers")
    max_miles = st.sidebar.slider("Max distance (miles)", min_value=0.0, max_value=radius, value=radius, step=0.5)

    leads = data.list_leads(search, tiers, max_miles)
    noun = "contractor" if len(leads) == 1 else "contractors"
    st.header(f"{len(leads)} {noun} within {max_miles:g} miles of {territory['zip']}")
    if not leads:
        st.info("No contractors match. Try another search or wider filters.")
        return

    # The selected lead is remembered by id. Every run points the table's selection at that
    # lead's current row, so a filter, a re-sort, or a save never shows a different lead.
    ids = [lead.gaf_id for lead in leads]
    st.session_state.shown_ids = ids
    if st.session_state.get("lead_id") not in ids:  # the first run, or the lead was filtered out
        st.session_state.lead_id = ids[0]
    st.session_state.lead_table = {"selection": {"rows": [ids.index(st.session_state.lead_id)], "columns": [], "cells": []}}

    table_column, detail_column = st.columns([5, 3])

    with table_column:
        st.dataframe(
            [
                {
                    "Name": lead.name,
                    "City": ", ".join(part for part in (lead.city, lead.state) if part) or None,
                    "Miles": lead.distance_miles,
                    "Tier": lead.tier,
                    # e.g. "4.9 (312)": the rating, then how many reviews it comes from.
                    "Rating": None if lead.rating is None else f"{lead.rating:.1f} ({lead.review_count})",
                }
                for lead in leads
            ],
            column_config={"Miles": st.column_config.NumberColumn(format="%.1f")},
            hide_index=True,
            height=560,
            placeholder=DASH,
            key="lead_table",
            on_select=remember_pick,
            selection_mode="single-row-required",
        )

    with detail_column:
        lead = data.get_lead(st.session_state.lead_id)
        st.subheader(lead.name, anchor=False)
        st.caption(" · ".join(part for part in (lead.tier, lead.phone) if part) or DASH)

        why_tab, brief_tab, notes_tab = st.tabs(["Why", "Brief", "Notes"], height=355)
        with why_tab:
            st.caption("The score breakdown goes here.")
        with brief_tab:
            st.caption("The AI-written brief goes here.")
        with notes_tab:
            st.caption("The rep's notes and status go here.")
