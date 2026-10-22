"""Generate and verify the pre-generated demo explanation (specs/005-demo-mode-and-approval §1.3,
FR-1.7 item 3) [LLM-DEP].

Run this ONCE, offline, ahead of the presentation — not during it. It is the ONLY thing allowed to
write `src/demo/pregenerated_explanation.json`; nobody hand-edits that file.

What it does:
  1. Builds the fixed demo scenario's numbers (the same slice-1 reading/limit/ratio/score this
     whole feature is built around) and runs them through the REAL numeric-provenance guardrail
     (`agents.risk_reasoning.guardrail`) — the exact same check the live pipeline would apply, so a
     "pass" here is a genuine guarantee, not a separate, weaker check.
  2. Calls the configured LLM (`LLM_API_KEY`/`LLM_BASE_URL`/`LLM_MODEL`) up to 5 times, pausing
     between attempts to stay gentle on a free-tier quota, stopping at the first candidate that
     passes the guardrail.
  3. On success, writes the verified text + metadata (provider, exact model id, generation date) to
     `src/demo/pregenerated_explanation.json`. On failure (no candidate passed after 5 tries, or
     every call failed/was blocked), exits non-zero and writes nothing — an old, already-verified
     file is never overwritten with a failure.

Sends the model ONLY the demonstration scenario's numbers (score/severity/one factor's value+limit)
— nothing private, no real bridge, no real municipality, no secret of any kind.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from agents.risk_reasoning.agent import _SYSTEM_PROMPT  # noqa: E402
from agents.risk_reasoning.assessment import ContributingFactor, FactorDirection  # noqa: E402
from agents.risk_reasoning.guardrail import build_legitimate_set, provenance_guardrail  # noqa: E402
from agents.risk_reasoning.tools.engineering_standard import EngineeringStandard  # noqa: E402
from demo.explanation import PREGENERATED_EXPLANATION_PATH  # noqa: E402
from demo.llm_client import LLMBlockedOrEmpty, LLMCallFailed, call_llm_with_retry, load_llm_config  # noqa: E402

MAX_CANDIDATES = 5
PAUSE_BETWEEN_CANDIDATES_S = 8.0  # gentle on a free-tier quota; see spec item 3.
PROVIDER_LABEL = "Google Gemini"  # today's project decision — update if the provider ever changes.

# The fixed demo scenario — the same numbers `demo.pipeline.run_slice1(reading_value=3.4)` produces.
_SCORE = 85
_SEVERITY = "CRITICAL"
_FACTOR = ContributingFactor(
    factor_name="threshold", source_analysis_id=1, value=3.4, limit=1.0, ratio=3.4, weight=1.0,
    contribution=85.0, direction=FactorDirection.RAISED,
)
_STANDARD = EngineeringStandard(available=True, limits={}, standard_code="DEMO", standard_version="v1")


def _demo_user_prompt() -> str:
    return (
        f"Computed score (fixed input, do not recompute): {_SCORE}\n"
        f"Severity band (fixed input): {_SEVERITY}\n"
        f"Contributing factors (value/limit already computed): "
        f"[{{\"name\": \"{_FACTOR.factor_name}\", \"value\": {_FACTOR.value}, "
        f"\"limit\": {_FACTOR.limit}}}]\n"
        "Write a short (2-4 sentence) plain-language explanation of this score for a government "
        "engineer. Cite only the numbers given above."
    )


def _legitimate_set():
    return build_legitimate_set(
        ran_results=[], score=_SCORE, factors=[_FACTOR], standard=_STANDARD, tolerance=0.0,
    )


@dataclass(frozen=True, slots=True)
class Candidate:
    text: str
    passed: bool
    offending: tuple


def _try_one_candidate() -> Candidate | None:
    """Returns None on a transport/blocked failure (already logged); a Candidate otherwise."""
    config = load_llm_config()
    try:
        text = call_llm_with_retry(system=_SYSTEM_PROMPT, user=_demo_user_prompt(), config=config)
    except LLMCallFailed as exc:
        print(f"  attempt failed (transport): {exc}")
        return None
    except LLMBlockedOrEmpty as exc:
        print(f"  attempt failed (blocked/empty): {exc}")
        return None

    verdict = provenance_guardrail(text, _legitimate_set())
    if verdict.passed:
        print(f"  candidate passed the guardrail: {text!r}")
        return Candidate(text=text, passed=True, offending=())
    offending = ", ".join(tok.raw for tok in verdict.offending)
    print(f"  candidate REJECTED by the guardrail (untraceable number(s): {offending}): {text!r}")
    return Candidate(text=text, passed=False, offending=verdict.offending)


def main() -> int:
    config = load_llm_config()  # fails loudly (missing var name only) before any network call.
    print(f"Provider base URL: {config.base_url}")
    print(f"Model: {config.model}")
    print(f"Attempting up to {MAX_CANDIDATES} candidates, {PAUSE_BETWEEN_CANDIDATES_S}s apart...\n")

    for i in range(MAX_CANDIDATES):
        print(f"Candidate {i + 1}/{MAX_CANDIDATES}...")
        candidate = _try_one_candidate()
        if candidate is not None and candidate.passed:
            payload = {
                "text": candidate.text,
                "provider": PROVIDER_LABEL,
                "model": config.model,
                "generated_at": datetime.now(UTC).isoformat(),
                "guardrail_passed": True,
            }
            PREGENERATED_EXPLANATION_PATH.write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8"
            )
            print(f"\nWrote {PREGENERATED_EXPLANATION_PATH}")
            return 0
        if i < MAX_CANDIDATES - 1:
            time.sleep(PAUSE_BETWEEN_CANDIDATES_S)

    print(
        f"\nNo candidate passed after {MAX_CANDIDATES} attempts. Nothing written — the demo will "
        "keep using whatever explanation source it already had (an existing verified file, or the "
        "template fallback). Try again later if this was a rate-limit/quota issue."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
