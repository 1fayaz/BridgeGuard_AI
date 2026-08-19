"""A703 — escalation ladder: retry -> failover -> escalate; severity-dependent close (FR-6/FR-8).

Two concerns, cleanly separated because reality separates them:

  (1) The SEND LADDER (synchronous): the provider either accepts a send (SENT) or rejects it
      (FAILED). On a FAILED, retry the same channel up to the config retry_max; when a channel is
      exhausted, move to the next (channel, recipient) in the plan — that step is the failover /
      escalate-to-next-contact. EVERY send is a recorded attempt; no failure is silent.

  (2) The CLOSE (out of band): after an attempt is accepted, delivery + ack arrive later via
      receipt/webhook (the fake's mark_delivered / mark_acknowledged). The close condition is
      severity-dependent (FR-6): SAFE/WATCH close on DELIVERED; WARNING/CRITICAL are NOT closed by
      delivery alone — they stay OPEN/ESCALATED until a recorded human ACK.

Honesty constraints carried from the plan:
  * retry_max / backoff / escalation_timeout are TODO config — the ladder must REFUSE to run on an
    unset retry_max, never guess one (a wrong retry count on a Critical alert is a safety failure).
  * build_attempt_plan must REFUSE to fabricate a routing chain from an unconfigured policy.
The ladder LOGIC is exercised with an explicit plan (simulating configured routing) over the fake.

Acceptance (tasks.md A703): primary FAILED -> retry -> failover -> escalate to next contact, each
logged; SAFE/WATCH CLOSED on DELIVERED; WARNING/CRITICAL NOT closed by DELIVERED alone, stays
OPEN/ESCALATED until ACK then CLOSED; no failure silent. = FR-6/FR-8, AC-5/AC-7.
"""
from __future__ import annotations

import pytest

from agents.alert_escalation.escalation import (
    close_condition_for,
    build_attempt_plan,
    run_send_ladder,
    resolve_escalation,
)
from agents.alert_escalation.config.alert_policy import AlertPolicy
from agents.alert_escalation.dispatch.fake_notifier import FakeNotifier
from agents.alert_escalation.statuses import DeliveryState, EscalationState
from agents.risk_reasoning.statuses import Severity


# ------------------------------------------------------------------ close condition (FR-6) ---
def test_safe_and_watch_close_on_delivered():
    assert close_condition_for(Severity.SAFE.value) is DeliveryState.DELIVERED
    assert close_condition_for(Severity.WATCH.value) is DeliveryState.DELIVERED


def test_warning_and_critical_close_only_on_ack():
    assert close_condition_for(Severity.WARNING.value) is DeliveryState.ACKNOWLEDGED
    assert close_condition_for(Severity.CRITICAL.value) is DeliveryState.ACKNOWLEDGED


def test_withheld_score_verdict_requires_ack_to_close():
    # No band => treat as high: a human must acknowledge it, delivery alone never closes it.
    assert close_condition_for(None) is DeliveryState.ACKNOWLEDGED


# ------------------------------------------------------------------ plan refuses to guess ---
def test_build_attempt_plan_refuses_on_unconfigured_policy():
    # No roster / channels / escalation order supplied: the ladder must not invent a routing chain.
    p = AlertPolicy(policy_version="v0-unset")
    with pytest.raises(ValueError):
        build_attempt_plan(p, Severity.WARNING.value)


def test_build_attempt_plan_uses_config_when_supplied():
    p = AlertPolicy(
        policy_version="rev1",
        retry_max=1,
        backoff_seconds=30,
        escalation_timeout_seconds=300,
        contact_roster=(("WARNING", "engineer@gov"),),
        escalation_order=("engineer@gov", "oncall@gov"),
        channel_per_band=(("WARNING", "email"),),
        authority_recipients=(),
    )
    plan = build_attempt_plan(p, Severity.WARNING.value)
    # One entry per contact in the escalation order, each on the band channel.
    assert plan == (("email", "engineer@gov"), ("email", "oncall@gov"))


# ------------------------------------------------------------------ retry_max refuses TODO ---
def test_run_send_ladder_refuses_on_todo_retry_max():
    n = FakeNotifier()
    plan = (("email", "engineer@gov"),)
    with pytest.raises(ValueError):
        run_send_ladder(plan=plan, notifier=n, retry_max=float("nan"), message="m")


# ------------------------------------------------------------------ the ladder itself ---
def test_first_channel_accepted_stops_the_ladder():
    n = FakeNotifier()
    plan = (("email", "a@gov"), ("sms", "b@gov"))
    outcome = run_send_ladder(plan=plan, notifier=n, retry_max=2, message="m")
    assert len(outcome.attempts) == 1                       # stopped at first accept
    assert outcome.attempts[0].state is DeliveryState.SENT
    assert outcome.accepted_attempt is not None
    assert outcome.accepted_attempt.channel == "email"


