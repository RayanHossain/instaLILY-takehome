"""The rep's two pages: Top leads, the landing page, and All leads, the full ranked table.

streamlit_app.py at the repo root calls main() on every rerun:
    streamlit run streamlit_app.py
main() draws the sidebar both pages share, then runs the page the rep is on; each page's
file in app_pages/ calls its function here. Every read goes through app/ui/data.py. Each page fits
one 1440x900 laptop screen: the table and the detail boxes scroll on their own, so the page
never does.
"""

import re

import streamlit as st

from app.ui import data

DASH = "—"  # shown for a missing value
# On All leads, each detail tab scrolls inside a bordered box of this height, with the scrollbar below.
TAB_HEIGHT = 310
# On Top leads, the brief, the score, and the notes sit side by side in bordered boxes this tall.
TOP_BOX_HEIGHT = 520
# Streamlit keeps a scrolling container's scrollbar hidden until the mouse is over it, and
# macOS hides it until you scroll, so a box cut off between two sections looked finished.
# This keeps a scrollbar showing in the detail boxes whenever there's more below. It targets
# only their key= classes; grey and translucent for light and dark mode.
# Chrome and Safari draw the -webkit- scrollbar, always visible, but only once the standard
# scrollbar properties Streamlit sets are back to auto. Firefox has no -webkit- scrollbars,
# so it gets a thin grey one instead.
DETAIL_SCROLLBAR_CSS = """<style>
:is(.st-key-why_box, .st-key-brief_box, .st-key-notes_box) {
    scrollbar-width: auto;
    scrollbar-color: auto;
}
:is(.st-key-why_box, .st-key-brief_box, .st-key-notes_box)::-webkit-scrollbar { width: 8px; }
:is(.st-key-why_box, .st-key-brief_box, .st-key-notes_box)::-webkit-scrollbar-thumb {
    background: rgba(128, 128, 128, 0.6);
    border-radius: 4px;
}
@supports not selector(::-webkit-scrollbar) {
    :is(.st-key-why_box, .st-key-brief_box, .st-key-notes_box) {
        scrollbar-width: thin;
        scrollbar-color: rgba(128, 128, 128, 0.6) transparent;
    }
}
</style>"""

# Each tag's chip color, by kind: preset names amber, tiers blue, an opportunity green, a risk
# red. Translucent, so the chips read in light and dark mode.
PRESET_TAG_COLOR = "rgba(240, 160, 0, 0.4)"  # every preset name, e.g. "Balanced"
TAG_COLORS = {
    "President's Club": "rgba(47, 111, 219, 0.3)",
    "Master Elite": "rgba(47, 111, 219, 0.3)",
    "Certified Plus": "rgba(47, 111, 219, 0.3)",
    "New business": "rgba(33, 160, 90, 0.3)",
    "Low rating": "rgba(220, 53, 69, 0.35)",
}


def plain(text: str) -> str:
    """Escape Markdown, so scraped or AI-written text shows exactly as written ("$5" isn't math)."""
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|$~<>:])", r"\\\1", text)


def call_link(phone: str) -> str:
    """The phone number as a Markdown tap-to-call link."""
    digits = re.sub(r"\D", "", phone)
    return f":material/call: [{plain(phone)}](tel:+1{digits[-10:]})"


def remember_pick() -> None:
    """Store the clicked lead's id. Row positions change with every filter, sort, and preset; ids don't."""
    rows, ids = st.session_state.lead_table["selection"]["rows"], st.session_state.shown_ids
    if rows and rows[0] < len(ids):
        st.session_state.lead_id = ids[rows[0]]


def step_lead(selected_key: str, step: int) -> None:
    """Move the page's selected lead one down its list (Next, step 1) or up it (Previous, step -1).

    Args:
        selected_key: The session state key holding the page's selected lead: "top_lead_id"
            on Top leads, "lead_id" on All leads.
        step: 1 for the next lead, -1 for the previous one.
    """
    ids = st.session_state.shown_ids
    position = ids.index(st.session_state[selected_key]) + step
    st.session_state[selected_key] = ids[min(max(position, 0), len(ids) - 1)]


