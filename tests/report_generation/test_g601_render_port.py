"""G601 — RenderPort seam + FakeRenderer (deterministic stub).

The real render step calls ReportLab + matplotlib to turn a ReportModel into PDF bytes. That is
the only [RENDER-DEP] part of the agent, and neither library is installed. Everything around it
(assembly, fidelity gate, marks, persistence, the service) is deterministic and must be testable
without a live renderer. This stub stands in: given a ReportModel it records the model it was
handed and returns a deterministic fake artifact ref — so Phases 7/8/9 exercise every control-flow
branch without producing real bytes.

It implements the same `render(report_model) -> RenderedArtifact` shape the service (G901) calls,
so swapping in the real renderer (G603) changes only the produced BYTES, never the control flow.
Determinism is structural (no randomness, no clock) — required for reproducible tests + resume.

Acceptance (tasks.md G601): the fake records the exact model handed to it and returns a stable
ref; swapping in the real renderer changes only the bytes, not the flow.
"""
from __future__ import annotations

from agents.report_generation.assembler import assemble_report
from agents.report_generation.config.headline_table import HeadlineTable
from agents.report_generation.config.report_config import ReportConfig
from agents.report_generation.render.port import RenderedArtifact, RenderPort
from agents.report_generation.render.fake_renderer import FakeRenderer
from agents.report_generation.model import ReportModel, ReportSection, Slot
from agents.report_generation.tools.analysis_results_read import AnalysisResultsReadResult
from agents.report_generation.tools.validated_readings_read import ValidatedReadingsReadResult
from agents.risk_reasoning.statuses import Severity


HEADLINES = HeadlineTable(
    phrases=tuple((s, f"HEADLINE::{s.value}") for s in Severity),
    withheld_phrase="HEADLINE::WITHHELD",
)
CONFIG = ReportConfig(
    report_template_version="rev2", appendix_max_rows=500,
    letterhead_ref="lh.png", template_ref="t.html",
)


def _model():
    return ReportModel(
        bridge_id="bridge-7", assessment_id=1001, assessment_version=3, severity="WARNING",
        rendered_at="T",
        sections=(
            ReportSection(name="exec_summary", available=True, slots=(
                Slot(48, "risk_assessments:1001:risk_score"),
            )),
            ReportSection(name="charts", available=False, slots=()),
        ),
    )


# ------------------------------------------------------------------ protocol ---
def test_fake_renderer_satisfies_the_render_port():
    r = FakeRenderer()
    assert isinstance(r, RenderPort)


# ------------------------------------------------------------------ records ---
def test_records_the_exact_model_handed_to_it():
    r = FakeRenderer()
    m = _model()
    r.render(m)
    assert r.rendered_models == [m]           # the exact model object, for assertion in later phases


def test_records_each_render_in_order():
    r = FakeRenderer()
    a, b = _model(), _model()
    r.render(a)
    r.render(b)
    assert r.rendered_models == [a, b]


# ------------------------------------------------------------------ deterministic ref ---
def test_returns_a_rendered_artifact_with_a_stable_ref():
    r = FakeRenderer()
    art = r.render(_model())
    assert isinstance(art, RenderedArtifact)
    assert art.artifact_ref                    # non-empty
    # deterministic: same model identity -> same ref (no clock/random)
    r2 = FakeRenderer()
    assert r2.render(_model()).artifact_ref == art.artifact_ref


def test_ref_distinguishes_different_assessments():
    r = FakeRenderer()
    a = r.render(_model())
    other = ReportModel(
        bridge_id="bridge-7", assessment_id=2002, assessment_version=1, severity="SAFE",
        rendered_at="T",
        sections=(ReportSection(name="exec_summary", available=True, slots=(
            Slot(5, "risk_assessments:2002:risk_score"),
        )),),
    )
    b = r.render(other)
    assert a.artifact_ref != b.artifact_ref     # ref encodes identity+version


# ------------------------------------------------------------------ swap-in fidelity ---
def test_fake_renders_a_model_assembled_by_the_real_assembler():
    # The seam accepts exactly what the pipeline produces — proves control-flow compatibility.
    assessment = dict(
        id=1001, bridge_id="bridge-7", cycle_id="cycle-42", assessment_version=3,
        risk_score=48, severity="WARNING", recommendation="Inspect.",
        explanation="Elevated.", review_status="FINAL", source_analysis_ids=[11],
        standard_code="AASHTO", standard_version="2020", superseded_by=None,
    )
    analysis = AnalysisResultsReadResult(
        available=True, results=({"id": 11, "result": {"ratio": 0.62}, "source_validated_ids": [110]},),
        missing_ids=())
    readings = ValidatedReadingsReadResult(
        available=True, readings=({"id": 110, "value": 1.1},), missing_ids=(),
        truncated=False, total_available=1)
    m = assemble_report(assessment, analysis, readings, CONFIG, HEADLINES, rendered_at="T")

    art = FakeRenderer().render(m)
    assert art.artifact_ref
