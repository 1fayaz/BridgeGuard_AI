"""assemble_report(...) (G402) — the pure "assemble, never re-decide" spine (FR-1).

Builds a ReportModel by COPYING finalized values into provenance-carrying Slots. The contract that
makes this agent safe: every slot value is either

  * a verbatim copy of a finalized upstream field (its source_ref names the row+field), or
  * the single fixed HeadlineTable lookup keyed on the band (its source_ref names the config
    table) — the ONE value in the whole document not taken from an upstream row.

Nothing here recomputes, re-derives, re-maps, or rewords an upstream value (that would create a
new, ungoverned narrative that bypasses the numeric-provenance guardrail the Risk Agent already
passed). A section whose upstream read came back unavailable is marked available=False (FR-6),
never fabricated.

Pure function: it reads its inputs and returns a ReportModel; it mutates nothing and uses no clock
(rendered_at is passed in).
"""
from __future__ import annotations

from typing import Any

from agents.report_generation.config.headline_table import HeadlineTable
from agents.report_generation.config.report_config import ReportConfig
from agents.report_generation.model import ReportModel, ReportSection, Slot
from agents.report_generation.tools.analysis_results_read import AnalysisResultsReadResult
from agents.report_generation.tools.validated_readings_read import ValidatedReadingsReadResult
from agents.risk_reasoning.statuses import Severity


def _exec_summary(assessment: dict[str, Any], headlines: HeadlineTable) -> ReportSection:
    """The exec summary: the verbatim explanation + the verdict values + the fixed band headline.

    Always available — the verdict and its WHY render even when data-backed sections degrade.
    """
    aid = assessment["id"]
    slots: list[Slot] = [
        # The WHY, copied byte-for-byte (FR-2). Never reworded.
        Slot(value=assessment["explanation"], source_ref=f"risk_assessments:{aid}:explanation"),
        Slot(value=assessment["risk_score"], source_ref=f"risk_assessments:{aid}:risk_score"),
        Slot(value=assessment["severity"], source_ref=f"risk_assessments:{aid}:severity"),
        Slot(value=assessment["recommendation"], source_ref=f"risk_assessments:{aid}:recommendation"),
    ]

    # The ONE non-copied value: a fixed lookup keyed on the band. Its provenance is the config
    # table, not an upstream row. When the score was withheld (no severity), use the withheld line.
    severity_str = assessment["severity"]
    if severity_str is None:
        headline = headlines.withheld_headline()
        slots.append(Slot(value=headline, source_ref="headline_table:WITHHELD"))
    else:
        headline = headlines.headline_for(Severity(severity_str))
        slots.append(Slot(value=headline, source_ref=f"headline_table:{severity_str}"))

    return ReportSection(name="exec_summary", available=True, slots=tuple(slots))


def _math_results(analysis: AnalysisResultsReadResult) -> ReportSection:
    """The math-results section: SA calculation payloads copied verbatim (FR-1).

    Unavailable (marked, FR-6) when the referenced analysis rows were missing.
    """
    if not analysis.available:
        return ReportSection(name="math_results", available=False, slots=())
    slots = tuple(
        Slot(value=row["result"], source_ref=f"analysis_results:{row['id']}:result")
        for row in analysis.results
    )
    return ReportSection(name="math_results", available=True, slots=slots)


def _appendix(readings: ValidatedReadingsReadResult) -> ReportSection:
    """The raw-data appendix: DCA reading values copied verbatim (FR-1), bounded upstream (G303).

    Unavailable (marked, FR-6) when the referenced readings were missing.
    """
    if not readings.available:
        return ReportSection(name="appendix", available=False, slots=())
    slots = tuple(
        Slot(value=r["value"], source_ref=f"validated_readings:{r['id']}:value")
        for r in readings.readings
    )
    return ReportSection(name="appendix", available=True, slots=slots)


def assemble_report(
    assessment: dict[str, Any],
    analysis: AnalysisResultsReadResult,
    readings: ValidatedReadingsReadResult,
    config: ReportConfig,
    headlines: HeadlineTable,
    *,
    rendered_at: str,
) -> ReportModel:
    """Assemble a ReportModel from finalized rows by copying (G402). Pure; mutates nothing."""
    sections = (
        _exec_summary(assessment, headlines),
        _math_results(analysis),
        _appendix(readings),
    )
    return ReportModel(
        bridge_id=assessment["bridge_id"],
        assessment_id=assessment["id"],
        assessment_version=assessment["assessment_version"],
        severity=assessment["severity"],
        rendered_at=rendered_at,
        sections=sections,
    )
