"""A701 — NotifierPort seam + FakeNotifier (deterministic stub) [NOTIFY-DEP].

The service (A901) never calls a real email/SMS provider directly; it calls a NotifierPort. The
fake records each dispatch attempt and lets a test drive DELIVERED / FAILED / ACKNOWLEDGED
transitions, so Phases 4-9 are testable without a live provider. Because the real provider will
implement this one shape, swapping it in changes only the wire send, not the control flow
(tiering / consistency / approval / escalation).

Acceptance (tasks.md A701): the fake records the exact (channel, recipient, message) handed to it
and returns a stable id + an initial SENT/QUEUED state; a test can drive it to DELIVERED, FAILED,
or ACKNOWLEDGED; the port is a runtime-checkable Protocol the fake satisfies.
"""
from __future__ import annotations

from agents.alert_escalation.dispatch.port import DispatchAttempt, NotifierPort
from agents.alert_escalation.dispatch.fake_notifier import FakeNotifier
from agents.alert_escalation.statuses import DeliveryState


def test_fake_satisfies_the_notifier_port_protocol():
    assert isinstance(FakeNotifier(), NotifierPort)


def test_send_records_the_exact_attempt():
    n = FakeNotifier()
    attempt = n.send(channel="email", recipient="engineer@gov", message="WARNING: pier 3")
    assert isinstance(attempt, DispatchAttempt)
    assert len(n.sent) == 1
    rec = n.sent[0]
    assert (rec.channel, rec.recipient, rec.message) == ("email", "engineer@gov", "WARNING: pier 3")


def test_send_returns_a_stable_provider_id_and_initial_state():
    n = FakeNotifier()
    a = n.send(channel="sms", recipient="+100", message="CRITICAL")
    assert a.provider_message_id  # a non-empty id
    assert a.state is DeliveryState.SENT  # accepted by the (fake) provider — NOT yet delivered


def test_provider_ids_are_unique_per_send():
    n = FakeNotifier()
    a = n.send(channel="email", recipient="a@gov", message="m1")
    b = n.send(channel="email", recipient="b@gov", message="m2")
    assert a.provider_message_id != b.provider_message_id


def test_ids_are_deterministic_no_clock_no_random():
    # Two fresh fakes given the same send sequence produce the same ids (index-derived, replayable).
    n1, n2 = FakeNotifier(), FakeNotifier()
    id1 = n1.send(channel="email", recipient="a@gov", message="m").provider_message_id
    id2 = n2.send(channel="email", recipient="a@gov", message="m").provider_message_id
    assert id1 == id2


# --- driving provider-side transitions (what a delivery receipt / webhook / ack would report) ---
def test_can_be_driven_to_delivered():
    n = FakeNotifier()
    a = n.send(channel="email", recipient="e@gov", message="m")
    assert n.mark_delivered(a.provider_message_id) is DeliveryState.DELIVERED
    assert n.state_of(a.provider_message_id) is DeliveryState.DELIVERED


def test_can_be_driven_to_failed():
    n = FakeNotifier()
    a = n.send(channel="email", recipient="e@gov", message="m")
    assert n.mark_failed(a.provider_message_id) is DeliveryState.FAILED
    assert n.state_of(a.provider_message_id) is DeliveryState.FAILED


def test_can_be_driven_to_acknowledged():
    n = FakeNotifier()
    a = n.send(channel="sms", recipient="+1", message="m")
    n.mark_delivered(a.provider_message_id)
    assert n.mark_acknowledged(a.provider_message_id) is DeliveryState.ACKNOWLEDGED
    assert n.state_of(a.provider_message_id) is DeliveryState.ACKNOWLEDGED


def test_a_preconfigured_failing_channel_sends_failed():
    # A test can arrange a channel to fail on send (drives the retry->failover path in A703).
    n = FakeNotifier(failing_channels=("email",))
    a = n.send(channel="email", recipient="e@gov", message="m")
    assert a.state is DeliveryState.FAILED
    b = n.send(channel="sms", recipient="+1", message="m")
    assert b.state is DeliveryState.SENT  # a different channel still sends
