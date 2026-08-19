"""R1101 — scenario harness (fake store + fake model), the shared E2E fixture.

This module is deliberately NOT a test module (underscore prefix -> pytest does not collect it). It
is imported by test_r1101 (which proves the harness) and by test_r1102 (which drives it to assert
every spec AC). It contains NO scoring/judgment logic of its own — it only assembles inputs and
calls the real `run_assessment` service entrypoint (R1002), so what it exercises is the production
control flow, not a re-implementation of it.

Each `ScenarioCase` bundles: a name, a fresh in-memory store seeded with SA results + standards, a
FakeReasoningModel scenario, the score/coverage configs, the trigger payload, and a declared
`Expectation`. `run_case` runs one assessment through the real service and returns its structured
summary. Determinism is structural (no clock, no randomness) so the whole catalog is replayable.

The safety numbers used here are TEST FIXTURES chosen to exercise each band/branch — they are NOT a
claim about real bridge thresholds (those stay TODO in the shipped config, R101/R102). A concrete
`score_weights_version` stamps which fixture weights a run used, mirroring the real audit contract.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.risk_reasoning.caveats import collect_caveats
from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.fake_model import FakeReasoningModel, Scenario
from agents.risk_reasoning.scorer import FactorInput
from agents.risk_reasoning.service import AssessmentSummary, run_assessment
from agents.risk_reasoning.store import FakeRiskStore
from agents.risk_reasoning.tools.calculation_results import AnalysisResultRow
from agents.risk_reasoning.tools.engineering_standard import StandardEntry


# The full catalog of scenarios the E2E must cover (tasks.md R1101). Kept as an explicit list so a
# test can assert the harness has not silently dropped one.
SCENARIO_NAMES: tuple[str, ...] = (
    "normal",           # all-RAN, standard present -> scored FINAL
    "conflicting",      # opposing factors (high vibration + in-limit deflection) -> scored
    "below_floor",      # too few RAN results -> withheld (coverage floor)
    "standard_missing", # no engineering standard -> withheld (degraded path)
    "all_flags",        # all four SA data-quality flags present -> scored, caveats carried
    "critical",         # CRITICAL band -> PENDING_HUMAN_REVIEW (mandate #3)
    "borderline",       # score within the near-boundary margin of a cut-point
    "invented_number",  # a single fabricated-number draft -> guardrail fails closed
    "regenerate_once",  # one bad draft then clean -> emitted after exactly one regeneration
    "fail_closed",      # two bad drafts -> withheld, RISK_GUARDRAIL_FAIL
    "reassessment",     # same (bridge, cycle) delivered twice -> supersede, not duplicate
    "malformed",        # partial/malformed trigger payload -> structured error, never a crash
)


# --------------------------------------------------------------------------- store


class HarnessStore(FakeRiskStore):
    """The persistent risk store plus the three read ports, so one object serves both roles.

    The base `rows` property is the persisted assessments (read-only); the SA input rows live under
    `analysis` to avoid colliding with it. `baseline_for` returns no history (cold-start trend);
    `standard_for` serves the seeded standards, or None (drives the standard-unavailable path).
    """

    def __init__(self, analysis=None, standards=None):
        super().__init__()
        self.analysis = list(analysis or [])
        self.standards = dict(standards or {})

    def current_results_for(self, bridge_id, cycle_id):
        return [r for r in self.analysis
                if r.bridge_id == bridge_id and r.cycle_id == cycle_id and r.superseded_by is None]

    def baseline_for(self, bridge_id, window):
        return []

    def standard_for(self, bridge_type):
        return self.standards.get(bridge_type)


# --------------------------------------------------------------------------- inputs


def _row(rid, calc, value, *, outcome="RAN", flags=None, limit=1.0):
    """One SA analysis_results row on bridge b1 / cycle c1 (the harness scope)."""
    return AnalysisResultRow(
        id=rid, bridge_id="b1", cycle_id="c1", sensor_id=f"s{rid}", calculation=calc,
        outcome=outcome, reason_code=None if outcome == "RAN" else "NO_CHANGE",
        result={"value": value, "limit": limit}, flags=flags or {},
        source_validated_ids=[rid], superseded_by=None,
    )


def _extractor(results, standard):
    """Turn RAN results into FactorInputs (the injected domain seam). Deterministic, pure."""
    return [FactorInput(r.calculation.lower(), r.id, float(r.result["value"]),
                        float(r.result["limit"])) for r in results if r.outcome == "RAN"]


def _standard(limit=1.0):
    return {"girder": StandardEntry("IRC:6", "2017", {"max": limit})}


# Fixture band table (NOT real thresholds): WATCH>=25, WARNING>=50, CRITICAL>=75, near-margin 3.
def _score_config(weights):
    return ScoreConfig(
        score_weights_version="harness-rev1", weights=weights,
        ratio_at_zero_score=0.0, ratio_at_full_score=1.0,
        watch_min=25.0, warning_min=50.0, critical_min=75.0, band_near_margin=3.0,
    )


def _coverage_config(floor=0.5):
    return CoverageConfig(coverage_floor=floor, completeness_full_fraction=1.0)


# --------------------------------------------------------------------------- case model


@dataclass(frozen=True, slots=True)
class Expectation:
    """What a scenario's summary must show. `None` fields are not asserted (scenario-specific)."""

    ok: bool = True
    withheld: bool = False
    severity: str | None = None
    score: int | None = None
    review_status: str | None = None
    reason_contains: str | None = None
    error: bool = False


