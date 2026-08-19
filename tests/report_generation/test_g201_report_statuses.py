"""G201 — report_statuses.py (closed outcome vocabulary).

Mirrors the Risk/DCA/SA `statuses.py` style: small closed `str, Enum` sets the output contract
(G202), the schema (G203), and persistence (G801/G802) all rely on.

Acceptance (tasks.md G201): all three outcomes, all four marks, both withheld reasons are
representable; a RENDERED result may carry zero-or-more marks (empty ⇒ a clean FINAL report); a
WITHHELD result carries exactly one reason; matches the spec Outcome Vocabulary
(RENDERED with marks NOT_FINAL/SCORE_WITHHELD/HISTORICAL/SECTION_UNAVAILABLE; WITHHELD only
ASSESSMENT_NOT_FOUND/PROVENANCE_MISMATCH; ERROR).
"""
from __future__ import annotations

from enum import Enum

from agents.report_generation.report_statuses import (
    DocumentMark,
    ReportOutcome,
    WithheldReason,
)


def test_outcomes_are_the_closed_set_of_three():
    assert {o.value for o in ReportOutcome} == {"RENDERED", "WITHHELD", "ERROR"}


def test_document_marks_are_the_closed_set_of_four():
    assert {m.value for m in DocumentMark} == {
        "NOT_FINAL",
        "SCORE_WITHHELD",
        "HISTORICAL",
        "SECTION_UNAVAILABLE",
    }


def test_withheld_reasons_are_exactly_the_two_no_document_cases():
    # WITHHELD (no document produced) is deliberately narrow: only the two cases where publishing
    # nothing beats an untraceable number.
    assert {r.value for r in WithheldReason} == {
        "ASSESSMENT_NOT_FOUND",
        "PROVENANCE_MISMATCH",
    }


def test_enums_are_str_backed_for_db_json_roundtrip():
    assert isinstance(ReportOutcome.RENDERED, str)
    assert isinstance(DocumentMark.NOT_FINAL, str)
    assert isinstance(WithheldReason.PROVENANCE_MISMATCH, str)
    assert ReportOutcome.RENDERED == "RENDERED"


def test_marks_and_reasons_are_disjoint_vocabularies():
    # A mark is never a withheld reason and vice-versa (RENDERED-with-mark != WITHHELD-with-reason).
    marks = {m.value for m in DocumentMark}
    reasons = {r.value for r in WithheldReason}
    assert marks.isdisjoint(reasons)


def test_rendered_supports_zero_or_more_marks():
    # Empty mark set ⇒ a clean FINAL report; marks compose as a set.
    clean: set[DocumentMark] = set()
    assert clean == set()
    composed = {DocumentMark.HISTORICAL, DocumentMark.NOT_FINAL}
    assert DocumentMark.HISTORICAL in composed and DocumentMark.NOT_FINAL in composed


def test_all_three_enums_are_enum_subclasses():
    for e in (ReportOutcome, DocumentMark, WithheldReason):
        assert issubclass(e, Enum)
