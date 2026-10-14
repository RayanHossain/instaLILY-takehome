"""Coveo search adapter for GAF's contractor locator.

GAF's "find a contractor" page searches a Coveo index. We replay the same
search request directly, without the browser's analytics, facets, or history.
"""

from typing import Any

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
