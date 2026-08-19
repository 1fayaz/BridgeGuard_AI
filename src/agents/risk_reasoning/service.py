"""Service entrypoint (R1002) — FR-8 / FR-3a.

`run_assessment` is the single callable n8n invokes per bridge on SA-cycle-complete. It validates
the trigger payload, runs one assessment (assess_bridge), persists it (persist_assessment), and
returns a plain structured summary. It NEVER raises: a malformed payload or any internal failure
becomes an error/withheld summary, so a bad trigger can never crash the worker (FR-8, Principle V).

Idempotent by scope (FR-3a): a redelivered trigger for the same (bridge_id, cycle_id) supersedes
the prior row rather than duplicating or crashing (persistence handles the supersede).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.orchestrator import assess_bridge
from agents.risk_reasoning.persistence import persist_assessment
from agents.risk_reasoning.scorer import FactorInput


@dataclass(frozen=True, slots=True)
class AssessmentSummary:
    """The structured per-trigger result returned to n8n (never an exception).

    `ok` False + `error` -> the trigger was rejected (bad payload / internal failure), nothing
    persisted with a verdict. `ok` True -> an assessment was produced and persisted; `withheld`
    distinguishes a scored verdict from a score-withheld one, and `reason` explains a withhold.
    """

    ok: bool
    bridge_id: str | None = None
    cycle_id: str | None = None
    risk_score: int | None = None
    severity: str | None = None
    review_status: str | None = None
    withheld: bool = False
    reason: str | None = None
    error: str | None = None


def _validate(payload: Any) -> tuple[str, str, str] | str:
    """Return (bridge_id, cycle_id, bridge_type) or an error string. Never raises."""
    if not isinstance(payload, dict):
        return "payload must be an object with bridge_id, cycle_id, bridge_type"
    for key in ("bridge_id", "cycle_id", "bridge_type"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            return f"{key} is required and must be a non-empty string"
    return payload["bridge_id"], payload["cycle_id"], payload["bridge_type"]


def run_assessment(
    payload: Any,
    *,
    store: Any,
    score_config: ScoreConfig,
    coverage_config: CoverageConfig,
    model: Any,
    factor_extractor: Callable[[list, Any], list[FactorInput]],
    expected_calc_count: int,
    model_id: str,
    model_version: str,
    baseline_window: str = "30d",
) -> AssessmentSummary:
    """Run + persist one assessment from a trigger payload (FR-3a). Never raises."""
    parsed = _validate(payload)
    if isinstance(parsed, str):
        return AssessmentSummary(ok=False, error=parsed)
    bridge_id, cycle_id, bridge_type = parsed

    # Deterministic trace id from the scope (no clock/random available; the live SDK supplies the
    # real trace id when wired — R701/R1001).
    trace_id = f"trace:{bridge_id}:{cycle_id}"

    try:
        assessment = assess_bridge(
            bridge_id=bridge_id, cycle_id=cycle_id, store=store, bridge_type=bridge_type,
            score_config=score_config, coverage_config=coverage_config, model=model,
            factor_extractor=factor_extractor, expected_calc_count=expected_calc_count,
            model_id=model_id, model_version=model_version, trace_id=trace_id,
            baseline_window=baseline_window,
        )
        guardrail_failed = assessment.is_withheld and "guardrail" in assessment.explanation.lower()
        persist_assessment(store, assessment, guardrail_failed=guardrail_failed)
    except Exception as exc:  # last-resort guard; assess_bridge already isolates, but never leak.
        return AssessmentSummary(ok=False, bridge_id=bridge_id, cycle_id=cycle_id,
                                 error=f"internal error: {exc!s}")

    return AssessmentSummary(
        ok=True,
        bridge_id=bridge_id,
        cycle_id=cycle_id,
        risk_score=assessment.risk_score,
        severity=assessment.severity.value if assessment.severity is not None else None,
        review_status=assessment.review_status.value,
        withheld=assessment.is_withheld,
        reason=assessment.explanation if assessment.is_withheld else None,
    )
