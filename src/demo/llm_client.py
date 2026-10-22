"""Provider-neutral LLM client (specs/005-demo-mode-and-approval §1.3, FR-1.8) [LLM-DEP].

Speaks the OpenAI-compatible chat-completions wire shape over plain HTTP (`httpx`, already a
project dependency) against whatever `LLM_BASE_URL` names — today that's Google's Gemini API
(`https://generativelanguage.googleapis.com/v1beta/openai/`, confirmed 2026-10 against
https://ai.google.dev/gemini-api/docs/openai, not from training memory), but nothing here is
Gemini-specific. Swapping provider is an environment-variable change, not a code change.

**The key is never logged, never put in a URL, never included in any exception message.** The
OpenAI-compatible endpoint takes it as an `Authorization: Bearer` header, which already avoids
Gemini's native REST `?key=` query-param pitfall entirely — `_redact_url` below is kept anyway as a
defensive second layer, in case `LLM_BASE_URL` is ever pointed at a native-style endpoint that does
put the key in the URL.

Three outcomes, by design, so a caller never has to guess what a bare `Exception` meant:
  - `LLMConfigError`    — a required env var is missing. Never contains any var's VALUE.
  - `LLMCallFailed`     — a transport/HTTP failure (timeout, 429, 5xx, malformed response).
  - `LLMBlockedOrEmpty` — the call succeeded but returned nothing usable: an empty/missing message,
    or any signal of safety-blocked content. Per FR spec item 4: this is a FAILURE, never silently
    treated as "no explanation needed."
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Final

import httpx

_KEY_QUERY_PARAM_RE: Final = re.compile(r"([?&])key=[^&\s]+")


def _redact_url(url: str) -> str:
    """Strip a `key=...` query param if present. Defensive — the OpenAI-compat endpoint used here
    never puts the key in the URL at all, but any error message built from a URL goes through this
    first regardless, so pointing `LLM_BASE_URL` at a different endpoint shape stays safe too."""
    return _KEY_QUERY_PARAM_RE.sub(r"\1key=REDACTED", url)


class LLMConfigError(Exception):
    """A required `LLM_*` environment variable is missing. Message never contains any value."""


class LLMCallFailed(Exception):
    """Transport/HTTP failure (timeout, rate limit, server error, malformed response)."""


class LLMBlockedOrEmpty(Exception):
    """The call succeeded but returned no usable text (empty, missing, or safety-blocked)."""


@dataclass(frozen=True, slots=True)
class LLMConfig:
    api_key: str
    base_url: str
    model: str


def load_llm_config() -> LLMConfig:
    """Read `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL` from the environment. Fails loudly and
    specifically (which variable, never its value) rather than silently defaulting any of them —
    the same discipline `src/api/settings.py` already uses for every other secret in this repo."""
    missing = [
        name for name in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
        if not os.environ.get(name)
    ]
    if missing:
        raise LLMConfigError(
            "missing required environment variable(s): " + ", ".join(missing)
        )
    return LLMConfig(
        api_key=os.environ["LLM_API_KEY"],
        base_url=os.environ["LLM_BASE_URL"],
        model=os.environ["LLM_MODEL"],
    )


def _looks_blocked_or_empty(body: dict) -> bool:
    choices = body.get("choices")
    if not choices:
        return True
    choice = choices[0]
    finish_reason = str(choice.get("finish_reason") or "").lower()
    if finish_reason in ("content_filter", "safety", "blocked"):
        return True
    message = choice.get("message") or {}
    content = message.get("content")
    return not content or not str(content).strip()


def call_llm(*, system: str, user: str, config: LLMConfig, timeout_s: float = 20.0) -> str:
    """One call. No retry here — that's the caller's concern (different callers want different
    retry/pause policy); this function either returns real text or raises one of the three
    exceptions above. Never includes the key, or any header, in any exception message."""
    url = config.base_url.rstrip("/") + "/chat/completions"
    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=timeout_s,
        )
    except httpx.TimeoutException as exc:
        raise LLMCallFailed(f"timed out after {timeout_s}s calling {_redact_url(url)}") from exc
    except httpx.HTTPError as exc:
        raise LLMCallFailed(f"transport error calling {_redact_url(url)}: {type(exc).__name__}") from exc

    if response.status_code == 429:
        raise LLMCallFailed(f"rate limited (429) by {_redact_url(url)}")
    if response.status_code >= 400:
        # The provider's error body is safe to surface (code/message only, per Gemini's documented
        # shape) — but redact defensively in case any field ever echoes the request URL.
        detail = _redact_url(response.text[:500])
        raise LLMCallFailed(f"HTTP {response.status_code} from {_redact_url(url)}: {detail}")

    try:
        body = response.json()
    except ValueError as exc:
        raise LLMCallFailed("response was not valid JSON") from exc

    if _looks_blocked_or_empty(body):
        raise LLMBlockedOrEmpty("empty choices, empty content, or a safety/content-filter signal")

    return str(body["choices"][0]["message"]["content"])


def call_llm_with_retry(
    *, system: str, user: str, config: LLMConfig,
    timeout_s: float = 20.0, retry_pause_s: float = 5.0,
) -> str:
    """At most one retry, only for the transient failure class (`LLMCallFailed` — timeout/429/5xx).
    `LLMBlockedOrEmpty` is NOT retried: a safety block or empty reply against the identical fixed
    demo prompt is unlikely to differ on a second attempt, and retrying it only spends free-tier
    quota for no benefit."""
    try:
        return call_llm(system=system, user=user, config=config, timeout_s=timeout_s)
    except LLMCallFailed:
        time.sleep(retry_pause_s)
        return call_llm(system=system, user=user, config=config, timeout_s=timeout_s)
