"""NotifierPort seam (A701) — the interface the service dispatches through [NOTIFY-DEP].

The service (A901) never calls a real email/SMS provider directly; it calls a NotifierPort. The
fake (A701) records each attempt for tests; the real provider (SMTP/SendGrid/SES, Twilio/SNS —
a build/plan decision) sends genuine messages and reconciles delivery via receipts/webhooks.
Because both implement this one shape, swapping the real provider in changes only the wire send,
never the control flow around it (tiering, consistency, approval, escalation).

A `send` returns a DispatchAttempt carrying the provider's message id + the INITIAL delivery state.
Per FR-7, that initial state is at most SENT (the provider accepted it) — never DELIVERED: delivery
is confirmed later, out of band, via a receipt/webhook (modelled by the fake's mark_* methods and,
in production, by callbacks that advance the row's delivery_state).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agents.alert_escalation.statuses import DeliveryState


@dataclass(frozen=True, slots=True)
class DispatchAttempt:
    """The result of one send: the provider's id + the initial delivery state (SENT or FAILED)."""

    provider_message_id: str
    state: DeliveryState


@runtime_checkable
class NotifierPort(Protocol):
    """Send one notification on a channel to a recipient, returning the initial dispatch attempt."""

    def send(self, *, channel: str, recipient: str, message: str) -> DispatchAttempt:
        ...
