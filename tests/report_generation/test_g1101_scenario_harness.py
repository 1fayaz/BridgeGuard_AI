"""G1101 — scenario harness catalog (fake store + fake renderer).

Acceptance (tasks.md G1101): every named scenario is present; each yields its documented outcome +
marks; replaying the catalog twice gives identical summaries (deterministic — no clock/random).

This asserts the harness itself (the shared fixture G1102's AC assertions build on). The scenarios
run through the REAL service (run_report), so this is a genuine end-to-end drive, not a stub.
"""
from __future__ import annotations

from _report_harness import (
    SCENARIO_NAMES,
    all_cases,
    run_case,
    summary_fingerprint,
)
from agents.report_generation.report_statuses import ReportOutcome


def _by_name():
    return {c.name: c for c in all_cases()}


def test_all_named_scenarios_present():
    names = {c.name for c in all_cases()}
    assert names == set(SCENARIO_NAMES)


def test_no_duplicate_scenarios():
    names = [c.name for c in all_cases()]
    assert len(names) == len(set(names))


def test_each_scenario_matches_its_expected_outcome():
    for case in all_cases():
        summary = run_case(case)
        assert summary.outcome is case.expectation.outcome, (
            f"{case.name}: expected {case.expectation.outcome}, got {summary.outcome}")


def test_each_scenario_matches_its_expected_marks():
    for case in all_cases():
        summary = run_case(case)
        for mark in case.expectation.marks:
            assert mark in summary.marks, f"{case.name}: missing mark {mark}"


def test_withheld_scenarios_name_their_reason():
    for case in all_cases():
        if case.expectation.outcome is ReportOutcome.WITHHELD:
            summary = run_case(case)
            assert summary.withheld_reason is case.expectation.withheld_reason, (
                f"{case.name}: wrong withheld reason")


def test_artifact_presence_matches_expectation():
    for case in all_cases():
        summary = run_case(case)
        if case.expectation.artifact_expected:
            assert summary.artifact_ref, f"{case.name}: expected an artifact ref"
        else:
            assert summary.artifact_ref is None, f"{case.name}: expected NO artifact ref"


def test_no_scenario_raises():
    # FR-12: every scripted scenario yields a structured summary, never a stack trace.
    for case in all_cases():
        summary = run_case(case)
        assert summary is not None
        assert summary.outcome in (
            ReportOutcome.RENDERED, ReportOutcome.WITHHELD, ReportOutcome.ERROR)


def test_catalog_is_deterministic_across_replays():
    # Replaying the whole catalog twice yields identical fingerprints (no clock/random).
    first = {c.name: summary_fingerprint(run_case(c)) for c in all_cases()}
    second = {c.name: summary_fingerprint(run_case(c)) for c in all_cases()}
    assert first == second


def test_off_book_withholds_without_an_artifact():
    case = _by_name()["OFF_BOOK"]
    summary = run_case(case)
    assert summary.outcome is ReportOutcome.WITHHELD
    assert summary.artifact_ref is None


def test_redelivery_is_idempotent_single_current_row():
    from agents.report_generation.store import FakeReportStore
    case = _by_name()["REDELIVERY"]
    store = FakeReportStore()
    run_case(case, store)                      # prestep + main both run against this store
    current = [r for r in store.rows if r.superseded_by is None]
    assert len(current) == 1                   # no duplicate current report
