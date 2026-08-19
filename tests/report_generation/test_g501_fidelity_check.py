"""G501 — fidelity_check(report_model, source_index, tolerance) (pure, FR-5).

The report-layer anti-drift gate. For every slot in the ReportModel, verify its value EQUALS the
authoritative value at its source_ref in a source_index built from the finalized rows (+ the
headline config table — the legitimate source for the one non-copied value). Exact match by
default (tolerance 0.0). A slot whose value matches no source value is offending -> the gate fails
-> the service withholds (PROVENANCE_MISMATCH) and writes no document.

Comparison is on the slot's BOUND (raw) value, never a formatted string — display formatting is
applied later at render, not here.

Acceptance (tasks.md G501): a model whose every slot traces -> pass; a slot value absent from any
source -> fail, naming the offending slot+value; a value within 0.0 (exact) -> pass; formatting
differences are moot (raw values compared); tolerance comes from config.
"""
from __future__ import annotations

from agents.report_generation.fidelity import build_source_index, fidelity_check
from agents.report_generation.model import ReportModel, ReportSection, Slot


def _index():
    # An authoritative source_ref -> value map, as build_source_index would produce.
    return {
        "risk_assessments:1001:risk_score": 48,
        "risk_assessments:1001:severity": "WARNING",
        "risk_assessments:1001:explanation": "Deflection elevated at pier 3.",
        "risk_assessments:1001:recommendation": "Schedule inspection.",
        "headline_table:WARNING": "Elevated readings; review recommended.",
        "analysis_results:11:result": {"ratio": 0.62},
        "validated_readings:110:value": 1.1,
    }


def _clean_model():
    return ReportModel(
        bridge_id="bridge-7", assessment_id=1001, assessment_version=3, severity="WARNING",
        rendered_at="T",
        sections=(
            ReportSection(name="exec_summary", available=True, slots=(
                Slot(48, "risk_assessments:1001:risk_score"),
                Slot("WARNING", "risk_assessments:1001:severity"),
                Slot("Deflection elevated at pier 3.", "risk_assessments:1001:explanation"),
                Slot("Elevated readings; review recommended.", "headline_table:WARNING"),
            )),
            ReportSection(name="math_results", available=True, slots=(
                Slot({"ratio": 0.62}, "analysis_results:11:result"),
            )),
            ReportSection(name="appendix", available=True, slots=(
                Slot(1.1, "validated_readings:110:value"),
            )),
        ),
    )


# ------------------------------------------------------------------ pass ---
def test_clean_model_passes():
    v = fidelity_check(_clean_model(), _index(), tolerance=0.0)
    assert v.passed is True
    assert v.offending == ()


def test_exact_number_match_passes():
    v = fidelity_check(_clean_model(), _index(), tolerance=0.0)
    assert v.passed is True  # 48 == 48, 1.1 == 1.1 exactly


def test_nested_payload_matches_by_content():
    # The analysis payload {"ratio": 0.62} matches its source exactly.
    v = fidelity_check(_clean_model(), _index(), tolerance=0.0)
    assert v.passed is True


# ------------------------------------------------------------------ fail ---
def test_offbook_number_is_caught_and_named():
    m = _clean_model()
    # Inject a fabricated score that appears in NO source row.
    bad = ReportModel(
        bridge_id=m.bridge_id, assessment_id=m.assessment_id,
        assessment_version=m.assessment_version, severity=m.severity, rendered_at=m.rendered_at,
        sections=(
            ReportSection(name="exec_summary", available=True, slots=(
                Slot(99, "risk_assessments:1001:risk_score"),  # source says 48
            )),
        ),
    )
    v = fidelity_check(bad, _index(), tolerance=0.0)
    assert v.passed is False
    assert any(ref == "risk_assessments:1001:risk_score" and val == 99 for ref, val in v.offending)


