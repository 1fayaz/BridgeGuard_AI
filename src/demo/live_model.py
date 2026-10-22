"""The real, minimal LLM call for the demo's explanation step — opt-in only, laptop only
(specs/005-demo-mode-and-approval §1.3, FR-1.8 item 7) [LLM-DEP].

Uses the provider-neutral client (`demo.llm_client`) against whatever `LLM_API_KEY`/`LLM_BASE_URL`/
`LLM_MODEL` name — currently Google's Gemini API via its OpenAI-compatible endpoint, by explicit
project decision. Switching provider is an environment-variable change, not a code change; this
module has no provider-specific logic at all.

Implements the same `draft(attempt, context) -> str` shape every other demo "model" satisfies
(`explanation.py`), so it drops into `assess_bridge` with no other change. On any failure — missing
config, timeout, rate limit, empty/blocked reply — this re-raises; `assess_bridge`'s existing
`on_model_failure` hook is what keeps the demo working, by falling through to the pre-generated
text and, beneath that, the labelled template.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from agents.risk_reasoning.agent import _SYSTEM_PROMPT
from demo.llm_client import LLMConfig, call_llm_with_retry, load_llm_config


def _context_to_prompt(context: dict[str, Any], prior_attempt_rejected: bool) -> str:
    """Send the model ONLY the demonstration scenario's numbers — nothing private, nothing from a
    real bridge or real municipality (the demo pipeline's context never contains either)."""
    factors = [
        {
            "name": f.factor_name, "value": f.value, "limit": f.limit,
            "direction": f.direction.value,
        }
        for f in context.get("factors", ())
    ]
    standard = context.get("standard")
    lines = [
        f"Computed score (fixed input, do not recompute): {context.get('score')}",
        f"Severity band (fixed input): {context.get('severity')}",
        f"Contributing factors (value/limit already computed): {json.dumps(factors)}",
    ]
    if standard is not None and getattr(standard, "available", False):
        lines.append(
            f"Applicable standard: {standard.standard_code} {standard.standard_version}"
        )
    caveats = context.get("caveats")
    if caveats:
        lines.append(f"Data-quality caveats: {caveats}")
    if prior_attempt_rejected:
        lines.append(
            "Your previous draft cited a number not present above. Write a new explanation "
            "citing ONLY the numbers listed above."
        )
    lines.append(
        "Write a short (2-4 sentence) plain-language explanation of this score for a government "
        "engineer. Cite only the numbers given above."
    )
    return "\n".join(lines)


@dataclass
class LiveReasoningModel:
    """Calls the real LLM once per `draft`, via the provider-neutral client. [LLM-DEP] — requires
    `LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL` to be set; raises `LLMConfigError` immediately if not,
    which `on_model_failure` catches exactly like any other failure."""

    config: LLMConfig | None = None  # loaded lazily so construction never requires env vars yet.

    def draft(self, attempt: int, context: dict[str, Any]) -> str:
        config = self.config or load_llm_config()
        return call_llm_with_retry(
            system=_SYSTEM_PROMPT,
            user=_context_to_prompt(context, attempt > 0),
            config=config,
        )
