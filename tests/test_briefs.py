"""The briefs' rules on their own: which selling points fit a lead, and the checks on the AI's brief."""

from typing import Any

import pytest

from app.briefs import Brief, check_brief, match_selling_points

LOW_RATING = {"flag": "Low rating", "kind": "risk", "reason": "rated 3.2 from 41 reviews"}
NEW_BUSINESS = {"flag": "New business", "kind": "opportunity", "reason": "founded 2025"}


def matched(**lead: Any) -> dict[str, str]:
    """The selling points that fit a lead with nothing special about it, apart from what's given."""
    plain = {"tier": "Certified", "other_trades": [], "services": [], "postal_code": "07470", "stability": 50, "flags": []}
    return match_selling_points(**(plain | lead))


def valid_brief(**changes: Any) -> Brief:
    """A brief that passes every check for a lead given fact 7, matched to introductory pricing, owned by Dana Reyes."""
    brief = {
        "why_this_contractor": "It replaces roofs across Morris County. Its crews work near the branch.",
        "first_touch": {"opener": "Call to introduce the branch and its stock.", "reason": "It is close by."},
        "follow_ups": [{"step": "Offer introductory pricing on a first order.", "reason": "A low-risk way to start."}],
        "questions": ["What jobs are you bidding next month?", "Which shingle lines do you install most?"],
        "selling_points": ["introductory_pricing"],
        "ask_for": "Dana Reyes",
        "cited_fact_ids": [7],
    }
    return Brief.model_validate(brief | changes)


def check(brief: Brief) -> None:
    """Run the checks for that lead."""
    check_brief(brief, fact_ids={7}, matched_points={"introductory_pricing"}, owners=["Dana Reyes (Owner)"])


def test_a_plain_lead_only_fits_introductory_pricing() -> None:
    assert list(matched()) == ["introductory_pricing"]  # it fits every lead, but never as the opening offer


def test_other_trades_fit_one_stop_supply() -> None:
    assert matched(other_trades=["Siding", "Gutters"])["one_stop_supply"] == "it also does Siding, Gutters"


@pytest.mark.parametrize(("tier", "fits"), [("President's Club", True), ("Master Elite", True), ("Certified Plus", False), (None, False)])
def test_top_tiers_fit_full_gaf_systems(tier: str | None, fits: bool) -> None:
    assert ("full_gaf_systems" in matched(tier=tier)) is fits


@pytest.mark.parametrize(
    ("postal_code", "fits"),
    [("10013", True), ("10475", True), ("11358", True), ("11432", True), ("11691", True), ("10501", False), ("11501", False), ("07470", False), (None, False)],
)
def test_new_york_city_zip_codes_fit_delivery_windows(postal_code: str | None, fits: bool) -> None:
    assert ("delivery_windows" in matched(postal_code=postal_code)) is fits


@pytest.mark.parametrize(
    ("services", "fits"),
    [(["Roof replacement"], True), (["Re-roofing"], True), (["Reroofing"], True), (["Roof repair", "Inspections"], False)],
)
def test_replacement_or_re_roofing_services_fit_rooftop_delivery(services: list[str], fits: bool) -> None:
    assert ("rooftop_delivery" in matched(services=services)) is fits


@pytest.mark.parametrize(
    ("stability", "flags", "fits"),
    [(75, [], True), (74.9, [], False), (90, [LOW_RATING], False), (90, [NEW_BUSINESS], True)],
)
def test_credit_terms_fit_a_stable_account_with_no_risk_flag(stability: float, flags: list[dict[str, str]], fits: bool) -> None:
    assert ("credit_terms" in matched(stability=stability, flags=flags)) is fits


def test_a_valid_brief_passes_the_checks() -> None:
    check(valid_brief())


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"cited_fact_ids": [7, 999]}, "cited_fact_ids [999] are not among the facts given"),
        ({"selling_points": ["credit_terms"]}, "selling_points ['credit_terms'] are not among the matched selling points"),
        ({"why_this_contractor": "It is ranked first under Big accounts."}, "never mention a rank"),
        ({"questions": ["Did you know your score is 82?", "What jobs are next?"]}, "never mention a rank"),
        ({"why_this_contractor": "One. Two. Three."}, "has 3 sentences, not one or two"),
        ({"follow_ups": []}, "follow_ups has 0 steps"),
        ({"questions": ["Only one?"]}, "questions has 1, not two or three"),
        ({"first_touch": {"opener": "Offer credit terms right away.", "reason": "Cash flow."}}, "never the opening offer"),
        ({"ask_for": "Pat Smith"}, "ask_for 'Pat Smith' is not one of the owners given"),
    ],
)
def test_a_brief_breaking_a_rule_fails_the_checks(changes: dict[str, Any], problem: str) -> None:
    with pytest.raises(ValueError, match=problem.replace("[", r"\[").replace("]", r"\]")):
        check(valid_brief(**changes))


def test_abbreviations_dont_count_as_sentences() -> None:
    check(valid_brief(why_this_contractor="Matute Roofing Inc. replaces roofs in Wayne. It is close by."))
