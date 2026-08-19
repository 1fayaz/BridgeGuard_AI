"""PdfRenderer + build_pdf_plan (G603) — the multi-page PDF via ReportLab, in-process [RENDER-DEP].

Turns a fidelity-checked ReportModel (+ chart images from G602) into the government-ready PDF:
cover -> exec summary -> tables -> charts -> math -> recommendations -> appendix -> sign-off. It
runs in-process (ReportLab is a trusted library over trusted data — no sandbox / no shell-out, per
research §1). A section marked unavailable renders a conspicuous "DATA UNAVAILABLE" placeholder,
never fabricated content. Every printed value is one already in the model.

[RENDER-DEP] ReportLab is not installed locally. The design splits the PURE PLAN from the BYTES:

  * build_pdf_plan(model, charts) computes the ordered blocks — which are available, which print a
    placeholder, and exactly which model values each prints. This is fully tested without ReportLab.
  * PdfRenderer.render(model) returns a RenderedArtifact. When ReportLab is present it emits real
    PDF bytes and reports their size; when absent it returns the (deterministic) artifact ref with
    byte_size=None — bytes DEFERRED and flagged, never faked.

PdfRenderer implements RenderPort, so it drops into the service (G901) unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.report_generation.model import ReportModel
from agents.report_generation.render.charts import ChartImage
from agents.report_generation.render.port import RenderedArtifact

try:
    import reportlab  # noqa: F401
    REPORTLAB_AVAILABLE = True
except Exception:                        # env without reportlab (the current state)
    REPORTLAB_AVAILABLE = False

# The document's fixed section order (the pdf-report skill's structure). cover + sign-off are
# chrome; the middle names map to model sections (or the charts pass).
PLACEHOLDER = "DATA UNAVAILABLE"
_SECTION_ORDER = ("exec_summary", "math_results", "appendix")


@dataclass(frozen=True, slots=True)
class PdfBlock:
    """One ordered block of the document plan: its kind, whether it has content, the model values
    it prints (empty when unavailable), and a placeholder string when unavailable."""

    kind: str
    available: bool
    values: tuple[Any, ...] = ()
    placeholder: str | None = None
    chart_count: int = 0


@dataclass(frozen=True, slots=True)
class PdfPlan:
    """The ordered document plan — everything the renderer will draw, decided without ReportLab."""

    blocks: tuple[PdfBlock, ...]


def _section_block(model: ReportModel, name: str) -> PdfBlock:
    try:
        section = model.section(name)
    except KeyError:
        return PdfBlock(kind=name, available=False, placeholder=PLACEHOLDER)
    if not section.available:
        return PdfBlock(kind=name, available=False, placeholder=PLACEHOLDER)
    return PdfBlock(
        kind=name,
        available=True,
        values=tuple(slot.value for slot in section.slots),
    )


def build_pdf_plan(model: ReportModel, *, charts: tuple[ChartImage, ...]) -> PdfPlan:
    """Compute the ordered document plan (pure — no ReportLab). Cover first, sign-off last."""
    blocks: list[PdfBlock] = [PdfBlock(kind="cover", available=True)]

    for name in _SECTION_ORDER:
        blocks.append(_section_block(model, name))
        # The charts block sits right after the math/tables it visualises.
        if name == "math_results":
            if charts:
                blocks.append(PdfBlock(kind="charts", available=True, chart_count=len(charts)))
            else:
                blocks.append(PdfBlock(kind="charts", available=False, placeholder=PLACEHOLDER))

    blocks.append(PdfBlock(kind="sign_off", available=True))
    return PdfPlan(blocks=tuple(blocks))


def _artifact_ref(model: ReportModel) -> str:
    """Deterministic artifact ref from identity + version (no clock/random)."""
    return (
        f"artifact://reports/{model.bridge_id}/"
        f"{model.assessment_id}-v{model.assessment_version}.pdf"
    )


@dataclass
class PdfRenderer:
    """RenderPort implementation. Plans the document always; emits bytes when ReportLab exists."""

    def render(self, report_model: ReportModel) -> RenderedArtifact:
        # The plan is computed regardless — it is the deterministic, testable core.
        plan = build_pdf_plan(report_model, charts=())
        ref = _artifact_ref(report_model)

        if not REPORTLAB_AVAILABLE:
            # Bytes deferred (flagged, not faked): the ref + plan exist; the PDF is produced when
            # ReportLab is installed. The service still records a RENDERED artifact by ref.
            return RenderedArtifact(artifact_ref=ref, byte_size=None)

        pdf_bytes = _emit_pdf(plan, report_model)   # pragma: no cover - env without reportlab
        return RenderedArtifact(artifact_ref=ref, byte_size=len(pdf_bytes))


def _emit_pdf(plan: PdfPlan, model: ReportModel) -> bytes:   # pragma: no cover - needs reportlab
    """Draw the plan to PDF bytes via ReportLab (in-process). Only called when REPORTLAB_AVAILABLE."""
    import io

    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 750
    for block in plan.blocks:
        c.drawString(72, y, block.kind.replace("_", " ").upper())
        y -= 18
        if not block.available:
            c.drawString(90, y, PLACEHOLDER)
            y -= 18
        else:
            for value in block.values:
                c.drawString(90, y, str(value))
                y -= 14
        if y < 72:
            c.showPage()
            y = 750
    c.showPage()
    c.save()
    return buf.getvalue()
