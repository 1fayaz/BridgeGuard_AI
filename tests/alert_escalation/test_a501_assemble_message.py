"""A501 — assemble_message(verdict, templates) (pure, verbatim).

Builds the alert message by COPYING the verdict into the fixed severity->template (A102): the
verbatim explanation, the score/severity/recommendation as-is, and the band label taken straight
from the source `severity`. No recomputation, re-mapping, or rewording — each message field records
the source value it was copied from (its source_ref), so the consistency gate (A502) can verify
every field traces to the verdict.

Acceptance (tasks.md A501): the message's band label EQUALS the source severity; the explanation is
byte-identical to verdict.explanation; score/recommendation equal the source; no field is
computed/derived; the template is the fixed A102 lookup (changes only if config changes, not data).
= FR-1, AC-1.
"""
from __future__ import annotations

from agents.alert_escalation.config.message_template_table import (
    TODO_TEMPLATE,
    MessageTemplateTable,
)
from agents.alert_escalation.message import AssembledMessage, assemble_message
from agents.risk_reasoning.statuses import Severity


TEMPLATES = MessageTemplateTable(
    templates=(
        (Severity.SAFE, "Routine status for {bridge_id}: {explanation}"),
        (Severity.WATCH, "Watch on {bridge_id} (score {risk_score}): {explanation}"),
        (Severity.WARNING, "WARNING {bridge_id}: {recommendation} — {explanation}"),
        (Severity.CRITICAL, "CRITICAL {bridge_id}: {recommendation} — {explanation}"),
    ),
)


def _verdict(**over):
    base = dict(
        id=1001,
        bridge_id="bridge-7",
        cycle_id="cycle-42",
        assessment_version=3,
        risk_score=70,
        severity="WARNING",
        recommendation="Schedule inspection within 30 days.",
        explanation="Deflection ratio elevated at pier 3; within limit but trending up.",
        review_status="FINAL",
        trace_id="trace-xyz",
    )
    base.update(over)
    return base


def test_returns_an_assembled_message_shape():
    m = assemble_message(_verdict(), TEMPLATES)
    assert isinstance(m, AssembledMessage)


def test_band_label_equals_source_severity():
    m = assemble_message(_verdict(severity="WARNING"), TEMPLATES)
    assert m.band == "WARNING"
    # and it records where it came from
    assert m.field_source("band") == "risk_assessments:1001:severity"


def test_explanation_is_byte_identical_verbatim():
    v = _verdict(explanation="Exact WHY string, copied verbatim. 48mm at pier 3.")
    m = assemble_message(v, TEMPLATES)
    assert m.explanation == "Exact WHY string, copied verbatim. 48mm at pier 3."
    assert m.field_source("explanation") == "risk_assessments:1001:explanation"


def test_score_and_recommendation_equal_the_source():
    v = _verdict(risk_score=70, recommendation="Schedule inspection within 30 days.")
    m = assemble_message(v, TEMPLATES)
    assert m.risk_score == 70
    assert m.recommendation == "Schedule inspection within 30 days."


def test_body_is_the_fixed_template_filled_with_verbatim_values():
    v = _verdict(severity="WARNING")
    m = assemble_message(v, TEMPLATES)
    expected = f"WARNING bridge-7: {v['recommendation']} — {v['explanation']}"
    assert m.body == expected


def test_body_changes_with_template_not_with_recomputation():
    v = _verdict(severity="SAFE", risk_score=10, review_status="FINAL")
    a = assemble_message(v, MessageTemplateTable(templates=((Severity.SAFE, "All clear: {explanation}"),)))
    b = assemble_message(v, MessageTemplateTable(templates=((Severity.SAFE, "Nominal: {explanation}"),)))
    assert a.body == f"All clear: {v['explanation']}"
    assert b.body == f"Nominal: {v['explanation']}"


def test_no_field_is_computed_every_field_traces_to_the_verdict():
    m = assemble_message(_verdict(), TEMPLATES)
    for field in ("band", "explanation", "risk_score", "recommendation"):
        assert m.field_source(field), f"{field} has no source_ref (would be a computed/derived value)"
        assert m.field_source(field).startswith("risk_assessments:")


def test_withheld_score_verdict_assembles_without_a_band_template():
    # No severity -> the band label is None; the message still carries the verbatim explanation.
    v = _verdict(severity=None, risk_score=None, review_status="PENDING_HUMAN_REVIEW",
                 explanation="Coverage below floor; no reliable score.")
    m = assemble_message(v, TEMPLATES)
    assert m.band is None
    assert m.explanation == "Coverage below floor; no reliable score."


def test_unconfigured_band_uses_the_todo_template_sentinel_not_a_guess():
    v = _verdict(severity="CRITICAL")
    empty = MessageTemplateTable()
    m = assemble_message(v, empty)
    # the template is the loud sentinel; the assembler never invents wording
    assert TODO_TEMPLATE in m.body or m.body == TODO_TEMPLATE


def test_assembly_is_pure_does_not_mutate_the_verdict():
    v = _verdict()
    before = dict(v)
    assemble_message(v, TEMPLATES)
    assert v == before


def test_carries_the_review_status_for_the_consistency_gate():
    # A502 needs to know finality to catch "settled over a pending verdict" — carry it verbatim.
    m = assemble_message(_verdict(review_status="PENDING_HUMAN_REVIEW"), TEMPLATES)
    assert m.review_status == "PENDING_HUMAN_REVIEW"
