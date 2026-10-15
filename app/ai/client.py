"""The project's one way to call an AI model: generate().

Calls go to the Gemma model named by GEMINI_MODEL on the Gemini API, paced to
GEMINI_REQUESTS_PER_MINUTE. Every answer is saved in ai_cache before it is parsed, and
an answer that validates is reused for the same model, prompt, and input, so a rerun
makes no calls. Prompts are versioned text files in app/ai/prompts/.
"""

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AiCache
from app.settings import Settings

PROMPTS = Path(__file__).parent / "prompts"
TIMEOUT_SECONDS = 120  # the SDK sets no timeout of its own, so a stuck request would wait forever
# Pauses after a 429, a 503, or a timeout before trying again, when the error suggests none.
RETRY_PAUSES = [15, 30, 60]

Output = TypeVar("Output", bound=BaseModel)


@dataclass
class Stats:
    """What generate() has done in this process, for a stage's closing summary."""

    calls: int = 0  # requests that got an answer
    seconds: float = 0.0  # time spent waiting for those answers
    cache_hits: int = 0
    invalid: int = 0  # answers that failed validation
    failed: int = 0  # inputs given up on, still invalid after the retry
    rate_limited: int = 0  # 429s
    unavailable: int = 0  # 503s
    timeouts: int = 0


stats = Stats()
_last_request_at = 0.0  # time.monotonic() when the last request started, for pacing


def generate(
    session: Session,
    settings: Settings,
    prompt_name: str,
    input_text: str,
    output_model: type[Output],
    *,
    transport: httpx.BaseTransport | None = None,
) -> Output | None:
    """Ask the model the prompt about input_text, and return its answer as an output_model.

    The newest valid answer cached for the same model, prompt, and input is returned
    without a call. Otherwise each answer is saved, then validated; an invalid answer
    gets one retry that shows the model the validation error.

    Args:
        session: An open session. Each answer is committed as soon as it is saved.
        settings: The Gemini key, model, and requests per minute.
        prompt_name: A file in app/ai/prompts, without ".txt". Its name carries its
            version (e.g. "extract_facts_v1"): to change a prompt or its output model,
            add a new file, so cached answers to the old one aren't reused.
        input_text: What the prompt is about. It is sent after the prompt.
        output_model: The Pydantic model the answer must match. It is also sent as the
            response schema, which steers Gemma but doesn't bind it: hence the validation.
        transport: Tests pass an httpx.MockTransport; None uses the real network.

    Returns:
        The validated answer, or None if it was still invalid after the retry.

    Raises:
        SystemExit: GEMINI_API_KEY isn't set, or the API kept answering 429, 503, or nothing.
    """
    cache_key = hashlib.sha256(f"{settings.gemini_model}\n{prompt_name}\n{input_text}".encode()).hexdigest()
    cached = session.scalar(
        select(AiCache.response)
        .where(AiCache.cache_key == cache_key, AiCache.valid)
        .order_by(AiCache.id.desc())
        .limit(1)
    )
    if cached is not None:
        stats.cache_hits += 1
        return output_model.model_validate_json(_strip_code_fence(cached))

    if not settings.gemini_api_key:
        raise SystemExit("GEMINI_API_KEY is not set. Put a Gemini API key in .env to run the AI stages.")
    prompt = (PROMPTS / f"{prompt_name}.txt").read_text(encoding="utf-8")
    contents: list[types.Content] = [types.UserContent(parts=[types.Part.from_text(text=f"{prompt}\n\n{input_text}")])]
    config = types.GenerateContentConfig(response_mime_type="application/json", response_schema=output_model)
    http_options = types.HttpOptions(
        timeout=TIMEOUT_SECONDS * 1000,  # milliseconds
        httpx_client=httpx.Client(transport=transport) if transport else None,
    )

    with genai.Client(api_key=settings.gemini_api_key.get_secret_value(), http_options=http_options) as client:
        for _ in range(2):  # the first answer, and one retry if it's invalid
            answer = _ask(client, settings, contents, config)
            saved = AiCache(cache_key=cache_key, model=settings.gemini_model, prompt_name=prompt_name, response=answer)
            session.add(saved)
            session.commit()  # saved before it is parsed
            try:
                result = output_model.model_validate_json(_strip_code_fence(answer))
            except ValidationError as error:
                stats.invalid += 1
                saved.error = str(error)
                session.commit()
                # The retry shows the model its answer and what was wrong with it.
                contents += [
                    types.ModelContent(parts=[types.Part.from_text(text=answer)]),
                    types.UserContent(
                        parts=[types.Part.from_text(text=f"That answer is not valid:\n{error}\n\nReply with the corrected JSON only.")]
                    ),
                ]
                continue
            saved.valid = True
            session.commit()
            return result

    stats.failed += 1
    return None


def _ask(
    client: genai.Client, settings: Settings, contents: list[types.Content], config: types.GenerateContentConfig
) -> str:
    """Send one request, paced, and return the text of the answer.

    A 429, a 503, or no answer within the timeout is tried again after a pause: the one
    the error suggests, if it suggests one. After four tries in all, the stage stops
    cleanly, and a rerun picks up from the cache.
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
            if error.code not in (429, 503):
                raise
            if error.code == 429:
                stats.rate_limited += 1
            else:
                stats.unavailable += 1
            problem = f"HTTP {error.code}"
            # A 429 can say how long to wait: {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "37s"}.
            details = error.details.get("error", {}).get("details", []) if isinstance(error.details, dict) else []
            suggested = [float(d["retryDelay"].removesuffix("s")) for d in details if d.get("@type", "").endswith("RetryInfo")]
        except httpx.TimeoutException:
            stats.timeouts += 1
            problem, suggested = f"no answer within {TIMEOUT_SECONDS} s", []
        else:
            stats.calls += 1
            stats.seconds += time.monotonic() - _last_request_at
            return response.text or ""

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
