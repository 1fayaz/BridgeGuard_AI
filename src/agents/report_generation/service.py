"""run_report(...) (G901) — the per-report orchestrator. Never raises (FR-12).

Wires the whole per-report flow for one finalized assessment (plan §6):

    resolve the assessment (G301)
      -> WITHHELD/ASSESSMENT_NOT_FOUND if absent (nothing to render), stop
    read analysis + readings (G302/G303)  -> assemble the model (G402)
    fidelity gate (G501) against a fresh authoritative read of the source of record
      -> WITHHELD/PROVENANCE_MISMATCH if any printed value fails to trace, no artifact, stop
    render (via the injected RenderPort)  -> determine marks (G701)
    atomic write: persist the report_artifacts row + decision_log audit (G802)
      -> ReportSummary

It ALWAYS returns a structured ReportSummary and NEVER raises (FR-12 / Principle V): any read,
assemble, render, or persist failure is isolated into a structured ERROR summary. There is NO model
anywhere in this path — assembly is deterministic templating (Principle IV).

Atomicity: the artifact row is written only after a successful render, so a mid-render failure
leaves no partial artifact (the report analogue of append-+-supersede). The two WITHHELD cases
differ by whether an assessment identity exists to key a row on: ASSESSMENT_NOT_FOUND audits only
(no identity), while PROVENANCE_MISMATCH persists a first-class WITHHELD report_artifacts row.
"""
from __future__ import annotations

from typing import Any

from agents.report_generation.assembler import assemble_report
from agents.report_generation.config.headline_table import HeadlineTable
from agents.report_generation.config.report_config import ReportConfig
from agents.report_generation.fidelity import build_source_index, fidelity_check
from agents.report_generation.marks import determine_marks
from agents.report_generation.persistence import persist_report
from agents.report_generation.render.port import RenderPort
from agents.report_generation.report_result import ReportResult, ReportSummary
from agents.report_generation.report_statuses import ReportOutcome, WithheldReason
from agents.report_generation.store import FakeReportStore
from agents.report_generation.tools.analysis_results_read import get_analysis_results
from agents.report_generation.tools.risk_assessment_read import (
    AssessmentScope,
    get_risk_assessment,
)
from agents.report_generation.tools.validated_readings_read import get_validated_readings
from agents.risk_reasoning.statuses import Severity

__all__ = ["AssessmentScope", "run_report"]


def run_report(
    scope: AssessmentScope,
    *,
    sources: Any,
    store: FakeReportStore,
    config: ReportConfig,
    headlines: HeadlineTable,
    renderer: RenderPort,
    rendered_at: str,
    historical: bool = False,
) -> ReportSummary:
    """Render one report for a finalized assessment (G901). Always structured; never raises."""
    try:
        return _run(
            scope, sources=sources, store=store, config=config, headlines=headlines,
            renderer=renderer, rendered_at=rendered_at, historical=historical,
        )
    except Exception as exc:  # FR-12: no failure escapes as a crash.
        store.append_audit(
            scope.bridge_id, scope.cycle_id, "REPORT_ERROR",
            f"report could not be produced due to an internal error: {exc!s}",
        )
        return ReportSummary.from_error(str(exc))


def _run(
    scope, *, sources, store, config, headlines, renderer, rendered_at, historical,
) -> ReportSummary:
    # 1. Resolve the assessment. Absent -> WITHHELD/ASSESSMENT_NOT_FOUND (nothing to render).
    read = get_risk_assessment(scope, sources, historical=historical)
    if not read.found:
        store.append_audit(
            scope.bridge_id, scope.cycle_id, "REPORT_WITHHELD",
            f"no assessment found for scope; withheld ({WithheldReason.ASSESSMENT_NOT_FOUND.value})",
        )
        return ReportSummary(
            ok=False, outcome=ReportOutcome.WITHHELD,
            withheld_reason=WithheldReason.ASSESSMENT_NOT_FOUND,
        )

    assessment = read.assessment
    source_ids = tuple(assessment.get("source_analysis_ids", ()))

    # 2. Read analysis + readings for ASSEMBLY.
    analysis = get_analysis_results(source_ids, sources)
    validated_ids = tuple(
        vid for row in analysis.results for vid in row.get("source_validated_ids", ())
    )
    # appendix_max_rows may be a TODO sentinel (NaN); fall back to 0 rows rather than crash.
    max_rows = int(config.appendix_max_rows) if config.appendix_max_rows == config.appendix_max_rows else 0
    readings = get_validated_readings(validated_ids, sources, max_rows=max_rows)

    # 3. Assemble the model (copy-only).
    model = assemble_report(assessment, analysis, readings, config, headlines, rendered_at=rendered_at)

    # 4. Fidelity gate against a FRESH authoritative read of the source of record (catches drift).
    verify_analysis = get_analysis_results(source_ids, sources)
    verify_readings = get_validated_readings(validated_ids, sources, max_rows=max_rows)
    # Index every band headline PLUS the withheld headline, so a withheld-score report's exec
    # headline (source_ref headline_table:WITHHELD) traces to a legitimate config source.
    headline_pairs = tuple((s.value, headlines.headline_for(s)) for s in Severity) + (
        ("WITHHELD", headlines.withheld_headline()),
    )
    index = build_source_index(
        assessment, verify_analysis.results, verify_readings.readings, headline_pairs,
    )
    verdict = fidelity_check(model, index, tolerance=config.fidelity_tolerance)
    if not verdict.passed:
        # A first-class WITHHELD report_artifacts row (the assessment identity is known).
        result = ReportResult(
            bridge_id=assessment["bridge_id"], cycle_id=assessment["cycle_id"],
            assessment_id=assessment["id"], assessment_version=assessment["assessment_version"],
            outcome=ReportOutcome.WITHHELD, marks=(),
            withheld_reason=WithheldReason.PROVENANCE_MISMATCH, artifact_ref=None,
            source_analysis_ids=source_ids,
            standard_code=assessment.get("standard_code"),
            standard_version=assessment.get("standard_version"),
            template_version=config.report_template_version, rendered_at=rendered_at,
        )
        persist_report(store, result)
        return ReportSummary.from_result(result)

    # 5. Render (via the port). A render failure is caught by run_report -> ERROR (no artifact).
    artifact = renderer.render(model)

    # 6. Determine marks.
    marks = determine_marks(assessment, model.sections, historical=historical)

    # 7. Atomic write: the artifact row + audit, only after a successful render.
    result = ReportResult(
        bridge_id=assessment["bridge_id"], cycle_id=assessment["cycle_id"],
        assessment_id=assessment["id"], assessment_version=assessment["assessment_version"],
        outcome=ReportOutcome.RENDERED, marks=marks, withheld_reason=None,
        artifact_ref=artifact.artifact_ref,
        source_analysis_ids=source_ids,
        standard_code=assessment.get("standard_code"),
        standard_version=assessment.get("standard_version"),
        template_version=config.report_template_version, rendered_at=rendered_at,
    )
    persist_report(store, result)
    return ReportSummary.from_result(result)
