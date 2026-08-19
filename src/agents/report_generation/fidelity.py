"""The fidelity gate (G501) — the report-layer anti-drift control (FR-5).

Every value a report prints must EQUAL the finalized upstream value it claims to come from. This
gate walks every slot in an assembled ReportModel and checks its value against a `source_index`
built from the finalized rows (plus the headline config table — the legitimate source for the one
value the report does not copy from a row). A slot whose value matches no source value is
OFFENDING; any offending slot fails the gate, and the service withholds the report
(PROVENANCE_MISMATCH) and writes no document. Fail-closed: an untraceable value never reaches a
government artifact.

Comparison is on the slot's BOUND (raw) value, never a formatted string — display formatting is
applied later at render, not here. Numbers compare within `tolerance` (0.0 = exact, the fail-safe
default); everything else compares by equality.

Pure function: it reads the model + index and returns a verdict; it mutates nothing and involves
no model.
"""
from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from typing import Any

from agents.report_generation.model import ReportModel


@dataclass(frozen=True, slots=True)
class FidelityVerdict:
    """The gate's result: passed, plus the (source_ref, value) pairs that traced to no source."""

    passed: bool
    offending: tuple[tuple[str, Any], ...]


def build_source_index(
    assessment: dict[str, Any],
    analysis: tuple[dict[str, Any], ...],
    readings: tuple[dict[str, Any], ...],
    headline_pairs: tuple[tuple[str, str], ...],
) -> dict[str, Any]:
    """Build the authoritative source_ref -> value map from the finalized rows + headline config.

    The keys mirror exactly the source_refs the assembler (G402) stamps on its slots, so a slot is
    verified by looking up its own source_ref and comparing values.
    """
    aid = assessment["id"]
    index: dict[str, Any] = {
        f"risk_assessments:{aid}:risk_score": assessment.get("risk_score"),
        f"risk_assessments:{aid}:severity": assessment.get("severity"),
        f"risk_assessments:{aid}:explanation": assessment.get("explanation"),
        f"risk_assessments:{aid}:recommendation": assessment.get("recommendation"),
    }
    for row in analysis:
        index[f"analysis_results:{row['id']}:result"] = row["result"]
    for r in readings:
        index[f"validated_readings:{r['id']}:value"] = r["value"]
    # The headline is config, not a row: it is a legitimate source for the one non-copied value.
    for severity_str, phrase in headline_pairs:
        index[f"headline_table:{severity_str}"] = phrase
    return index


def _matches(slot_value: Any, source_value: Any, tolerance: float) -> bool:
    """True if the slot value equals the source value (numbers within tolerance; else equality).

    bool is excluded from the numeric branch (bool is a subclass of int) so True/1 don't conflate.
    """
    if (
        isinstance(slot_value, Real)
        and isinstance(source_value, Real)
        and not isinstance(slot_value, bool)
        and not isinstance(source_value, bool)
    ):
        return abs(float(slot_value) - float(source_value)) <= tolerance
    return slot_value == source_value


def fidelity_check(
    report_model: ReportModel,
    source_index: dict[str, Any],
    tolerance: float,
) -> FidelityVerdict:
    """Verify every printed slot traces to a source value (G501). Pure; fail-closed on any drift."""
    offending: list[tuple[str, Any]] = []
    for slot in report_model.all_slots():
        if slot.source_ref not in source_index:
            # No such source -> cannot be traced -> offending (untraceable value).
            offending.append((slot.source_ref, slot.value))
            continue
        if not _matches(slot.value, source_index[slot.source_ref], tolerance):
            offending.append((slot.source_ref, slot.value))
    return FidelityVerdict(passed=not offending, offending=tuple(offending))
