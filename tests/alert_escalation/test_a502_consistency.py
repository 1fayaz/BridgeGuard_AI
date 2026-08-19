"""A502 — consistency_check(message, verdict) (pure, fail-closed).

The alert-layer analogue of the Report agent's fidelity gate and the Risk agent's numeric-
provenance guardrail — plain code, no SDK. Before an alert is dispatched, verify the assembled
message does not CONTRADICT the verdict:

  * the message's band label EQUALS the source severity/risk_score band, and
  * the message does not present a PENDING_HUMAN_REVIEW verdict as settled/final.

A contradiction TRIPWIRES the gate (passed=False, the offending contradiction named); the service
(A901) then withholds -> CONSISTENCY_MISMATCH and dispatches nothing. Fail-closed: an alert that
misstates the record never reaches an engineer.

Acceptance (tasks.md A502): a faithful message passes; a message whose band contradicts the source
verdict fails, naming the contradiction; a message presenting a pending verdict as settled fails; a
consistent message over a pending verdict (correctly marked not-final) passes. = FR-9, AC-8.
"""
from __future__ import annotations

from agents.alert_escalation.consistency import ConsistencyVerdict, consistency_check
from agents.alert_escalation.message import assemble_message
from agents.alert_escalation.config.message_template_table import MessageTemplateTable
from agents.risk_reasoning.statuses import Severity


TEMPLATES = MessageTemplateTable(
    templates=tuple((s, f"{s.value}: {{explanation}}") for s in Severity),
)


def _verdict(**over):
    base = dict(
        id=1001, bridge_id="b", cycle_id="c", assessment_version=3,
        risk_score=70, severity="WARNING",
        recommendation="Schedule inspection.", explanation="Elevated at pier 3.",
        review_status="FINAL", trace_id="t",
    )
    base.update(over)
    return base


# ------------------------------------------------------------------ passing ---
def test_faithful_message_passes():
    v = _verdict(severity="WARNING")
    m = assemble_message(v, TEMPLATES)
    verdict = consistency_check(m, v)
    assert verdict.passed is True
    assert verdict.contradiction is None


def test_consistent_message_over_a_pending_verdict_passes():
    # Correctly not claiming settled: a pending verdict assembled faithfully passes.
    v = _verdict(severity="CRITICAL", risk_score=91, review_status="PENDING_HUMAN_REVIEW")
    m = assemble_message(v, TEMPLATES)
    assert consistency_check(m, v).passed is True


def test_returns_a_consistency_verdict_shape():
    v = _verdict()
    assert isinstance(consistency_check(assemble_message(v, TEMPLATES), v), ConsistencyVerdict)


# ------------------------------------------------------------------ band contradiction ---
def test_message_band_contradicting_the_verdict_fails():
    # Assemble faithfully, then tamper the band to a lower one — the gate must catch it.
    v = _verdict(severity="WARNING")
    m = assemble_message(v, TEMPLATES)
    tampered = _tamper(m, band="SAFE")
    verdict = consistency_check(tampered, v)
    assert verdict.passed is False
    assert verdict.contradiction is not None
    assert "band" in verdict.contradiction.lower()


def test_message_claiming_safe_over_a_warning_score_fails():
    v = _verdict(severity="WARNING", risk_score=70)
    m = assemble_message(v, TEMPLATES)
    tampered = _tamper(m, band="SAFE")
    assert consistency_check(tampered, v).passed is False


# ------------------------------------------------------------------ finality contradiction ---
def test_message_presenting_a_pending_verdict_as_settled_fails():
    # The message's own review_status says FINAL while the verdict is PENDING -> contradiction.
    v = _verdict(severity="WARNING", review_status="PENDING_HUMAN_REVIEW")
    m = assemble_message(v, TEMPLATES)
    tampered = _tamper(m, review_status="FINAL")
    verdict = consistency_check(tampered, v)
    assert verdict.passed is False
    assert "final" in verdict.contradiction.lower() or "pending" in verdict.contradiction.lower()


# ------------------------------------------------------------------ withheld-score verdict ---
def test_withheld_score_verdict_with_no_band_is_consistent():
    # No severity in the verdict and no band on the message -> not a contradiction.
    v = _verdict(severity=None, risk_score=None, review_status="PENDING_HUMAN_REVIEW",
                 explanation="Coverage below floor.")
    m = assemble_message(v, TEMPLATES)
    assert consistency_check(m, v).passed is True


def test_message_inventing_a_band_over_a_withheld_verdict_fails():
    # The verdict withheld its score (no band); a message asserting a concrete band contradicts it.
    v = _verdict(severity=None, risk_score=None, review_status="PENDING_HUMAN_REVIEW",
                 explanation="Coverage below floor.")
    m = assemble_message(v, TEMPLATES)
    tampered = _tamper(m, band="SAFE")
    assert consistency_check(tampered, v).passed is False


# --- helper: rebuild an AssembledMessage with one field overridden (frozen dataclass) ---
def _tamper(message, **over):
    from dataclasses import replace
    return replace(message, **over)
