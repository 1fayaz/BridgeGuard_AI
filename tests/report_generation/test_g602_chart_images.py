"""G602 — chart_images(report_model) (matplotlib/Agg) [RENDER-DEP].

Renders each AVAILABLE chart-data block to a static PNG via matplotlib's headless Agg backend (no
browser). A block whose section is unavailable is SKIPPED and its section marked unavailable (FR-6)
— never drawn empty. Charts plot ONLY values already in the model (no new analytical quantity is
computed — FR-1).

[RENDER-DEP] matplotlib is not installed locally. The PURE decision (which blocks are chartable,
which are skipped, which values + provenance get plotted) is fully tested here; the actual PNG byte
production is guarded behind MATPLOTLIB_AVAILABLE and asserted only when the library exists. Live
byte generation is deferred — flagged, not faked.

Acceptance (tasks.md G602): each available chart block yields a chart (PNG when matplotlib exists);
an unavailable block yields no image + a SECTION_UNAVAILABLE mark; no chart derives a new quantity.
"""
from __future__ import annotations

from agents.report_generation.render.charts import (
    MATPLOTLIB_AVAILABLE,
    ChartImage,
    chart_images,
)
from agents.report_generation.report_statuses import DocumentMark
from agents.report_generation.model import ReportModel, ReportSection, Slot


def _model(appendix_available=True, charts_available=True):
    appendix = (
        ReportSection(name="appendix", available=True, slots=(
            Slot(1.1, "validated_readings:110:value"),
            Slot(2.2, "validated_readings:120:value"),
            Slot(3.3, "validated_readings:130:value"),
        ))
        if appendix_available
        else ReportSection(name="appendix", available=False, slots=())
    )
    charts = (
        ReportSection(name="charts", available=True, slots=(
            Slot(0.62, "analysis_results:11:ratio"),
        ))
        if charts_available
        else ReportSection(name="charts", available=False, slots=())
    )
    return ReportModel(
        bridge_id="bridge-7", assessment_id=1001, assessment_version=3, severity="WARNING",
        rendered_at="T",
        sections=(
            ReportSection(name="exec_summary", available=True, slots=(
                Slot(48, "risk_assessments:1001:risk_score"),
            )),
            appendix,
            charts,
        ),
    )


# ------------------------------------------------------------------ available -> chart ---
def test_available_chart_section_yields_a_chart():
    res = chart_images(_model(), chart_sections=("appendix",))
    assert len(res.images) == 1
    assert isinstance(res.images[0], ChartImage)
    assert res.images[0].section == "appendix"


def test_chart_plots_only_the_model_slot_values():
    # No new analytical quantity — the plotted series is exactly the slot values (FR-1).
    res = chart_images(_model(), chart_sections=("appendix",))
    img = res.images[0]
    assert img.values == (1.1, 2.2, 3.3)
    assert img.source_refs == (
        "validated_readings:110:value",
        "validated_readings:120:value",
        "validated_readings:130:value",
    )


def test_multiple_chart_sections_each_yield_a_chart():
    res = chart_images(_model(), chart_sections=("appendix", "charts"))
    sections = {img.section for img in res.images}
    assert sections == {"appendix", "charts"}


# ------------------------------------------------------------------ unavailable -> skip + mark ---
def test_unavailable_chart_section_is_skipped_and_marked():
    res = chart_images(_model(appendix_available=False), chart_sections=("appendix",))
    assert res.images == ()
    assert DocumentMark.SECTION_UNAVAILABLE in res.marks
    assert "appendix" in res.unavailable_sections


def test_missing_chart_section_is_treated_as_unavailable():
    # A requested chart section not present in the model at all -> unavailable, not a raise.
    res = chart_images(_model(), chart_sections=("nonexistent",))
    assert res.images == ()
    assert DocumentMark.SECTION_UNAVAILABLE in res.marks
    assert "nonexistent" in res.unavailable_sections


def test_mixed_available_and_unavailable():
    res = chart_images(
        _model(appendix_available=True, charts_available=False),
        chart_sections=("appendix", "charts"),
    )
    assert [img.section for img in res.images] == ["appendix"]
    assert "charts" in res.unavailable_sections
    assert DocumentMark.SECTION_UNAVAILABLE in res.marks


def test_no_marks_when_all_available():
    res = chart_images(_model(), chart_sections=("appendix", "charts"))
    assert res.marks == ()
    assert res.unavailable_sections == ()


# ------------------------------------------------------------------ never raises ---
def test_empty_chart_sections_yields_nothing_no_raise():
    res = chart_images(_model(), chart_sections=())
    assert res.images == ()
    assert res.marks == ()


# ------------------------------------------------------------------ [RENDER-DEP] bytes ---
def test_png_bytes_present_only_when_matplotlib_is_installed():
    # Honest RENDER-DEP branch: with matplotlib, the chart carries PNG bytes; without it, the chart
    # is still planned (available, values + provenance recorded) but bytes are deferred (None).
    res = chart_images(_model(), chart_sections=("appendix",))
    img = res.images[0]
    if MATPLOTLIB_AVAILABLE:
        assert img.png is not None and len(img.png) > 0
        assert img.png[:8] == b"\x89PNG\r\n\x1a\n"   # PNG magic
    else:
        assert img.png is None                        # deferred, flagged not faked
        assert img.bytes_deferred is True
