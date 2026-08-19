"""A702 — delivery state machine: SENT != DELIVERED != ACKNOWLEDGED (FR-7).

A dispatch advances QUEUED -> SENT -> DELIVERED, and ACKNOWLEDGED only on a recorded human ack;
FAILED is reachable from QUEUED/SENT. The three "good" states are DISTINCT and must never be
conflated — a provider accept (SENT) is not delivery, and delivery is not a human ack. This is the
pure transition guard the escalation ladder (A703) and the service (A901) build on; it rejects a
transition that would fake progress (e.g. jumping straight to DELIVERED on a send-accept).

Acceptance (tasks.md A702): a send-accept sets SENT, not DELIVERED; DELIVERED requires the receipt;
ACKNOWLEDGED requires an explicit ack; the three are distinct; an illegal jump is refused.
"""
from __future__ import annotations

import pytest

from agents.alert_escalation.delivery import advance, is_terminal, can_transition
from agents.alert_escalation.statuses import DeliveryState

Q = DeliveryState.QUEUED
S = DeliveryState.SENT
D = DeliveryState.DELIVERED
F = DeliveryState.FAILED
A = DeliveryState.ACKNOWLEDGED


def test_send_accept_is_sent_not_delivered():
    # The provider accepting a message is SENT — never DELIVERED (FR-7).
    assert advance(Q, S) is S
    assert S is not D


def test_delivered_requires_a_receipt_from_sent():
    assert advance(S, D) is D


def test_acknowledged_requires_delivered_first():
    assert advance(D, A) is A


def test_three_good_states_are_distinct():
    assert len({S, D, A}) == 3


def test_failed_is_reachable_from_queued_and_sent():
    assert advance(Q, F) is F
    assert advance(S, F) is F


# ------------------------------------------------------------------ illegal transitions ---
def test_cannot_jump_queued_straight_to_delivered():
    # No faking progress: DELIVERED must come through SENT, not straight off the queue.
    assert can_transition(Q, D) is False
    with pytest.raises(ValueError):
        advance(Q, D)


def test_cannot_acknowledge_before_delivered():
    assert can_transition(S, A) is False
    with pytest.raises(ValueError):
        advance(S, A)


def test_cannot_leave_a_terminal_failed_state_silently():
    # FAILED is terminal for that attempt; progress happens via a NEW attempt (failover), not by
    # mutating a failed one into delivered.
    assert can_transition(F, D) is False


def test_delivered_and_acknowledged_are_terminal_success():
    assert is_terminal(D) is True
    assert is_terminal(A) is True
    assert is_terminal(F) is True
    assert is_terminal(S) is False
    assert is_terminal(Q) is False


def test_idempotent_reassertion_of_same_state_is_allowed():
    # Re-reporting the current state (a duplicate webhook) is a no-op, not an error.
    assert advance(D, D) is D
    assert advance(S, S) is S
