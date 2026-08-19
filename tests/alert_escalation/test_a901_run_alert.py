"""A901 — run_alert(...) orchestrator: resolve -> tier -> assemble -> consistency -> approve ->
dispatch -> escalate -> persist. Always returns a structured DispatchSummary; never raises (FR-12).

Wires every pure piece built in Phases 3-8 into the one per-alert flow (plan §1). The acceptance is
the full behaviour matrix from tasks.md A901:
  * SAFE scope        -> DASHBOARD_ONLY, no push, closed;
  * WATCH-FINAL       -> AUTO_FIRE, dispatched, closed on DELIVERED;
  * WARNING           -> held AWAITING_APPROVAL (no dispatch) until approved, then dispatched +
                         escalates to ACK (not closed by DELIVERED alone);
  * CRITICAL (pending)-> gated on both axes (needs approval AND never auto-fires);
  * contradicting msg -> WITHHELD/CONSISTENCY_MISMATCH (no dispatch);
  * missing verdict   -> WITHHELD/ASSESSMENT_NOT_FOUND;
  * injected exception-> structured ERROR summary, nothing raises out (FR-12).

Delivery is out of band: the fake's deliver_on_send / ack_on_send simulate a receipt/ack having
arrived by reconciliation time; the send itself is always SENT (FR-7), never DELIVERED.
"""
from __future__ import annotations

from agents.alert_escalation.service import run_alert
from agents.alert_escalation.tools.verdict_read import AssessmentScope
from agents.alert_escalation.config.alert_policy import AlertPolicy
from agents.alert_escalation.config.message_template_table import MessageTemplateTable
from agents.alert_escalation.dispatch.fake_notifier import FakeNotifier
from agents.alert_escalation.store import FakeAlertStore
from agents.alert_escalation.statuses import (
    AlertOutcome,
    ApprovalState,
    DispatchDecision,
    WithheldReason,
)
from agents.risk_reasoning.statuses import Severity


# --------------------------------------------------------------------- fixtures ---
class _FakeSource:
    """Minimal AssessmentSource: one current verdict keyed by (bridge, cycle)."""

    def __init__(self, verdict: dict | None):
        self._verdict = verdict

    def current_assessment_for(self, bridge_id, cycle_id):
        return self._verdict

    def assessment_by_id(self, assessment_id):
        return self._verdict


def _verdict(**over):
    base = dict(
        id=1001,
        bridge_id="bridge-7",
        cycle_id="cycle-42",
        assessment_version=3,
        risk_score=48,
        severity="WARNING",
        recommendation="Schedule inspection.",
        explanation="Deflection ratio elevated at pier 3.",
        review_status="FINAL",
        trace_id="trace-xyz",
    )
    base.update(over)
    return base


def _policy(**over):
    base = dict(
        policy_version="rev1",
        retry_max=1,
        backoff_seconds=30,
        escalation_timeout_seconds=300,
        contact_roster=(
            ("WATCH", "watch@gov"),
            ("WARNING", "engineer@gov"),
            ("CRITICAL", "oncall@gov"),
        ),
        escalation_order=("engineer@gov", "oncall@gov"),
        channel_per_band=(
            ("WATCH", "email"),
            ("WARNING", "email"),
            ("CRITICAL", "sms"),
        ),
        authority_recipients=(),
    )
    base.update(over)
    return AlertPolicy(**base)


def _templates():
    body = "Bridge {bridge_id} {severity} (score {risk_score}): {recommendation} — {explanation}"
    return MessageTemplateTable(
        templates=(
            (Severity.SAFE, body),
            (Severity.WATCH, body),
            (Severity.WARNING, body),
            (Severity.CRITICAL, body),
        )
    )


def _scope():
    return AssessmentScope(bridge_id="bridge-7", cycle_id="cycle-42")


NOW = "2026-07-13T00:00:00Z"


def _run(source, *, notifier=None, approval=None, policy=None, templates=None, store=None):
    return run_alert(
        _scope(),
        sources=source,
        store=store or FakeAlertStore(),
        policy=policy or _policy(),
        templates=templates or _templates(),
        notifier=notifier or FakeNotifier(),
        now=NOW,
        approval=approval,
    )


# --------------------------------------------------------------------- SAFE -> dashboard-only ---
def test_safe_is_dashboard_only_no_push_closed():
    src = _FakeSource(_verdict(severity="SAFE", risk_score=10, review_status="FINAL"))
    notifier = FakeNotifier()
    summary = _run(src, notifier=notifier)
    assert summary.outcome is AlertOutcome.DISPATCHED
    assert summary.dispatch_decision is DispatchDecision.DASHBOARD_ONLY
    assert summary.ok is True                       # dashboard event recorded + closed
    assert notifier.sent == []                       # NO outbound push


# --------------------------------------------------------------------- WATCH-FINAL -> auto-fire ---
def test_watch_final_auto_fires_and_closes_on_delivered():
    src = _FakeSource(_verdict(severity="WATCH", risk_score=45, review_status="FINAL"))
    notifier = FakeNotifier(deliver_on_send=("email",))    # a receipt arrives
    summary = _run(src, notifier=notifier)
    assert summary.dispatch_decision is DispatchDecision.AUTO_FIRE
    assert len(notifier.sent) == 1                          # it was pushed
    assert summary.ok is True                               # SAFE/WATCH close on DELIVERED
    assert summary.delivered_channels == ("email",)


