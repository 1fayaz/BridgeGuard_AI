"""run_alert(...) (A901) — the per-alert orchestrator. Never raises (FR-12).

Wires the whole per-alert flow for one finalized verdict (plan §1), composing the pure pieces built
in Phases 3-8 — nothing here re-judges the verdict (FR-1), and there is NO model anywhere:

    resolve the verdict (A301)
      -> WITHHELD/ASSESSMENT_NOT_FOUND if absent (nothing to alert on), stop
    decide the tier (A401)
      -> DASHBOARD_ONLY: record the dashboard event, no push, closed
    assemble the message by copying (A501)
    consistency gate (A502)
      -> WITHHELD/CONSISTENCY_MISMATCH if the message contradicts the verdict — no dispatch, stop
    approval gate (A601) — the single un-bypassable chokepoint
      -> NEEDS_APPROVAL without a recorded approval: held AWAITING_APPROVAL, no push
    dispatch via the injected NotifierPort (A701/A702), climbing the escalation ladder (A703)
    reconcile delivery + resolve the severity-dependent close (A703)
    persist the alert_dispatches row + decision_log audit (A802)
      -> DispatchSummary

It ALWAYS returns a structured DispatchSummary and NEVER raises (FR-12 / Principle V): any read,
dispatch, or persist failure is isolated into a structured ERROR summary with the failure named.

Injected collaborators (all defaulted, overridable for tests): `sources` (the verdict read port),
`notifier` (the NotifierPort), and `assemble` (the copy-only message assembler). `now` is the
timestamp seam — there is no clock in the service. `approval` is the recorded human decision for a
gated dispatch (a (state, approver) pair) or None if none has been recorded yet.

[DB-DEP]/[NOTIFY-DEP] Runs against FakeAlertStore + FakeNotifier now; the live Neon write and the
real provider send/receipt reconciliation are deferred (no instance/provider locally).
"""
from __future__ import annotations

from typing import Any, Callable

from agents.alert_escalation.approval import approval_gate
from agents.alert_escalation.config.alert_policy import AlertPolicy
from agents.alert_escalation.config.message_template_table import MessageTemplateTable
from agents.alert_escalation.consistency import consistency_check
from agents.alert_escalation.escalation import (
    build_attempt_plan,
    resolve_escalation,
    run_send_ladder,
)
from agents.alert_escalation.message import AssembledMessage, assemble_message
from agents.alert_escalation.persistence import persist_dispatch
from agents.alert_escalation.alert_result import AlertResult, DispatchSummary
from agents.alert_escalation.statuses import (
    AlertOutcome,
    ApprovalState,
    DeliveryState,
    DispatchDecision,
    EscalationState,
    WithheldReason,
)
from agents.alert_escalation.store import FakeAlertStore
from agents.alert_escalation.tiering import decide_tier
from agents.alert_escalation.tools.verdict_read import AssessmentScope, get_risk_assessment

__all__ = ["AssessmentScope", "run_alert"]


def run_alert(
    scope: AssessmentScope,
    *,
    sources: Any,
    store: FakeAlertStore,
    policy: AlertPolicy,
    templates: MessageTemplateTable,
    notifier: Any,
    now: str,
    historical: bool = False,
    approval: tuple[str, str | None] | None = None,
    assemble: Callable[[dict, MessageTemplateTable], AssembledMessage] = assemble_message,
) -> DispatchSummary:
    """Dispatch + escalate one alert for a finalized verdict (A901). Always structured; never raises."""
    try:
        return _run(
            scope, sources=sources, store=store, policy=policy, templates=templates,
            notifier=notifier, now=now, historical=historical, approval=approval, assemble=assemble,
        )
    except Exception as exc:  # FR-12: no failure escapes as a crash.
        store.append_audit(
            scope.bridge_id, scope.cycle_id, "ALERT_ERROR",
            f"alert could not be processed due to an internal error: {exc!s}",
        )
        return DispatchSummary.from_error(str(exc))


