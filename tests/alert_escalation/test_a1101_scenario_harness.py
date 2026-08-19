"""A1101 — scenario harness catalog (fake store + fake notifier).

Acceptance (tasks.md A1101): every named scenario is present; each yields its documented
decision/delivery/escalation state; replaying the catalog twice gives identical summaries
(deterministic — no clock/random).

This asserts the harness itself (the shared fixture A1102's AC assertions build on). The scenarios
run through the REAL service (run_alert), so this is a genuine end-to-end drive, not a stub.
"""
from __future__ import annotations

from _alert_harness import (
    SCENARIO_NAMES,
    all_cases,
    run_case,
    summary_fingerprint,
)
from agents.alert_escalation.dispatch.fake_notifier import FakeNotifier
from agents.alert_escalation.store import FakeAlertStore
from agents.alert_escalation.statuses import AlertOutcome


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


def test_each_scenario_matches_its_expected_decision():
    for case in all_cases():
        summary = run_case(case)
        assert summary.dispatch_decision is case.expectation.dispatch_decision, (
            f"{case.name}: expected {case.expectation.dispatch_decision}, "
            f"got {summary.dispatch_decision}")


def test_each_scenario_matches_its_expected_ok():
    for case in all_cases():
        summary = run_case(case)
        assert summary.ok is case.expectation.ok, (
            f"{case.name}: expected ok={case.expectation.ok}, got {summary.ok}")


def test_push_expectation_matches_notifier_activity():
    # A scenario that expects an outbound push must actually have sent; one that does not must be silent.
    for case in all_cases():
        notifier = FakeNotifier(
            failing_channels=case.failing_channels,
            deliver_on_send=case.deliver_on_send,
            ack_on_send=case.ack_on_send,
        )
        run_case(case, notifier=notifier)
        pushed = len(notifier.sent) > 0
        assert pushed is case.expectation.pushed, (
            f"{case.name}: expected pushed={case.expectation.pushed}, got {pushed}")


def test_escalated_expectation_matches():
    for case in all_cases():
        summary = run_case(case)
        assert summary.escalated is case.expectation.escalated, (
            f"{case.name}: expected escalated={case.expectation.escalated}, got {summary.escalated}")


def test_withheld_scenarios_name_their_reason():
    for case in all_cases():
        if case.expectation.outcome is AlertOutcome.WITHHELD:
            summary = run_case(case)
            assert summary.withheld_reason is case.expectation.withheld_reason, (
                f"{case.name}: wrong withheld reason")


def test_no_scenario_raises():
    # FR-12: every scripted scenario yields a structured summary, never a stack trace.
    for case in all_cases():
        summary = run_case(case)
        assert summary is not None
        assert summary.outcome in (
            AlertOutcome.DISPATCHED, AlertOutcome.WITHHELD, AlertOutcome.ERROR)


def test_catalog_is_deterministic_across_replays():
    # Replaying the whole catalog twice yields identical fingerprints (no clock/random).
    first = {c.name: summary_fingerprint(run_case(c)) for c in all_cases()}
    second = {c.name: summary_fingerprint(run_case(c)) for c in all_cases()}
    assert first == second


def test_contradiction_withholds_without_a_push():
    case = _by_name()["CONTRADICTION"]
    notifier = FakeNotifier()
    summary = run_case(case, notifier=notifier)
    assert summary.outcome is AlertOutcome.WITHHELD
    assert notifier.sent == []


def test_redelivery_is_idempotent_single_current_row():
    case = _by_name()["REDELIVERY"]
    store = FakeAlertStore()
    run_case(case, store)                      # prestep + main both run against this store
    current = [r for r in store.rows if r.superseded_by is None]
    assert len(current) == 1                   # no duplicate current dispatch


def test_channel_fail_escalates_and_logs_every_attempt():
    case = _by_name()["CHANNEL_FAIL"]
    notifier = FakeNotifier(failing_channels=("email",))
    summary = run_case(case, notifier=notifier)
    assert summary.escalated is True
    # retry_max=1 -> 2 sends per contact, 2 contacts (both email) = 4 recorded attempts, all failed.
    assert len(notifier.sent) == 4