def test_watch_final_without_a_receipt_stays_open_not_ok():
    src = _FakeSource(_verdict(severity="WATCH", risk_score=45, review_status="FINAL"))
    notifier = FakeNotifier()                               # no receipt yet -> SENT only
    summary = _run(src, notifier=notifier)
    assert summary.dispatch_decision is DispatchDecision.AUTO_FIRE
    assert summary.ok is False                              # not delivered -> not closed


# --------------------------------------------------------------------- WARNING -> gated ---
def test_warning_without_approval_is_held_awaiting_no_push():
    src = _FakeSource(_verdict(severity="WARNING", review_status="FINAL"))
    notifier = FakeNotifier()
    summary = _run(src, notifier=notifier, approval=None)
    assert summary.dispatch_decision is DispatchDecision.NEEDS_APPROVAL
    assert summary.ok is False                              # nothing dispatched, held
    assert notifier.sent == []                              # NO push without approval (FR-5)


def test_warning_approved_dispatches_but_not_closed_by_delivered_alone():
    # Approved -> dispatched; a DELIVERED receipt is NOT enough to close a WARNING (needs ACK, FR-6).
    src = _FakeSource(_verdict(severity="WARNING", review_status="FINAL"))
    notifier = FakeNotifier(deliver_on_send=("email",))
    summary = _run(src, notifier=notifier, approval=("APPROVED", "reviewer@gov"))
    assert summary.dispatch_decision is DispatchDecision.NEEDS_APPROVAL
    assert len(notifier.sent) == 1                          # dispatched
    assert summary.ok is False                              # delivered but NOT acked -> still open


def test_warning_approved_and_acked_closes():
    src = _FakeSource(_verdict(severity="WARNING", review_status="FINAL"))
    notifier = FakeNotifier(ack_on_send=("email",))         # a human ack arrives
    summary = _run(src, notifier=notifier, approval=("APPROVED", "reviewer@gov"))
    assert summary.ok is True                               # acked -> closed
    assert summary.delivered_channels == ("email",)


# --------------------------------------------------------------------- CRITICAL pending -> both axes ---
def test_critical_pending_is_gated_and_never_auto_fires():
    src = _FakeSource(_verdict(severity="CRITICAL", risk_score=90,
                               review_status="PENDING_HUMAN_REVIEW"))
    notifier = FakeNotifier()
    summary = _run(src, notifier=notifier, approval=None)
    assert summary.dispatch_decision is DispatchDecision.NEEDS_APPROVAL
    assert summary.ok is False
    assert notifier.sent == []                              # gated on approval AND never auto-fired


# --------------------------------------------------------------------- consistency fail-closed ---
def test_contradicting_message_is_withheld_no_dispatch():
    # With the real copy-only assembler the message band always equals the verdict severity, so the
    # gate cannot trip in the honest flow (a good property). To prove the gate is WIRED IN, inject a
    # buggy assembler that mis-labels the band; the consistency gate must catch the contradiction
    # and withhold — fail-closed, nothing dispatched (FR-9).
    from agents.alert_escalation.message import AssembledMessage

    def _bad_assemble(verdict, templates):
        return AssembledMessage(
            band="SAFE",                       # contradicts the WARNING verdict
            risk_score=verdict.get("risk_score"),
            recommendation=verdict["recommendation"],
            explanation=verdict["explanation"],
            review_status=verdict["review_status"],
            body="mislabeled",
            sources={},
        )

    src = _FakeSource(_verdict(severity="WARNING", review_status="FINAL"))
    notifier = FakeNotifier()
    summary = run_alert(
        _scope(),
        sources=src,
        store=FakeAlertStore(),
        policy=_policy(),
        templates=_templates(),
        notifier=notifier,
        now=NOW,
        approval=("APPROVED", "reviewer@gov"),
        assemble=_bad_assemble,   # injected collaborator (defaults to the real assemble_message)
    )
    assert summary.outcome is AlertOutcome.WITHHELD
    assert summary.withheld_reason is WithheldReason.CONSISTENCY_MISMATCH
    assert notifier.sent == []


# --------------------------------------------------------------------- missing verdict ---
def test_missing_verdict_is_withheld_assessment_not_found():
    src = _FakeSource(None)
    summary = _run(src)
    assert summary.outcome is AlertOutcome.WITHHELD
    assert summary.withheld_reason is WithheldReason.ASSESSMENT_NOT_FOUND
    assert summary.ok is False


# --------------------------------------------------------------------- never raises (FR-12) ---
def test_provider_exception_is_a_structured_error_not_a_crash():
    class _BoomNotifier:
        sent = []
        def send(self, **_):
            raise RuntimeError("provider down")
        def state_of(self, _):
            return None
    src = _FakeSource(_verdict(severity="WATCH", review_status="FINAL"))
    summary = _run(src, notifier=_BoomNotifier())
    assert summary.outcome is AlertOutcome.ERROR
    assert summary.ok is False
    assert "provider down" in (summary.error or "")


def test_read_exception_is_a_structured_error_not_a_crash():
    class _BoomSource:
        def current_assessment_for(self, *_):
            raise RuntimeError("db unreachable")
        def assessment_by_id(self, *_):
            raise RuntimeError("db unreachable")
    summary = _run(_BoomSource())
    assert summary.outcome is AlertOutcome.ERROR
    assert "db unreachable" in (summary.error or "")


def test_audit_written_for_a_dispatched_alert():
    src = _FakeSource(_verdict(severity="WATCH", review_status="FINAL"))
    store = FakeAlertStore()
    _run(src, notifier=FakeNotifier(deliver_on_send=("email",)), store=store)
    kinds = [a.decision for a in store.audit_rows]
    assert kinds and kinds[-1] in ("ALERT_DISPATCHED", "ALERT_ESCALATED")
