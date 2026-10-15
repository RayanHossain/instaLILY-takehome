"""Scoring rules: four component scores from 0 to 100, flags, and reasons in plain words.

Every number is in config/scoring.yaml, checked here when it's loaded. Each component is
the weighted average of its signals, each scored 0-100; a signal with no data scores
missing_points (50), so missing data is neutral. A preset's weights combine the four
components into a total, which is worked out when leads are read and never stored.
Scoring uses rules only, never the AI.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, model_validator

from app.db.models import Score

COMPONENTS = ["value", "winnability", "stability", "distance"]


class Bucket(BaseModel):
    """Points for a number at or above at_least. The highest bucket the number reaches wins."""

    at_least: float
    points: int


class BucketSignal(BaseModel):
    """A signal scored by buckets of a number, and its weight in its component."""

    weight: int
    buckets: list[Bucket]


class TierSignal(BaseModel):
    """A signal scored by the contractor's GAF tier, and its weight in its component."""

    weight: int
    points: dict[str, int]


class OtherTradesSignal(BaseModel):
    """Points when the contractor's facts name any other trade, and when they don't."""

    weight: int
    any: int
    none: int


class ValueRules(BaseModel):
    """Value's signals: review count, tier, and other trades."""

    reviews: BucketSignal
    tier: TierSignal
    other_trades: OtherTradesSignal


class WinnabilityRules(BaseModel):
    """Winnability's signals: years in business and tier."""

    years_in_business: BucketSignal
    tier: TierSignal


class StabilityRules(BaseModel):
    """Stability's one signal: the rating, counted only with enough reviews."""

    min_reviews: int
    rating: list[Bucket]


class FlagRules(BaseModel):
    """The thresholds of the two flags."""

    low_rating_below: float
    low_rating_min_reviews: int
    new_business_years_under: int


class Preset(BaseModel):
    """Weights for the four components. They must add up to 100."""

    value: int
    winnability: int
    stability: int
    distance: int

    @model_validator(mode="after")
    def weights_add_up_to_100(self) -> "Preset":
        """Refuse a preset whose weights don't add up to 100."""
        weights = self.value + self.winnability + self.stability + self.distance
        if weights != 100:
            raise ValueError(f"weights add up to {weights}, not 100")
        return self


class ScoringConfig(BaseModel):
    """Everything in config/scoring.yaml."""

    rules_version: str
    missing_points: int
    value: ValueRules
    winnability: WinnabilityRules
    stability: StabilityRules
    flags: FlagRules
    default_preset: str
    presets: dict[str, Preset]

    @model_validator(mode="after")
    def default_preset_exists(self) -> "ScoringConfig":
        """Refuse a default_preset that isn't one of the presets."""
        if self.default_preset not in self.presets:
            raise ValueError(f"default_preset {self.default_preset!r} is not one of the presets")
        return self


def load_scoring_config() -> ScoringConfig:
    """Read and check config/scoring.yaml. A preset whose weights don't add up to 100 fails here, by name."""
    return ScoringConfig.model_validate(yaml.safe_load(Path("config/scoring.yaml").read_text()))


def founding_year(gaf_year: int | None) -> tuple[int | None, str | None]:
    """The founding year the rules use, and where it came from: GAF's "In business since" only.

    Contractors submit documents to GAF to get certified, so GAF's year is the checked one;
    a year on their own website or in their About text is easier to inflate. Extracted
    founding years stay facts with their quotes, but never feed the score.

    Returns:
        (year, "the GAF profile"), or (None, None) when GAF gives no year.
    """
    if gaf_year is None:
        return None, None
    return gaf_year, "the GAF profile"


def score_contractor(
    config: ScoringConfig,
    *,
    review_count: int | None,
    rating: float | None,
    tier: str | None,
    other_trades: list[str],
    founded_year: int | None,
    founded_from: str | None,
    distance_miles: float | None,
    radius_miles: float,
    current_year: int,
) -> dict[str, Any]:
    """Score one contractor: its four components, its flags, and the reasons behind each component.

    Args:
        config: The rules, from config/scoring.yaml.
        review_count: GAF's review count, or None.
        rating: GAF's rating, or None when there are no reviews.
        tier: The contractor's GAF tier, or None.
        other_trades: The other trades its facts name, if any.
        founded_year: The year the business started, or None if unknown.
        founded_from: Where founded_year came from, e.g. "the GAF profile".
        distance_miles: Miles from the branch, or None without coordinates.
        radius_miles: The territory radius, where the distance score reaches 0.
        current_year: Passed in so that tests don't depend on the clock.

    Returns:
        The scores table's columns: value, winnability, stability, distance, flags, reasons, rules_version.
    """
    years = current_year - founded_year if founded_year is not None and founded_year <= current_year else None
    reasons = {
        "value": value_signals(config, review_count, tier, other_trades),
        "winnability": winnability_signals(config, years, founded_year, founded_from, tier),
        "stability": stability_signals(config, rating, review_count),
        "distance": distance_signals(config, distance_miles, radius_miles),
    }
    return {
        **{component: average(signals) for component, signals in reasons.items()},
        "flags": flags(config, rating, review_count, years, founded_year),
        "reasons": reasons,
        "rules_version": config.rules_version,
    }


