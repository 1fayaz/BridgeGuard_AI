"""Tool 2 — get_historical_baseline (R502, FR-3) — read-only.

Reads the rolling baseline / prior assessments for one bridge so the reasoner can judge TREND
(degrading vs. stable) and deviation from normal, not just absolute current values. Read-only; a
bridge with no history returns a structured "no baseline" signal (cold-start trend), never a raise.

[DB-DEP] The live source (sensor-comparison data / prior risk_assessments) does not exist yet, so
the read is written against a source PROTOCOL and runs against an in-memory fake now.

Open Item (deferred to plan.md): the EXACT baseline contract shape — which sensor-comparison fields
and over what window. `BaselinePoint` is intentionally minimal (enough for trend + provenance) so
the real contract can extend it without reshaping the call site.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class BaselinePoint:
    """One historical reference point for a bridge (minimal v1 shape).

    `reference` pins WHICH baseline this came from, so an assessment that used it is reproducible
    (FR-9/FR-10). `prior_score` carries a previous risk score for crude trend context; richer
    sensor-comparison fields are deferred to the real baseline contract.
    """

    bridge_id: str
    reference: str
    prior_score: float | None = None


class BaselineSource(Protocol):
    """The read port this tool needs — implemented by the fake now, a real store later."""

    def baseline_for(self, bridge_id: str, window: str) -> list[BaselinePoint]:
        ...


@dataclass(frozen=True, slots=True)
class HistoricalBaseline:
    """The tool's structured return: the bridge's baseline points (possibly none)."""

    points: tuple[BaselinePoint, ...]

    @property
    def has_baseline(self) -> bool:
        return bool(self.points)


def get_historical_baseline(
    bridge_id: str,
    window: str,
    source: BaselineSource,
) -> HistoricalBaseline:
    """Read the bridge's historical baseline (FR-3, tool 2). Read-only; never raises."""
    points = source.baseline_for(bridge_id, window)
    return HistoricalBaseline(points=tuple(points))
