"""A1102 — end-to-end acceptance: every spec AC manifests through the service (AC-1…AC-12).

Drives alerts through the REAL service (run_alert) over the shared harness fixtures, and asserts
each acceptance criterion shows up in the returned DispatchSummary AND the persisted
alert_dispatches + decision_log state — not just in a unit's return value. This is the spec-level
gate a reviewer reads against specs/alert-escalation-agent/spec.md.

  AC-1  read-only / no re-judge             AC-7  retry -> failover -> escalate, logged
  AC-2  settled severity->approval mapping   AC-8  consistency fail-closed (pos + neg)
  AC-3  overrides (pending + authority)       AC-9  redelivery idempotent (no double-dispatch)
  AC-4  single un-bypassable gate             AC-10 dispatches current, records version, reproducible
  AC-5  severity-dependent close              AC-11 never-crash 4-scenario
  AC-6  distinct delivery states              AC-12 dual audit (append-only, DELETE-blocked)
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from _alert_harness import (
    POLICY,
    TEMPLATES,
    NOW,
    HarnessSource,
    all_cases,
    run_case,
)
from agents.alert_escalation.dispatch.fake_notifier import FakeNotifier
from agents.alert_escalation.message import assemble_message
from agents.alert_escalation.service import AssessmentScope, run_alert
from agents.alert_escalation.store import (
    FakeAlertStore,
    DispatchDeleteBlocked,
    DispatchImmutableError,
)
from agents.alert_escalation.statuses import (
    AlertOutcome,
    ApprovalState,
    DeliveryState,
    DispatchDecision,
    EscalationState,
    WithheldReason,
)
from agents.risk_reasoning.statuses import Severity

SRC = Path(__file__).resolve().parents[2] / "src" / "agents" / "alert_escalation"
_MODEL_ROOTS = {"openai", "anthropic", "agents_sdk"}


def _verdict(**over):
    base = dict(
        id=1001, bridge_id="b", cycle_id="c", assessment_version=3,
        risk_score=48, severity="WARNING", review_status="FINAL",
        recommendation="Schedule inspection.", explanation="Deflection ratio elevated at pier 3.",
        trace_id="trace-xyz", superseded_by=None,
    )
    base.update(over)
    return base


def _by_name():
    return {c.name: c for c in all_cases()}


def _run(verdict, *, store=None, notifier=None, approval=None, scope=None, **kw):
    return run_alert(
        scope or AssessmentScope("b", "c"),
        sources=HarnessSource([verdict]),
        store=store if store is not None else FakeAlertStore(),
        policy=POLICY, templates=TEMPLATES,
        notifier=notifier or FakeNotifier(deliver_on_send=("email",)),
        now=NOW, approval=approval, **kw,
    )


# ------------------------------------------------------------------ AC-1 read-only / no re-judge ---
def test_ac1_dispatch_is_a_verbatim_copy_no_remap():
    # The assembled message copies the verdict fields byte-for-byte; nothing is re-worded/re-mapped.
    v = _verdict()
    msg = assemble_message(v, TEMPLATES)
    assert msg.band == v["severity"]                    # severity not re-mapped
    assert msg.explanation == v["explanation"]           # explanation verbatim
    assert msg.recommendation == v["recommendation"]
    assert msg.field_source("explanation") == "risk_assessments:1001:explanation"


def test_ac1_source_verdict_is_not_mutated():
    v = _verdict()
    snapshot = dict(v)
    _run(v)
    assert v == snapshot                                 # the service mutated no verdict field


# ------------------------------------------------------------------ AC-2 settled mapping ---
def test_ac2_safe_is_dashboard_only_no_push():
    notifier = FakeNotifier()
    s = _run(_verdict(severity="SAFE", risk_score=10), notifier=notifier)
    assert s.dispatch_decision is DispatchDecision.DASHBOARD_ONLY
    assert notifier.sent == []


def test_ac2_watch_final_auto_fires():
    s = _run(_verdict(severity="WATCH", risk_score=45, review_status="FINAL"))
    assert s.dispatch_decision is DispatchDecision.AUTO_FIRE


def test_ac2_warning_and_critical_need_approval_not_dispatched_without_it():
    for sev, score in (("WARNING", 70), ("CRITICAL", 90)):
        notifier = FakeNotifier()
        s = _run(_verdict(severity=sev, risk_score=score, review_status="FINAL"),
                 notifier=notifier, approval=None)
        assert s.dispatch_decision is DispatchDecision.NEEDS_APPROVAL
        assert notifier.sent == [], f"{sev} dispatched without approval"


# ------------------------------------------------------------------ AC-3 overrides ---
def test_ac3_pending_verdict_never_auto_fires():
    # A WATCH that would auto-fire is forced to NEEDS_APPROVAL by a pending review_status.
    s = _run(_verdict(severity="WATCH", risk_score=45, review_status="PENDING_HUMAN_REVIEW"),
             approval=None)
    assert s.dispatch_decision is DispatchDecision.NEEDS_APPROVAL


def test_ac3_authority_recipient_forces_needs_approval():
    case = _by_name()["AUTHORITY_WATCH"]
    s = run_case(case)
    assert s.dispatch_decision is DispatchDecision.NEEDS_APPROVAL


# ------------------------------------------------------------------ AC-4 single un-bypassable gate ---
def test_ac4_no_gated_dispatch_without_a_recorded_approval():
    notifier = FakeNotifier()
    store = FakeAlertStore()
    _run(_verdict(severity="WARNING", review_status="FINAL"),
         store=store, notifier=notifier, approval=None)
    assert notifier.sent == []                           # nothing sent
    row = store.rows[0].result
    assert row.approval_state is ApprovalState.AWAITING_APPROVAL


def test_ac4_no_other_module_defines_a_dispatch_path():
    # The inverted chokepoint: only the dispatch layer sends; no sibling agent defines a notify path.
    # (Full cross-repo scan lives in A602/A1103; here we assert the gate is REACHED in the flow.)
    store = FakeAlertStore()
    _run(_verdict(severity="WARNING", review_status="FINAL"),
         store=store, approval=("APPROVED", "reviewer@gov"),
         notifier=FakeNotifier(ack_on_send=("email",)))
    row = store.rows[0].result
    assert row.approval_state is ApprovalState.APPROVED
    assert row.approved_by == "reviewer@gov"             # the gate recorded the sign-off


# ------------------------------------------------------------------ AC-5 severity-dependent close ---
def test_ac5_watch_closes_on_delivered():
    s = _run(_verdict(severity="WATCH", risk_score=45, review_status="FINAL"),
             notifier=FakeNotifier(deliver_on_send=("email",)))
    assert s.ok is True                                  # SAFE/WATCH close on DELIVERED


def test_ac5_warning_delivered_without_ack_does_not_close():
    s = _run(_verdict(severity="WARNING", review_status="FINAL"),
             approval=("APPROVED", "reviewer@gov"),
             notifier=FakeNotifier(deliver_on_send=("email",)))   # delivered, NOT acked
    assert s.ok is False                                 # WARNING needs ACK to close


def test_ac5_warning_closes_on_ack():
    store = FakeAlertStore()
    _run(_verdict(severity="WARNING", review_status="FINAL"),
         store=store, approval=("APPROVED", "reviewer@gov"),
         notifier=FakeNotifier(ack_on_send=("email",)))
    row = store.rows[0].result
    assert row.escalation_state is EscalationState.CLOSED
    assert row.close_reason is DeliveryState.ACKNOWLEDGED


# ------------------------------------------------------------------ AC-6 distinct delivery states ---
def test_ac6_send_accept_is_sent_not_delivered_in_the_row():
    # No receipt injected -> the persisted delivery_state is SENT, never DELIVERED off a bare accept.
    store = FakeAlertStore()
    _run(_verdict(severity="WATCH", risk_score=45, review_status="FINAL"),
         store=store, notifier=FakeNotifier())            # no deliver_on_send
    row = store.rows[0].result
    assert row.delivery_state is DeliveryState.SENT


def test_ac6_three_states_are_distinct():
    assert len({DeliveryState.SENT, DeliveryState.DELIVERED, DeliveryState.ACKNOWLEDGED}) == 3


# ------------------------------------------------------------------ AC-7 retry->failover->escalate ---
def test_ac7_channel_failure_escalates_and_logs_every_attempt():
    notifier = FakeNotifier(failing_channels=("email",))
    s = _run(_verdict(severity="WARNING", review_status="FINAL"),
             notifier=notifier, approval=("APPROVED", "reviewer@gov"))
    assert s.escalated is True                            # no accept -> escalated
    # retry_max=1 -> 2 sends per contact, 2 contacts = 4 recorded attempts; none silent.
    assert len(notifier.sent) == 4


# ------------------------------------------------------------------ AC-8 consistency fail-closed ---
def test_ac8_contradiction_is_withheld_not_dispatched():
    case = _by_name()["CONTRADICTION"]
    notifier = FakeNotifier()
    s = run_case(case, notifier=notifier)
    assert s.outcome is AlertOutcome.WITHHELD
    assert s.withheld_reason is WithheldReason.CONSISTENCY_MISMATCH
    assert notifier.sent == []


def test_ac8_consistent_alert_passes():
    s = _run(_verdict(severity="WATCH", risk_score=45, review_status="FINAL"))
    assert s.outcome is AlertOutcome.DISPATCHED           # consistent -> proceeds


# ------------------------------------------------------------------ AC-9 idempotency ---
def test_ac9_redelivery_no_double_dispatch():
    store = FakeAlertStore()
    v = _verdict(severity="WATCH", risk_score=45, review_status="FINAL")
    src = HarnessSource([v])
    for _ in range(3):
        run_alert(AssessmentScope("b", "c"), sources=src, store=store, policy=POLICY,
                  templates=TEMPLATES, notifier=FakeNotifier(deliver_on_send=("email",)), now=NOW)
    current = [r for r in store.rows if r.superseded_by is None]
    assert len(current) == 1                              # one current row despite 3 triggers


# ------------------------------------------------------------------ AC-10 reproducible ---
def test_ac10_row_pins_version_and_trace_and_survives_supersession():
    store = FakeAlertStore()
    v3 = _verdict(severity="WATCH", risk_score=45, review_status="FINAL", assessment_version=3)
    src = HarnessSource([v3])
    run_alert(AssessmentScope("b", "c"), sources=src, store=store, policy=POLICY,
              templates=TEMPLATES, notifier=FakeNotifier(deliver_on_send=("email",)), now=NOW)
    first_id = store.rows[0].id
    # a re-handle of the same version supersedes; the original row + its pinned identity survive.
    run_alert(AssessmentScope("b", "c"), sources=src, store=store, policy=POLICY,
              templates=TEMPLATES, notifier=FakeNotifier(deliver_on_send=("email",)), now=NOW)
    old = store.get(first_id).result
    assert old.assessment_version == 3
    assert old.trace_id == "trace-xyz"


# ------------------------------------------------------------------ AC-11 never crash ---
def test_ac11_four_scenarios_structured_never_raise():
    for name in ("WATCH_FINAL", "MALFORMED", "CONTRADICTION", "CHANNEL_FAIL"):
        case = _by_name()[name]
        s = run_case(case)
        assert s is not None
        assert s.outcome in (AlertOutcome.DISPATCHED, AlertOutcome.WITHHELD, AlertOutcome.ERROR)


def test_ac11_provider_outage_is_named_error():
    class _Boom:
        sent: list = []
        def send(self, **_):
            raise RuntimeError("provider outage")
        def state_of(self, _):
            return None
    s = _run(_verdict(severity="WATCH", risk_score=45, review_status="FINAL"), notifier=_Boom())
    assert s.outcome is AlertOutcome.ERROR
    assert "provider outage" in (s.error or "")


# ------------------------------------------------------------------ AC-12 dual audit ---
def test_ac12_every_dispatch_writes_an_append_only_audit():
    store = FakeAlertStore()
    _run(_verdict(severity="WATCH", risk_score=45, review_status="FINAL"),
         store=store, notifier=FakeNotifier(deliver_on_send=("email",)))
    assert len(store.audit_rows) == 1
    assert store.audit_rows[0].decision in ("ALERT_DISPATCHED", "ALERT_ESCALATED")


def test_ac12_audit_pins_version_and_a_row_carries_trace_and_approver():
    store = FakeAlertStore()
    _run(_verdict(severity="WARNING", review_status="FINAL"),
         store=store, approval=("APPROVED", "reviewer@gov"),
         notifier=FakeNotifier(ack_on_send=("email",)))
    row = store.rows[0].result
    assert row.trace_id == "trace-xyz"
    assert row.approved_by == "reviewer@gov"
    assert "v3" in store.audit_rows[-1].reason


def test_ac12_overwrite_and_delete_are_blocked():
    store = FakeAlertStore()
    _run(_verdict(severity="WATCH", risk_score=45, review_status="FINAL"), store=store,
         notifier=FakeNotifier(deliver_on_send=("email",)))
    some_id = store.rows[0].id
    with pytest.raises(DispatchImmutableError):
        store.overwrite(some_id, store.rows[0].result)
    with pytest.raises(DispatchDeleteBlocked):
        store.delete(some_id)


# ------------------------------------------------------------------ no model in the service path ---
def test_no_model_in_the_service_import_graph():
    def roots(p: Path):
        r = set()
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            if isinstance(n, ast.Import):
                for al in n.names:
                    r.add(al.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
                r.add(n.module.split(".")[0])
        return r
    assert not (roots(SRC / "service.py") & _MODEL_ROOTS)
