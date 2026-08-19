"""determine_marks(...) (G701) — the RENDERED document's sign-off marks (pure, FR-4/6/7/8).

A RENDERED report is honest about its own standing via a set of marks:

  * NOT_FINAL           the underlying verdict is not settled — the assessment is held for human
                        review, or is CRITICAL (which is never final on the agent's say-so). A
                        NOT_FINAL report must not be consumed downstream as a final decision (FR-7).
  * SCORE_WITHHELD      the assessment emitted no score (degraded/guardrail path); the report is
                        rendered honestly from the verbatim withheld explanation, and is also
                        NOT_FINAL (a withheld score is never final) (FR-8).
  * HISTORICAL          a superseded assessment was rendered (a regulatory re-print) (FR-4/AC-4a).
  * SECTION_UNAVAILABLE at least one section had no upstream data and prints a placeholder (FR-6).

Pure function: derived entirely from the finalized assessment fields + the assembled sections +
whether this was a historical read. An empty result means a clean FINAL report. The order is fixed
(NOT_FINAL, SCORE_WITHHELD, HISTORICAL, SECTION_UNAVAILABLE) so persisted marks are reproducible.
"""
from __future__ import annotations

from typing import Any, Sequence

from agents.report_generation.model import ReportSection
from agents.report_generation.report_statuses import DocumentMark

# Fixed emission order -> reproducible persisted/audited mark lists (Constitution VI).
_ORDER = (
    DocumentMark.NOT_FINAL,
    DocumentMark.SCORE_WITHHELD,
    DocumentMark.HISTORICAL,
    DocumentMark.SECTION_UNAVAILABLE,
)


def determine_marks(
    assessment: dict[str, Any],
    sections: Sequence[ReportSection],
    *,
    historical: bool,
) -> tuple[DocumentMark, ...]:
    """Compute the RENDERED document's marks (G701). Pure; empty ⇒ a clean FINAL report."""
    present: set[DocumentMark] = set()

    withheld_score = assessment.get("risk_score") is None
    if withheld_score:
        present.add(DocumentMark.SCORE_WITHHELD)

    # NOT_FINAL: held for review, CRITICAL, or a withheld score (all "not settled").
    if (
        assessment.get("review_status") == "PENDING_HUMAN_REVIEW"
        or assessment.get("severity") == "CRITICAL"
        or withheld_score
    ):
        present.add(DocumentMark.NOT_FINAL)

    if historical or assessment.get("superseded_by") is not None:
        present.add(DocumentMark.HISTORICAL)

    if any(not section.available for section in sections):
        present.add(DocumentMark.SECTION_UNAVAILABLE)

    # Emit in the fixed order (deduplicated by the set), so the tuple is reproducible.
    return tuple(mark for mark in _ORDER if mark in present)
