"""FakeRenderer (G601) — deterministic RenderPort stub for tests.

Stands in for the ReportLab/matplotlib renderer so the marks, persistence, and service phases are
testable without those [RENDER-DEP] libraries. It records the exact ReportModel it was handed (so
later phases can assert what would have been drawn) and returns a deterministic artifact ref
derived from the model's identity + version — no bytes, no clock, no randomness. Same `render`
shape as the real renderer, so swapping the real one in changes only the produced bytes.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agents.report_generation.model import ReportModel
from agents.report_generation.render.port import RenderedArtifact


@dataclass
class FakeRenderer:
    """Deterministic renderer stand-in. Records each model and returns a stable fake ref."""

    rendered_models: list[ReportModel] = field(default_factory=list)

    def render(self, report_model: ReportModel) -> RenderedArtifact:
        self.rendered_models.append(report_model)
        # Deterministic ref from identity + version — same model -> same ref (no clock/random).
        ref = (
            f"fake://reports/{report_model.bridge_id}/"
            f"{report_model.assessment_id}-v{report_model.assessment_version}.pdf"
        )
        return RenderedArtifact(artifact_ref=ref, byte_size=None)