def _run(
    scope, *, sources, store, policy, templates, notifier, now, historical, approval, assemble,
) -> DispatchSummary:
    # 1. Resolve the verdict. Absent -> WITHHELD/ASSESSMENT_NOT_FOUND (no identity to key a row on).
    read = get_risk_assessment(scope, sources, historical=historical)
    if not read.found:
        store.append_audit(
            scope.bridge_id, scope.cycle_id, "ALERT_WITHHELD",
            f"no verdict found for scope; withheld ({WithheldReason.ASSESSMENT_NOT_FOUND.value})",
        )
        return DispatchSummary(
            ok=False, outcome=AlertOutcome.WITHHELD,
            withheld_reason=WithheldReason.ASSESSMENT_NOT_FOUND,
        )

    verdict = read.assessment
    ident = _Identity.of(verdict, now)
    severity_value = verdict.get("severity")

    # 2. Decide the tier (the settled severity->approval mapping).
    tier = decide_tier(verdict, policy)

    # 3. DASHBOARD_ONLY (SAFE): record the dashboard event, no push, closed.
    if tier.decision is DispatchDecision.DASHBOARD_ONLY:
        result = ident.dispatched(
            decision=DispatchDecision.DASHBOARD_ONLY,
            escalation_state=EscalationState.CLOSED,
        )
        persist_dispatch(store, result)
        return DispatchSummary.from_result(result)

    # 4. Assemble the message by COPYING the verdict (never re-judging).
    message = assemble(verdict, templates)

    # 5. Consistency gate (fail-closed): a message that contradicts the verdict is never dispatched.
    consistency = consistency_check(message, verdict)
    if not consistency.passed:
        result = ident.withheld(WithheldReason.CONSISTENCY_MISMATCH)
        persist_dispatch(store, result)
        return DispatchSummary.from_result(result)

    # 6. Approval gate — the single un-bypassable chokepoint. A gated dispatch without a recorded
    #    approval is HELD (nothing sent); the state is recorded either way.
    gate = approval_gate(tier.decision, approval=approval)
    if not gate.may_dispatch:
        result = ident.dispatched(
            decision=tier.decision,
            escalation_state=EscalationState.OPEN,   # held, awaiting the sign-off
            approval_state=gate.approval_state,
            approved_by=gate.approved_by,
        )
        persist_dispatch(store, result)
        return DispatchSummary.from_result(result)

    # 7. Dispatch: climb the escalation ladder (retry -> failover -> escalate), every attempt logged.
    plan = build_attempt_plan(policy, severity_value)
    ladder = run_send_ladder(
        plan=plan, notifier=notifier, retry_max=policy.retry_max, message=message.body,
    )
    accepted = ladder.accepted_attempt

    # 8. Reconcile delivery (out of band) + resolve the severity-dependent close.
    if accepted is None:
        # Whole chain failed to send: nothing accepted -> ESCALATED (needs a human), never silent.
        last = ladder.attempts[-1] if ladder.attempts else None
        result = ident.dispatched(
            decision=tier.decision,
            channel=last.channel if last else None,
            recipient=last.recipient if last else None,
            provider_message_id=last.provider_message_id if last else None,
            delivery_state=DeliveryState.FAILED if last else None,
            escalation_state=EscalationState.ESCALATED,
            approval_state=gate.approval_state,
            approved_by=gate.approved_by,
        )
        persist_dispatch(store, result)
        return DispatchSummary.from_result(result)

    delivery_state = notifier.state_of(accepted.provider_message_id) or accepted.state
    escalation_state, close_reason = resolve_escalation(
        severity_value=severity_value, accepted_state=delivery_state,
    )
    result = ident.dispatched(
        decision=tier.decision,
        channel=accepted.channel,
        recipient=accepted.recipient,
        provider_message_id=accepted.provider_message_id,
        delivery_state=delivery_state,
        escalation_state=escalation_state,
        close_reason=close_reason,
        approval_state=gate.approval_state,
        approved_by=gate.approved_by,
    )
    persist_dispatch(store, result)
    return DispatchSummary.from_result(result)


class _Identity:
    """The pinned verdict identity shared by every AlertResult this run builds (FR-11/FR-13)."""

    __slots__ = ("bridge_id", "cycle_id", "assessment_id", "assessment_version", "trace_id", "now")

    def __init__(self, bridge_id, cycle_id, assessment_id, assessment_version, trace_id, now):
        self.bridge_id = bridge_id
        self.cycle_id = cycle_id
        self.assessment_id = assessment_id
        self.assessment_version = assessment_version
        self.trace_id = trace_id
        self.now = now

    @classmethod
    def of(cls, verdict: dict, now: str) -> "_Identity":
        return cls(
            bridge_id=verdict["bridge_id"],
            cycle_id=verdict["cycle_id"],
            assessment_id=verdict["id"],
            assessment_version=verdict["assessment_version"],
            trace_id=verdict.get("trace_id", ""),
            now=now,
        )

    def dispatched(
        self,
        *,
        decision: DispatchDecision,
        channel: str | None = None,
        recipient: str | None = None,
        provider_message_id: str | None = None,
        delivery_state: DeliveryState | None = None,
        escalation_state: EscalationState,
        close_reason: DeliveryState | None = None,
        approval_state: ApprovalState | None = None,
        approved_by: str | None = None,
    ) -> AlertResult:
        return AlertResult(
            bridge_id=self.bridge_id, cycle_id=self.cycle_id,
            assessment_id=self.assessment_id, assessment_version=self.assessment_version,
            outcome=AlertOutcome.DISPATCHED, withheld_reason=None,
            dispatch_decision=decision,
            channel=channel, recipient=recipient, provider_message_id=provider_message_id,
            delivery_state=delivery_state, escalation_state=escalation_state,
            close_reason=close_reason,
            approval_state=approval_state, approved_by=approved_by,
            trace_id=self.trace_id, attempted_at=self.now,
        )

    def withheld(self, reason: WithheldReason) -> AlertResult:
        return AlertResult(
            bridge_id=self.bridge_id, cycle_id=self.cycle_id,
            assessment_id=self.assessment_id, assessment_version=self.assessment_version,
            outcome=AlertOutcome.WITHHELD, withheld_reason=reason,
            dispatch_decision=None,
            channel=None, recipient=None, provider_message_id=None,
            delivery_state=None, escalation_state=None, close_reason=None,
            approval_state=None, approved_by=None,
            trace_id=self.trace_id, attempted_at=self.now,
        )
