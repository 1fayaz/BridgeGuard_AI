"""G401 — ReportModel shape (the assembled, pre-render document model).

The ReportModel is what the assembler (G402) builds and the renderer (G603) draws. Its defining
property: every value it will PRINT is held in a `Slot` that records BOTH the value AND the source
reference it was copied from — so the fidelity gate (G501) can verify each printed value traces to
a finalized upstream row (FR-5), and so nothing is ever computed into the document (FR-1).

Acceptance (tasks.md G401): constructs typed from finalized rows; each value slot records its
source ref; a section with no upstream content is marked available=False (not omitted, not faked).
"""
from __future__ import annotations

import pytest

from agents.report_generation.model import (
    ReportModel,
    ReportSection,
    Slot,
)


# ------------------------------------------------------------------ Slot ---
def test_slot_carries_value_and_source_reference():
    s = Slot(value=48, source_ref="risk_assessments:1001:risk_score")
    assert s.value == 48
    assert s.source_ref == "risk_assessments:1001:risk_score"


def test_slot_source_ref_is_required_nonempty():
    # A printed value with no provenance is exactly what FR-5 forbids — reject it at construction.
    with pytest.raises(ValueError):
        Slot(value=48, source_ref="")


def test_slot_value_may_be_any_copied_scalar():
    for v in (0, 48, 0.62, "WARNING", "Deflection elevated.", None):
        s = Slot(value=v, source_ref="risk_assessments:1001:field")
        assert s.value == v


# ------------------------------------------------------------------ ReportSection ---
def test_available_section_holds_slots():
    sec = ReportSection(
        name="exec_summary",
        available=True,
        slots=(Slot(value="Deflection elevated.", source_ref="risk_assessments:1001:explanation"),),
    )
    assert sec.available is True
    assert sec.name == "exec_summary"
    assert len(sec.slots) == 1


def test_unavailable_section_is_marked_not_omitted():
    # A section with no upstream content is present-but-empty and flagged, never silently dropped.
    sec = ReportSection(name="charts", available=False, slots=())
    assert sec.available is False
    assert sec.slots == ()


def test_available_section_with_no_slots_is_rejected():
    # available=True is a claim there IS content; it must carry at least one slot.
    with pytest.raises(ValueError):
        ReportSection(name="charts", available=True, slots=())


def test_unavailable_section_with_slots_is_rejected():
    # available=False means no content — it must not also carry slots (incoherent).
    with pytest.raises(ValueError):
        ReportSection(
            name="charts",
            available=False,
            slots=(Slot(value=1, source_ref="x:1:y"),),
        )


# ------------------------------------------------------------------ ReportModel ---
def _model(**over):
    base = dict(
        bridge_id="bridge-7",
        assessment_id=1001,
        assessment_version=3,
        severity="WARNING",
        rendered_at="RENDERED_AT_SEAM",
        sections=(
            ReportSection(
                name="exec_summary",
                available=True,
                slots=(
                    Slot(value="Deflection elevated at pier 3.",
                         source_ref="risk_assessments:1001:explanation"),
                    Slot(value=48, source_ref="risk_assessments:1001:risk_score"),
                ),
            ),
            ReportSection(name="charts", available=False, slots=()),
        ),
    )
    base.update(over)
    return ReportModel(**base)


def test_model_constructs_from_finalized_identity_fields():
    m = _model()
    assert m.bridge_id == "bridge-7"
    assert m.assessment_id == 1001
    assert m.assessment_version == 3
    assert m.severity == "WARNING"


def test_model_exposes_sections_by_name():
    m = _model()
    assert m.section("exec_summary").available is True
    assert m.section("charts").available is False


def test_all_slots_iterates_every_printed_value_with_provenance():
    # The fidelity gate (G501) walks exactly this: every slot across every available section.
    m = _model()
    slots = list(m.all_slots())
    # only the available section's slots are printable content
    assert len(slots) == 2
    assert all(s.source_ref for s in slots)
    values = {s.value for s in slots}
    assert 48 in values and "Deflection elevated at pier 3." in values


def test_unavailable_sections_contribute_no_printed_slots():
    m = _model()
    # the charts section is unavailable -> it yields nothing to the fidelity walk
    assert all(s.source_ref.startswith("risk_assessments:1001") for s in m.all_slots())


def test_section_lookup_of_unknown_name_raises():
    m = _model()
    with pytest.raises(KeyError):
        m.section("nonexistent")