def test_reworded_explanation_is_caught():
    m = _clean_model()
    bad = ReportModel(
        bridge_id=m.bridge_id, assessment_id=m.assessment_id,
        assessment_version=m.assessment_version, severity=m.severity, rendered_at=m.rendered_at,
        sections=(
            ReportSection(name="exec_summary", available=True, slots=(
                Slot("Deflection was elevated.", "risk_assessments:1001:explanation"),  # reworded
            )),
        ),
    )
    v = fidelity_check(bad, _index(), tolerance=0.0)
    assert v.passed is False
    assert any(ref.endswith(":explanation") for ref, _ in v.offending)


def test_unknown_source_ref_is_offending():
    # A slot referencing a source that does not exist cannot be traced -> offending.
    bad = ReportModel(
        bridge_id="b", assessment_id=1001, assessment_version=3, severity="WARNING", rendered_at="T",
        sections=(
            ReportSection(name="exec_summary", available=True, slots=(
                Slot(48, "risk_assessments:1001:phantom_field"),
            )),
        ),
    )
    v = fidelity_check(bad, _index(), tolerance=0.0)
    assert v.passed is False
    assert any(ref.endswith(":phantom_field") for ref, _ in v.offending)


# ------------------------------------------------------------------ tolerance ---
def test_tolerance_zero_rejects_any_numeric_drift():
    m = ReportModel(
        bridge_id="b", assessment_id=1001, assessment_version=3, severity="WARNING", rendered_at="T",
        sections=(ReportSection(name="appendix", available=True, slots=(
            Slot(1.10001, "validated_readings:110:value"),  # source is 1.1
        )),),
    )
    v = fidelity_check(m, _index(), tolerance=0.0)
    assert v.passed is False


def test_nonzero_tolerance_admits_values_within_band():
    m = ReportModel(
        bridge_id="b", assessment_id=1001, assessment_version=3, severity="WARNING", rendered_at="T",
        sections=(ReportSection(name="appendix", available=True, slots=(
            Slot(1.104, "validated_readings:110:value"),  # source 1.1, within 0.01
        )),),
    )
    assert fidelity_check(m, _index(), tolerance=0.01).passed is True
    assert fidelity_check(m, _index(), tolerance=0.0).passed is False


# ------------------------------------------------------------------ unavailable sections skipped ---
def test_unavailable_sections_contribute_no_checks():
    m = ReportModel(
        bridge_id="b", assessment_id=1001, assessment_version=3, severity="WARNING", rendered_at="T",
        sections=(
            ReportSection(name="exec_summary", available=True, slots=(
                Slot(48, "risk_assessments:1001:risk_score"),
            )),
            ReportSection(name="charts", available=False, slots=()),  # no slots -> nothing to check
        ),
    )
    assert fidelity_check(m, _index(), tolerance=0.0).passed is True


# ------------------------------------------------------------------ build_source_index ---
def test_build_source_index_maps_finalized_values():
    assessment = dict(
        id=1001, risk_score=48, severity="WARNING",
        explanation="Deflection elevated at pier 3.", recommendation="Schedule inspection.",
    )
    analysis = ({"id": 11, "result": {"ratio": 0.62}},)
    readings = ({"id": 110, "value": 1.1},)
    headline_pairs = (("WARNING", "Elevated readings; review recommended."),)

    idx = build_source_index(assessment, analysis, readings, headline_pairs)
    assert idx["risk_assessments:1001:risk_score"] == 48
    assert idx["risk_assessments:1001:explanation"] == "Deflection elevated at pier 3."
    assert idx["analysis_results:11:result"] == {"ratio": 0.62}
    assert idx["validated_readings:110:value"] == 1.1
    assert idx["headline_table:WARNING"] == "Elevated readings; review recommended."


def test_built_index_validates_the_assembled_model():
    # End-to-end: an index built from the finalized rows accepts the model assembled from them.
    assessment = dict(
        id=1001, risk_score=48, severity="WARNING",
        explanation="Deflection elevated at pier 3.", recommendation="Schedule inspection.",
    )
    analysis = ({"id": 11, "result": {"ratio": 0.62}},)
    readings = ({"id": 110, "value": 1.1},)
    headline_pairs = (("WARNING", "Elevated readings; review recommended."),)
    idx = build_source_index(assessment, analysis, readings, headline_pairs)
    assert fidelity_check(_clean_model(), idx, tolerance=0.0).passed is True