def log_call(rep_id: int, gaf_id: str, name: str, next_id: str | None, selected_key: str) -> None:
    """Save the call sheet's outcome and note through the services, then queue the next lead's call sheet."""
    outcome = st.session_state[f"outcome_{gaf_id}"]
    data.add_note(rep_id, gaf_id, outcome, st.session_state[f"call_note_{gaf_id}"])
    st.session_state.pop(f"status_{gaf_id}", None)  # the Notes picker starts on the new status
    st.toast(f"Logged: {name} is now {outcome}")
    if next_id:
        st.session_state[selected_key] = next_id
        st.session_state.call_next = True  # the page opens the next lead's call sheet


@st.dialog("Call sheet", width="medium", position="right")
def call_sheet(rep_id: int, lead: data.LeadDetail, status: str, next_id: str | None, selected_key: str) -> None:
    """The call sheet, a drawer beside the page: the opener, questions to tick off, follow-ups, and the outcome.

    "Log call" (Cmd+Enter) saves the outcome and note through the services, then opens
    the next lead's call sheet. selected_key is the page's selected-lead key, which
    step_lead explains.
    """
    st.markdown(f"**{plain(lead.name)}**")
    if lead.phone:
        st.markdown(call_link(lead.phone))
    if lead.brief:
        st.markdown(f"> {plain(lead.brief.first_touch.opener)}")
        st.markdown("**Ask**")
        for number, question in enumerate(lead.brief.questions):
            st.checkbox(plain(question), key=f"asked_{lead.gaf_id}_{number}")
        st.markdown("**Then**")
        st.markdown("\n".join(f"- {plain(follow_up.step)}" for follow_up in lead.brief.follow_ups))
    else:
        st.caption(f"No brief: briefs are written for each preset's top {data.top_leads_per_preset()} leads.")

    # Starts on the lead's current status, so logging a call never moves it back down the ladder.
    outcome = "Contacted" if status == "New" else status
    st.segmented_control("Outcome", data.STATUSES[1:], default=outcome, required=True, key=f"outcome_{lead.gaf_id}")
    st.text_area("Note", key=f"call_note_{lead.gaf_id}", placeholder="What did they say?")
    # log_call saves before anything redraws; the rerun then closes this sheet and redraws the page.
    log_args = (rep_id, lead.gaf_id, lead.name, next_id, selected_key)
    if st.button("Log call", key=f"log_{lead.gaf_id}", type="primary", shortcut="Cmd+Enter", on_click=log_call, args=log_args):
        st.rerun()


def show_header(lead: data.LeadDetail) -> bool:
    """The lead's header: the name with preset, tier, and flag badges, one caption line, the phone and links, and About.

    Returns:
        True when the rep clicked Call.
    """
    with st.container(gap="xsmall"):
        with st.container(horizontal=True, vertical_alignment="center", gap="xsmall"):
            st.subheader(lead.name, anchor=False, width="content")
            for preset in lead.top_presets:
                st.badge(preset, color="orange", help=f"In {preset}'s top {data.top_leads_per_preset()}")
            if lead.tier:
                st.badge(lead.tier, color="blue")
            for flag in lead.score.flags if lead.score else []:
                st.badge(flag["flag"], color="green" if flag["kind"] == "opportunity" else "red", help=flag["reason"])

        area = ", ".join(part for part in (lead.city, lead.state) if part)
        rating = "no reviews" if lead.rating is None else f"★ {lead.rating:.1f} ({lead.review_count} reviews)"
        parts = [
            plain(area) if area else None,
            None if lead.distance_miles is None else f"{lead.distance_miles:.1f} mi",
            None if lead.founded_year is None else f"since {lead.founded_year}",
            rating,
        ]
        st.caption(" · ".join(part for part in parts if part))

        with st.container(horizontal=True, vertical_alignment="center", gap="small"):
            called = st.button("Call", icon=":material/phone_in_talk:", type="primary")
            if lead.phone:
                st.markdown(call_link(lead.phone), width="content")
            if lead.website_url:
                st.link_button("Website", lead.website_url, icon=":material/language:")
            if lead.profile_url:
                st.link_button("GAF profile", lead.profile_url, icon=":material/open_in_new:")

        if lead.about_text:
            with st.expander("About"):
                with st.container(height=150, border=False):
                    st.markdown(plain(lead.about_text))
    return called


