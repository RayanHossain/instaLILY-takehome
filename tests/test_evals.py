"""The extraction eval against a small gold file, with the real AI client talking to a fake Gemini API."""

import time
from functools import partial
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from app.ai import client as ai
from app.evals.extract import evaluate_extract
from tests.test_extract import SETTINGS, add_contractors, answer_with_the_fixture

# What the text really says about Matute Roofing, for this test: the fixture answer finds
# "Roofing" (not a gold service), misses "Roof repair" and "Doors", and finds "Rockland
# County, NY" (not gold), so precision and recall differ by field.
GOLD = """
"1113654":
  founded_year: []
  services: ["Residential roofing", "commercial  ROOFING", "Metal roofing", "Roof repair"]
  other_trades: ["Siding", "Gutters", "Windows", "Doors"]
  building_types: ["Residential", "Commercial"]
  service_areas: ["North Jersey", "Bergen County, NJ"]
  owner_names: []
"""


def test_the_eval_scores_each_field_and_answers_from_the_cache(
    session: Session, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    add_contractors(session)
    gold_path = tmp_path / "gold.yaml"
    gold_path.write_text(GOLD, encoding="utf-8")
    requests: list[httpx.Request] = []

    def gemini(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return answer_with_the_fixture(request)

    monkeypatch.setattr(ai, "generate", partial(ai.generate, transport=httpx.MockTransport(gemini)))
    monkeypatch.setattr(ai, "_last_request_at", 0.0)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)

    scores = {score.field: score for score in evaluate_extract(session, SETTINGS, gold_path)}

    assert len(requests) == 1  # a cache miss: the AI is asked once
    assert (scores["services"].gold, scores["services"].found, scores["services"].right) == (4, 4, 3)
    assert (scores["services"].precision, scores["services"].recall) == (0.75, 0.75)  # case and spacing don't matter
    assert (scores["other_trades"].precision, scores["other_trades"].recall) == (1.0, 0.75)  # the invented solar quote was dropped
    assert (scores["service_areas"].precision, scores["service_areas"].recall) == (2 / 3, 1.0)
    assert (scores["founded_year"].precision, scores["founded_year"].recall) == (None, None)  # nothing to find, nothing found

    evaluate_extract(session, SETTINGS, gold_path)
    assert len(requests) == 1  # the second eval is answered from the cache
