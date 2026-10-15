"""The AI client against a fake Gemini API (an httpx.MockTransport) and a fake clock."""

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import client
from app.db.models import AiCache
from app.settings import Settings

# _env_file=None: never read the developer's .env. The key only ever reaches the mock transport.
SETTINGS = Settings(
    _env_file=None, database_url="unused", coveo_org_id="test-org", coveo_api_key="test-key", gemini_api_key="test-key"
)
PROMPT = "company_v1"
INPUT = "Acme Roofing has served Newark since 1999."

RATE_LIMITED = (
    429,
    {
        "error": {
            "code": 429,
            "message": "Resource has been exhausted.",
            "status": "RESOURCE_EXHAUSTED",
            "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "7s"}],
        }
    },
)
UNAVAILABLE = (503, {"error": {"code": 503, "message": "The model is overloaded.", "status": "UNAVAILABLE"}})
DEADLINE_EXCEEDED = (
    504,
    {"error": {"code": 504, "message": "Deadline expired before operation could complete.", "status": "DEADLINE_EXCEEDED"}},
)


class Company(BaseModel):
    name: str
    founded_year: int | None


class FakeClock:
    """Stands in for time.monotonic and time.sleep: time moves only when the code pauses."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.pauses: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.pauses.append(seconds)
        self.now += seconds


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeClock:
    """A test prompt, fresh counts and pacing, and the fake clock."""
    (tmp_path / f"{PROMPT}.txt").write_text("Return the company's name and founding year as JSON.")
    monkeypatch.setattr(client, "PROMPTS", tmp_path)
    monkeypatch.setattr(client, "stats", client.Stats())
    monkeypatch.setattr(client, "_last_request_at", 0.0)
    fake = FakeClock()
    monkeypatch.setattr(time, "monotonic", fake.monotonic)
    monkeypatch.setattr(time, "sleep", fake.sleep)
    return fake


def answer(text: str) -> tuple[int, dict[str, Any]]:
    """A Gemini generateContent reply whose answer is text."""
    return 200, {"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}]}


def fake_gemini(replies: list[tuple[int, dict[str, Any]]], requests: list[httpx.Request]) -> httpx.MockTransport:
    """A fake Gemini API: answers each request with the next reply (the last one repeats) and keeps the requests."""

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status_code, body = replies.pop(0) if len(replies) > 1 else replies[0]
        return httpx.Response(status_code, json=body)

    return httpx.MockTransport(handle)


def test_invalid_answer_is_retried_once_with_the_error(session: Session, clock: FakeClock) -> None:
    requests: list[httpx.Request] = []
    replies = [answer('{"name": "Acme Roofing"}'), answer('{"name": "Acme Roofing", "founded_year": 1999}')]

    result = client.generate(session, SETTINGS, PROMPT, INPUT, Company, transport=fake_gemini(replies, requests))

    assert result == Company(name="Acme Roofing", founded_year=1999)
    assert json.loads(requests[0].content)["generationConfig"]["maxOutputTokens"] == 2048  # a runaway answer is cut off
    saved = session.scalars(select(AiCache).order_by(AiCache.id)).all()
    assert [(row.valid, row.error is None) for row in saved] == [(False, False), (True, True)]  # both kept
    retry = json.loads(requests[1].content)["contents"]
    assert [turn["role"] for turn in retry] == ["user", "model", "user"]  # the question, the bad answer, the error
    assert "founded_year" in retry[2]["parts"][0]["text"]  # the error names the missing field
    assert clock.pauses == [6.0]  # paced: 10 requests per minute is one every 6 seconds


def test_answer_still_invalid_after_the_retry_is_recorded_and_skipped(session: Session) -> None:
    requests: list[httpx.Request] = []

    result = client.generate(session, SETTINGS, PROMPT, INPUT, Company, transport=fake_gemini([answer("No idea.")], requests))

    assert result is None
    assert len(requests) == 2
    assert (client.stats.invalid, client.stats.failed) == (2, 1)
    assert [row.valid for row in session.scalars(select(AiCache))] == [False, False]


def test_cache_hit_makes_no_call(session: Session) -> None:
    requests: list[httpx.Request] = []
    # Gemma sometimes wraps its JSON in a code fence despite the JSON mode; it is stripped before validation.
    transport = fake_gemini([answer('```json\n{"name": "Acme Roofing", "founded_year": 1999}\n```')], requests)

    first = client.generate(session, SETTINGS, PROMPT, INPUT, Company, transport=transport)
    second = client.generate(session, SETTINGS, PROMPT, INPUT, Company, transport=transport)

    assert first == second == Company(name="Acme Roofing", founded_year=1999)
    assert len(requests) == 1
    assert (client.stats.calls, client.stats.cache_hits) == (1, 1)

    # The model is part of the cache key, so another model is asked afresh.
    other_model = SETTINGS.model_copy(update={"gemini_model": "gemma-4-31b-it"})
    client.generate(session, other_model, PROMPT, INPUT, Company, transport=transport)
    assert len(requests) == 2


@pytest.mark.parametrize(
    ("reply", "pauses"),
    [
        (RATE_LIMITED, [7.0, 7.0, 7.0]),  # the 429 says to wait 7 s, so that is the pause
        (UNAVAILABLE, [15, 30, 60]),  # a 503 suggests nothing, so the default pauses apply
        (DEADLINE_EXCEEDED, [15, 30, 60]),
    ],
)
def test_retryable_error_stops_the_stage_cleanly_after_four_tries(
    session: Session, clock: FakeClock, reply: tuple[int, dict[str, Any]], pauses: list[float]
) -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(SystemExit, match="a rerun picks up from the cache"):
        client.generate(session, SETTINGS, PROMPT, INPUT, Company, transport=fake_gemini([reply], requests))

    assert len(requests) == 4
    assert client.stats.http_errors == {reply[0]: 4}
    assert clock.pauses == pauses
    assert session.scalars(select(AiCache)).all() == []  # nothing came back, so nothing was saved


def test_missing_key_is_named_before_any_call(session: Session) -> None:
    requests: list[httpx.Request] = []
    no_key = SETTINGS.model_copy(update={"gemini_api_key": None})

    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        client.generate(session, no_key, PROMPT, INPUT, Company, transport=fake_gemini([answer("{}")], requests))

    assert requests == []
