"""A401 — decide_tier(verdict, policy) (pure): the settled severity->approval decision.

This is the one place the settled mapping lives (FR-2/FR-3). Given a finalized verdict + the alert
policy, it returns a DispatchDecision plus the resolved channel/recipient:

  SAFE                      -> DASHBOARD_ONLY (no push)
  WATCH & review = FINAL    -> AUTO_FIRE (internal channel)
  WARNING / CRITICAL        -> NEEDS_APPROVAL

Overrides (apply on top of the band default):
  * any authority-facing recipient -> NEEDS_APPROVAL, regardless of band
  * review_status = PENDING_HUMAN_REVIEW -> never AUTO_FIRE at any band (routes to NEEDS_APPROVAL)
  * a withheld-score verdict (no severity band) -> NEEDS_APPROVAL (a human must see it)

Pure decision over the verdict + policy; no I/O, no model.
"""
from __future__ import annotations

from agents.alert_escalation.config.alert_policy import AlertPolicy
from agents.alert_escalation.statuses import DispatchDecision
from agents.alert_escalation.tiering import TierDecision, decide_tier
from agents.risk_reasoning.statuses import ReviewStatus, Severity


def _policy(**over) -> AlertPolicy:
    base = dict(
        policy_version="test-policy",
        retry_max=3,
        backoff_seconds=30,
        escalation_timeout_seconds=300,
        # (band, recipient) routing
        contact_roster=(
            ("WATCH", "monitoring-team@gov"),
            ("WARNING", "engineer@gov"),
            ("CRITICAL", "authority@city.gov"),
        ),
        escalation_order=("engineer@gov", "oncall@gov"),
        # (band, channel) routing
        channel_per_band=(
            ("WATCH", "email"),
            ("WARNING", "email"),
            ("CRITICAL", "sms"),
        ),
        authority_recipients=("authority@city.gov",),
    )
    base.update(over)
    return AlertPolicy(**base)


def _verdict(**over):
    base = dict(
        id=1001,
        bridge_id="bridge-7",
        cycle_id="cycle-42",
        assessment_version=3,
        risk_score=48,
        severity="WARNING",
        recommendation="Schedule inspection.",
        explanation="Deflection ratio elevated at pier 3.",
        review_status="FINAL",
        trace_id="trace-xyz",
    )
    base.update(over)
    return base


# ------------------------------------------------------------------ SAFE ---
def test_safe_is_dashboard_only_no_push():
    d = decide_tier(_verdict(severity="SAFE", risk_score=10), _policy())
    assert d.decision is DispatchDecision.DASHBOARD_ONLY
    assert d.channel is None
    assert d.recipient is None


# ------------------------------------------------------------------ WATCH ---
def test_watch_final_auto_fires_internal():
    d = decide_tier(_verdict(severity="WATCH", risk_score=45, review_status="FINAL"), _policy())
    assert d.decision is DispatchDecision.AUTO_FIRE
    assert d.channel == "email"
    assert d.recipient == "monitoring-team@gov"


def test_watch_pending_does_not_auto_fire():
    # The PENDING override forbids AUTO_FIRE at any band.
    d = decide_tier(
        _verdict(severity="WATCH", risk_score=45, review_status="PENDING_HUMAN_REVIEW"),
        _policy(),
    )
    assert d.decision is DispatchDecision.NEEDS_APPROVAL


def test_watch_to_authority_recipient_needs_approval():
    # Blast-radius override: a WATCH whose recipient is authority-facing must be gated.
    pol = _policy(contact_roster=(("WATCH", "authority@city.gov"),))
    d = decide_tier(_verdict(severity="WATCH", risk_score=45, review_status="FINAL"), pol)
    assert d.decision is DispatchDecision.NEEDS_APPROVAL


# ------------------------------------------------------------------ WARNING ---
def test_warning_needs_approval_even_when_final():
    d = decide_tier(_verdict(severity="WARNING", risk_score=70, review_status="FINAL"), _policy())
    assert d.decision is DispatchDecision.NEEDS_APPROVAL
    assert d.channel == "email"
    assert d.recipient == "engineer@gov"


