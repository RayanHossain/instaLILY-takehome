"""Coveo search adapter for GAF's contractor locator.

GAF's "find a contractor" page searches a Coveo index. We replay the same
search request directly, without the browser's analytics, facets, or history.
"""

import time
from collections.abc import Iterator
from typing import Any

import httpx

from app.sources import USER_AGENT

SEARCH_PIPELINE = "prod-gaf-recommended-residential-contractors"
PAGE_SIZE = 100

FIELDS_TO_INCLUDE = [
    "gaf_contractor_id",
    "gaf_contractor_type",
    "gaf_contractor_dba",
    "gaf_navigation_title",
    "gaf_phone",
    "gaf_f_city",
    "gaf_f_state_code",
    "gaf_postal_code",
    "gaf_f_country_code",
    "gaf_latitude",
    "gaf_longitude",
    "gaf_rating",
    "gaf_number_of_reviews",
    "gaf_f_contractor_certifications_and_awards_residential",
    "gaf_f_contractor_designations_residential",
    "gaf_f_contractor_specialties_residential",
    "gaf_f_contractor_raq_specialties_residential",
    "gaf_f_contractor_technologies_residential",
    "gaf_enrolled_in_gaf_leads",
    "distanceinmiles",
    "uri",
]


def build_search_body(lat: float, lng: float, radius_miles: float, first_result: int = 0) -> dict[str, Any]:
    """Build the JSON body for one page of contractors within radius_miles of (lat, lng).

    Coveo computes each contractor's distance with a query function, then filters
    on that computed field. dist() returns meters; 0.000621371 converts to miles.
    """
    return {
        "aq": f"@distanceinmiles <= {radius_miles} AND @gaf_f_country_code = USA",
        "cq": 'NOT @gaf_content_type=="NO CONTENT TYPE FILTER"',
        "queryFunctions": [
            {
                "fieldName": "@distanceinmiles",
                "function": f"dist(@gaf_latitude, @gaf_longitude, {lat}, {lng})*0.000621371",
            }
        ],
        "pipeline": SEARCH_PIPELINE,
        "searchHub": SEARCH_PIPELINE,
        "sortCriteria": "relevancy",
        "locale": "en-US",
        "numberOfResults": PAGE_SIZE,
        "firstResult": first_result,
        "fieldsToInclude": FIELDS_TO_INCLUDE,
    }


def fetch_pages(
    org_id: str,
    api_key: str,
    lat: float,
    lng: float,
    radius_miles: float,
    *,
    transport: httpx.BaseTransport | None = None,
) -> Iterator[httpx.Response]:
    """Yield each page of search results as the raw HTTP response, until every result is fetched.

    The caller should save each response before parsing it: the next page is only
    requested (and this response's totalCount only read) after the caller is done.
    Exits with a message if Coveo rejects the API key.

    Tests pass an httpx.MockTransport as transport; None uses the real network.
    """
    url = f"https://{org_id}.org.coveo.com/rest/search/v2?organizationId={org_id}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "User-Agent": USER_AGENT,
    }

    first_result = 0
    with httpx.Client(headers=headers, timeout=30, transport=transport) as client:
        while True:
            response = client.post(url, json=build_search_body(lat, lng, radius_miles, first_result))
            if response.status_code in (401, 403):
                raise SystemExit(
                    f"Coveo rejected the API key (HTTP {response.status_code}). "
                    "Replace COVEO_API_KEY in .env with a current key."
                )
            response.raise_for_status()
            yield response

            first_result += PAGE_SIZE
            if first_result >= response.json()["totalCount"]:
                return
            time.sleep(1)  # about one request per second, to be polite to GAF's search


def parse_result(result: dict[str, Any]) -> dict[str, Any]:
    """Map one Coveo search result to contractor column values.

    Coveo puts the fields we asked for under result["raw"]. A field GAF has no
    value for is left out of the result entirely.
    """
    raw = result["raw"]
    review_count = raw.get("gaf_number_of_reviews")
    enrolled = raw.get("gaf_enrolled_in_gaf_leads")
    return {
        "gaf_id": raw["gaf_contractor_id"],
        "name": raw["gaf_navigation_title"],
        "phone": raw.get("gaf_phone"),
        "city": raw.get("gaf_f_city"),
        "state": raw.get("gaf_f_state_code"),
        "postal_code": raw.get("gaf_postal_code"),
        "lat": raw.get("gaf_latitude"),
        "lng": raw.get("gaf_longitude"),
        "profile_url": raw.get("uri"),
        # GAF reports 0.0 when there are no reviews; that means unrated, not a bad rating.
        "rating": raw.get("gaf_rating") if review_count else None,
        "review_count": review_count,
        "certifications": raw.get("gaf_f_contractor_certifications_and_awards_residential", []),
        "designations": raw.get("gaf_f_contractor_designations_residential", []),
        "specialties": raw.get("gaf_f_contractor_specialties_residential", []),
        # GAF sends 1 for enrolled contractors, never sends 0, and omits the field for
        # everyone else. Omitted could mean "not enrolled" or "not reported", so we
        # store None (unknown) rather than guess False.
        "enrolled_in_gaf_leads": None if enrolled is None else bool(enrolled),
    }
