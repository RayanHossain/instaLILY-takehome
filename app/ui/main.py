"""The rep's lead list: contractors ranked by a preset, and the selected one's details.

streamlit_app.py at the repo root calls main() on every rerun:
    streamlit run streamlit_app.py
Every read goes through app/ui/data.py. The page fits one 1440x900 laptop screen: the
table and the detail tabs scroll on their own, so the page never does.
"""

import re

import streamlit as st

from app.ui import data

DASH = "—"  # shown for a missing value

# Each tag's chip color, by kind: tiers blue, an opportunity green, a risk red, Top pick
# amber, Brief violet. Translucent, so the chips read in light and dark mode.
TAG_COLORS = {
    "President's Club": "rgba(47, 111, 219, 0.3)",
    "Master Elite": "rgba(47, 111, 219, 0.3)",
    "Certified Plus": "rgba(47, 111, 219, 0.3)",
    "New business": "rgba(33, 160, 90, 0.3)",
    "Low rating": "rgba(220, 53, 69, 0.35)",
    "Top pick": "rgba(240, 160, 0, 0.4)",
    "Brief": "rgba(130, 90, 220, 0.3)",
}


def plain(text: str) -> str:
    """Escape Markdown, so scraped or AI-written text shows exactly as written ("$5" isn't math)."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|$~<>:])", r"\\\1", text)


def remember_pick() -> None:
    """Store the clicked lead's id. Row positions change with every filter, sort, and preset; ids don't."""
    rows, ids = st.session_state.lead_table["selection"]["rows"], st.session_state.shown_ids
    if rows and rows[0] < len(ids):
        st.session_state.lead_id = ids[rows[0]]


def show_why(lead: data.LeadDetail, weights: data.Preset) -> None:
    """The Why tab: the total, each component as a bar with its weight, and the signals behind it."""
    if lead.score is None or lead.reasons is None:
        st.caption("Not scored yet.")
        return
    st.markdown(f"**{lead.score.total:.0f}** out of 100 under {lead.score.preset}")
    for component, signals in lead.reasons.items():
        points = getattr(lead.score, component)
        st.progress(round(points), text=f"{component.capitalize()} {points:.0f} · {getattr(weights, component)}% of the score")
        # A guess is greyed out: its data was missing, so it scored the neutral middle.
        st.caption(" · ".join(f":gray[{plain(signal.input)}]" if signal.guess else plain(signal.input) for signal in signals))
    st.caption(":gray[Grey: no data, so a neutral 50.]")


def main() -> None:
    """Draw the page: sidebar filters, the preset, the lead table, and the selected lead's details."""
    st.set_page_config(page_title="Roofing leads", layout="wide")
    territory = data.load_territory()
    radius = float(territory["radius_miles"])
    scoring = data.load_scoring_config()

    search = st.sidebar.text_input("Search", placeholder="Name or phone")
    tiers = st.sidebar.multiselect("Tier", data.TIERS, placeholder="All tiers")
    max_miles = st.sidebar.slider("Max distance (miles)", min_value=0.0, max_value=radius, value=radius, step=0.5)

    title_column, preset_column = st.columns([3, 2], vertical_alignment="center")
    with preset_column:
        # required: a second click can't leave the page without a preset. bind: ?preset=Quick+wins deep-links.
        preset = st.segmented_control(
            "Rank by",
            list(scoring.presets),
            default=scoring.default_preset,
            required=True,
            key="preset",
            bind="query-params",
            label_visibility="collapsed",
        )

    leads = data.list_leads(search, tiers, max_miles, preset)
    title_column.header("Roofing leads", anchor=False)
    noun = "contractor" if len(leads) == 1 else "contractors"
    st.caption(f"{len(leads)} {noun} near {territory['zip']}, within {max_miles:g} miles")
    if not leads:
        st.info("No contractors match. Try another search or wider filters.")
        return

    # The selected lead is remembered by id. Every run points the table's selection at that
    # lead's current row, so a filter, a re-sort, or a preset switch never shows a different lead.
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
                    "Score": None if lead.score is None else round(lead.score.total),
                    "Contractor": lead.name,
                    "Area": ", ".join(part for part in (lead.city, lead.state) if part) or None,
                    "Mi": lead.distance_miles,
                    "Tags": lead.tags,
                }
                for lead in leads
            ],
            column_config={
                # No color: "auto" paints every score under 50 red, which reads as a bad lead.
                "Score": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%d", width=64),
                "Contractor": st.column_config.TextColumn(width=180),
                "Area": st.column_config.TextColumn(width=110),
                "Mi": st.column_config.NumberColumn(format="%.1f", width=42),
                "Tags": st.column_config.MultiselectColumn(options=data.TAGS, color=[TAG_COLORS[tag] for tag in data.TAGS]),
            },
            hide_index=True,
            height=560,
            placeholder=DASH,
            key="lead_table",
            on_select=remember_pick,
            selection_mode="single-row-required",
        )

    with detail_column:
        lead = data.get_lead(st.session_state.lead_id, preset)
        st.subheader(lead.name, anchor=False)
        st.caption(" · ".join(part for part in (lead.tier, lead.phone) if part) or DASH)

        why_tab, brief_tab, notes_tab = st.tabs(["Why", "Brief", "Notes"], height=355)
        with why_tab:
            show_why(lead, scoring.presets[preset])
        with brief_tab:
            st.caption("The AI-written brief goes here.")
        with notes_tab:
            st.caption("The rep's notes and status go here.")