def test_retry_then_failover_then_escalate_each_logged():
    # email fails (retried), sms fails (retried), phone accepted. Every send is a recorded attempt.
    n = FakeNotifier(failing_channels=("email", "sms"))
    plan = (("email", "a@gov"), ("sms", "a@gov"), ("phone", "oncall@gov"))
    outcome = run_send_ladder(plan=plan, notifier=n, retry_max=1, message="m")

    # retry_max=1 => 2 sends per failing channel, then 1 accepted on phone = 2 + 2 + 1 = 5 attempts.
    assert len(outcome.attempts) == 5
    channels = [a.channel for a in outcome.attempts]
    assert channels == ["email", "email", "sms", "sms", "phone"]
    # every email/sms attempt FAILED (logged, not silent); phone SENT and accepted.
    assert [a.state for a in outcome.attempts[:4]] == [DeliveryState.FAILED] * 4
    assert outcome.attempts[4].state is DeliveryState.SENT
    assert outcome.accepted_attempt.channel == "phone"
    assert outcome.accepted_attempt.recipient == "oncall@gov"


def test_whole_chain_failing_leaves_no_accepted_attempt_but_logs_all():
    n = FakeNotifier(failing_channels=("email", "sms"))
    plan = (("email", "a@gov"), ("sms", "b@gov"))
    outcome = run_send_ladder(plan=plan, notifier=n, retry_max=0, message="m")
    assert len(outcome.attempts) == 2                       # retry_max=0 => one send each
    assert all(a.state is DeliveryState.FAILED for a in outcome.attempts)
    assert outcome.accepted_attempt is None                 # nothing accepted


# ------------------------------------------------------------------ severity-dependent close ---
def test_safe_watch_closed_on_delivered():
    # SAFE/WATCH: a DELIVERED receipt closes the escalation.
    state, reason = resolve_escalation(
        severity_value=Severity.WATCH.value, accepted_state=DeliveryState.DELIVERED
    )
    assert state is EscalationState.CLOSED
    assert reason is DeliveryState.DELIVERED


def test_watch_delivered_not_yet_delivered_stays_open():
    state, reason = resolve_escalation(
        severity_value=Severity.WATCH.value, accepted_state=DeliveryState.SENT
    )
    assert state is EscalationState.OPEN
    assert reason is None


def test_warning_not_closed_by_delivered_alone():
    # The core FR-6 assertion: delivery is NOT acknowledgement for WARNING/CRITICAL.
    state, reason = resolve_escalation(
        severity_value=Severity.WARNING.value, accepted_state=DeliveryState.DELIVERED
    )
    assert state is EscalationState.OPEN
    assert reason is None


def test_warning_closed_only_on_ack():
    state, reason = resolve_escalation(
        severity_value=Severity.WARNING.value, accepted_state=DeliveryState.ACKNOWLEDGED
    )
    assert state is EscalationState.CLOSED
    assert reason is DeliveryState.ACKNOWLEDGED


def test_nothing_accepted_is_escalated_not_closed():
    # Exhausted the chain with no accept: ESCALATED (unresolved, needs a human), never silently CLOSED.
    state, reason = resolve_escalation(
        severity_value=Severity.CRITICAL.value, accepted_state=None
    )
    assert state is EscalationState.ESCALATED
    assert reason is None


def test_failed_accepted_state_is_escalated():
    state, reason = resolve_escalation(
        severity_value=Severity.WARNING.value, accepted_state=DeliveryState.FAILED
    )
    assert state is EscalationState.ESCALATED
    assert reason is None


# ------------------------------------------------------------------ end-to-end over the fake ---
def test_warning_delivered_then_acked_closes():
    # Full FR-6 lifecycle over the fake: send accepted (SENT) -> delivered receipt -> stays OPEN ->
    # human ack -> CLOSED.
    n = FakeNotifier()
    plan = (("email", "engineer@gov"),)
    outcome = run_send_ladder(plan=plan, notifier=n, retry_max=1, message="Bridge 12 WARNING")
    pid = outcome.accepted_attempt.provider_message_id

    n.mark_delivered(pid)
    state, _ = resolve_escalation(
        severity_value=Severity.WARNING.value, accepted_state=n.state_of(pid)
    )
    assert state is EscalationState.OPEN            # delivered but not acked -> still open

    n.mark_acknowledged(pid)
    state, reason = resolve_escalation(
        severity_value=Severity.WARNING.value, accepted_state=n.state_of(pid)
    )
    assert state is EscalationState.CLOSED
    assert reason is DeliveryState.ACKNOWLEDGED
