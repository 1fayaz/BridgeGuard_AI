"""A101 — AlertPolicy config shape (config-level acceptance).

Acceptance (tasks.md A101): constructs; the non-physical audit field `policy_version` is concrete;
every operational value a human must still supply — the contact roster + escalation order, the
per-band channels, the retry/backoff counts, the escalation timeout, and the authority-recipient
set (the FR-3 blast-radius override set) — is a clearly-flagged TODO sentinel a reviewer can see
is unset; `is_fully_configured` is False while any is unset. We do NOT guess a roster, a retry
count, a timeout window, or which recipients are authority-facing for a safety-critical system.

Mirrors the Report ReportConfig / Risk ScoreConfig discipline: an unset value is loudly flagged
(NaN for numbers, None for references), never silently defaulted to a plausible value. There is
NO safe default here — unlike the report's fidelity_tolerance, every AlertPolicy field a human
supplies is genuinely a policy choice, so all of them gate `is_fully_configured`.
"""
from __future__ import annotations

import math

from agents.alert_escalation.config.alert_policy import AlertPolicy


def test_constructs_with_concrete_policy_version_only():
    # Constructible from just the audit version; every operational field defaults to a TODO sentinel.
    p = AlertPolicy(policy_version="v0-unset")
    assert p.policy_version == "v0-unset"


def test_policy_version_is_concrete_not_a_sentinel():
    # Stamps WHICH policy an alert used (non-physical audit field); always present, never NaN/None.
    p = AlertPolicy(policy_version="2026-07-alert-policy-rev1")
    assert isinstance(p.policy_version, str)
    assert p.policy_version  # non-empty


def test_retry_backoff_timeout_are_todo_sentinels_by_default():
    # The retry count, backoff, and escalation timeout must be SEEN as unset, not guessed — a wrong
    # escalation window on a Critical alert is a safety failure.
    p = AlertPolicy(policy_version="v0-unset")
    assert math.isnan(p.retry_max), "retry_max was given a non-TODO default"
    assert math.isnan(p.backoff_seconds), "backoff_seconds was given a non-TODO default"
    assert math.isnan(p.escalation_timeout_seconds), "escalation timeout was given a non-TODO default"


def test_roster_channels_authority_set_are_none_by_default():
    # The roster, escalation order, per-band channels, and authority-recipient set are references we
    # do not invent — None until a stakeholder supplies them.
    p = AlertPolicy(policy_version="v0-unset")
    assert p.contact_roster is None
    assert p.escalation_order is None
    assert p.channel_per_band is None
    assert p.authority_recipients is None


def test_unconfigured_is_not_fully_configured():
    p = AlertPolicy(policy_version="v0-unset")
    assert p.retry_config_is_todo is True
    assert p.roster_is_todo is True
    assert p.channels_are_todo is True
    assert p.authority_set_is_todo is True
    assert p.is_fully_configured is False


def test_partial_config_is_still_not_fully_configured():
    # Supplying the retry/backoff/timeout but leaving the roster/channels/authority set TODO must NOT pass.
    p = AlertPolicy(
        policy_version="rev1",
        retry_max=3,
        backoff_seconds=30,
        escalation_timeout_seconds=300,
    )
    assert p.retry_config_is_todo is False
    assert p.roster_is_todo is True
    assert p.is_fully_configured is False


def test_a_nan_retry_value_is_treated_as_unset():
    # Even with everything else supplied, a single NaN retry field must not pass as configured.
    p = AlertPolicy(
        policy_version="rev1",
        retry_max=float("nan"),
        backoff_seconds=30,
        escalation_timeout_seconds=300,
        contact_roster=(("engineer@gov", "sms:+100"),),
        escalation_order=("engineer@gov", "oncall@gov"),
        channel_per_band=(("WATCH", "email"), ("WARNING", "email"), ("CRITICAL", "sms")),
        authority_recipients=("authority@city.gov",),
    )
    assert p.retry_config_is_todo is True
    assert p.is_fully_configured is False


def test_an_empty_authority_set_is_a_real_choice_not_unset():
    # None = "we have not decided which recipients are authority-facing" (unset, do not guess).
    # An explicitly-empty tuple = "no recipient is authority-facing" — a real, reviewed choice.
    p_unset = AlertPolicy(policy_version="rev1")
    assert p_unset.authority_set_is_todo is True

    p_explicit_empty = AlertPolicy(policy_version="rev1", authority_recipients=())
    assert p_explicit_empty.authority_set_is_todo is False


def test_fully_supplied_config_is_fully_configured():
    p = AlertPolicy(
        policy_version="2026-07-alert-policy-rev1",
        retry_max=3,
        backoff_seconds=30,
        escalation_timeout_seconds=300,
        contact_roster=(("engineer@gov", "sms:+100"),),
        escalation_order=("engineer@gov", "oncall@gov"),
        channel_per_band=(("WATCH", "email"), ("WARNING", "email"), ("CRITICAL", "sms")),
        authority_recipients=("authority@city.gov",),
    )
    assert p.retry_config_is_todo is False
    assert p.roster_is_todo is False
    assert p.channels_are_todo is False
    assert p.authority_set_is_todo is False
    assert p.is_fully_configured is True
