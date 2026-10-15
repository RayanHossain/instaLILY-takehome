"""The rep's lead list: a table of contractors and the selected one's details.

Run from the repo root: streamlit run app/ui/app.py
Every read goes through app/ui/data.py.
"""

import sys
from pathlib import Path

# `streamlit run app/ui/app.py` puts this file's folder (app/ui) first on sys.path, where
# "import app" would find this file instead of the app package. Adding the repo root
# ahead of it, once, makes "app" mean the package.
REPO_ROOT = str(Path(__file__).resolve().parents[2])
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import streamlit as st

from app.ui import data

DASH = "—"  # shown for a missing value


def show_field(label: str, value: object) -> None:
    """Show one "Label: value" line of the detail panel, with a dash for a missing value."""
    st.markdown(f"**{label}:** {DASH if value is None or value == '' else value}")


st.set_page_config(page_title="Roofing leads", layout="wide")
territory = data.load_territory()
radius = float(territory["radius_miles"])

search = st.sidebar.text_input("Search", placeholder="Name or phone")
tiers = st.sidebar.multiselect("Tier", data.TIERS, placeholder="All tiers")
max_miles = st.sidebar.slider("Max distance (miles)", min_value=0.0, max_value=radius, value=radius, step=0.5)

leads = data.list_leads(search, tiers, max_miles)
st.header(f"{len(leads)} contractors within {max_miles:g} miles of {territory['zip']}")
if not leads:
    st.info("No contractors match. Try another search or wider filters.")
    st.stop()

table_column, detail_column = st.columns([2, 1], gap="large")

with table_column:
    table = st.dataframe(
        [
            {
                "Name": lead.name,
                "City": ", ".join(part for part in (lead.city, lead.state) if part) or None,
                "Miles": lead.distance_miles,
                "Tier": lead.tier,
                "Rating": "No reviews" if lead.rating is None else f"{lead.rating:.1f}",
                "Reviews": lead.review_count,
                "Phone": lead.phone,
            }
            for lead in leads
        ],
        column_config={"Miles": st.column_config.NumberColumn(format="%.1f")},
        hide_index=True,
        height=700,
        placeholder=DASH,
        on_select="rerun",
        selection_mode="single-row-required",
    )

with detail_column:
    # Exactly one row is always selected. Its position is in the leads list,
    # even after the rep re-sorts the table by clicking a column.
    lead = data.get_lead(leads[table.selection.rows[0]].gaf_id)

    st.subheader(lead.name)
    show_field("Address", lead.street_address)
    show_field("Phone", lead.phone)
    show_field("Website", None if lead.website_url is None else f"[{lead.website_url}]({lead.website_url})")
    show_field("GAF profile", None if lead.profile_url is None else f"[View on gaf.com]({lead.profile_url})")
    show_field("Distance", None if lead.distance_miles is None else f"{lead.distance_miles:.1f} miles")
    show_field("Tier", lead.tier)
    show_field("Certifications", ", ".join(lead.certifications))
    show_field("Rating", "No reviews" if lead.rating is None else f"{lead.rating:.1f} ({lead.review_count} reviews)")
    show_field("In business since", lead.in_business_since)
    show_field("GAF Leads", {True: "Yes", False: "No", None: "Unknown"}[lead.enrolled_in_gaf_leads])
    if lead.about_text:
        st.markdown("**About**")
        st.text(lead.about_text)  # plain text, so a "$" or "*" in it isn't read as Markdown

    st.divider()
    st.markdown("**Why this lead:** the score breakdown arrives in a later slice.")
    st.markdown("**Brief:** the AI-written brief arrives in a later slice.")
    st.markdown("**Notes and status:** the rep's notes and status arrive in a later slice.")
