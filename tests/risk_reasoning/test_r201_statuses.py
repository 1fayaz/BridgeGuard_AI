"""R201 — risk_statuses.py closed vocabulary (FR-4 / FR-11).

Acceptance (tasks.md R201): all 4 severities + both review statuses representable; a withheld
assessment is expressible as severity=None + review_status=PENDING_HUMAN_REVIEW; the enums are a
closed set (str, Enum) that round-trips to the DB/JSON values. Matches the spec output contract.
"""
from __future__ import annotations

from agents.risk_reasoning.statuses import Severity, ReviewStatus


def test_all_four_severities_present_and_closed():
    assert {s.value for s in Severity} == {"SAFE", "WATCH", "WARNING", "CRITICAL"}


def test_both_review_statuses_present_and_closed():
    assert {r.value for r in ReviewStatus} == {"FINAL", "PENDING_HUMAN_REVIEW"}


def test_enums_are_str_valued_for_db_json_roundtrip():
    # str, Enum so the value persists/round-trips cleanly (same as DCA/SA statuses).
    assert Severity.CRITICAL == "CRITICAL"
    assert ReviewStatus.PENDING_HUMAN_REVIEW == "PENDING_HUMAN_REVIEW"
    assert Severity("WATCH") is Severity.WATCH
    assert ReviewStatus("FINAL") is ReviewStatus.FINAL


def test_withheld_assessment_is_representable():
    # The withheld shape (FR-6/FR-7): no band, pending human review. Severity is simply absent.
    severity = None
    review = ReviewStatus.PENDING_HUMAN_REVIEW
    assert severity is None
    assert review is ReviewStatus.PENDING_HUMAN_REVIEW


def test_severity_is_ordered_safe_to_critical():
    # A stable declaration order lets downstream reason about "at least WARNING" etc.
    assert list(Severity) == [
        Severity.SAFE, Severity.WATCH, Severity.WARNING, Severity.CRITICAL
    ]