@dataclass
class ScenarioCase:
    """One replayable scenario: seeded store + model + configs + trigger payload + expectation."""

    name: str
    store: HarnessStore
    model: FakeReasoningModel
    score_config: ScoreConfig
    coverage_config: CoverageConfig
    payload: Any
    expected: Expectation
    expected_calc_count: int = 1


def run_case(case: ScenarioCase) -> AssessmentSummary:
    """Run one scenario through the REAL service entrypoint (R1002). Never raises."""
    return run_assessment(
        case.payload, store=case.store,
        score_config=case.score_config, coverage_config=case.coverage_config,
        model=case.model, factor_extractor=_extractor,
        expected_calc_count=case.expected_calc_count,
        model_id="frontier-x", model_version="2026-05",
    )


def collect_case_caveats(case: ScenarioCase):
    """The caveats the reasoning context would carry for this case's RAN results (AC-8 helper)."""
    ran = [r for r in case.store.analysis if r.outcome == "RAN"]
    return collect_caveats(ran)


# --------------------------------------------------------------------------- the catalog

_PAYLOAD = {"bridge_id": "b1", "cycle_id": "c1", "bridge_type": "girder"}


def _case_normal() -> ScenarioCase:
    # value 0.60 / limit 1.0 -> 60 -> WARNING, FINAL.
    return ScenarioCase(
        "normal",
        HarnessStore(analysis=[_row(1, "RMS", 0.60)], standards=_standard()),
        FakeReasoningModel(Scenario.CLEAN),
        _score_config((("rms", 1.0),)), _coverage_config(),
        dict(_PAYLOAD),
        Expectation(ok=True, withheld=False, severity="WARNING", score=60, review_status="FINAL"),
    )


def _case_conflicting() -> ScenarioCase:
    # High vibration (0.80) raises, in-limit deflection (0.20) lowers; equal weights -> 50 WARNING.
    return ScenarioCase(
        "conflicting",
        HarnessStore(
            analysis=[_row(1, "RMS", 0.80), _row(2, "DEFLECTION", 0.20)],
            standards=_standard(),
        ),
        FakeReasoningModel(Scenario.CONFLICTING),
        _score_config((("rms", 1.0), ("deflection", 1.0))), _coverage_config(),
        dict(_PAYLOAD),
        Expectation(ok=True, withheld=False, severity="WARNING", score=50),
        expected_calc_count=2,
    )


def _case_below_floor() -> ScenarioCase:
    # Only 1 of 4 expected calcs RAN -> 25% < 50% floor -> withhold.
    return ScenarioCase(
        "below_floor",
        HarnessStore(analysis=[_row(1, "RMS", 0.60)], standards=_standard()),
        FakeReasoningModel(Scenario.CLEAN),
        _score_config((("rms", 1.0),)), _coverage_config(floor=0.5),
        dict(_PAYLOAD),
        Expectation(ok=True, withheld=True, review_status="PENDING_HUMAN_REVIEW",
                    reason_contains="coverage"),
        expected_calc_count=4,
    )


def _case_standard_missing() -> ScenarioCase:
    # Full calc coverage but no engineering standard -> withhold (degraded path).
    return ScenarioCase(
        "standard_missing",
        HarnessStore(analysis=[_row(1, "RMS", 0.60)], standards={}),
        FakeReasoningModel(Scenario.CLEAN),
        _score_config((("rms", 1.0),)), _coverage_config(),
        dict(_PAYLOAD),
        Expectation(ok=True, withheld=True, review_status="PENDING_HUMAN_REVIEW",
                    reason_contains="standard"),
    )


def _case_all_flags() -> ScenarioCase:
    # A scored run where the single RAN result carries all four SA data-quality flags (AC-8).
    flags = {"clock_drift": True, "interpolated_input": True,
             "rate_mismatch": True, "abnormal_quiet": True}
    return ScenarioCase(
        "all_flags",
        HarnessStore(analysis=[_row(1, "RMS", 0.60, flags=flags)], standards=_standard()),
        FakeReasoningModel(Scenario.CLEAN),
        _score_config((("rms", 1.0),)), _coverage_config(),
        dict(_PAYLOAD),
        Expectation(ok=True, withheld=False, severity="WARNING"),
    )


