"""Per-assessment orchestrator (R703) — FR-1 / FR-3a / FR-6 / FR-7 / FR-8 / FR-11.

`assess_bridge` wires the whole per-assessment flow for one bridge at one SA cycle:

    three read-only tool fetches
      -> coverage gate (score vs. withhold, FR-6)
      -> deterministic score + severity band (FR-2 / FR-4, pure code)
      -> model drafts the explanation (the ONLY [LLM-DEP] step)
      -> numeric-provenance guardrail loop (regenerate-once-then-fail-closed, FR-7)
      -> review_status (CRITICAL / withheld -> PENDING_HUMAN_REVIEW, FR-11)
      -> one RiskAssessment (scored or withheld)

It ALWAYS returns a structured RiskAssessment and NEVER raises (FR-8 / Principle V): any tool or
model failure is isolated into a withheld PENDING_HUMAN_REVIEW assessment. The score is always the
deterministic value (R302), never the model's — the model only explains it.

Two domain seams are injected rather than invented here (they depend on the SA result contract and
the standard's shape, which are config/plan decisions): `factor_extractor` turns RAN results +
standard into FactorInputs, and `expected_calc_count` is how many calcs the bridge should have run.
"""
from __future__ import annotations

from typing import Any, Callable

from agents.risk_reasoning.assessment import RiskAssessment
from agents.risk_reasoning.band import severity_for
from agents.risk_reasoning.caveats import collect_caveats
from agents.risk_reasoning.completeness import data_completeness
from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.coverage import coverage_check
from agents.risk_reasoning.guardrail import build_legitimate_set, run_guardrail_loop
from agents.risk_reasoning.review import apply_review_status
from agents.risk_reasoning.scorer import FactorInput, score_bridge
from agents.risk_reasoning.statuses import ReviewStatus, Severity
from agents.risk_reasoning.tools.calculation_results import get_calculation_results
from agents.risk_reasoning.tools.engineering_standard import get_engineering_standard
from agents.risk_reasoning.tools.historical_baseline import get_historical_baseline

# Numeric-provenance match tolerance (FR-7). Exact-match (0.0) is the strictest, fail-SAFE default:
# it can only reject more numbers, never accept a fabricated one. A configured rounding tolerance
# (Open Item / config TODO) would loosen it; we never guess a looser value for a safety control.
DEFAULT_GUARDRAIL_TOLERANCE: float = 0.0


# The factor_extractor turns RAN analysis results + the standard into weighted-score inputs.
FactorExtractor = Callable[[list, Any], list[FactorInput]]


def assess_bridge(
    *,
    bridge_id: str,
    cycle_id: str,
    store: Any,
    bridge_type: str,
    score_config: ScoreConfig,
    coverage_config: CoverageConfig,
    model: Any,
    factor_extractor: FactorExtractor,
    expected_calc_count: int,
    model_id: str,
    model_version: str,
    trace_id: str,
    baseline_window: str = "30d",
    guardrail_tolerance: float = DEFAULT_GUARDRAIL_TOLERANCE,
) -> RiskAssessment:
    """Assess one bridge at one cycle (FR-3a). Always returns a RiskAssessment; never raises."""
    try:
        return _assess(
            bridge_id=bridge_id, cycle_id=cycle_id, store=store, bridge_type=bridge_type,
            score_config=score_config, coverage_config=coverage_config, model=model,
            factor_extractor=factor_extractor, expected_calc_count=expected_calc_count,
            model_id=model_id, model_version=model_version, trace_id=trace_id,
            baseline_window=baseline_window, guardrail_tolerance=guardrail_tolerance,
        )
    except Exception as exc:  # FR-8: no failure escapes as a crash — withhold and route to review.
        return _withheld(
            bridge_id, cycle_id, (),
            f"Assessment could not be completed due to an internal error: {exc!s}. "
            "Score withheld and routed to human review.",
            model_id, model_version, trace_id, standard_code=None, standard_version=None,
            confidence=0.0, data_completeness=0.0,
        )


