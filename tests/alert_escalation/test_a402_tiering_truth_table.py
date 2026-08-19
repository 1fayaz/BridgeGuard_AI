"""A402 — the settled severity->approval truth table as a spec-level gate (AC-2/AC-3).

A401 unit-tests decide_tier's branches; THIS is the dedicated acceptance gate a reviewer reads
against the spec's settled table (FR-2/FR-3). It drives every combination of band x finality x
recipient-blast-radius and asserts the full mapping in one place, plus the two failure directions
the spec forbids: a build that auto-fires WARNING/CRITICAL, or auto-fires a PENDING verdict, or
pushes on SAFE, must fail here.
"""
from __future__ import annotations

import itertools

from agents.alert_escalation.config.alert_policy import AlertPolicy
from agents.alert_escalation.statuses import DispatchDecision
from agents.alert_escalation.tiering import decide_tier
from agents.risk_reasoning.statuses import ReviewStatus, Severity


def _policy(band: str, recipient: str) -> AlertPolicy:
    return AlertPolicy(
        policy_version="truth-table",
        retry_max=3,
        backoff_seconds=30,
        escalation_timeout_seconds=300,
        contact_roster=((band, recipient),),
        escalation_order=("oncall@gov",),
        channel_per_band=((band, "email"),),
        authority_recipients=("authority@city.gov",),
    )


def _verdict(severity, review):
    return dict(
        id=1, bridge_id="b", cycle_id="c", assessment_version=1,
        risk_score=None if severity is None else 50,
        severity=severity, review_status=review,
        recommendation="r", explanation="e", trace_id="t",
    )


def _expected(severity: str | None, review: str, authority: bool) -> DispatchDecision:
    """The spec's settled table, expressed independently of the implementation."""
    if severity is None:
        return DispatchDecision.NEEDS_APPROVAL          # withheld score -> human must see it
    if severity == "SAFE":
        return DispatchDecision.DASHBOARD_ONLY          # never a push, regardless of anything else
    if severity in ("WARNING", "CRITICAL"):
        return DispatchDecision.NEEDS_APPROVAL          # band default gates
    # WATCH:
    if review == ReviewStatus.PENDING_HUMAN_REVIEW.value:
        return DispatchDecision.NEEDS_APPROVAL          # finality override
    if authority:
        return DispatchDecision.NEEDS_APPROVAL          # blast-radius override
    return DispatchDecision.AUTO_FIRE                   # WATCH + FINAL + internal


def test_full_truth_table():
    severities = [s.value for s in Severity] + [None]  # + the withheld-score case
    reviews = [r.value for r in ReviewStatus]
    authority_choices = [False, True]

    for severity, review, authority in itertools.product(severities, reviews, authority_choices):
        recipient = "authority@city.gov" if authority else "internal@gov"
        band_key = severity if severity is not None else "WATCH"  # roster key is irrelevant when None
        pol = _policy(band_key, recipient)
        got = decide_tier(_verdict(severity, review), pol).decision
        want = _expected(severity, review, authority)
        assert got is want, (
            f"severity={severity} review={review} authority={authority}: got {got}, want {want}"
        )


def test_no_warning_or_critical_ever_auto_fires():
    # The safety floor: a high-severity alert is NEVER dispatched without a human, on any finality.
    for severity in ("WARNING", "CRITICAL"):
        for review in (r.value for r in ReviewStatus):
            pol = _policy(severity, "engineer@gov")
            d = decide_tier(_verdict(severity, review), pol)
            assert d.decision is not DispatchDecision.AUTO_FIRE


def test_no_pending_verdict_ever_auto_fires():
    # The finality floor: a not-yet-final verdict is never auto-fired, at any band.
    for severity in (s.value for s in Severity):
        pol = _policy(severity, "internal@gov")
        d = decide_tier(_verdict(severity, ReviewStatus.PENDING_HUMAN_REVIEW.value), pol)
        assert d.decision is not DispatchDecision.AUTO_FIRE


def test_safe_never_pushes():
    for review in (r.value for r in ReviewStatus):
        pol = _policy("SAFE", "internal@gov")
        d = decide_tier(_verdict("SAFE", review), pol)
        assert d.decision is DispatchDecision.DASHBOARD_ONLY
        assert d.channel is None