def value_signals(
    config: ScoringConfig, review_count: int | None, tier: str | None, other_trades: list[str]
) -> list[dict[str, Any]]:
    """Value's signals, each with its input in plain words, its points, its weight, and whether
    it's a guess: its data was missing, so it scored the neutral middle."""
    rules = config.value
    reviews = review_count or 0
    return [
        {
            "signal": "reviews",
            "input": _count(reviews, "review") if reviews else "no reviews",
            "points": _bucket_points(reviews, rules.reviews.buckets),
            "weight": rules.reviews.weight,
            "guess": not reviews,
        },
        {
            "signal": "tier",
            "input": tier or "no tier",
            "points": rules.tier.points.get(tier, config.missing_points),
            "weight": rules.tier.weight,
            "guess": tier is None,
        },
        {
            "signal": "other trades",
            "input": ", ".join(other_trades) if other_trades else "no other trades found",
            "points": rules.other_trades.any if other_trades else rules.other_trades.none,
            "weight": rules.other_trades.weight,
            "guess": not other_trades,  # none found isn't proof of none
        },
    ]


def winnability_signals(
    config: ScoringConfig, years: int | None, founded_year: int | None, founded_from: str | None, tier: str | None
) -> list[dict[str, Any]]:
    """Winnability's signals. The years signal also records where the founding year came from."""
    rules = config.winnability
    return [
        {
            "signal": "years in business",
            "input": "founding year unknown" if years is None else f"{_count(years, 'year')} in business (founded {founded_year}, per {founded_from})",
            "points": config.missing_points if years is None else _bucket_points(years, rules.years_in_business.buckets),
            "weight": rules.years_in_business.weight,
            "guess": years is None,
            "founded_from": founded_from,
        },
        {
            "signal": "tier",
            "input": tier or "no tier",
            "points": rules.tier.points.get(tier, config.missing_points),
            "weight": rules.tier.weight,
            "guess": tier is None,
        },
    ]


def stability_signals(config: ScoringConfig, rating: float | None, review_count: int | None) -> list[dict[str, Any]]:
    """Stability's one signal: the rating, when it comes from enough reviews."""
    rules = config.stability
    reviews = review_count or 0
    if rating is not None and reviews >= rules.min_reviews:
        return [
            {"signal": "rating", "input": f"rated {rating:.1f} from {reviews} reviews", "points": _bucket_points(rating, rules.rating), "weight": 100, "guess": False}
        ]
    text = "no reviews" if not reviews else f"only {_count(reviews, 'review')}, too few to count the rating"
    return [{"signal": "rating", "input": text, "points": config.missing_points, "weight": 100, "guess": True}]


def distance_signals(config: ScoringConfig, distance_miles: float | None, radius_miles: float) -> list[dict[str, Any]]:
    """Distance's one signal: 100 at the branch, falling linearly to 0 at the territory radius."""
    if distance_miles is None:
        return [{"signal": "distance", "input": "location unknown", "points": config.missing_points, "weight": 100, "guess": True}]
    points = round(max(0.0, 100 * (1 - distance_miles / radius_miles)), 1)
    return [{"signal": "distance", "input": f"{distance_miles:.1f} miles from the branch", "points": points, "weight": 100, "guess": False}]


def flags(
    config: ScoringConfig, rating: float | None, review_count: int | None, years: int | None, founded_year: int | None
) -> list[dict[str, str]]:
    """The contractor's flags, each a risk or an opportunity, with its reason."""
    rules = config.flags
    found = []
    if rating is not None and (review_count or 0) >= rules.low_rating_min_reviews and rating < rules.low_rating_below:
        found.append({"flag": "Low rating", "kind": "risk", "reason": f"rated {rating:.1f} from {review_count} reviews"})
    if years is not None and years < rules.new_business_years_under:
        found.append({"flag": "New business", "kind": "opportunity", "reason": f"founded {founded_year}"})
    return found


def average(signals: list[dict[str, Any]]) -> float:
    """A component's score: the weighted average of its signals' points, to one decimal."""
    return round(sum(signal["points"] * signal["weight"] for signal in signals) / sum(signal["weight"] for signal in signals), 1)


def total(score: Score, preset: Preset) -> float:
    """A lead's total under a preset: the weighted sum of its four components, to one decimal.

    The services rank leads with it, and the brief stage ranks through the services, so the
    two can't drift apart.
    """
    weighted = sum(getattr(score, component) * getattr(preset, component) for component in COMPONENTS)
    return round(weighted / 100, 1)


def _bucket_points(number: float, buckets: list[Bucket]) -> int:
    """The points of the highest bucket the number reaches."""
    return max((bucket for bucket in buckets if number >= bucket.at_least), key=lambda bucket: bucket.at_least).points


def _count(number: int, word: str) -> str:
    """'1 review', '312 reviews': a number and a word, plural when it needs to be."""
    return f"{number} {word}" if number == 1 else f"{number} {word}s"
