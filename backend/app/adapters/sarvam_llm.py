"""Sarvam-105B adapter. Structured-output helper + defensive JSON parsing —
the core small-model pattern, validated even at M0."""
from __future__ import annotations

import json
import re
import time

import httpx

from app import config


def _extract_json(text: str) -> dict:
    """Strip code fences / prose and parse the first JSON object."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?", "", t).strip()
    t = re.sub(r"```$", "", t).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", t, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON object found in LLM output: {text[:300]!r}")
    return json.loads(m.group(0))


# sarvam-105b is a REASONING model: even at reasoning_effort="low" it spends tokens on
# a hidden chain-of-thought (returned in message.reasoning_content) that counts against
# max_tokens. Budget to the tier ceiling and auto-retry on truncation.
# NOTE: starter tier hard-caps max_tokens at 4096 — exceeding it is a 400 error.
TIER_MAX_TOKENS = 4096
DEFAULT_MAX_TOKENS = 4096
LENGTH_RETRIES = 5
LOW_REASONING_LENGTH_RETRIES = 3

# Transient failures shouldn't kill a ~30-call run. Retry on rate-limit / server errors, and on
# 403: a genuinely bad key fails on the first call, so a 403 after many successes is a transient
# auth/abuse hiccup (seen under concurrent load) and is worth a bounded retry.
TRANSIENT_STATUS = {403, 429, 500, 502, 503, 504}


def with_transient_retry(fn, tries: int = 3):
    for i in range(tries):
        try:
            return fn()
        except httpx.RequestError:  # network/transport/timeout — always transient
            if i < tries - 1:
                time.sleep(1.5 * (i + 1))
                continue
            raise
        except Exception as e:  # noqa: BLE001 - inspect status to decide retry
            if getattr(e, "status_code", None) in TRANSIENT_STATUS and i < tries - 1:
                time.sleep(_retry_delay_s(e, i))
                continue
            raise


def _retry_delay_s(error: Exception, attempt_index: int) -> float:
    headers = getattr(error, "headers", {}) or {}
    retry_after = None
    for key in ("retry-after", "Retry-After"):
        if key in headers:
            retry_after = headers[key]
            break
    try:
        return max(float(retry_after), 1.5 * (attempt_index + 1))
    except (TypeError, ValueError):
        return 1.5 * (attempt_index + 1)


def complete_json(client, system: str, user: str, run, stage: str,
                  temperature: float = 0.2, max_tokens: int = DEFAULT_MAX_TOKENS,
                  fallback_text: bool = False) -> dict:
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    def _reasoning_effort(attempt: int):
        # Keep the first attempt plus three truncation retries at low reasoning. If
        # those still exhaust the token budget, disable reasoning completely.
        return None if attempt > LOW_REASONING_LENGTH_RETRIES + 1 else "low"

    def _call(mt: int, attempt: int) -> tuple[str, str]:
        mt = min(mt, TIER_MAX_TOKENS)  # never exceed the tier ceiling (400 otherwise)
        reasoning_effort = _reasoning_effort(attempt)
        t0 = time.time()
        resp = with_transient_retry(lambda: client.chat.completions(
            messages=messages,
            model=config.LLM_MODEL,
            temperature=temperature,
            max_tokens=mt,
            reasoning_effort=reasoning_effort,
        ))
        dt = round(time.time() - t0, 2)
        choice = resp.choices[0]
        content = choice.message.content or ""
        finish = choice.finish_reason
        try:
            usage = resp.usage.model_dump() if getattr(resp, "usage", None) else None
        except Exception:
            usage = str(getattr(resp, "usage", None))
        run.log(stage=stage, kind="llm", model=config.LLM_MODEL, attempt=attempt,
                reasoning_effort=reasoning_effort,
                max_tokens=mt, finish_reason=finish, user=user[:800],
                response=content[:2000], latency_s=dt, usage=usage)
        return content, finish

    content, finish = _call(max_tokens, attempt=1)
    # Repair: reasoning ate the budget (truncated / empty) -> retry at the tier ceiling.
    # Reasoning length varies run to run, so fresh attempts often land even with the same cap.
    for attempt in range(2, LENGTH_RETRIES + 2):
        if finish != "length" and content.strip():
            break
        content, finish = _call(TIER_MAX_TOKENS, attempt=attempt)

    if not content.strip():
        raise ValueError(
            f"LLM returned empty content (finish_reason={finish}); reasoning likely "
            f"exceeded max_tokens even after {LENGTH_RETRIES} retries."
        )
    try:
        return _extract_json(content)
    except (ValueError, json.JSONDecodeError):
        if fallback_text:  # speaker/framing turns: a bare sentence is acceptable
            raw = content.strip().strip("`").strip()
            if len(raw) >= 2 and raw[0] == raw[-1] == '"':
                raw = raw[1:-1]
            return {"text": raw}
        raise
