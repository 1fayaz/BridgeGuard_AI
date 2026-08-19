"""chart_images(report_model) (G602) — static PDF charts via matplotlib/Agg.

Turns each AVAILABLE chart-data section of a ReportModel into a static PNG using matplotlib's
headless `Agg` backend (no browser — the dashboard's Recharts/Plotly are a different, interactive
output). A section that is unavailable (or absent) is SKIPPED and reported as unavailable so the
service can add a SECTION_UNAVAILABLE mark (FR-6) — never drawn empty. A chart plots ONLY the slot
values already in the model; it derives no new analytical quantity (FR-1).

[RENDER-DEP] matplotlib may not be installed in every environment. The PURE decision — which
sections are chartable, which are skipped, and exactly which values + provenance would be plotted —
is computed regardless. The PNG byte production is guarded behind MATPLOTLIB_AVAILABLE: when the
library is present, each available chart carries real PNG bytes; when it is absent, the chart is
still planned (values + provenance recorded) and `png` is left None with `bytes_deferred=True`
(deferred, flagged — never faked).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.report_generation.model import ReportModel
from agents.report_generation.report_statuses import DocumentMark

try:
    import matplotlib
    matplotlib.use("Agg")               # headless — must be set before pyplot is imported
    import matplotlib.pyplot as _plt
    MATPLOTLIB_AVAILABLE = True
except Exception:                        # pragma: no cover - env without matplotlib
    _plt = None
    MATPLOTLIB_AVAILABLE = False


@dataclass(frozen=True, slots=True)
class ChartImage:
    """One planned chart: which section, the exact plotted values + their provenance, and (when
    matplotlib is present) the rendered PNG bytes."""

    section: str
    values: tuple[float, ...]
    source_refs: tuple[str, ...]
    png: bytes | None = None
    bytes_deferred: bool = False


@dataclass(frozen=True, slots=True)
class ChartImagesResult:
    """The chart pass result: the produced charts, plus which requested sections were unavailable
    and the marks that implies."""

    images: tuple[ChartImage, ...]
    unavailable_sections: tuple[str, ...]
    marks: tuple[DocumentMark, ...]


def _render_png(values: tuple[float, ...]) -> bytes | None:
    """Render a simple line chart of `values` to PNG bytes via Agg. None if matplotlib is absent."""
    if not MATPLOTLIB_AVAILABLE:            # pragma: no cover - env without matplotlib
        return None
    import io

    fig = _plt.figure()
    try:
        ax = fig.add_subplot(1, 1, 1)
        ax.plot(range(len(values)), list(values))
        buf = io.BytesIO()
        fig.savefig(buf, format="png")
        return buf.getvalue()
    finally:
        _plt.close(fig)                      # release the figure — no state leak between charts


def chart_images(
    report_model: ReportModel,
    *,
    chart_sections: tuple[str, ...],
) -> ChartImagesResult:
    """Render the model's available chart sections to PNGs (G602). Never raises.

    `chart_sections` names which sections carry chartable series (e.g. ("appendix", "charts")).
    Each available one yields a ChartImage; each unavailable/absent one is reported as unavailable.
    """
    images: list[ChartImage] = []
    unavailable: list[str] = []

    for name in chart_sections:
        try:
            section = report_model.section(name)
        except KeyError:
            unavailable.append(name)         # a requested section not in the model -> unavailable
            continue

        if not section.available:
            unavailable.append(name)
            continue

        values = tuple(slot.value for slot in section.slots)
        refs = tuple(slot.source_ref for slot in section.slots)
        png = _render_png(values)
        images.append(
            ChartImage(
                section=name,
                values=values,
                source_refs=refs,
                png=png,
                bytes_deferred=not MATPLOTLIB_AVAILABLE,
            )
        )

    marks = (DocumentMark.SECTION_UNAVAILABLE,) if unavailable else ()
    return ChartImagesResult(
        images=tuple(images),
        unavailable_sections=tuple(unavailable),
        marks=marks,
    )
