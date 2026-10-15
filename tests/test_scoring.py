"""The scoring rules on their own: each component, every bucket edge, the flags, presets, and totals."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from app.db.models import Score
from app.scoring import (
    ScoringConfig,
    average,
    distance_signals,
    flags,
    founding_year,
    load_scoring_config,
    score_contractor,
    stability_signals,
    total,
    value_signals,
    winnability_signals,
)

CONFIG = load_scoring_config()


def points(signals: list[dict[str, Any]], name: str) -> float:
    """The points of the named signal."""
    return next(signal["points"] for signal in signals if signal["signal"] == name)


def test_value_with_complete_and_missing_data() -> None:
    complete = value_signals(CONFIG, 312, "Master Elite", ["Siding"])

    assert [(signal["input"], signal["points"]) for signal in complete] == [("312 reviews", 90), ("Master Elite", 85), ("Siding", 80)]
    assert average(complete) == 86.5  # (90*50 + 85*30 + 80*20) / 100
    assert average(value_signals(CONFIG, None, None, [])) == 50  # missing data is neutral


@pytest.mark.parametrize(
    ("reviews", "expected"), [(None, 50), (0, 50), (4, 50), (5, 55), (24, 55), (25, 70), (99, 70), (100, 90)]
)
def test_review_count_buckets(reviews: int | None, expected: int) -> None:
    assert points(value_signals(CONFIG, reviews, None, []), "reviews") == expected


@pytest.mark.parametrize(
    ("tier", "value", "winnability"),
    [("President's Club", 100, 20), ("Master Elite", 85, 50), ("Certified Plus", 60, 80), ("Certified", 40, 60), (None, 50, 50)],
)
def test_tier_points_in_value_and_winnability(tier: str | None, value: int, winnability: int) -> None:
    assert points(value_signals(CONFIG, None, tier, []), "tier") == value
    assert points(winnability_signals(CONFIG, None, None, None, tier), "tier") == winnability


def test_other_trades_any_or_none() -> None:
    assert points(value_signals(CONFIG, None, None, ["Gutters", "Siding"]), "other trades") == 80
    assert points(value_signals(CONFIG, None, None, []), "other trades") == 50


def test_winnability_with_complete_and_missing_data() -> None:
    complete = winnability_signals(CONFIG, 17, 2009, "the GAF profile", "Master Elite")

    assert complete[0]["input"] == "17 years in business (founded 2009, per the GAF profile)"
    assert average(complete) == 45  # (40*50 + 50*50) / 100
    assert average(winnability_signals(CONFIG, None, None, None, None)) == 50


@pytest.mark.parametrize(
    ("years", "expected"), [(0, 100), (1, 100), (2, 85), (4, 85), (5, 60), (14, 60), (15, 40), (None, 50)]
)
def test_years_in_business_buckets(years: int | None, expected: int) -> None:
    assert points(winnability_signals(CONFIG, years, None, None, None), "years in business") == expected


@pytest.mark.parametrize(
    ("rating", "reviews", "expected"),
    [
        (4.5, 5, 90),
        (4.49, 5, 75),
        (4.0, 5, 75),
        (3.99, 5, 55),
        (3.5, 5, 55),
        (3.49, 5, 25),
        (4.9, 4, 50),  # too few reviews for the rating to count
        (None, None, 50),
    ],
)
def test_stability_buckets(rating: float | None, reviews: int | None, expected: int) -> None:
    assert average(stability_signals(CONFIG, rating, reviews)) == expected


@pytest.mark.parametrize(("miles", "expected"), [(0, 100), (12.5, 50), (25, 0), (40, 0), (None, 50)])
def test_distance_falls_linearly_to_0_at_the_radius(miles: float | None, expected: float) -> None:
    assert average(distance_signals(CONFIG, miles, 25)) == expected


def test_flags_fire_at_their_thresholds_and_not_just_past_them() -> None:
    assert flags(CONFIG, 3.4, 5, None, None) == [{"flag": "Low rating", "kind": "risk", "reason": "rated 3.4 from 5 reviews"}]
    assert flags(CONFIG, 3.5, 5, None, None) == []  # not below 3.5
    assert flags(CONFIG, 3.4, 4, None, None) == []  # too few reviews
    assert flags(CONFIG, None, None, 2, 2024) == [{"flag": "New business", "kind": "opportunity", "reason": "founded 2024"}]
    assert flags(CONFIG, None, None, 3, 2023) == []  # 3 years in business is not new


def test_score_contractor_records_where_the_founding_year_came_from() -> None:
    scored = score_contractor(
        CONFIG,
        review_count=312,
        rating=4.8,
        tier="Master Elite",
        other_trades=["Siding"],
        founded_year=2025,
        founded_from="the GAF profile",
        distance_miles=5.0,
        radius_miles=25,
        current_year=2026,
    )

    assert (scored["value"], scored["winnability"], scored["stability"], scored["distance"]) == (86.5, 75, 90, 80)
    assert scored["reasons"]["winnability"][0]["founded_from"] == "the GAF profile"
    assert scored["flags"] == [{"flag": "New business", "kind": "opportunity", "reason": "founded 2025"}]
    assert scored["rules_version"] == CONFIG.rules_version


@pytest.mark.parametrize(("gaf_year", "expected"), [(2009, (2009, "the GAF profile")), (None, (None, None))])
def test_the_founding_year_is_gafs_in_business_since_only(
    gaf_year: int | None, expected: tuple[int | None, str | None]
) -> None:
    assert founding_year(gaf_year) == expected


def test_a_preset_whose_weights_dont_add_up_to_100_fails_to_load() -> None:
    raw = yaml.safe_load(Path("config/scoring.yaml").read_text())
    raw["presets"]["Big accounts"]["value"] = 60  # 60 + 15 + 15 + 15 = 105

    with pytest.raises(ValidationError, match=r"Big accounts[\s\S]*weights add up to 105, not 100"):
        ScoringConfig.model_validate(raw)


def test_total_is_the_presets_weighted_sum() -> None:
    score = Score(value=80, winnability=60, stability=50, distance=90)

    assert total(score, CONFIG.presets["Balanced"]) == 71.5  # (80*35 + 60*30 + 50*15 + 90*20) / 100
    assert total(score, CONFIG.presets["Big accounts"]) == 74.0
    assert total(score, CONFIG.presets["Quick wins"]) == 71.0


def test_a_signal_is_a_guess_only_when_its_data_was_missing() -> None:
    def guesses(signals: list[dict[str, Any]]) -> list[bool]:
        return [signal["guess"] for signal in signals]

    assert guesses(value_signals(CONFIG, None, None, [])) == [True, True, True]
    assert guesses(value_signals(CONFIG, 312, "Master Elite", ["Siding"])) == [False, False, False]
    # Master Elite scores the same 50 points as no tier, but it's known, so not a guess.
    assert guesses(winnability_signals(CONFIG, 17, 2009, "the GAF profile", "Master Elite")) == [False, False]
    assert guesses(winnability_signals(CONFIG, None, None, None, None)) == [True, True]
    assert guesses(stability_signals(CONFIG, 4.8, 3)) == [True]  # too few reviews to count the rating
    assert guesses(stability_signals(CONFIG, 4.8, 30)) == [False]
    assert guesses(distance_signals(CONFIG, 12.5, 25)) == [False]  # halfway: 50 points, but measured
    assert guesses(distance_signals(CONFIG, None, 25)) == [True]
