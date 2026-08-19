"""FakeNotifier (A701) — deterministic NotifierPort stub for tests [NOTIFY-DEP].

Stands in for the real email/SMS provider so the escalation state machine, persistence, and service
phases are testable without a live provider. It records the exact (channel, recipient, message) of
each send and returns a deterministic, index-derived provider id (no clock, no randomness, so a
scenario replays identically). A test drives the out-of-band transitions a real delivery
receipt / webhook / human ack would report, via mark_delivered / mark_failed / mark_acknowledged.

Same `send` shape as the real provider, so swapping the real one in changes only the wire send.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.alert_escalation.dispatch.port import DispatchAttempt
from agents.alert_escalation.statuses import DeliveryState


@dataclass(frozen=True, slots=True)
class _SentRecord:
    channel: str
    recipient: str
    message: str
    provider_message_id: str


@dataclass
class FakeNotifier:
    """Deterministic notifier stand-in. Records each send; a test drives delivery/ack transitions.

    `failing_channels` lets a test arrange a channel to FAIL on send (to exercise the
    retry -> failover path in A703). Everything is index-derived and in-memory — no clock/random.
    """

    failing_channels: tuple[str, ...] = ()
    # Channels whose out-of-band receipt/ack has "already arrived" by reconciliation time. The SEND
    # still returns SENT (FR-7: a send-accept is never delivery); these only advance the STORED
    # state, so a service reconciling via state_of() sees DELIVERED / ACKNOWLEDGED — modelling a
    # receipt/webhook/ack that landed between dispatch and the reconciliation read.
    deliver_on_send: tuple[str, ...] = ()
    ack_on_send: tuple[str, ...] = ()
    sent: list[_SentRecord] = field(default_factory=list)
    _states: dict[str, DeliveryState] = field(default_factory=dict)

    def send(self, *, channel: str, recipient: str, message: str) -> DispatchAttempt:
        # Deterministic id from the send index — replayable across fresh fakes.
        pid = f"fake-msg-{len(self.sent)}"
        self.sent.append(_SentRecord(channel, recipient, message, pid))
        # A preconfigured failing channel reports FAILED on send; otherwise the provider accepts it
        # (SENT) — NOT delivered: delivery is confirmed later via mark_delivered (FR-7).
        state = DeliveryState.FAILED if channel in self.failing_channels else DeliveryState.SENT
        # The RETURNED attempt is always the true send state (SENT/FAILED). A simulated out-of-band
        # receipt/ack advances only the stored state a later reconciliation read observes.
        stored = state
        if state is DeliveryState.SENT:
            if channel in self.ack_on_send:
                stored = DeliveryState.ACKNOWLEDGED
            elif channel in self.deliver_on_send:
                stored = DeliveryState.DELIVERED
        self._states[pid] = stored
        return DispatchAttempt(provider_message_id=pid, state=state)

    # --- out-of-band transitions a real receipt/webhook/ack would drive ---
    def mark_delivered(self, provider_message_id: str) -> DeliveryState:
        self._states[provider_message_id] = DeliveryState.DELIVERED
        return DeliveryState.DELIVERED

    def mark_failed(self, provider_message_id: str) -> DeliveryState:
        self._states[provider_message_id] = DeliveryState.FAILED
        return DeliveryState.FAILED

    def mark_acknowledged(self, provider_message_id: str) -> DeliveryState:
        self._states[provider_message_id] = DeliveryState.ACKNOWLEDGED
        return DeliveryState.ACKNOWLEDGED

    def state_of(self, provider_message_id: str) -> DeliveryState | None:
        return self._states.get(provider_message_id)
