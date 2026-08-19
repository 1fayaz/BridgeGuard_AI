"""R303 — scorer + band integration & reproducibility (FR-2, FR-4, AC-2).

Acceptance (tasks.md R303): drives R301->R302->R103: a mix of high/low ratios -> expected score +
bands; a not-scorable result is excluded from the score and recorded as a gap (not silently
dropped); identical pinned inputs -> identical score (AC-2). The model is NOT involved — assert the
score is pure code (Principle IV — arithmetic out of the model).

This is a pure-integration test: it composes already-built units (no new production code), proving
the deterministic spine score_bridge -> severity_for behaves end to end.
"""
from __future__ import annotations

import ast
import inspect

from agents.risk_reasoning import scorer as scorer_module
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.scorer import score_bridge, FactorInput
from agents.risk_reasoning.band import severity_for
from agents.risk_reasoning.statuses import Severity


def _full_config() -> ScoreConfig:
    # A fully-supplied config: weights, ratio normalisation, and the FR-4 band table.
    return ScoreConfig(
        score_weights_version="2026-06-weights-rev3",
        weights=(("vibration", 0.4), ("deflection", 0.4), ("strain", 0.2)),
        ratio_at_zero_score=0.0,
        ratio_at_full_score=1.0,
        watch_min=25.0, warning_min=50.0, critical_min=75.0,
    )


def _inp(name, sid, value, limit) -> FactorInput:
    return FactorInput(factor_name=name, source_analysis_id=sid, value=value, limit=limit)


def test_high_ratios_drive_a_critical_band():
    cfg = _full_config()
    inputs = [
        _inp("vibration", 1, 0.95, 1.0),   # 95
        _inp("deflection", 2, 0.90, 1.0),  # 90
        _inp("strain", 3, 0.80, 1.0),      # 80
    ]
    # weighted avg = 0.4*95 + 0.4*90 + 0.2*80 = 38 + 36 + 16 = 90 -> CRITICAL
    r = score_bridge(inputs, cfg)
    assert r.score == 90
    assert severity_for(r.score, cfg).severity is Severity.CRITICAL


def test_low_ratios_drive_a_safe_band():
    cfg = _full_config()
    inputs = [
        _inp("vibration", 1, 0.10, 1.0),   # 10
        _inp("deflection", 2, 0.15, 1.0),  # 15
        _inp("strain", 3, 0.20, 1.0),      # 20
    ]
    # weighted avg = 4 + 6 + 4 = 14 -> SAFE
    r = score_bridge(inputs, cfg)
    assert r.score == 14
    assert severity_for(r.score, cfg).severity is Severity.SAFE


def test_mixed_conflicting_ratios_land_mid_band_with_directions():
    cfg = _full_config()
    inputs = [
        _inp("vibration", 1, 0.90, 1.0),   # 90 (high)
        _inp("deflection", 2, 0.30, 1.0),  # 30 (comfortably under)
        _inp("strain", 3, 0.55, 1.0),      # 55
    ]
    # 0.4*90 + 0.4*30 + 0.2*55 = 36 + 12 + 11 = 59 -> WARNING
    r = score_bridge(inputs, cfg)
    assert r.score == 59
    assert severity_for(r.score, cfg).severity is Severity.WARNING
    by = {f.factor_name: f.direction.value for f in r.factors}
    assert by["vibration"] == "RAISED"
    assert by["deflection"] == "LOWERED"


def test_not_scorable_factor_excluded_and_recorded():
    cfg = _full_config()
    inputs = [
        _inp("vibration", 1, 0.90, 1.0),       # 90
        _inp("deflection", 2, 0.30, float("nan")),  # no limit -> gap
        _inp("strain", 3, 0.50, 1.0),          # 50
    ]
    # only vibration(0.4) + strain(0.2) scored: (36 + 10)/0.6 = 76.67 -> 77
    r = score_bridge(inputs, cfg)
    assert r.score == 77
    assert len(r.factors) == 2
    assert any("deflection" in g for g in r.gaps)


def test_identical_inputs_reproduce_identical_score_and_band():
    cfg = _full_config()
    inputs = [
        _inp("vibration", 1, 0.73, 1.0),
        _inp("deflection", 2, 0.41, 1.0),
        _inp("strain", 3, 0.66, 1.0),
    ]
    first = score_bridge(inputs, cfg)
    first_band = severity_for(first.score, cfg).severity
    for _ in range(10):
        again = score_bridge(inputs, cfg)
        assert again.score == first.score
        assert severity_for(again.score, cfg).severity is first_band


def test_scorer_is_pure_code_no_model_dependency():
    # Principle IV / FR-2: the score must NOT come from an LLM. Assert STRUCTURALLY (via the parsed
    # import graph, not a substring grep of docstrings) that the scorer imports only stdlib or
    # other risk_reasoning modules — never an LLM/agent SDK / model client.
    tree = ast.parse(inspect.getsource(scorer_module))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_roots.add(node.module)

    forbidden_roots = {"openai", "anthropic", "agents_sdk"}
    assert not (imported_roots & forbidden_roots), \
        f"scorer must not import an LLM client: {imported_roots & forbidden_roots}"

    # Any 'agents...' import must stay WITHIN this agent's own package (no cross-agent / SDK loop).
    for mod in imported_roots:
        if mod.startswith("agents"):
            assert mod.startswith("agents.risk_reasoning"), \
                f"scorer reaches outside risk_reasoning: {mod!r}"
