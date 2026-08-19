"""R801 — apply_review_status(severity, is_withheld) (FR-11, mandate #3, AC-12).

Acceptance (tasks.md R801): a CRITICAL assessment -> PENDING_HUMAN_REVIEW; a withheld assessment ->
PENDING_HUMAN_REVIEW; a SAFE/WATCH/WARNING scored assessment -> FINAL (but the field is ALWAYS
explicitly set, never absent). Pure, applied before emission.
"""
from __future__ import annotations

from agents.risk_reasoning.review import apply_review_status
from agents.risk_reasoning.statuses import Severity, ReviewStatus


def test_critical_is_pending_human_review():
    assert apply_review_status(Severity.CRITICAL, is_withheld=False) is ReviewStatus.PENDING_HUMAN_REVIEW


def test_withheld_is_pending_human_review_regardless_of_severity():
    # A withheld assessment has severity None; it must be held for review.
    assert apply_review_status(None, is_withheld=True) is ReviewStatus.PENDING_HUMAN_REVIEW


def test_safe_watch_warning_are_final():
    assert apply_review_status(Severity.SAFE, is_withheld=False) is ReviewStatus.FINAL
    assert apply_review_status(Severity.WATCH, is_withheld=False) is ReviewStatus.FINAL
    assert apply_review_status(Severity.WARNING, is_withheld=False) is ReviewStatus.FINAL


def test_withheld_takes_precedence_even_if_a_severity_is_passed():
    # Defensive: if a caller somehow passes a non-critical severity with is_withheld=True,
    # the withhold still wins (never emit a withheld verdict as FINAL).
    assert apply_review_status(Severity.WATCH, is_withheld=True) is ReviewStatus.PENDING_HUMAN_REVIEW


def test_result_is_always_a_concrete_review_status():
    # The field is never None/absent — every assessment carries an explicit finality flag.
    for sev in (Severity.SAFE, Severity.WATCH, Severity.WARNING, Severity.CRITICAL):
        assert isinstance(apply_review_status(sev, is_withheld=False), ReviewStatus)
    assert isinstance(apply_review_status(None, is_withheld=True), ReviewStatus)
