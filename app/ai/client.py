"""The project's one way to call an AI model: generate().

Calls go to the Gemma model named by GEMINI_MODEL on the Gemini API, paced to
GEMINI_REQUESTS_PER_MINUTE. Every answer is saved in ai_cache before it is parsed, and
an answer that validates is reused for the same model, prompt, and input, so a rerun
makes no calls. Every attempt, a cache hit included, is logged in ai_calls under the
stage run that asked, and totals() counts a run's attempts. Prompts are versioned text
files in app/ai/prompts/.
"""

import hashlib
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AiCache, AiCall, StageRun
from app.settings import Settings

PROMPTS = Path(__file__).parent / "prompts"
TIMEOUT_SECONDS = 120  # the SDK sets no timeout of its own, so a stuck request would wait forever
# Real answers are under 1,000 tokens. The cap ends a runaway answer (a model stuck repeating
# itself) within a minute, as cut-off JSON that fails validation and gets the one retry.
MAX_OUTPUT_TOKENS = 2048
# HTTP errors worth trying again: the set the google-genai SDK itself retries by default.
RETRY_CODES = {408, 429, 500, 502, 503, 504}
# Pauses before trying again after one of those errors or a timeout, when the error suggests none.
RETRY_PAUSES = [15, 30, 60]
# Each attempt's outcome in ai_calls, in the order totals() counts them. A 429 is "rate-limited",
# a 503 "overloaded", and any other API error, or a timeout, "error".
OUTCOMES = ["ok", "ok after a retry", "invalid", "rate-limited", "overloaded", "error"]
ERROR_OUTCOMES = {429: "rate-limited", 503: "overloaded"}

Output = TypeVar("Output", bound=BaseModel)

_last_request_at = 0.0  # time.monotonic() when the last request started, for pacing


def generate(
    session: Session,
    settings: Settings,
    prompt_name: str,
    input_text: str,
    output_model: type[Output],
    *,
    run: StageRun,
    contractor_id: str | None = None,
    transport: httpx.BaseTransport | None = None,
) -> Output | None:
    """Ask the model the prompt about input_text, and return its answer as an output_model.

    The newest valid answer cached for the same model, prompt, and input is returned
    without a call. Otherwise each answer is saved, then validated; an invalid answer
    gets one retry that shows the model the validation error. Every attempt, the cache
    hit included, is logged as a row in ai_calls.

    Args:
        session: An open session. Each answer and each ai_calls row is committed at once.
        settings: The Gemini key, model, and requests per minute.
        prompt_name: A file in app/ai/prompts, without ".txt". Its name carries its
            version (e.g. "extract_facts_v1"): to change a prompt or its output model,
            add a new file, so cached answers to the old one aren't reused.
        input_text: What the prompt is about. It is sent after the prompt.
        output_model: The Pydantic model the answer must match. It is also sent as the
            response schema, which steers Gemma but doesn't bind it: hence the validation.
        run: The stage run asking. Each ai_calls row belongs to it.
        contractor_id: The contractor the input is about, if any, for the ai_calls rows.
        transport: Tests pass an httpx.MockTransport; None uses the real network.

    Returns:
        The validated answer, or None if it was still invalid after the retry.

    Raises:
        SystemExit: GEMINI_API_KEY isn't set, or the API kept failing with an error worth retrying.
    """

    def log(
        outcome: str,
        *,
        cache_hit: bool = False,
        seconds: float | None = None,
        usage: types.GenerateContentResponseUsageMetadata | None = None,
        error: str | None = None,
    ) -> None:
        """Write this attempt's row to ai_calls, and commit it."""
        session.add(
            AiCall(
                run_id=run.id,
                stage=run.stage,
                contractor_id=contractor_id,
                prompt_name=prompt_name,
                model=settings.gemini_model,
                cache_hit=cache_hit,
                outcome=outcome,
                latency_seconds=seconds,
                input_tokens=usage.prompt_token_count if usage else None,
                output_tokens=usage.candidates_token_count if usage else None,
                error=error,
            )
        )
        session.commit()

    cache_key = hashlib.sha256(f"{settings.gemini_model}\n{prompt_name}\n{input_text}".encode()).hexdigest()
    cached = session.scalar(
        select(AiCache.response)
        .where(AiCache.cache_key == cache_key, AiCache.valid)
        .order_by(AiCache.id.desc())
        .limit(1)
    )
    if cached is not None:
        log("ok", cache_hit=True)
        return output_model.model_validate_json(_strip_code_fence(cached))

    if not settings.gemini_api_key:
        raise SystemExit("GEMINI_API_KEY is not set. Put a Gemini API key in .env to run the AI stages.")
    prompt = (PROMPTS / f"{prompt_name}.txt").read_text(encoding="utf-8")
    contents: list[types.Content] = [types.UserContent(parts=[types.Part.from_text(text=f"{prompt}\n\n{input_text}")])]
    config = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=output_model, max_output_tokens=MAX_OUTPUT_TOKENS
    )
    http_options = types.HttpOptions(
        timeout=TIMEOUT_SECONDS * 1000,  # milliseconds
        httpx_client=httpx.Client(transport=transport) if transport else None,
    )

    with genai.Client(api_key=settings.gemini_api_key.get_secret_value(), http_options=http_options) as client:
        for attempt in range(2):  # the first answer, and one retry if it's invalid
            response, seconds = _ask(client, settings, contents, config, log)
            answer = response.text or ""
            saved = AiCache(cache_key=cache_key, model=settings.gemini_model, prompt_name=prompt_name, response=answer)
            session.add(saved)
            session.commit()  # saved before it is parsed
            try:
                result = output_model.model_validate_json(_strip_code_fence(answer))
            except ValidationError as error:
                saved.error = str(error)
                log("invalid", seconds=seconds, usage=response.usage_metadata, error=str(error))
                # The retry shows the model its answer and what was wrong with it.
                contents += [
                    types.ModelContent(parts=[types.Part.from_text(text=answer)]),
                    types.UserContent(
                        parts=[types.Part.from_text(text=f"That answer is not valid:\n{error}\n\nReply with the corrected JSON only.")]
                    ),
                ]
                continue
            saved.valid = True
            log("ok" if attempt == 0 else "ok after a retry", seconds=seconds, usage=response.usage_metadata)
            return result
    return None