def show_why(lead: data.LeadDetail, weights: data.Preset | None) -> None:
    """The Why box: the total, each component as a bar, and the signals behind it.

    Args:
        lead: The lead to explain.
        weights: The picked preset's weights, on All leads: the total is under that preset,
            and each bar says its share. None on Top leads, which has no picker: it shows
            the total under each preset whose top N the lead is in, since the components
            are the same under every preset and only the weights change.
    """
    if lead.score is None or lead.reasons is None:
        st.caption("Not scored yet.")
        return
    if weights:
        st.markdown(f"**{lead.score.total:.0f}** out of 100 under {lead.score.preset}")
    else:
        st.markdown("Out of 100: " + " · ".join(f"**{lead.totals[name]:.0f}** {name}" for name in lead.top_presets))
    for component, signals in lead.reasons.items():
        points = getattr(lead.score, component)
        share = f" · {getattr(weights, component)}% of the score" if weights else ""
        st.progress(round(points), text=f"{component.capitalize()} {points:.0f}{share}")
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

    It runs as the form's callback, before the page redraws, so the page already shows the save.
    """
    status = st.session_state[f"status_{gaf_id}"]
    data.add_note(rep_id, gaf_id, status, st.session_state[f"note_{gaf_id}"])
    st.session_state[f"note_{gaf_id}"] = ""
    st.session_state.pop(f"outcome_{gaf_id}", None)  # the call sheet's outcome starts on the new status
    group = data.status_group(status)
    # Top leads has no status filter, so every lead stays on it.
    if st.session_state.get("status_group", "All") in (group, "All"):
        st.toast(f"Saved: {name}")
    else:  # the lead leaves the All leads table, so the panel moves to the top lead
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


def top_leads_page() -> None:
    """The landing page: every lead in a preset's top N that has a brief, one at a time, with its brief, score, and notes side by side.

    Previous (K) and Next (J) step through them: the leads every preset picks first, and
    each lead's tags say which presets picked it. Log call opens the next one. Every lead
    stays on the page whatever its status.
    """
    rep = data.current_rep()
    leads = data.briefed_top_leads()
    if not leads:
        st.header("Top leads", anchor=False)
        st.info("No top lead has a brief yet. Run the brief stage, or look through All leads.")
        return

    ids = [lead.gaf_id for lead in leads]
    st.session_state.shown_ids = ids
    # This page keeps its own selected lead, apart from the All leads table's.
    if st.session_state.get("top_lead_id") not in ids:
        st.session_state.top_lead_id = ids[0]
    position = ids.index(st.session_state.top_lead_id)
    next_id = ids[position + 1] if position + 1 < len(ids) else None

    with st.container(horizontal=True, vertical_alignment="center"):
        st.header("Top leads", anchor=False, width="content")
        st.space("stretch")
        st.button("Previous", icon=":material/arrow_back:", shortcut="K", disabled=position == 0, on_click=step_lead, args=("top_lead_id", -1))
        st.button("Next", icon=":material/arrow_forward:", shortcut="J", disabled=next_id is None, on_click=step_lead, args=("top_lead_id", 1))

    status = data.current_statuses(rep.id, ids)[st.session_state.top_lead_id]
    top_n = data.top_leads_per_preset()
    order = f"Every lead in a preset's top {top_n} that has a brief. Leads more presets pick come first, then the highest total."
    st.caption(f"Lead {position + 1} of {len(ids)} · Status: **{status}**", help=order)

    lead = data.get_lead(st.session_state.top_lead_id)
    if show_header(lead) or st.session_state.pop("call_next", False):
        call_sheet(rep.id, lead, status, next_id, "top_lead_id")

    st.html(DETAIL_SCROLLBAR_CSS)
    brief_column, why_column, notes_column = st.columns([5, 3, 3])
    with brief_column:
        st.markdown("**Brief**")
        with st.container(height=TOP_BOX_HEIGHT, border=True, key="brief_box"):
            show_brief(lead)
    with why_column:
        st.markdown("**Why**")
        with st.container(height=TOP_BOX_HEIGHT, border=True, key="why_box"):
            show_why(lead, None)
    with notes_column:
        st.markdown("**Notes**")
        with st.container(height=TOP_BOX_HEIGHT, border=True, key="notes_box"):
            show_notes(rep.id, lead, status)


def all_leads_page() -> None:
    """The All leads page: the preset picker, sidebar filters, the status filter, the lead table, and the selected lead."""
    territory = data.load_territory()
    radius = int(territory["radius_miles"])
    scoring = data.load_scoring_config()
    rep = data.current_rep()

    title_column, preset_column = st.columns([3, 2], vertical_alignment="center")
    title_column.header("All leads", anchor=False)
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

    # live: the table filters as the rep types. type="search" adds a clear button.
    search = st.sidebar.text_input("Search", placeholder="Name or phone", type="search", live=True)
    tiers = st.sidebar.multiselect("Tier", data.TIERS, placeholder="All tiers")
    max_miles = st.sidebar.slider("Max distance", min_value=1, max_value=radius, value=radius, format="%d mi")

    leads = data.list_leads(search, tiers, max_miles, preset)
    noun = "contractor" if len(leads) == 1 else "contractors"
    st.caption(f"{len(leads)} {noun} near {territory['zip']}, within {max_miles} miles")

    table_column, detail_column = st.columns([5, 3])

    with table_column:
        statuses = data.current_statuses(rep.id, [lead.gaf_id for lead in leads])
        counts = {group: sum(data.status_group(statuses[lead.gaf_id]) == group for lead in leads) for group in data.STATUS_GROUPS}
        with st.container(horizontal=True, vertical_alignment="center"):
            group = st.segmented_control(
                "Status",
                [*data.STATUS_GROUPS, "All"],
                default="To contact",
                required=True,
                key="status_group",
                format_func=lambda option: f"{option} {counts[option]}" if option in counts else option,
                label_visibility="collapsed",
            )
            st.space("stretch")
            st.button("Previous", icon=":material/keyboard_arrow_up:", shortcut="K", type="tertiary", on_click=step_lead, args=("lead_id", -1))
            st.button("Next", icon=":material/keyboard_arrow_down:", shortcut="J", type="tertiary", on_click=step_lead, args=("lead_id", 1))
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
        position = ids.index(st.session_state.lead_id)
        st.session_state.lead_table = {"selection": {"rows": [position], "columns": [], "cells": []}}
        next_id = ids[position + 1] if position + 1 < len(ids) else None

        tags = data.all_tags()
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
                "Tags": st.column_config.MultiselectColumn(options=tags, color=[TAG_COLORS.get(tag, PRESET_TAG_COLOR) for tag in tags]),
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
        if show_header(lead) or st.session_state.pop("call_next", False):
            call_sheet(rep.id, lead, statuses[lead.gaf_id], next_id, "lead_id")

        why_tab, brief_tab, notes_tab = st.tabs(["Why", "Brief" if lead.brief else "Brief (none)", "Notes"])
        st.html(DETAIL_SCROLLBAR_CSS)
        with why_tab:
            with st.container(height=TAB_HEIGHT, border=True, key="why_box"):
                show_why(lead, scoring.presets[preset])
        with brief_tab:
            with st.container(height=TAB_HEIGHT, border=True, key="brief_box"):
                show_brief(lead)
        with notes_tab:
            with st.container(height=TAB_HEIGHT, border=True, key="notes_box"):
                show_notes(rep.id, lead, statuses[lead.gaf_id])


def main() -> None:
    """Draw the sidebar both pages share (the page links, the app's name, and the rep), then run the rep's page.

    Top leads is the landing page. Each page's file in app_pages/ calls its function above.
    """
    st.set_page_config(page_title="Ridgeline Leads", layout="wide")
    if data.database_missing():
        st.error("No database yet. From the repo root, run: `mkdir -p data && cp seed/leads.db data/leads.db`")
        st.stop()
    rep = data.current_rep()

    page = st.navigation(
        [
            st.Page("app_pages/top_leads.py", title="Top leads", icon=":material/star:", default=True),
            st.Page("app_pages/all_leads.py", title="All leads", icon=":material/table_rows:"),
        ]
    )
    st.sidebar.subheader("Ridgeline Leads", anchor=False)
    st.sidebar.caption(f"Signed in as **{rep.name}**")
    page.run()