def _case_critical() -> ScenarioCase:
    # value 0.90 -> 90 -> CRITICAL -> PENDING_HUMAN_REVIEW (mandate #3).
    return ScenarioCase(
        "critical",
        HarnessStore(analysis=[_row(1, "RMS", 0.90)], standards=_standard()),
        FakeReasoningModel(Scenario.CLEAN),
        _score_config((("rms", 1.0),)), _coverage_config(),
        dict(_PAYLOAD),
        Expectation(ok=True, withheld=False, severity="CRITICAL",
                    review_status="PENDING_HUMAN_REVIEW"),
    )


def _case_borderline() -> ScenarioCase:
    # value 0.74 -> 74, one below the CRITICAL cut (75) and within the near-margin (3) -> WARNING,
    # near_boundary True (asserted via severity_for in the test).
    return ScenarioCase(
        "borderline",
        HarnessStore(analysis=[_row(1, "RMS", 0.74)], standards=_standard()),
        FakeReasoningModel(Scenario.CLEAN),
        _score_config((("rms", 1.0),)), _coverage_config(),
        dict(_PAYLOAD),
        Expectation(ok=True, withheld=False, severity="WARNING", score=74),
    )


def _case_invented_number() -> ScenarioCase:
    # A single fabricated draft on every attempt -> guardrail fails closed (same as two-bad).
    return ScenarioCase(
        "invented_number",
        HarnessStore(analysis=[_row(1, "RMS", 0.60)], standards=_standard()),
        FakeReasoningModel(Scenario.TWO_BAD),
        _score_config((("rms", 1.0),)), _coverage_config(),
        dict(_PAYLOAD),
        Expectation(ok=True, withheld=True, review_status="PENDING_HUMAN_REVIEW",
                    reason_contains="guardrail"),
    )


def _case_regenerate_once() -> ScenarioCase:
    # attempt 0 fabricates, attempt 1 is clean -> emitted after exactly one regeneration.
    return ScenarioCase(
        "regenerate_once",
        HarnessStore(analysis=[_row(1, "RMS", 0.60)], standards=_standard()),
        FakeReasoningModel(Scenario.ONE_BAD_THEN_CLEAN),
        _score_config((("rms", 1.0),)), _coverage_config(),
        dict(_PAYLOAD),
        Expectation(ok=True, withheld=False, severity="WARNING"),
    )


def _case_fail_closed() -> ScenarioCase:
    # Both attempts fabricate -> withheld, RISK_GUARDRAIL_FAIL, fabrication never emitted as score.
    return ScenarioCase(
        "fail_closed",
        HarnessStore(analysis=[_row(1, "RMS", 0.60)], standards=_standard()),
        FakeReasoningModel(Scenario.TWO_BAD),
        _score_config((("rms", 1.0),)), _coverage_config(),
        dict(_PAYLOAD),
        Expectation(ok=True, withheld=True, review_status="PENDING_HUMAN_REVIEW",
                    reason_contains="guardrail"),
    )


def _case_reassessment() -> ScenarioCase:
    # A normal scored case; the test delivers it twice to assert supersede-not-duplicate.
    return ScenarioCase(
        "reassessment",
        HarnessStore(analysis=[_row(1, "RMS", 0.60)], standards=_standard()),
        FakeReasoningModel(Scenario.CLEAN),
        _score_config((("rms", 1.0),)), _coverage_config(),
        dict(_PAYLOAD),
        Expectation(ok=True, withheld=False, severity="WARNING"),
    )


def _case_malformed() -> ScenarioCase:
    # A partial payload (missing cycle_id + bridge_type) -> structured error, never a crash.
    return ScenarioCase(
        "malformed",
        HarnessStore(analysis=[_row(1, "RMS", 0.60)], standards=_standard()),
        FakeReasoningModel(Scenario.CLEAN),
        _score_config((("rms", 1.0),)), _coverage_config(),
        {"bridge_id": "b1"},
        Expectation(ok=False, error=True),
    )


_BUILDERS = (
    _case_normal, _case_conflicting, _case_below_floor, _case_standard_missing,
    _case_all_flags, _case_critical, _case_borderline, _case_invented_number,
    _case_regenerate_once, _case_fail_closed, _case_reassessment, _case_malformed,
)


def all_cases() -> list[ScenarioCase]:
    """Build a fresh, independent instance of every scenario (no shared mutable state)."""
    return [build() for build in _BUILDERS]
