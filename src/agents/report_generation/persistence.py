"""Report persistence (G802) — FR-9 / FR-10 / FR-11 [DB-DEP].

`persist_report` writes one report (rendered, withheld, or error) to the store and appends the
matching decision_log entry, so the structured record alone answers what was rendered / withheld,
from which assessment version, on which sources (AC-9). It pins every provenance field
(assessment id+version, source_analysis_ids, standard code+version, template_version — FR-11) and
is idempotent by assessment version: re-persisting the same (assessment_id, assessment_version)
SUPERSEDES the prior row rather than crashing on the uniqueness constraint (a re-render appends +
links, never overwrites).

Audit-kind selection mirrors the 0009 decision_kind extension:
  RENDERED -> REPORT_RENDERED
  WITHHELD -> REPORT_WITHHELD
  ERROR    -> REPORT_ERROR

[DB-DEP] Runs against FakeReportStore now; the live Neon write is deferred (no instance locally).
"""
from __future__ import annotations

from agents.report_generation.report_result import ReportResult
from agents.report_generation.report_statuses import ReportOutcome
from agents.report_generation.store import FakeReportStore

_AUDIT_KIND = {
    ReportOutcome.RENDERED: "REPORT_RENDERED",
    ReportOutcome.WITHHELD: "REPORT_WITHHELD",
    ReportOutcome.ERROR: "REPORT_ERROR",
}


def _audit_reason(result: ReportResult) -> str:
    """A short, structured reason line for the audit row — records the pinned version + outcome."""
    base = f"assessment {result.assessment_id} v{result.assessment_version}"
    if result.outcome is ReportOutcome.RENDERED:
        marks = ",".join(m.value for m in result.marks) or "FINAL"
        return f"rendered {base} [{marks}]"
    if result.outcome is ReportOutcome.WITHHELD:
        reason = result.withheld_reason.value if result.withheld_reason else "WITHHELD"
        return f"withheld {base}: {reason}"
    return f"error {base}"


def persist_report(store: FakeReportStore, result: ReportResult) -> int:
    """Persist one report + its audit entry (FR-9). Returns the new row id.

    If a current report already exists for this (assessment_id, assessment_version), the new one
    supersedes it (append + link); otherwise it is a fresh insert. Idempotent by assessment
    version — a redelivered trigger or a re-render never duplicates or crashes.
    """
    existing = store.current(result.assessment_id, result.assessment_version)
    if existing is not None:
        old_id = next(
            sr.id for sr in store.rows
            if sr.result is existing and sr.superseded_by is None
        )
        row_id = store.insert_superseding(old_id, result)
    else:
        row_id = store.insert(result)

    store.append_audit(
        result.bridge_id,
        result.cycle_id,
        _AUDIT_KIND[result.outcome],
        _audit_reason(result),
    )
    return row_id
