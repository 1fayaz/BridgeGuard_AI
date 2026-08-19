"""G603 — PdfRenderer.render(report_model) (ReportLab) [RENDER-DEP].

Assembles the multi-page PDF (cover -> exec summary -> tables -> charts -> math -> recommendations
-> appendix -> sign-off) from the fidelity-checked model + chart images, via ReportLab, in-process
(no sandbox). A section marked unavailable renders a conspicuous "data unavailable" block, never
fabricated content. Every printed value is one already in the model.

[RENDER-DEP] ReportLab is not installed locally. The PURE PDF PLAN — the ordered blocks, which are
available vs. a "data unavailable" placeholder, and exactly which model values each block prints —
is fully tested here. The actual PDF byte production is guarded behind REPORTLAB_AVAILABLE: when
present, render() returns a RenderedArtifact with real bytes; when absent, it returns the artifact
ref with bytes deferred (flagged, not faked). PdfRenderer implements RenderPort so it drops into
the service (G901) unchanged.

Acceptance (tasks.md G603): produces an artifact from the model; every printed value is one already
in the model; an unavailable section renders the marked block, not fabricated content; runs
in-process (no E2B/shell-out).
"""
from __future__ import annotations

from agents.report_generation.render.charts import chart_images
from agents.report_generation.render.pdf import (
    REPORTLAB_AVAILABLE,
    PdfBlock,
    PdfRenderer,
    build_pdf_plan,
)
from agents.report_generation.render.port import RenderPort, RenderedArtifact
from agents.report_generation.model import ReportModel, ReportSection, Slot


def _model(math_available=True, appendix_available=True):
    return ReportModel(
        bridge_id="bridge-7", assessment_id=1001, assessment_version=3, severity="WARNING",
        rendered_at="T",
        sections=(
            ReportSection(name="exec_summary", available=True, slots=(
                Slot("Deflection elevated at pier 3.", "risk_assessments:1001:explanation"),
                Slot(48, "risk_assessments:1001:risk_score"),
                Slot("WARNING", "risk_assessments:1001:severity"),
                Slot("Elevated readings; review recommended.", "headline_table:WARNING"),
                Slot("Schedule inspection.", "risk_assessments:1001:recommendation"),
            )),
            (ReportSection(name="math_results", available=True, slots=(
                Slot({"ratio": 0.62}, "analysis_results:11:result"),
            )) if math_available else ReportSection(name="math_results", available=False, slots=())),
            (ReportSection(name="appendix", available=True, slots=(
                Slot(1.1, "validated_readings:110:value"),
            )) if appendix_available else ReportSection(name="appendix", available=False, slots=())),
        ),
    )


# ------------------------------------------------------------------ PDF plan (pure) ---
def test_plan_has_ordered_document_blocks():
    plan = build_pdf_plan(_model(), charts=())
    kinds = [b.kind for b in plan.blocks]
    # cover first, sign-off last; the section blocks in between
    assert kinds[0] == "cover"
    assert kinds[-1] == "sign_off"
    assert "exec_summary" in kinds


def test_available_section_block_prints_only_model_values():
    plan = build_pdf_plan(_model(), charts=())
    exec_block = next(b for b in plan.blocks if b.kind == "exec_summary")
    assert exec_block.available is True
    # every printed value on the block traces to a model slot value
    assert 48 in exec_block.values
    assert "Deflection elevated at pier 3." in exec_block.values
    assert "Elevated readings; review recommended." in exec_block.values


def test_unavailable_section_renders_a_marked_placeholder_not_fabrication():
    plan = build_pdf_plan(_model(math_available=False), charts=())
    math_block = next(b for b in plan.blocks if b.kind == "math_results")
    assert math_block.available is False
    assert math_block.values == ()                 # nothing printed
    assert math_block.placeholder == "DATA UNAVAILABLE"


def test_no_block_prints_a_value_absent_from_the_model():
    m = _model()
    model_values = {s.value if not isinstance(s.value, dict) else repr(s.value)
                    for s in m.all_slots()}
    plan = build_pdf_plan(m, charts=())
    for b in plan.blocks:
        for v in b.values:
            key = v if not isinstance(v, dict) else repr(v)
            assert key in model_values, f"block {b.kind} prints {v!r} not in the model"


def test_chart_block_references_only_supplied_chart_images():
    charts = chart_images(_model(), chart_sections=("appendix",)).images
    plan = build_pdf_plan(_model(), charts=charts)
    chart_block = next(b for b in plan.blocks if b.kind == "charts")
    assert chart_block.available is True
    assert chart_block.chart_count == 1


def test_no_chart_images_makes_charts_block_unavailable():
    plan = build_pdf_plan(_model(), charts=())
    chart_block = next(b for b in plan.blocks if b.kind == "charts")
    assert chart_block.available is False
    assert chart_block.placeholder == "DATA UNAVAILABLE"


# ------------------------------------------------------------------ RenderPort ---
def test_pdf_renderer_satisfies_render_port():
    assert isinstance(PdfRenderer(), RenderPort)


def test_render_returns_an_artifact_with_a_ref():
    art = PdfRenderer().render(_model())
    assert isinstance(art, RenderedArtifact)
    assert art.artifact_ref                        # a stable ref regardless of byte availability
    assert art.artifact_ref.endswith("1001-v3.pdf")


def test_render_is_deterministic_ref():
    a = PdfRenderer().render(_model())
    b = PdfRenderer().render(_model())
    assert a.artifact_ref == b.artifact_ref        # identity+version derived, no clock/random


# ------------------------------------------------------------------ [RENDER-DEP] bytes ---
def test_pdf_bytes_present_only_when_reportlab_installed():
    art = PdfRenderer().render(_model())
    if REPORTLAB_AVAILABLE:
        assert art.byte_size is not None and art.byte_size > 0
    else:
        assert art.byte_size is None               # deferred, flagged not faked


def test_render_runs_in_process_no_shell_out():
    # Structural: the pdf module imports no subprocess/sandbox — asserted by the constitution
    # check (G1103) across the package. Here we simply prove render() completes synchronously.
    art = PdfRenderer().render(_model(math_available=False, appendix_available=False))
    assert art.artifact_ref                        # degraded model still renders (marked blocks)
