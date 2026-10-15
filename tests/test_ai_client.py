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
from app.db.models import AiCache, AiCall, StageRun
from app.settings import Settings

# _env_file=None: never read the developer's .env. The key only ever reaches the mock transport.
SETTINGS = Settings(
    _env_file=None, database_url="unused", coveo_org_id="test-org", coveo_api_key="test-key", gemini_api_key="test-key"
)
PROMPT = "company_v1"
INPUT = "Acme Roofing has served Newark since 1999."
VALID = '{"name": "Acme Roofing", "founded_year": 1999}'

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
    """A test prompt, fresh pacing, and the fake clock."""
    (tmp_path / f"{PROMPT}.txt").write_text("Return the company's name and founding year as JSON.")
    monkeypatch.setattr(client, "PROMPTS", tmp_path)
    monkeypatch.setattr(client, "_last_request_at", 0.0)
    fake = FakeClock()
    monkeypatch.setattr(time, "monotonic", fake.monotonic)
    monkeypatch.setattr(time, "sleep", fake.sleep)
    return fake


@pytest.fixture
def run(session: Session) -> StageRun:
    """The stage run a test's AI calls belong to."""
    run = StageRun(stage="test", model=SETTINGS.gemini_model)
    session.add(run)
    session.commit()
    return run


