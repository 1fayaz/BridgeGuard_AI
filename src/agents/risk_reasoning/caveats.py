"""Caveat propagation (R802) — AC-8.

The Structural Analysis results carry data-quality flags (clock_drift, interpolated_input,
rate_mismatch, abnormal_quiet). A risk verdict resting on a drifted or interpolated block is less
trustworthy than one on clean data, so those flags must be carried into the reasoning and surfaced
in the explanation — never silently dropped.

`collect_caveats` turns each raised flag on each result into a structured caveat. The orchestrator
puts the caveat list into the model context so the drafted explanation can reflect them (AC-8).
"""
from __future__ import annotations

from dataclasses import dataclass

# The four SA data-quality flags this agent carries as caveats (spec input contract / AC-8).
CAVEAT_FLAGS: tuple[str, ...] = (
    "clock_drift",
    "interpolated_input",
    "rate_mismatch",
    "abnormal_quiet",
)


@dataclass(frozen=True, slots=True)
class Caveat:
    """One data-quality caveat: a raised flag on a specific SA result."""

    sensor_id: str
    source_analysis_id: int
    flag: str


def collect_caveats(results) -> tuple[Caveat, ...]:
    """Collect a caveat for every raised data-quality flag on every result (AC-8). Pure.

    Only flags that are truthy become caveats; a flag set False (or absent) is not a caveat.
    Multiple raised flags on one result each produce their own caveat, so nothing is dropped.
    """
    caveats: list[Caveat] = []
    for r in results:
        for flag in CAVEAT_FLAGS:
            if r.flags.get(flag):
                caveats.append(
                    Caveat(sensor_id=r.sensor_id, source_analysis_id=r.id, flag=flag)
                )
    return tuple(caveats)
