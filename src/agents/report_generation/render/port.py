"""RenderPort seam (G601) — the interface the service renders through.

The service (G901) never calls ReportLab/matplotlib directly; it calls a RenderPort. The fake
(G601) records the model for tests; the real renderer (G602/G603) produces genuine PDF bytes.
Because both implement this one shape, swapping the real renderer in changes only the produced
BYTES, never the control flow around it (assembly, fidelity gate, marks, persistence).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agents.report_generation.model import ReportModel


@dataclass(frozen=True, slots=True)
class RenderedArtifact:
    """The output of a render: a reference to the produced artifact (never the bytes inline).

    `artifact_ref` is where the document lives (an object-store key / URL / path — a plan-level
    decision). `byte_size` is optional metadata a real renderer fills in; the fake leaves it None.
    """

    artifact_ref: str
    byte_size: int | None = None


@runtime_checkable
class RenderPort(Protocol):
    """Turn an assembled, fidelity-checked ReportModel into a stored artifact."""

    def render(self, report_model: ReportModel) -> RenderedArtifact:
        ...
