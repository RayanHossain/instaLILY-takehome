"""The Coveo request builder and result parser, checked against a saved real response."""

import json
from pathlib import Path
from typing import Any

from app.sources.coveo import build_search_body, parse_result

FIXTURE = Path(__file__).parent / "fixtures" / "coveo_page.json"


def fixture_results() -> dict[str, dict[str, Any]]:
    """The saved search results, keyed by GAF contractor ID."""
    results = json.loads(FIXTURE.read_text())["results"]
    return {result["raw"]["gaf_contractor_id"]: result for result in results}


def test_build_search_body_matches_the_locator_request() -> None:
    body = build_search_body(lat=40.7217861, lng=-74.0094471, radius_miles=25, first_result=200)

    assert body["aq"] == "@distanceinmiles <= 25 AND @gaf_f_country_code = USA"
    assert body["cq"] == 'NOT @gaf_content_type=="NO CONTENT TYPE FILTER"'
    assert body["queryFunctions"] == [
        {
            "fieldName": "@distanceinmiles",
            "function": "dist(@gaf_latitude, @gaf_longitude, 40.7217861, -74.0094471)*0.000621371",
        }
    ]
    assert body["pipeline"] == body["searchHub"] == "prod-gaf-recommended-residential-contractors"
    assert (body["sortCriteria"], body["locale"]) == ("relevancy", "en-US")
    assert (body["numberOfResults"], body["firstResult"]) == (100, 200)
    assert "gaf_contractor_id" in body["fieldsToInclude"]
    # The browser's analytics, history, timezone, and facets are left out on purpose.
    assert not {"analytics", "actionsHistory", "timezone", "facets"} & body.keys()


def test_parse_unrated_contractor() -> None:
    assert parse_result(fixture_results()["7158181"]) == {
        "gaf_id": "7158181",
        "name": "Golovin Roofing LLC",
        "phone": "(959) 237-0800",
        "city": "Flushing",
        "state": "NY",
        "postal_code": "11358",
        "lat": 40.762181,
        "lng": -73.798373,
        "profile_url": "https://www.gaf.com/en-us/roofing-contractors/residential/usa/ny/flushing/golovin-roofing-llc-7158181",
        "rating": None,  # GAF says 0.0, but with no reviews that means unrated
        "review_count": 0,
        "certifications": ["GAF Certified™ - Certification"],
        "designations": ["CERTIFIED^_^RESIDENTIAL^_^C"],
        "specialties": [],  # GAF left the field out
        "enrolled_in_gaf_leads": None,  # GAF left the field out, so unknown
    }


def test_parse_rated_contractor_enrolled_in_gaf_leads() -> None:
    row = parse_result(fixture_results()["1150334"])

    assert (row["name"], row["rating"], row["review_count"]) == ("Apex Roofing Solutions", 5.0, 118)
    assert row["enrolled_in_gaf_leads"] is True
    assert row["postal_code"] == "07424"  # leading zero kept


def test_parse_contractor_with_specialties() -> None:
    row = parse_result(fixture_results()["1138492"])

    assert row["specialties"] == ["Metal"]
    assert row["rating"] == 5.0
    assert row["enrolled_in_gaf_leads"] is None