def answer(text: str) -> tuple[int, dict[str, Any]]:
    """A Gemini generateContent reply whose answer is text, reporting 120 tokens in and 30 out."""
    return 200, {
        "candidates": [{"content": {"role": "model", "parts": [{"text": text}]}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30},
    }


def fake_gemini(
    replies: list[tuple[int, dict[str, Any]]], requests: list[httpx.Request], clock: FakeClock | None = None
) -> httpx.MockTransport:
    """A fake Gemini API: answers each request with the next reply (the last one repeats) and keeps the requests.

    Given the fake clock, each request takes 2.5 seconds on it.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if clock:
            clock.now += 2.5
        status_code, body = replies.pop(0) if len(replies) > 1 else replies[0]
        return httpx.Response(status_code, json=body)

    return httpx.MockTransport(handle)


def logged(session: Session) -> list[AiCall]:
    """The ai_calls rows, oldest first."""
    return list(session.scalars(select(AiCall).order_by(AiCall.id)))


def test_invalid_answer_is_retried_once_with_the_error(session: Session, clock: FakeClock, run: StageRun) -> None:
    requests: list[httpx.Request] = []
    replies = [answer('{"name": "Acme Roofing"}'), answer(VALID)]

    result = client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=fake_gemini(replies, requests))

    assert result == Company(name="Acme Roofing", founded_year=1999)
    assert json.loads(requests[0].content)["generationConfig"]["maxOutputTokens"] == 2048  # a runaway answer is cut off
    saved = session.scalars(select(AiCache).order_by(AiCache.id)).all()
    assert [(row.valid, row.error is None) for row in saved] == [(False, False), (True, True)]  # both kept
    retry = json.loads(requests[1].content)["contents"]
    assert [turn["role"] for turn in retry] == ["user", "model", "user"]  # the question, the bad answer, the error
    assert "founded_year" in retry[2]["parts"][0]["text"]  # the error names the missing field
    assert [call.outcome for call in logged(session)] == ["invalid", "ok after a retry"]
    assert clock.pauses == [6.0]  # paced: 10 requests per minute is one every 6 seconds


def test_answer_still_invalid_after_the_retry_is_remembered_until_the_key_changes(session: Session, run: StageRun) -> None:
    requests: list[httpx.Request] = []
    transport = fake_gemini([answer("No idea.")], requests)

    assert client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=transport) is None
    assert client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=transport) is None

    assert len(requests) == 2  # the second call was skipped from memory: the model's fault isn't asked again
    assert [(call.cache_hit, call.outcome) for call in logged(session)] == [(False, "invalid"), (False, "invalid"), (True, "invalid")]
    assert [(row.valid, row.gave_up) for row in session.scalars(select(AiCache).order_by(AiCache.id))] == [(False, False), (False, True)]
    assert client.totals(session, run)["remembered as invalid"] == 1

    # The key covers the model, the prompt version, and the input, so another model is asked afresh.
    other_model = SETTINGS.model_copy(update={"gemini_model": "gemma-4-26b-a4b-it"})
    client.generate(session, other_model, PROMPT, INPUT, Company, run=run, transport=transport)
    assert len(requests) == 4


def test_api_errors_are_never_remembered(session: Session, run: StageRun) -> None:
    requests: list[httpx.Request] = []
    internal_error = (500, {"error": {"code": 500, "message": "Internal error encountered.", "status": "INTERNAL"}})
    transport = fake_gemini([internal_error], requests)

    assert client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=transport) is None
    assert client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=transport) is None

    assert len(requests) == 8  # Google's fault: every run tries again, four tries each


def test_cache_hit_makes_no_call(session: Session, run: StageRun) -> None:
    requests: list[httpx.Request] = []
    # Gemma sometimes wraps its JSON in a code fence despite the JSON mode; it is stripped before validation.
    transport = fake_gemini([answer(f"```json\n{VALID}\n```")], requests)

    first = client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=transport)
    second = client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=transport)

    assert first == second == Company(name="Acme Roofing", founded_year=1999)
    assert len(requests) == 1
    assert [(call.cache_hit, call.outcome) for call in logged(session)] == [(False, "ok"), (True, "ok")]

    # The model is part of the cache key, so another model is asked afresh.
    other_model = SETTINGS.model_copy(update={"gemini_model": "gemma-4-26b-a4b-it"})
    client.generate(session, other_model, PROMPT, INPUT, Company, run=run, transport=transport)
    assert len(requests) == 2


def test_rate_limit_stops_the_stage_cleanly_after_four_tries(session: Session, clock: FakeClock, run: StageRun) -> None:
    requests: list[httpx.Request] = []

    with pytest.raises(SystemExit, match="a rerun picks up from the cache"):
        client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=fake_gemini([RATE_LIMITED], requests))

    assert len(requests) == 4
    assert clock.pauses == [7.0, 7.0, 7.0]  # the 429 says to wait 7 s, so that is the pause
    calls = logged(session)
    assert [call.outcome for call in calls] == ["rate-limited"] * 4  # every try is logged
    assert calls[0].error == "HTTP 429: Resource has been exhausted."
    assert session.scalars(select(AiCache)).all() == []  # nothing came back, so nothing was saved


@pytest.mark.parametrize(
    ("reply", "outcome"),
    [
        (UNAVAILABLE, "overloaded"),
        (DEADLINE_EXCEEDED, "error"),
        ((500, {"error": {"code": 500, "message": "Internal error encountered.", "status": "INTERNAL"}}), "error"),
    ],
)
def test_other_errors_skip_the_input_after_four_tries(
    session: Session, clock: FakeClock, run: StageRun, reply: tuple[int, dict[str, Any]], outcome: str
) -> None:
    requests: list[httpx.Request] = []

    result = client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=fake_gemini([reply], requests))

    assert result is None  # skipped: the stage moves on to its next input
    assert len(requests) == 4
    assert clock.pauses == [15, 30, 60]  # these errors suggest no delay, so the default pauses apply
    calls = logged(session)
    assert [call.outcome for call in calls] == [outcome] * 4
    assert calls[0].error.startswith(f"HTTP {reply[0]}: ")


def test_a_dropped_connection_is_retried_then_the_input_skipped(session: Session, clock: FakeClock, run: StageRun) -> None:
    requests: list[httpx.Request] = []

    def drops(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.", request=request)

    result = client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=httpx.MockTransport(drops))

    assert result is None  # skipped, rather than stopping the stage
    assert len(requests) == 4
    assert clock.pauses == [15, 30, 60]
    calls = logged(session)
    assert [call.outcome for call in calls] == ["error"] * 4
    assert calls[0].error == "no answer (RemoteProtocolError: Server disconnected without sending a response.)"


def test_an_error_retrying_cant_fix_skips_the_input_at_once(session: Session, run: StageRun) -> None:
    requests: list[httpx.Request] = []
    bad_request = (400, {"error": {"code": 400, "message": "Request contains an invalid argument.", "status": "INVALID_ARGUMENT"}})

    result = client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=fake_gemini([bad_request], requests))

    assert result is None
    assert len(requests) == 1
    assert [(call.outcome, call.error) for call in logged(session)] == [("error", "HTTP 400: Request contains an invalid argument.")]


def test_missing_key_is_named_before_any_call(session: Session, run: StageRun) -> None:
    requests: list[httpx.Request] = []
    no_key = SETTINGS.model_copy(update={"gemini_api_key": None})

    with pytest.raises(SystemExit, match="GEMINI_API_KEY"):
        client.generate(session, no_key, PROMPT, INPUT, Company, run=run, transport=fake_gemini([answer("{}")], requests))

    assert requests == []
    assert logged(session) == []


def test_every_attempt_is_logged_and_counted(session: Session, clock: FakeClock, run: StageRun) -> None:
    requests: list[httpx.Request] = []
    transport = fake_gemini([UNAVAILABLE, answer('{"name": "Acme Roofing"}'), answer(VALID)], requests, clock)

    client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=transport)
    client.generate(session, SETTINGS, PROMPT, INPUT, Company, run=run, transport=transport)  # from the cache

    assert len(requests) == 3
    calls = logged(session)
    assert [(c.outcome, c.cache_hit, c.latency_seconds, c.input_tokens, c.output_tokens) for c in calls] == [
        ("overloaded", False, 2.5, None, None),  # a failed request reports no tokens
        ("invalid", False, 2.5, 120, 30),
        ("ok after a retry", False, 2.5, 120, 30),
        ("ok", True, None, None, None),  # a cache hit makes no request
    ]
    assert {(c.run_id, c.stage, c.prompt_name, c.model) for c in calls} == {(run.id, "test", PROMPT, SETTINGS.gemini_model)}
    assert calls[0].error == "HTTP 503: The model is overloaded."
    assert "founded_year" in calls[1].error
    assert client.totals(session, run) == {
        "requests to the model": 3,
        "cache hits": 1,
        "remembered as invalid": 0,
        "ok": 0,
        "ok after a retry": 1,
        "invalid": 1,
        "rate-limited": 0,
        "overloaded": 1,
        "error": 0,
        "input tokens": 240,
        "output tokens": 60,
        "average seconds per answer": 2.5,
    }
