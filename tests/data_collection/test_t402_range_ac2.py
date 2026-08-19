"""T402 — AC-2 acceptance: out-of-range readings rejected, logged, withheld.

AC-2 (spec): a value outside its sensor's physical bounds is marked CORRUPT, the
reason is recorded, and the value is NOT passed downstream. In-range values pass;
exact boundaries pass; None/NaN and unknown types are CORRUPT (never crash).

Beyond T401's unit checks, this test models the downstream GATE the orchestrator
applies: only OK readings flow on; a CORRUPT reading is withheld and carries a
non-empty reason for the decision_log (T204 RANGE entry).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from agents.data_collection.checks.range_check import check_range
from agents.data_collection.config.sensor_profiles import (
    SensorProfile,
    UnknownSensorType,
)
from agents.data_collection.statuses import ReadingStatus

PROFILE = SensorProfile(
    sensor_type="load_cell", unit="kN", cadence_s=30.0,
    phys_min=-10.0, phys_max=500.0, clock_drift_tolerance_s=2.0,
)


@dataclass(frozen=True, slots=True)
class GateOutcome:
    passed_downstream: bool
    status: ReadingStatus
    logged_reason: str | None


def range_gate(value: object, profile) -> GateOutcome:
    """Model the orchestrator's range gate: CORRUPT is withheld + logged."""
    res = check_range(value, profile)
    if res.status is ReadingStatus.CORRUPT:
        return GateOutcome(passed_downstream=False, status=res.status,
                           logged_reason=res.reason)
    return GateOutcome(passed_downstream=True, status=res.status, logged_reason=None)


def test_ac2_in_range_passes_downstream():
    out = range_gate(123.4, PROFILE)
    assert out.passed_downstream is True
    assert out.status is ReadingStatus.OK
    assert out.logged_reason is None


def test_ac2_below_min_rejected_logged_withheld():
    out = range_gate(-50.0, PROFILE)
    assert out.status is ReadingStatus.CORRUPT
    assert out.passed_downstream is False          # NOT passed downstream
    assert out.logged_reason and out.logged_reason.strip()  # a reason was logged
    assert "below" in out.logged_reason
    assert "kN" in out.logged_reason


def test_ac2_above_max_rejected_logged_withheld():
    out = range_gate(999.0, PROFILE)
    assert out.status is ReadingStatus.CORRUPT
    assert out.passed_downstream is False
    assert "above" in out.logged_reason


def test_ac2_exact_boundaries_pass():
    assert range_gate(-10.0, PROFILE).passed_downstream is True
    assert range_gate(500.0, PROFILE).passed_downstream is True


def test_ac2_none_and_nan_are_corrupt_withheld():
    for bad in (None, math.nan):
        out = range_gate(bad, PROFILE)
        assert out.status is ReadingStatus.CORRUPT
        assert out.passed_downstream is False
        assert out.logged_reason


def test_ac2_unknown_type_corrupt_withheld():
    out = range_gate(10.0, UnknownSensorType("seismometer"))
    assert out.status is ReadingStatus.CORRUPT
    assert out.passed_downstream is False
    assert "not registered" in out.logged_reason


def test_ac2_corrupt_always_carries_loggable_reason():
    # Every CORRUPT path must yield a non-blank reason (Const. VI auditability).
    for bad in (-9999.0, 9999.0, None, math.nan, "x"):
        out = range_gate(bad, PROFILE)
        assert out.status is ReadingStatus.CORRUPT
        assert out.logged_reason is not None and out.logged_reason.strip() != ""
