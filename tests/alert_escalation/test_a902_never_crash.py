"""A902 — never-crash 4-scenario constitution set (FR-12, AC-11).

Acceptance gate over A901. The constitution requires that NO input crashes the alert service — every
scenario yields a structured DispatchSummary, never a stack trace — and that a provider outage is a
named ok=false failure, never a crash or a silently-dropped alert.

The four-scenario constitution set:
  1. normal            -> DISPATCHED (structured summary);
  2. missing verdict   -> WITHHELD/ASSESSMENT_NOT_FOUND;
  3. malformed scope    -> structured outcome (WITHHELD or ERROR), never a raise;
  4. provider outage   -> ERROR, ok=false, the failure NAMED, no silent drop.

No new production code — this proves A901's outer FR-12 guarantee is real and load-bearing.
"""
from __future__ import annotations

from agents.alert_escalation.service import AssessmentScope, run_alert
from agents.alert_escalation.config.alert_policy import AlertPolicy
from agents.alert_escalation.config.message_template_table import MessageTemplateTable
from agents.alert_escalation.dispatch.fake_notifier import FakeNotifier
from agents.alert_escalation.store import FakeAlertStore
from agents.alert_escalation.statuses import AlertOutcome, WithheldReason
from agents.risk_reasoning.statuses import Severity


NOW = "2026-07-13T00:00:00Z"


class _Source:
    def __init__(self, verdict, *, raise_on_read=False):
        self._verdict = verdict
        self._raise = raise_on_read

    def current_assessment_for(self, bridge_id, cycle_id):
        if self._raise:
            raise RuntimeError("db unreachable")
        return self._verdict

    def assessment_by_id(self, assessment_id):
        if self._raise:
            raise RuntimeError("db unreachable")
        return self._verdict


class _BoomNotifier:
    sent: list = []

    def send(self, **_):
        raise RuntimeError("provider outage")

    def state_of(self, _):
        return None


def _verdict(**over):
    base = dict(
        id=1001, bridge_id="bridge-7", cycle_id="cycle-42", assessment_version=3,
        risk_score=45, severity="WATCH", recommendation="Monitor.",
        explanation="Nominal drift.", review_status="FINAL", trace_id="trace-xyz",
    )
    base.update(over)
    return base


def _policy():
    return AlertPolicy(
        policy_version="rev1", retry_max=1, backoff_seconds=30, escalation_timeout_seconds=300,
        contact_roster=(("WATCH", "watch@gov"),),
        escalation_order=("watch@gov",),
        channel_per_band=(("WATCH", "email"),),
        authority_recipients=(),
    )


def _templates():
    body = "Bridge {bridge_id} {severity} ({risk_score}): {recommendation} — {explanation}"
    return MessageTemplateTable(templates=tuple((s, body) for s in Severity))


def _run(source, scope, *, notifier=None):
    return run_alert(
        scope, sources=source, store=FakeAlertStore(), policy=_policy(),
        templates=_templates(), notifier=notifier or FakeNotifier(deliver_on_send=("email",)),
        now=NOW,
    )


SCOPE = AssessmentScope("bridge-7", "cycle-42")


# ------------------------------------------------------------------ the four scenarios ---
def test_1_normal_is_structured_dispatched():
    s = _run(_Source(_verdict()), SCOPE)
    assert s.outcome is AlertOutcome.DISPATCHED


def test_2_missing_verdict_is_structured_withheld():
    s = _run(_Source(None), AssessmentScope("ghost", "none"))
    assert s.outcome is AlertOutcome.WITHHELD
    assert s.withheld_reason is WithheldReason.ASSESSMENT_NOT_FOUND
    assert s.ok is False


def test_3_malformed_scope_is_structured_never_raises():
    # A scope whose fields are None is malformed; the service must return structured, not raise.
    s = _run(_Source(None), AssessmentScope(None, None))  # type: ignore[arg-type]
    assert s.outcome in (AlertOutcome.WITHHELD, AlertOutcome.ERROR)
    assert s.ok is False


def test_4_provider_outage_is_named_error_not_a_crash_or_silent_drop():
    s = _run(_Source(_verdict()), SCOPE, notifier=_BoomNotifier())
    assert s.outcome is AlertOutcome.ERROR
    assert s.ok is False
    assert "provider outage" in (s.error or "")     # the failure is NAMED, not swallowed


def test_read_outage_is_named_error():
    s = _run(_Source(None, raise_on_read=True), SCOPE)
    assert s.outcome is AlertOutcome.ERROR
    assert "db unreachable" in (s.error or "")


def test_all_four_scenarios_return_a_summary_none_raise():
    scenarios = [
        (_Source(_verdict()), SCOPE, None),
        (_Source(None), AssessmentScope("ghost", "none"), None),
        (_Source(None), AssessmentScope(None, None), None),  # type: ignore[arg-type]
        (_Source(_verdict()), SCOPE, _BoomNotifier()),
    ]
    for source, scope, notifier in scenarios:
        summary = _run(source, scope, notifier=notifier)     # must not raise for ANY
        assert summary is not None
        assert summary.outcome in (
            AlertOutcome.DISPATCHED, AlertOutcome.WITHHELD, AlertOutcome.ERROR)


def test_provider_outage_audits_the_error_event():
    # A provider outage is still an audited event (something happened), never a silent drop.
    store = FakeAlertStore()
    run_alert(
        SCOPE, sources=_Source(_verdict()), store=store, policy=_policy(),
        templates=_templates(), notifier=_BoomNotifier(), now=NOW,
    )
    assert [a.decision for a in store.audit_rows] == ["ALERT_ERROR"]
