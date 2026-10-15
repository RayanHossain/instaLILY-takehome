"""Briefs: the touch plan the AI writes for a top lead, and the rules and checks around it.

Rules in code pick the selling points that fit each lead, each with its reason. The AI
writes only from the facts it's given and cites them; check_brief() holds its answer
to the rules a Pydantic model can't express.
"""

import re

from pydantic import BaseModel

# A New York City ZIP code starts with one of these.
NYC_ZIP_PREFIXES = ("100", "101", "102", "103", "104", "110", "111", "112", "113", "114", "116")
# Words that would tell where the lead stands in a list. "position" is left out: a brief
# can fairly talk about positioning a product.
STANDING = re.compile(r"\b(rank\w*|scor(e|es|ed|ing)|top[ -]?(10|ten))\b|#\s?\d+", re.IGNORECASE)
# Abbreviations whose periods don't end a sentence, for counting sentences.
ABBREVIATIONS = re.compile(r"\b(Inc|Co|Corp|Ltd|LLC|St|Ave|Rd|Dr|Mr|Mrs|Ms|Jr|Sr)\.")


class FirstTouch(BaseModel):
    """The first contact: what the rep says or sends, and why it fits this contractor."""

    opener: str
    reason: str


class FollowUp(BaseModel):
    """A next step after the first touch, and why."""

    step: str
    reason: str


class Brief(BaseModel):
    """A short touch plan for one lead, written only from the facts it was given."""

    why_this_contractor: str  # one or two sentences
    first_touch: FirstTouch
    follow_ups: list[FollowUp]  # one to three
    questions: list[str]  # two or three, about upcoming jobs
    selling_points: list[str]  # selling point ids, from the lead's matched ones only
    ask_for: str | None = None  # an owner's name, when one is known
    cited_fact_ids: list[int]


def match_selling_points(
    *,
    tier: str | None,
    other_trades: list[str],
    services: list[str],
    postal_code: str | None,
    stability: float,
    flags: list[dict[str, str]],
) -> dict[str, str]:
    """The selling points that fit a lead: point id -> the reason it fits, in the order of the rules.

    Credit terms and introductory pricing fit only as later offers, never the opening one.
    """
    matched = {}
    if other_trades:
        matched["one_stop_supply"] = f"it also does {', '.join(other_trades)}"
    if tier in ("Master Elite", "President's Club"):
        matched["full_gaf_systems"] = f"it is GAF {tier}"
    if postal_code and postal_code.startswith(NYC_ZIP_PREFIXES):
        matched["delivery_windows"] = f"its address is in New York City (ZIP {postal_code})"
    replacement = [service for service in services if re.search(r"replac|re-?roof", service, re.IGNORECASE)]
    if replacement:
        matched["rooftop_delivery"] = f"its services include {', '.join(replacement)}"
    if stability >= 75 and not any(flag["kind"] == "risk" for flag in flags):
        matched["credit_terms"] = "it is a stable account with no risk flag; never the opening offer"
    matched["introductory_pricing"] = "it fits every new account; never the opening offer"
    return matched


def check_brief(brief: Brief, *, fact_ids: set[int], matched_points: set[str], owners: list[str]) -> None:
    """Raise ValueError naming every way the brief breaks a rule its Pydantic model can't express.

    Every cited fact and selling point must be one the lead was given; nothing may mention
    a rank, a score, or a top 10; why_this_contractor is one or two sentences, with one to
    three follow-ups and two or three questions; the first touch never offers credit terms
    or introductory pricing; and ask_for, if set, must be a known owner.
    """
    problems = []
    unknown_facts = sorted(set(brief.cited_fact_ids) - fact_ids)
    if unknown_facts:
        problems.append(f"cited_fact_ids {unknown_facts} are not among the facts given")
    unmatched = sorted(set(brief.selling_points) - matched_points)
    if unmatched:
        problems.append(f"selling_points {unmatched} are not among the matched selling points")
    standing = STANDING.search(brief.model_dump_json())
    if standing:
        problems.append(f"it says {standing.group(0)!r}: never mention a rank, a score, or a top 10")
    sentences = len(re.findall(r"[.!?](\s|$)", ABBREVIATIONS.sub(r"\1", brief.why_this_contractor.strip())))
    if not 1 <= sentences <= 2:
        problems.append(f"why_this_contractor has {sentences} sentences, not one or two")
    if not 1 <= len(brief.follow_ups) <= 3:
        problems.append(f"follow_ups has {len(brief.follow_ups)} steps, not one to three")
    if not 2 <= len(brief.questions) <= 3:
        problems.append(f"questions has {len(brief.questions)}, not two or three")
    first_touch = f"{brief.first_touch.opener} {brief.first_touch.reason}".lower()
    if "credit" in first_touch or "introductory" in first_touch:
        problems.append("the first touch offers credit terms or introductory pricing, which are never the opening offer")
    if brief.ask_for and not any(brief.ask_for.lower() in owner.lower() for owner in owners):
        problems.append(f"ask_for {brief.ask_for!r} is not one of the owners given")
    if problems:
        raise ValueError("; ".join(problems))
