"""Slice 1: SA calc runner -> Risk -> explanation strategy (specs/005-demo-mode-and-approval,
Delivery order #1).

`run_slice1` is the whole chain for one demo reading: compute the THRESHOLD calc against the demo
sensor's configured limit, then run the real, unmodified `assess_bridge` against it. No HTTP
endpoint, no in-process container, no background task yet — those are slices 2-3. This is the piece
that has to be real first: the deterministic score climbing is the entire point of the demo, and it
must not depend on anything not yet built.

**The `ScoreConfig`/`CoverageConfig` here are demo-only, constructed locally — never exported as
"the" application's shared config.** `assess_bridge` takes them as explicit parameters rather than
looking up a global, so this is safe by construction: nothing a real pipeline might build later can
accidentally pick up these values. They carry the same TODO-sentinel discipline as every other
safety config in this codebase for *real* weights/bounds/bands (`score_weights_version="demo-v1"`
makes that unmistakable in any audit trail) — these are deliberately concrete only because the whole
point of a demo is to show a real score moving, and band thresholds are this agent's own policy, not
an external structural-engineering limit.
"""
from __future__ import annotations

from dataclasses import dataclass

from agents.risk_reasoning.assessment import RiskAssessment
from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.orchestrator import assess_bridge
from agents.risk_reasoning.scorer import FactorInput
from agents.structural_analysis.config.demo_profile import (
    DEMO_ANALYSIS_PROFILE,
    DEMO_BRIDGE_ID,
    DEMO_SENSOR_ID,
)
from agents.structural_analysis.demo_calc import DemoAnalysisResult, run_demo_threshold_calc
from demo.explanation import (
    TEMPLATE_FALLBACK_TEXT,
    ExplanationKind,
    NotWiredModel,
    PregeneratedReasoningModel,
    template_fallback_hook,
)
from demo.live_model import LiveReasoningModel
from demo.risk_sources import DEMO_BRIDGE_TYPE, DemoRiskSources

# Demo-only policy — see module docstring on why this is safe to be concrete here.
_DEMO_SCORE_CONFIG = ScoreConfig(
    score_weights_version="demo-v1",
    weights=(("threshold", 1.0),),
    ratio_at_zero_score=0.0, ratio_at_full_score=4.0,
    watch_min=25.0, warning_min=55.0, critical_min=80.0,
)
_DEMO_COVERAGE_CONFIG = CoverageConfig(coverage_floor=0.5, completeness_full_fraction=1.0)


def _demo_factor_extractor(results, standard) -> list[FactorInput]:
    """Turn the one RAN THRESHOLD result into a FactorInput (the injected domain seam)."""
    return [
        FactorInput(
            factor_name="threshold", source_analysis_id=r.id,
            value=float(r.result["value"]), limit=float(r.result["limit_value"]),
        )
        for r in results if r.outcome == "RAN"
    ]


@dataclass(frozen=True, slots=True)
class Slice1Result:
    """Everything slice 1 produced for one demo reading — kept together for the tests/UI to show."""

    analysis_row: DemoAnalysisResult
    assessment: RiskAssessment
    explanation_kind: ExplanationKind


def _model_version_label(model: object) -> str:
    if isinstance(model, LiveReasoningModel):
        return "live"
    if isinstance(model, NotWiredModel):
        return "not-wired"
    return "pregenerated"


def _explanation_kind(model: object, explanation: str) -> ExplanationKind:
    """Infer which path actually produced the explanation. `assess_bridge` doesn't report whether
    `on_model_failure` fired, so the exact fallback string is the only signal — same trick as
    before, now disambiguated by the chosen model's type for the non-fallback case."""
    if explanation == TEMPLATE_FALLBACK_TEXT:
        return ExplanationKind.TEMPLATE_FALLBACK
    if isinstance(model, LiveReasoningModel):
        return ExplanationKind.LIVE_AI
    return ExplanationKind.PREGENERATED_AI


def run_slice1(
    *, reading_value: float, cycle_id: str = "demo-c1", model: object | None = None,
) -> Slice1Result:
    """Run the Signal + Risk stages for one demo reading. Never raises (FR-8, inherited).

    `model` defaults to `None`, which uses `PregeneratedReasoningModel()` — the primary demo path
    (FR-1.7 item 7). If no pre-generated explanation has been written yet
    (`scripts/demo/generate_explanation.py`), that model's `draft()` raises and
    `on_model_failure` falls back to the labelled template text — unchanged safety net, one layer
    further down. Pass `model=LiveReasoningModel()` to attempt a genuine live call instead (laptop
    only, opt-in only — never the default), or `model=NotWiredModel()` to force the fallback
    deliberately (e.g. in a test).
    """
    analysis_row = run_demo_threshold_calc(
        sensor_id=DEMO_SENSOR_ID, bridge_id=DEMO_BRIDGE_ID, cycle_id=cycle_id,
        value=reading_value, profile=DEMO_ANALYSIS_PROFILE,
    )
    sources = DemoRiskSources(analysis_row=analysis_row)
    chosen_model = model if model is not None else PregeneratedReasoningModel()

    assessment = assess_bridge(
        bridge_id=DEMO_BRIDGE_ID, cycle_id=cycle_id, store=sources, bridge_type=DEMO_BRIDGE_TYPE,
        score_config=_DEMO_SCORE_CONFIG, coverage_config=_DEMO_COVERAGE_CONFIG,
        model=chosen_model, factor_extractor=_demo_factor_extractor, expected_calc_count=1,
        model_id="demo-pipeline", model_version=_model_version_label(chosen_model),
        trace_id=f"demo:{cycle_id}",
        on_model_failure=template_fallback_hook,
    )

    kind = _explanation_kind(chosen_model, assessment.explanation)
    return Slice1Result(analysis_row=analysis_row, assessment=assessment, explanation_kind=kind)
