"""T801 — handle_late_arrival function-level acceptance.

Acceptance (tasks.md T801): a within-window late reading produces a correction chain
(new row superseding the prior) + a CORRECTION log entry; raw is never referenced so
raw row count can only grow (structural — this function takes no raw handle). Outside
the window -> raw-only, logged "outside recompute window".
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

from agents.data_collection.checks import late_arrival as la_mod
from agents.data_collection.checks.late_arrival import (
    CorrectionPlan,
    LateReading,
    ProcessedReading,
    handle_late_arrival,
)
from agents.data_collection.config.sensor_profiles import SensorProfile
from agents.data_collection.statuses import ReadingStatus

UTC = timezone.utc
NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=UTC)
PROFILE = SensorProfile(
    sensor_type="t", unit="x", cadence_s=60.0, phys_min=-1e9, phys_max=1e9,
    clock_drift_tolerance_s=5.0,
)  # pending_timeout_s = 180s = 3x cadence -> recompute window


def slot_time(seconds_ago: float) -> datetime:
    return NOW - timedelta(seconds=seconds_ago)


def test_within_window_changed_verdict_supersedes_and_logs():
    # Prior verdict was NO_DATA at t-120s; the late reading now yields OK.
    prior = ProcessedReading(row_id=42, sensor_id="s", sensor_time=slot_time(120),
                             value=None, status=ReadingStatus.NO_DATA)
    late = LateReading(sensor_id="s", sensor_time=slot_time(120), value=12.5)
    plan = handle_late_arrival(late, [prior], NOW, PROFILE, ReadingStatus.OK)

    assert plan.within_window is True
    assert plan.recomputed is True
    assert len(plan.new_rows) == 1
    row = plan.new_rows[0]
    assert row.status is ReadingStatus.OK
    assert row.value == 12.5
    assert row.supersedes_row_id == 42          # points at the prior row
    assert row.reason == "late-arrival recompute"
    assert len(plan.logs) == 1
    log = plan.logs[0]
    assert log.old_status is ReadingStatus.NO_DATA
    assert log.new_status is ReadingStatus.OK
    assert log.reason == "late-arrival recompute"


def test_outside_window_is_raw_only_logged():
    # 240s old > 180s window.
    late = LateReading(sensor_id="s", sensor_time=slot_time(240), value=9.0)
    plan = handle_late_arrival(late, [], NOW, PROFILE, ReadingStatus.OK)

    assert plan.within_window is False
    assert plan.recomputed is False
    assert plan.new_rows == []                  # nothing recomputed
    assert len(plan.logs) == 1
    assert "outside recompute window" in plan.logs[0].reason.lower()


def test_window_boundary_strictly_greater_is_outside():
    # Exactly at 180s is WITHIN (age > window is the outside test, strict).
    at_boundary = LateReading("s", slot_time(180), 1.0)
    plan_in = handle_late_arrival(at_boundary, [], NOW, PROFILE, ReadingStatus.OK)
    assert plan_in.within_window is True

    just_outside = LateReading("s", slot_time(180.5), 1.0)
    plan_out = handle_late_arrival(just_outside, [], NOW, PROFILE, ReadingStatus.OK)
    assert plan_out.within_window is False


def test_within_window_no_prior_creates_fresh_verdict():
    # No prior row for this slot -> fresh verdict, old_status None, no supersede target.
    late = LateReading("s", slot_time(60), 7.0)
    plan = handle_late_arrival(late, [], NOW, PROFILE, ReadingStatus.OK)
    assert plan.within_window is True
    assert plan.recomputed is True
    assert plan.new_rows[0].supersedes_row_id == -1
    assert plan.logs[0].old_status is None
    assert plan.logs[0].new_status is ReadingStatus.OK


def test_within_window_unchanged_verdict_logs_no_new_row():
    # Prior OK 7.0, late reading also OK 7.0 -> no churn: log only, no new row.
    prior = ProcessedReading(1, "s", slot_time(60), 7.0, ReadingStatus.OK)
    late = LateReading("s", slot_time(60), 7.0)
    plan = handle_late_arrival(late, [prior], NOW, PROFILE, ReadingStatus.OK)
    assert plan.within_window is True
    assert plan.recomputed is False
    assert plan.new_rows == []
    assert "unchanged" in plan.logs[0].reason.lower()


def test_correction_is_append_not_mutation_prior_untouched():
    # The prior ProcessedReading must be left intact (frozen + not returned mutated):
    # the plan describes a NEW row + a superseded_by LINK, never an edit to prior.
    prior = ProcessedReading(99, "s", slot_time(120), None, ReadingStatus.NO_DATA)
    before = (prior.row_id, prior.value, prior.status)
    plan = handle_late_arrival(
        LateReading("s", slot_time(120), 3.3), [prior], NOW, PROFILE, ReadingStatus.OK
    )
    assert (prior.row_id, prior.value, prior.status) == before  # untouched
    assert plan.new_rows[0].supersedes_row_id == 99             # linked, not edited


def test_function_takes_no_raw_store_handle_structural_guarantee():
    # Raw-never-overwritten is structural: handle_late_arrival has no parameter that
    # could be a raw store. (Const. II — the guarantee is built-in, not just promised.)
    params = set(inspect.signature(handle_late_arrival).parameters)
    assert params == {"reading", "processed_window", "now", "profile", "recompute_status"}
    assert not any("raw" in p for p in params)


def test_returns_correction_plan_type():
    plan = handle_late_arrival(
        LateReading("s", slot_time(60), 1.0), [], NOW, PROFILE, ReadingStatus.OK
    )
    assert isinstance(plan, CorrectionPlan)
