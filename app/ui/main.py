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


def show_fact(fact: data.LeadFact) -> None:
    """One fact: its value, then the quote it rests on and a link to where the quote is."""
    where = "GAF profile" if fact.source == "about_text" else "Website"
    link = f" · [{where}]({fact.source_url})" if fact.source_url else f" · {where}"
    st.markdown(f"**{plain(fact.value)}** :gray[({fact.field.replace('_', ' ')})]{link}")
    st.caption(f"“{plain(fact.quote)}”")


def show_brief(lead: data.LeadDetail) -> None:
    """The Brief tab: the touch plan in the order the rep uses it, then the quoted facts behind it."""
    brief = lead.brief
    if brief is None:
        st.caption(f"Briefs are written for each preset's top {data.top_leads_per_preset()} leads, and this one isn't in any.")
        if lead.facts:
            st.markdown("**What its GAF profile and website say**")
            for fact in lead.facts:
                show_fact(fact)
        return

    st.markdown(plain(brief.why_this_contractor))
    if brief.ask_for:
        st.markdown(f"Ask for: **{plain(brief.ask_for)}**")
    st.markdown(f"> {plain(brief.first_touch.opener)}")
    st.caption(plain(brief.first_touch.reason))
    st.markdown("**Follow-ups**")
    for follow_up in brief.follow_ups:
        st.markdown(f"- {plain(follow_up.step)}  \n  :gray[{plain(follow_up.reason)}]")
    st.markdown("**Questions**")
    st.markdown("\n".join(f"- {plain(question)}" for question in brief.questions))
    evidence = [fact for fact in lead.facts if fact.id in brief.cited_fact_ids]
    if evidence:
        with st.expander(f"Evidence: {len(evidence)} quoted facts"):
            for fact in evidence:
                show_fact(fact)
    else:
        st.caption("Written from the GAF profile only.")


def save_preset_choice(rep_id: int) -> None:
    """Save the preset the rep just picked, so their next visit starts on it."""
    data.save_preset(rep_id, st.session_state.preset)


def save_note(rep_id: int, gaf_id: str, name: str) -> None:
    """Save the Notes form: a note that sets the lead's status. Then say where the lead went.

    It runs as the form's callback, before the page redraws, so the table already shows the save.
    """
    status = st.session_state[f"status_{gaf_id}"]
    data.add_note(rep_id, gaf_id, status, st.session_state[f"note_{gaf_id}"])
    st.session_state[f"note_{gaf_id}"] = ""
    group = data.status_group(status)
    if st.session_state.status_group in (group, "All"):
        st.toast(f"Saved: {name}")
    else:  # the lead leaves the list, so the panel moves to the top lead
        st.toast(f"Saved: {name} is now {group}")


def show_notes(rep_id: int, lead: data.LeadDetail, status: str) -> None:
    """The Notes tab: a status picker and a note box, then the history, newest first."""
    with st.form(f"notes_{lead.gaf_id}", border=False):
        st.segmented_control(
            "Status", data.STATUSES, default=status, required=True, key=f"status_{lead.gaf_id}", label_visibility="collapsed"
        )
        st.text_area("Note", key=f"note_{lead.gaf_id}", placeholder="What happened?", height=68, label_visibility="collapsed")
        st.form_submit_button("Save", on_click=save_note, args=(rep_id, lead.gaf_id, lead.name))
    for note in data.lead_notes(rep_id, lead.gaf_id):
        st.markdown(f"**{note.status}** :gray[· {note.created_at.astimezone():%b %d, %H:%M}]")
        if note.text:
            st.markdown(plain(note.text))


def main() -> None:
    """Draw the page: sidebar filters, the preset, the status filter, the lead table, and the selected lead."""
    st.set_page_config(page_title="Roofing leads", layout="wide")
    territory = data.load_territory()
    radius = float(territory["radius_miles"])
    scoring = data.load_scoring_config()
    rep = data.current_rep()

    st.sidebar.caption(f"Signed in as **{rep.name}**")
    search = st.sidebar.text_input("Search", placeholder="Name or phone")
    tiers = st.sidebar.multiselect("Tier", data.TIERS, placeholder="All tiers")
    max_miles = st.sidebar.slider("Max distance (miles)", min_value=0.0, max_value=radius, value=radius, step=0.5)

    title_column, preset_column = st.columns([3, 2], vertical_alignment="center")
    with preset_column:
        # Starts on the rep's saved preset. required: a second click can't unselect it.
        # bind: ?preset=Quick+wins in the URL deep-links to a preset.
        preset = st.segmented_control(
            "Rank by",
            list(scoring.presets),
            default=rep.preset if rep.preset in scoring.presets else scoring.default_preset,
            required=True,
            key="preset",
            bind="query-params",
            on_change=save_preset_choice,
            args=(rep.id,),
            label_visibility="collapsed",
        )

    leads = data.list_leads(search, tiers, max_miles, preset)
    title_column.header("Roofing leads", anchor=False)
    noun = "contractor" if len(leads) == 1 else "contractors"
    st.caption(f"{len(leads)} {noun} near {territory['zip']}, within {max_miles:g} miles")

    table_column, detail_column = st.columns([5, 3])

    with table_column:
        statuses = data.current_statuses(rep.id, [lead.gaf_id for lead in leads])
        counts = {group: sum(data.status_group(statuses[lead.gaf_id]) == group for lead in leads) for group in data.STATUS_GROUPS}
        group = st.segmented_control(
            "Status",
            [*data.STATUS_GROUPS, "All"],
            default="To contact",
            required=True,
            key="status_group",
            format_func=lambda option: f"{option} {counts[option]}" if option in counts else option,
            label_visibility="collapsed",
        )
        leads = [lead for lead in leads if group == "All" or data.status_group(statuses[lead.gaf_id]) == group]
        if not leads:
            st.info("No leads here. Try another status, search, or wider filters.")
            return

        # The selected lead is remembered by id. Every run points the table's selection at that
        # lead's current row, so a filter, a re-sort, a preset switch, or a save never shows a
        # different lead. When the lead leaves the list, the panel moves to the top lead.
        ids = [lead.gaf_id for lead in leads]
        st.session_state.shown_ids = ids
        if st.session_state.get("lead_id") not in ids:  # the first run, or the lead left the list
            st.session_state.lead_id = ids[0]
        st.session_state.lead_table = {"selection": {"rows": [ids.index(st.session_state.lead_id)], "columns": [], "cells": []}}

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

        why_tab, brief_tab, notes_tab = st.tabs(["Why", "Brief" if lead.brief else "Brief (none)", "Notes"], height=355)
        with why_tab:
            show_why(lead, scoring.presets[preset])
        with brief_tab:
            show_brief(lead)
        with notes_tab:
            show_notes(rep.id, lead, statuses[lead.gaf_id])