def _assess(
    *, bridge_id, cycle_id, store, bridge_type, score_config, coverage_config, model,
    factor_extractor, expected_calc_count, model_id, model_version, trace_id,
    baseline_window, guardrail_tolerance,
) -> RiskAssessment:
    # 1. Three read-only fetches.
    calc = get_calculation_results(bridge_id, cycle_id, store)
    _baseline = get_historical_baseline(bridge_id, baseline_window, store)  # trend context (v1: read)
    standard = get_engineering_standard(bridge_type, store)

    results = list(calc.results)
    source_ids = tuple(r.id for r in results)
    ran = [r for r in results if r.outcome == "RAN"]
    flagged = sum(1 for r in ran if any(r.flags.values()))
    completeness = data_completeness(len(ran), expected_calc_count, flagged, coverage_config)

    # 2. Coverage gate (FR-6): score vs. withhold.
    gate = coverage_check(len(ran), expected_calc_count, standard.available, coverage_config)
    if not gate.should_score:
        return _withheld(
            bridge_id, cycle_id, source_ids, gate.reason or "Coverage insufficient to score.",
            model_id, model_version, trace_id,
            standard_code=standard.standard_code, standard_version=standard.standard_version,
            confidence=completeness, data_completeness=completeness,
        )

    # 3. Deterministic score + band (FR-2 / FR-4) — pure code, never the model.
    factors_in = factor_extractor(ran, standard)
    scored = score_bridge(factors_in, score_config)
    if not scored.scorable or scored.score is None:
        return _withheld(
            bridge_id, cycle_id, source_ids,
            "No scorable factors were available after retrieval; score withheld. "
            + ("; ".join(scored.gaps) if scored.gaps else ""),
            model_id, model_version, trace_id,
            standard_code=standard.standard_code, standard_version=standard.standard_version,
            confidence=completeness, data_completeness=completeness,
        )
    band = severity_for(scored.score, score_config)

    # 4-5. Model drafts the explanation; guardrail loop verifies it (FR-7).
    legitimate = build_legitimate_set(
        ran_results=ran, score=scored.score, factors=list(scored.factors),
        standard=standard, tolerance=guardrail_tolerance,
    )
    context = {
        "score": scored.score, "severity": band.severity.value,
        "factors": scored.factors, "standard": standard,
        "caveats": collect_caveats(ran),  # AC-8: SA data-quality flags reach the reasoning
    }
    loop = run_guardrail_loop(lambda attempt: model.draft(attempt, context), legitimate)

    if loop.failed_closed:
        offending = ", ".join(tok.raw for tok in loop.offending)
        return _withheld(
            bridge_id, cycle_id, source_ids,
            "Numeric-provenance guardrail failed closed after one regeneration: the explanation "
            f"cited untraceable number(s) {offending}. Score withheld and routed to human review.",
            model_id, model_version, trace_id,
            standard_code=standard.standard_code, standard_version=standard.standard_version,
            confidence=completeness, data_completeness=completeness,
        )

    # 6-7. review_status (FR-11) + build the scored assessment.
    review = apply_review_status(band.severity, is_withheld=False)
    return RiskAssessment(
        bridge_id=bridge_id, cycle_id=cycle_id,
        risk_score=scored.score, severity=band.severity,
        recommendation=_recommendation_for(band.severity),
        explanation=loop.draft or "",
        contributing_factors=scored.factors,
        confidence=completeness, data_completeness=completeness,
        review_status=review,
        source_analysis_ids=source_ids,
        baseline_ref=(f"{bridge_id}:{baseline_window}" if _baseline.has_baseline else None),
        standard_code=standard.standard_code, standard_version=standard.standard_version,
        score_weights_version=score_config.score_weights_version,
        model_id=model_id, model_version=model_version, trace_id=trace_id,
    )


def _recommendation_for(severity: Severity) -> str:
    return {
        Severity.SAFE: "Routine monitoring; no action required.",
        Severity.WATCH: "Continue monitoring; no closure required.",
        Severity.WARNING: "Increase inspection frequency; prepare for possible restriction.",
        Severity.CRITICAL: "Recommend closure — pending human review before any action.",
    }[severity]


def _withheld(
    bridge_id, cycle_id, source_ids, explanation, model_id, model_version, trace_id,
    *, standard_code, standard_version, confidence, data_completeness,
) -> RiskAssessment:
    """Build a first-class withheld assessment (score None, PENDING_HUMAN_REVIEW). Never silence."""
    return RiskAssessment(
        bridge_id=bridge_id, cycle_id=cycle_id,
        risk_score=None, severity=None,
        recommendation="Score withheld pending human review.",
        explanation=explanation,
        contributing_factors=(),
        confidence=confidence, data_completeness=data_completeness,
        review_status=ReviewStatus.PENDING_HUMAN_REVIEW,
        source_analysis_ids=tuple(source_ids),
        baseline_ref=None, standard_code=standard_code, standard_version=standard_version,
        score_weights_version="", model_id=model_id, model_version=model_version, trace_id=trace_id,
    )