# ------------------------------------------------------------------ CRITICAL ---
def test_critical_needs_approval():
    # Every CRITICAL arrives PENDING_HUMAN_REVIEW upstream; gated on both axes, resolves NEEDS_APPROVAL.
    d = decide_tier(
        _verdict(severity="CRITICAL", risk_score=91, review_status="PENDING_HUMAN_REVIEW"),
        _policy(),
    )
    assert d.decision is DispatchDecision.NEEDS_APPROVAL
    assert d.recipient == "authority@city.gov"


def test_critical_marked_final_would_still_need_approval():
    # Even a (hypothetical) FINAL critical is gated by its band — band default, not just the pending axis.
    d = decide_tier(_verdict(severity="CRITICAL", risk_score=91, review_status="FINAL"), _policy())
    assert d.decision is DispatchDecision.NEEDS_APPROVAL


# ------------------------------------------------------------------ withheld score ---
def test_withheld_score_verdict_routes_to_approval():
    # A withheld-score assessment has no severity band and is PENDING_HUMAN_REVIEW: a human must see it.
    d = decide_tier(
        _verdict(severity=None, risk_score=None, review_status="PENDING_HUMAN_REVIEW",
                 explanation="Coverage below floor; no reliable score."),
        _policy(),
    )
    assert d.decision is DispatchDecision.NEEDS_APPROVAL


# ------------------------------------------------------------------ purity / determinism ---
def test_decision_is_deterministic():
    v = _verdict(severity="WARNING", review_status="FINAL")
    assert decide_tier(v, _policy()).decision is decide_tier(v, _policy()).decision


def test_returns_a_tier_decision_shape():
    d = decide_tier(_verdict(severity="WATCH", review_status="FINAL"), _policy())
    assert isinstance(d, TierDecision)
    assert d.reason  # a short human-readable why is recorded


def test_full_truth_table_bands_x_finality_x_authority():
    # The complete settled mapping, asserted in one place.
    cases = [
        # (severity, review_status, authority_recipient?, expected)
        ("SAFE", "FINAL", False, DispatchDecision.DASHBOARD_ONLY),
        ("SAFE", "PENDING_HUMAN_REVIEW", False, DispatchDecision.DASHBOARD_ONLY),
        ("WATCH", "FINAL", False, DispatchDecision.AUTO_FIRE),
        ("WATCH", "PENDING_HUMAN_REVIEW", False, DispatchDecision.NEEDS_APPROVAL),
        ("WATCH", "FINAL", True, DispatchDecision.NEEDS_APPROVAL),
        ("WARNING", "FINAL", False, DispatchDecision.NEEDS_APPROVAL),
        ("WARNING", "PENDING_HUMAN_REVIEW", False, DispatchDecision.NEEDS_APPROVAL),
        ("CRITICAL", "FINAL", False, DispatchDecision.NEEDS_APPROVAL),
        ("CRITICAL", "PENDING_HUMAN_REVIEW", False, DispatchDecision.NEEDS_APPROVAL),
    ]
    for sev, review, authority, expected in cases:
        recipient = "authority@city.gov" if authority else f"{sev.lower()}-team@gov"
        pol = _policy(
            contact_roster=((sev, recipient),),
            channel_per_band=((sev, "email"),),
            authority_recipients=("authority@city.gov",),
        )
        d = decide_tier(_verdict(severity=sev, review_status=review), pol)
        assert d.decision is expected, f"{sev}/{review}/authority={authority} -> {d.decision}, want {expected}"


def test_safe_is_dashboard_only_even_when_pending():
    # SAFE never pushes regardless of finality (dashboard-only is not a dispatch to gate).
    d = decide_tier(_verdict(severity="SAFE", review_status="PENDING_HUMAN_REVIEW"), _policy())
    assert d.decision is DispatchDecision.DASHBOARD_ONLY
