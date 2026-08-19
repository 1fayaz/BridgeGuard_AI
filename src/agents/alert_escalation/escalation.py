"""Escalation ladder (A703) — retry -> failover -> escalate; severity-dependent close (FR-6/FR-8).

Two deterministic concerns, separated because delivery reality separates them:

  (1) The SEND LADDER (`run_send_ladder`, synchronous): walk an ordered attempt plan of
      (channel, recipient) steps. On each step the provider either accepts the send (SENT) or
      rejects it (FAILED). A FAILED step is retried on the SAME channel up to `retry_max` extra
      times (so 1 + retry_max sends per step); when a step is exhausted, move to the NEXT step —
      that move is the failover / escalate-to-next-contact. EVERY send is recorded as an attempt,
      so no failure is silent (FR-8). The first accepted send stops the ladder.

  (2) The CLOSE (`resolve_escalation`, out of band): once a send is accepted, delivery and human
      acknowledgement arrive later via receipt/webhook. The close condition is severity-dependent
      (FR-6): SAFE/WATCH close on DELIVERED; WARNING/CRITICAL (and a withheld-score verdict) are
      NOT closed by delivery alone — they stay OPEN/ESCALATED until a recorded human ACK.

Honesty (plan Open Items): `retry_max`, backoff, and the escalation timeout are TODO config. This
module REFUSES to run on an unset `retry_max` and REFUSES to fabricate an attempt plan from an
unconfigured policy — it never guesses a safety-critical routing chain or retry count. Backoff /
timeout are carried by the config and consumed by the live scheduler (n8n / real notifier); the
in-memory ladder is deterministic and clock-free, so there is nothing to sleep on here.

Pure logic + calls through the injected NotifierPort. No model, no I/O of its own.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from agents.alert_escalation.config.alert_policy import AlertPolicy
from agents.alert_escalation.dispatch.port import NotifierPort
from agents.alert_escalation.statuses import DeliveryState, EscalationState
from agents.risk_reasoning.statuses import Severity

# Bands whose alerts a human must acknowledge — delivery alone never closes them (FR-6).
_ACK_REQUIRED_BANDS = frozenset({Severity.WARNING.value, Severity.CRITICAL.value})


@dataclass(frozen=True, slots=True)
class LadderAttempt:
    """One recorded send attempt: which (channel, recipient), the provider id, and the state."""

    channel: str
    recipient: str
    provider_message_id: str
    state: DeliveryState


@dataclass(frozen=True, slots=True)
class LadderOutcome:
    """The result of walking the send ladder: every attempt (logged) + the accepted one, if any."""

    attempts: tuple[LadderAttempt, ...]
    accepted_attempt: LadderAttempt | None


def close_condition_for(severity_value: str | None) -> DeliveryState:
    """The delivery state that closes an escalation for this band (FR-6).

    SAFE/WATCH close on DELIVERED. WARNING/CRITICAL — and a withheld-score verdict with no band —
    require a human ACKNOWLEDGED; a delivery receipt alone is never enough.
    """
    if severity_value is None or severity_value in _ACK_REQUIRED_BANDS:
        return DeliveryState.ACKNOWLEDGED
    return DeliveryState.DELIVERED


def build_attempt_plan(policy: AlertPolicy, severity_value: str) -> tuple[tuple[str, str], ...]:
    """Build the ordered (channel, recipient) attempt plan for a band from config (FR-8).

    The channel is the band's configured channel; the recipients are the configured escalation
    order (primary contact first, then the failover/on-call chain). REFUSES to run if the policy is
    unconfigured — we do not invent a routing chain for a safety-critical alert.
    """
    if policy.channels_are_todo or policy.roster_is_todo:
        raise ValueError(
            "cannot build an attempt plan from an unconfigured policy: the per-band channel and "
            "the escalation order are TODO — supply them, do not guess a routing chain (FR-8)"
        )
    channel = policy.channel_for(severity_value)
    if channel is None:
        raise ValueError(f"no channel configured for band {severity_value!r} (FR-8)")
    order = policy.escalation_order or ()
    if not order:
        raise ValueError("escalation order is empty; supply the on-call chain (FR-8)")
    return tuple((channel, recipient) for recipient in order)


def run_send_ladder(
    *,
    plan: tuple[tuple[str, str], ...],
    notifier: NotifierPort,
    retry_max: float,
    message: str,
) -> LadderOutcome:
    """Walk the attempt plan: retry a failing channel, then fail over to the next contact (FR-8).

    Each plan step is tried up to (1 + retry_max) times; a step that keeps FAILING escalates to the
    next step. The first accepted send (SENT) stops the ladder. Every send — success or failure —
    is recorded in `attempts`, so no failure is silent. REFUSES to run on a TODO retry_max.
    """
    if isinstance(retry_max, float) and math.isnan(retry_max):
        raise ValueError(
            "retry_max is TODO (unset): the retry count is a safety-critical policy value and "
            "must be supplied, not guessed (FR-8)"
        )
    tries_per_step = 1 + int(retry_max)

    attempts: list[LadderAttempt] = []
    accepted: LadderAttempt | None = None
    for channel, recipient in plan:
        for _ in range(tries_per_step):
            sent = notifier.send(channel=channel, recipient=recipient, message=message)
            attempt = LadderAttempt(
                channel=channel,
                recipient=recipient,
                provider_message_id=sent.provider_message_id,
                state=sent.state,
            )
            attempts.append(attempt)
            if sent.state is not DeliveryState.FAILED:
                accepted = attempt
                break
        if accepted is not None:
            break
    return LadderOutcome(attempts=tuple(attempts), accepted_attempt=accepted)


def resolve_escalation(
    *, severity_value: str | None, accepted_state: DeliveryState | None
) -> tuple[EscalationState, DeliveryState | None]:
    """Resolve escalation state from the accepted attempt's current delivery state (FR-6).

    Returns (escalation_state, close_reason). The escalation CLOSES only when the accepted send has
    reached this band's close condition (DELIVERED for SAFE/WATCH, ACKNOWLEDGED for WARNING/
    CRITICAL). A still-progressing accepted send stays OPEN. Nothing accepted — or an accepted send
    that FAILED — is ESCALATED (unresolved, needs a human), never silently CLOSED.
    """
    if accepted_state is None or accepted_state is DeliveryState.FAILED:
        return EscalationState.ESCALATED, None

    needed = close_condition_for(severity_value)
    if accepted_state is needed:
        return EscalationState.CLOSED, needed
    # ACKNOWLEDGED satisfies a DELIVERED close condition too (it is strictly past delivery).
    if needed is DeliveryState.DELIVERED and accepted_state is DeliveryState.ACKNOWLEDGED:
        return EscalationState.CLOSED, DeliveryState.DELIVERED
    return EscalationState.OPEN, None