def totals(session: Session, run: StageRun) -> dict[str, float]:
    """Count a run's ai_calls rows: requests to the model by outcome, cache hits, tokens, and speed.

    The outcomes count requests only; a cache hit is not a request.
    """
    calls = session.scalars(select(AiCall).where(AiCall.run_id == run.id)).all()
    requests = [call for call in calls if not call.cache_hit]
    outcomes = Counter(call.outcome for call in requests)
    # How long the model took to answer, valid or not; errors are left out.
    answer_seconds = [call.latency_seconds or 0.0 for call in requests if call.outcome in ("ok", "ok after a retry", "invalid")]
    return {
        "requests to the model": len(requests),
        "cache hits": len(calls) - len(requests),
        **{outcome: outcomes[outcome] for outcome in OUTCOMES},
        "input tokens": sum(call.input_tokens or 0 for call in requests),
        "output tokens": sum(call.output_tokens or 0 for call in requests),
        "average seconds per answer": round(sum(answer_seconds) / len(answer_seconds), 1) if answer_seconds else 0.0,
    }


def _ask(
    client: genai.Client,
    settings: Settings,
    contents: list[types.Content],
    config: types.GenerateContentConfig,
    log: Callable[..., None],
) -> tuple[types.GenerateContentResponse, float]:
    """Send one request, paced, and return the response and the seconds it took.

    A failed attempt is logged. An error in RETRY_CODES (a 429, a 503, ...) or no answer
    within the timeout is tried again after a pause: the one the error suggests, if it
    suggests one. After four tries in all, the stage stops cleanly, and a rerun picks up
    from the cache. Any other API error is raised.
    """
    global _last_request_at
    tries = 0
    while True:
        tries += 1
        # Pacing: requests start at least 60 / GEMINI_REQUESTS_PER_MINUTE seconds apart.
        wait = _last_request_at + 60 / settings.gemini_requests_per_minute - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()
        try:
            response = client.models.generate_content(model=settings.gemini_model, contents=contents, config=config)
        except errors.APIError as error:
            problem = f"HTTP {error.code}"
            log(ERROR_OUTCOMES.get(error.code, "error"), seconds=time.monotonic() - _last_request_at, error=f"{problem}: {error.message}")
            if error.code not in RETRY_CODES:
                raise
            # A 429 can say how long to wait: {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}.
            details = error.details.get("error", {}).get("details", []) if isinstance(error.details, dict) else []
            suggested = [float(d["retryDelay"].removesuffix("s")) for d in details if d.get("@type", "").endswith("RetryInfo")]
        except httpx.TimeoutException:
            problem, suggested = f"no answer within {TIMEOUT_SECONDS} s", []
            log("error", seconds=time.monotonic() - _last_request_at, error=problem)
        else:
            return response, time.monotonic() - _last_request_at

        if tries > len(RETRY_PAUSES):
            raise SystemExit(
                f"ai: {problem} from {settings.gemini_model} on {tries} tries in a row, so the stage stopped. "
                "Answers so far are saved, and a rerun picks up from the cache."
            )
        delay = suggested[0] if suggested else RETRY_PAUSES[tries - 1]
        print(f"ai: {problem} from {settings.gemini_model}; trying again in {delay:.0f} s")
        time.sleep(delay)


def _strip_code_fence(answer: str) -> str:
    """The answer without the ``` or ```json fence Gemma sometimes wraps it in, despite the JSON mode."""
    return answer.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
