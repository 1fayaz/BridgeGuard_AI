"""Closed status vocabulary for the Report Generation Agent (G201).

Mirrors the Risk/DCA/SA `statuses.py` style: small closed enums the output contract (G202), the
schema (G203/G204), and persistence (G801/G802) all rely on. `str, Enum` so values round-trip
cleanly to/from the DB enums and JSON.

The spec's Outcome Vocabulary in three enums:

  * ReportOutcome  — what happened to the render: a document was produced (RENDERED), no document
    was produced on purpose (WITHHELD), or an unexpected failure (ERROR).
  * DocumentMark   — sign-off marks a RENDERED document may carry (zero or more). An empty mark
    set means a clean FINAL report.
  * WithheldReason — the deliberately narrow set of cases where producing NO document beats
    producing an untraceable one. Only these two; everything else degrades to a marked RENDERED.
"""
from __future__ import annotations

from enum import Enum


class ReportOutcome(str, Enum):
    """What happened to a report render. Closed set of three."""

    RENDERED = "RENDERED"      # a document was produced (possibly carrying marks)
    WITHHELD = "WITHHELD"      # no document produced, on purpose (carries a WithheldReason)
    ERROR = "ERROR"            # an unexpected failure — structured, never a crash (FR-12)


class DocumentMark(str, Enum):
    """Sign-off marks a RENDERED document may carry (zero or more; empty ⇒ clean FINAL)."""

    NOT_FINAL = "NOT_FINAL"                     # assessment pending human review or CRITICAL (FR-7)
    SCORE_WITHHELD = "SCORE_WITHHELD"           # upstream withheld its score; rendered honestly (FR-8)
    HISTORICAL = "HISTORICAL"                   # a superseded assessment was rendered (FR-4/AC-4a)
    SECTION_UNAVAILABLE = "SECTION_UNAVAILABLE" # a required section had no upstream data (FR-6)


class WithheldReason(str, Enum):
    """The only two cases where publishing NO document beats an untraceable number.

    Everything else (pending, critical, withheld score, missing section, historical) still yields
    a RENDERED document with the appropriate DocumentMark.
    """

    ASSESSMENT_NOT_FOUND = "ASSESSMENT_NOT_FOUND"   # the scope key resolves to no assessment row
    PROVENANCE_MISMATCH = "PROVENANCE_MISMATCH"     # a printed value did not trace to a source (FR-5)
