"""Coverage / completeness configuration (R102) — configuration, not code.

A CoverageConfig carries the constants that gate whether the agent SCORES a bridge or WITHHOLDS
the score (FR-6), plus the params of the deterministic data-completeness/confidence measure
(FR-6a). The coverage floor is the minimum fraction of the bridge's expected calculations that
must actually have RAN (and the standard be present) before a scored — possibly degraded —
assessment is emitted; below it the agent withholds the score and routes to human review.

Discipline (same as ScoreConfig / the SA AnalysisProfile): the coverage floor and the
completeness-formula params are SAFETY numbers and stay `TODO`/`NaN` until a structural engineer
supplies them — we do not guess how blind a bridge may be before a score becomes untrustworthy.
Only the NON-physical policy default is concrete: `require_standard_present` (scoring requires the
applicable standard, FR-6).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

TODO: Final[float] = float("nan")


def _is_todo(value: float) -> bool:
    return value != value  # NaN is the only value not equal to itself


@dataclass(frozen=True, slots=True)
class CoverageConfig:
    """Immutable coverage/completeness configuration for the score-vs-withhold gate (FR-6/6a)."""

    # --- Score-vs-withhold gate (FR-6): min fraction of expected RAN results to score. ---
    coverage_floor: float = TODO

    # --- Data-completeness / confidence formula (FR-6a): annotation only, never moves score. ---
    completeness_full_fraction: float = TODO  # present/expected fraction counted as fully complete

    # --- Policy (non-physical default): scoring requires the applicable standard present. ---
    require_standard_present: bool = True

    # ------------------------------------------------------------------ helpers ---
    @property
    def floor_is_todo(self) -> bool:
        """True if the coverage floor is still unset."""
        return _is_todo(self.coverage_floor)

    @property
    def completeness_is_todo(self) -> bool:
        """True if the completeness-formula params are still unset."""
        return _is_todo(self.completeness_full_fraction)

    @property
    def is_fully_configured(self) -> bool:
        """True only when both the floor and the completeness params are supplied."""
        return not (self.floor_is_todo or self.completeness_is_todo)

    def meets_floor(self, ran_fraction: float) -> bool:
        """True if observed RAN coverage is at or above the configured floor.

        With the floor still TODO, this is always False: the agent must never score on an unset
        floor (it withholds instead). The standard-present requirement is checked separately by
        the coverage gate (R401), since it depends on a retrieved input, not on this fraction.
        """
        if self.floor_is_todo:
            return False
        return ran_fraction >= self.coverage_floor
