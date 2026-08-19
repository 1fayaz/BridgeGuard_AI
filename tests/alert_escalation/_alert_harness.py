"""Shared E2E scenario harness for the Alert & Escalation Agent (A1101).

Underscore-prefixed so pytest does NOT collect it, but it is sibling-importable from the test
modules (prepend import mode), like the Report build's tests/report_generation/_report_harness.py.
Named `_alert_harness` (NOT `_harness` / `_report_harness`) to avoid a sys.modules name collision
with the Risk and Report suites' same-named helpers under prepend import mode — none of these suites
have __init__.py, so a shared module name would let whichever imports first win.

It scripts every alert scenario through the REAL service (run_alert) over a fake store + fake
notifier, so A1101 (this file's catalog) and A1102 (the AC assertions) drive one shared,
deterministic, replayable set of inputs:

  SAFE            a routine assessment                  -> DASHBOARD_ONLY, no push, closed
  WATCH_FINAL     a watch/final assessment              -> AUTO_FIRE, delivered, closed on DELIVERED
  WARNING_ACK     a warning, approved, then acked       -> NEEDS_APPROVAL, dispatched, closed on ACK
  WARNING_HELD    a warning with no approval             -> NEEDS_APPROVAL, held, no push (not ok)
  CRITICAL_PEND   a critical + pending verdict          -> NEEDS_APPROVAL, gated both axes, no push
  AUTHORITY_WATCH a watch to an authority recipient     -> NEEDS_APPROVAL (blast-radius override)
  CONTRADICTION   a mislabeled message vs the verdict   -> WITHHELD/CONSISTENCY_MISMATCH, no push
  CHANNEL_FAIL    the primary channel fails on send     -> failover to the next contact, escalated
  REDELIVERY      the same verdict version dispatched 2x -> idempotent, one current row
  SUPERSEDE       a newer verdict version dispatched     -> supersedes, both versions retained
  MALFORMED       a scope with None fields              -> structured (never raises)

Determinism is structural — no clock, no randomness (`now` is a fixed seam, the fake's provider ids
are index-derived) — so replaying the catalog twice yields identical summaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from agents.alert_escalation.config.alert_policy import AlertPolicy
from agents.alert_escalation.config.message_template_table import MessageTemplateTable
from agents.alert_escalation.dispatch.fake_notifier import FakeNotifier
from agents.alert_escalation.message import AssembledMessage
from agents.alert_escalation.alert_result import DispatchSummary
from agents.alert_escalation.service import AssessmentScope, run_alert
from agents.alert_escalation.store import FakeAlertStore
from agents.alert_escalation.statuses import AlertOutcome, DispatchDecision, WithheldReason
from agents.risk_reasoning.statuses import Severity

NOW = "2026-07-13T00:00:00Z"  # fixed seam — no clock in the harness

_BODY = "Bridge {bridge_id} {severity} (score {risk_score}): {recommendation} — {explanation}"

TEMPLATES = MessageTemplateTable(templates=tuple((s, _BODY) for s in Severity))

POLICY = AlertPolicy(
    policy_version="2026-07-alert-policy-rev1",
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
    authority_recipients=(),   # reviewed-empty: no recipient is authority-facing by default
)

# A variant policy where WATCH's roster recipient IS authority-facing — drives the AUTHORITY_WATCH
# blast-radius override (FR-3) without changing any other scenario's routing.
POLICY_AUTHORITY = AlertPolicy(
    policy_version="2026-07-alert-policy-rev1-authority",
    retry_max=POLICY.retry_max,
    backoff_seconds=POLICY.backoff_seconds,
    escalation_timeout_seconds=POLICY.escalation_timeout_seconds,
    contact_roster=POLICY.contact_roster,
    escalation_order=POLICY.escalation_order,
    channel_per_band=POLICY.channel_per_band,
    authority_recipients=("watch@gov",),
)

SCENARIO_NAMES = (
    "SAFE", "WATCH_FINAL", "WARNING_ACK", "WARNING_HELD", "CRITICAL_PEND",
    "AUTHORITY_WATCH", "CONTRADICTION", "CHANNEL_FAIL", "REDELIVERY", "SUPERSEDE", "MALFORMED",
)


# --- Fake source exposing the read protocol. ---------------------------------------------------
class HarnessSource:
    """A minimal AssessmentSource: current + historical reads over a fixed set of verdicts."""

    def __init__(self, verdicts: list[dict]):
        self._verdicts = [dict(v) for v in verdicts]

    def current_assessment_for(self, bridge_id, cycle_id):
        for v in self._verdicts:
            if (v["bridge_id"] == bridge_id and v["cycle_id"] == cycle_id
                    and v.get("superseded_by") is None):
                return dict(v)
        return None

    def assessment_by_id(self, assessment_id):
        for v in self._verdicts:
            if v["id"] == assessment_id:
                return dict(v)
        return None


def _verdict(**over):
    base = dict(
        id=1001, bridge_id="b", cycle_id="c", assessment_version=3,
        risk_score=48, severity="WARNING", review_status="FINAL",
        recommendation="Schedule inspection.",
        explanation="Deflection ratio elevated at pier 3.",
        trace_id="trace-xyz", superseded_by=None,
    )
    base.update(over)
    return base


def _mislabel_assemble(verdict, templates) -> AssembledMessage:
    """A buggy assembler that mislabels the band — used only by CONTRADICTION to trip the gate."""
    return AssembledMessage(
        band="SAFE",                       # contradicts the WARNING verdict
        risk_score=verdict.get("risk_score"),
        recommendation=verdict["recommendation"],
        explanation=verdict["explanation"],
        review_status=verdict["review_status"],
        body="mislabeled",
        sources={},
    )


@dataclass(frozen=True, slots=True)
class Expectation:
    outcome: AlertOutcome
    dispatch_decision: DispatchDecision | None = None
    withheld_reason: WithheldReason | None = None
    ok: bool = False
    pushed: bool = True          # whether an outbound send is expected (notifier.sent non-empty)
    escalated: bool = False


@dataclass(frozen=True, slots=True)
class ScenarioCase:
    name: str
    verdicts: tuple
    scope: AssessmentScope
    expectation: Expectation
    approval: tuple | None = None
    failing_channels: tuple = ()
    deliver_on_send: tuple = ()
    ack_on_send: tuple = ()
    assemble: Callable | None = None
    historical: bool = False
    policy: AlertPolicy | None = None    # per-case policy override (defaults to POLICY)
    # optional pre-steps: (scope, approval) pairs run before the main step (redelivery/supersede).
    presteps: tuple = ()


def all_cases() -> list[ScenarioCase]:
    """Build the full scenario catalog. Each is independent (its own verdicts/config)."""
    cases: list[ScenarioCase] = []

    cases.append(ScenarioCase(
        "SAFE", (_verdict(severity="SAFE", risk_score=10, review_status="FINAL"),),
        AssessmentScope("b", "c"),
        Expectation(AlertOutcome.DISPATCHED, DispatchDecision.DASHBOARD_ONLY, ok=True, pushed=False)))

    cases.append(ScenarioCase(
        "WATCH_FINAL", (_verdict(severity="WATCH", risk_score=45, review_status="FINAL"),),
        AssessmentScope("b", "c"),
        Expectation(AlertOutcome.DISPATCHED, DispatchDecision.AUTO_FIRE, ok=True, pushed=True),
        deliver_on_send=("email",)))

    cases.append(ScenarioCase(
        "WARNING_ACK", (_verdict(severity="WARNING", review_status="FINAL"),),
        AssessmentScope("b", "c"),
        Expectation(AlertOutcome.DISPATCHED, DispatchDecision.NEEDS_APPROVAL, ok=True, pushed=True),
        approval=("APPROVED", "reviewer@gov"), ack_on_send=("email",)))

    cases.append(ScenarioCase(
        "WARNING_HELD", (_verdict(severity="WARNING", review_status="FINAL"),),
        AssessmentScope("b", "c"),
        Expectation(AlertOutcome.DISPATCHED, DispatchDecision.NEEDS_APPROVAL, ok=False, pushed=False),
        approval=None))

    cases.append(ScenarioCase(
        "CRITICAL_PEND",
        (_verdict(severity="CRITICAL", risk_score=90, review_status="PENDING_HUMAN_REVIEW"),),
        AssessmentScope("b", "c"),
        Expectation(AlertOutcome.DISPATCHED, DispatchDecision.NEEDS_APPROVAL, ok=False, pushed=False),
        approval=None))

    cases.append(ScenarioCase(
        "AUTHORITY_WATCH", (_verdict(severity="WATCH", risk_score=45, review_status="FINAL"),),
        AssessmentScope("b", "c"),
        # WATCH would auto-fire, but its recipient (watch@gov) is authority-facing -> NEEDS_APPROVAL.
        Expectation(AlertOutcome.DISPATCHED, DispatchDecision.NEEDS_APPROVAL, ok=False, pushed=False),
        approval=None, policy=POLICY_AUTHORITY))

    cases.append(ScenarioCase(
        "CONTRADICTION", (_verdict(severity="WARNING", review_status="FINAL"),),
        AssessmentScope("b", "c"),
        Expectation(AlertOutcome.WITHHELD, None,
                    withheld_reason=WithheldReason.CONSISTENCY_MISMATCH, ok=False, pushed=False),
        approval=("APPROVED", "reviewer@gov"), assemble=_mislabel_assemble))

    cases.append(ScenarioCase(
        "CHANNEL_FAIL", (_verdict(severity="WARNING", review_status="FINAL"),),
        AssessmentScope("b", "c"),
        # primary email fails on every try -> failover to the next contact (also email) fails ->
        # nothing accepted -> escalated. A dispatched-but-escalated outcome (not ok).
        Expectation(AlertOutcome.DISPATCHED, DispatchDecision.NEEDS_APPROVAL, ok=False,
                    pushed=True, escalated=True),
        approval=("APPROVED", "reviewer@gov"), failing_channels=("email",)))

    cases.append(ScenarioCase(
        "REDELIVERY", (_verdict(severity="WATCH", risk_score=45, review_status="FINAL"),),
        AssessmentScope("b", "c"),
        Expectation(AlertOutcome.DISPATCHED, DispatchDecision.AUTO_FIRE, ok=True, pushed=True),
        deliver_on_send=("email",),
        presteps=((AssessmentScope("b", "c"), None),)))  # deliver once before

    cases.append(ScenarioCase(
        "SUPERSEDE",
        (_verdict(severity="WATCH", risk_score=45, review_status="FINAL", assessment_version=4),),
        AssessmentScope("b", "c"),
        Expectation(AlertOutcome.DISPATCHED, DispatchDecision.AUTO_FIRE, ok=True, pushed=True),
        deliver_on_send=("email",)))

    cases.append(ScenarioCase(
        "MALFORMED", (_verdict(),),
        AssessmentScope(None, None),  # type: ignore[arg-type]
        Expectation(AlertOutcome.WITHHELD, None,
                    withheld_reason=WithheldReason.ASSESSMENT_NOT_FOUND, ok=False, pushed=False)))

    return cases


def run_case(
    case: ScenarioCase,
    store: FakeAlertStore | None = None,
    notifier: FakeNotifier | None = None,
) -> DispatchSummary:
    """Drive one scenario through the REAL service. Returns the (final) summary. Never raises."""
    store = store if store is not None else FakeAlertStore()
    notifier = notifier if notifier is not None else FakeNotifier(
        failing_channels=case.failing_channels,
        deliver_on_send=case.deliver_on_send,
        ack_on_send=case.ack_on_send,
    )
    source = HarnessSource(list(case.verdicts))
    policy = case.policy if case.policy is not None else POLICY
    kwargs: dict[str, Any] = {}
    if case.assemble is not None:
        kwargs["assemble"] = case.assemble
    for scope, approval in case.presteps:
        run_alert(scope, sources=source, store=store, policy=policy, templates=TEMPLATES,
                  notifier=notifier, now=NOW, approval=approval, **kwargs)
    return run_alert(case.scope, sources=source, store=store, policy=policy, templates=TEMPLATES,
                     notifier=notifier, now=NOW, approval=case.approval,
                     historical=case.historical, **kwargs)


def summary_fingerprint(summary: DispatchSummary) -> tuple:
    """A hashable fingerprint of a summary, for determinism comparison."""
    return (
        summary.ok, summary.outcome.value,
        summary.dispatch_decision.value if summary.dispatch_decision else None,
        tuple(summary.delivered_channels), tuple(summary.failed_channels),
        summary.escalated,
        summary.withheld_reason.value if summary.withheld_reason else None,
        summary.error,
    )
