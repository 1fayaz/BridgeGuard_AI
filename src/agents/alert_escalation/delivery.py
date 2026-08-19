"""Delivery state machine (A702) — SENT != DELIVERED != ACKNOWLEDGED (FR-7).

A single dispatch attempt advances through a small, guarded state graph. The point of this module
is to make the three "good" states genuinely distinct and to REFUSE a transition that would fake
progress — e.g. jumping QUEUED straight to DELIVERED on a bare send-accept, or ACKNOWLEDGED before
a delivery receipt. The escalation ladder (A703) and the service (A901) advance delivery state only
through here, so no code path can silently conflate "provider accepted" with "a human saw it".

Legal transitions:
  QUEUED     -> SENT | FAILED
  SENT       -> DELIVERED | FAILED
  DELIVERED  -> ACKNOWLEDGED
  (any state -> itself: idempotent re-report of a duplicate receipt/webhook)

DELIVERED, ACKNOWLEDGED, and FAILED are terminal for that attempt; further progress after a FAILED
happens via a NEW attempt (failover), never by mutating the failed one. Pure functions; no I/O.
"""
from __future__ import annotations

from agents.alert_escalation.statuses import DeliveryState

_LEGAL: dict[DeliveryState, frozenset[DeliveryState]] = {
    DeliveryState.QUEUED: frozenset({DeliveryState.SENT, DeliveryState.FAILED}),
    DeliveryState.SENT: frozenset({DeliveryState.DELIVERED, DeliveryState.FAILED}),
    DeliveryState.DELIVERED: frozenset({DeliveryState.ACKNOWLEDGED}),
    DeliveryState.FAILED: frozenset(),
    DeliveryState.ACKNOWLEDGED: frozenset(),
}

_TERMINAL = frozenset(
    {DeliveryState.DELIVERED, DeliveryState.ACKNOWLEDGED, DeliveryState.FAILED}
)


def can_transition(current: DeliveryState, target: DeliveryState) -> bool:
    """True if `current -> target` is a legal delivery transition (or an idempotent no-op)."""
    if current is target:
        return True
    return target in _LEGAL[current]


def advance(current: DeliveryState, target: DeliveryState) -> DeliveryState:
    """Return `target` if the transition is legal, else raise (no faking progress, FR-7)."""
    if not can_transition(current, target):
        raise ValueError(
            f"illegal delivery transition {current.value} -> {target.value} "
            f"(a send-accept is not delivery; delivery is not an ack — FR-7)"
        )
    return target


def is_terminal(state: DeliveryState) -> bool:
    """True if the state ends this attempt's lifecycle (DELIVERED, ACKNOWLEDGED, or FAILED)."""
    return state in _TERMINAL
