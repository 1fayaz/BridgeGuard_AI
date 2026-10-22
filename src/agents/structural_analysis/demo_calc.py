"""The first Structural Analysis runner (specs/005-demo-mode-and-approval §1.3, FR-1.4).

Structural Analysis exists only as configuration today (`config/analysis_profiles.py`,
`config/calculations.py`) — no runner, store, or service has ever been built for it. This is the
minimal one: given one raw value and an `AnalysisProfile` whose `design_limit` is configured, it
computes a `THRESHOLD`-shaped result and nothing else (no RMS/FFT — the demo sensor maps to exactly
one calculation, §1.3's `demo_profile.py`).

Deliberately independent of any other agent's types (Principle III): this module returns its own
plain shape, shaped to mirror the real `analysis_results` columns (`value`/`limit_value`/`ratio`/
`passed`) closely enough that the demo-only adapter feeding Risk's `AnalysisSource` protocol
(`src/demo/risk_sources.py`) can wrap it with no logic of its own — but SA itself never imports
Risk's tool types.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from agents.structural_analysis.config.analysis_profiles import AnalysisProfile


@dataclass(frozen=True, slots=True)
class DemoAnalysisResult:
    """One THRESHOLD calc result, shaped like an `analysis_results` row (SA's own type)."""

    id: int
    bridge_id: str
    cycle_id: str
    sensor_id: str
    calculation: str
    outcome: str
    reason_code: str | None
    result: dict[str, Any]
    flags: dict[str, bool] = field(default_factory=dict)
    source_validated_ids: list[int] = field(default_factory=list)
    superseded_by: int | None = None


def run_demo_threshold_calc(
    *, sensor_id: str, bridge_id: str, cycle_id: str, value: float, profile: AnalysisProfile,
    result_id: int = 1,
) -> DemoAnalysisResult:
    """Compare one raw value against `profile.design_limit` (FR-9's threshold check).

    Refuses — rather than guessing — if the profile's limit is still the TODO sentinel. A real
    sensor's profile is exactly this unconfigured by default (`config/analysis_profiles.py`); this
    function existing does not change that, it only lets the one demo profile (`design_limit`
    configured, keyed by its own `sensor_id`) actually run.
    """
    if profile.threshold_config_is_todo:
        raise ValueError(
            f"profile for sensor_type={profile.sensor_type!r} has no configured design_limit "
            "(TODO) — refusing to guess a safety threshold"
        )
    limit = profile.design_limit
    ratio = value / limit if limit != 0.0 else math.inf
    return DemoAnalysisResult(
        id=result_id, bridge_id=bridge_id, cycle_id=cycle_id, sensor_id=sensor_id,
        calculation="THRESHOLD", outcome="RAN", reason_code=None,
        result={
            "value": value,
            "limit_value": limit,
            "ratio": ratio,
            "passed": value <= limit,
            "limit_basis": profile.limit_basis,
        },
    )
