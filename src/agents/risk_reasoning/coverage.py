"""Coverage gate (R401) — the score-vs-withhold decision (FR-6).

Before the agent scores a bridge, it checks how much of the expected input actually arrived. A
scored (possibly degraded) assessment is emitted ONLY when RAN coverage is at or above the
configured floor AND the applicable engineering standard is present. Below the floor, or with the
standard missing, the agent WITHHOLDS the score and routes to human review — it never invents a
missing input and never emits a falsely-confident score on a near-blind bridge (Principle IV
"always return a status"; Principle I).

This is a pure decision over counts; it never raises (zero expected -> withhold, not a /0) and
never guesses. The completeness/confidence annotation is computed separately (R402, FR-6a).
"""
from __future__ import annotations

from dataclasses import dataclass

from agents.risk_reasoning.config.coverage_config import CoverageConfig


@dataclass(frozen=True, slots=True)
class CoverageResult:
    """The score-vs-withhold verdict (FR-6).

    `should_score` True -> emit a scored assessment; False -> withhold the score and route to
    human review. `reason` names the gap when withholding (it becomes the withheld assessment's
    explanation seed), and is None when scoring.
    """

    should_score: bool
    ran_fraction: float
    standard_present: bool
    reason: str | None = None


def coverage_check(
    ran_count: int,
    expected_count: int,
    standard_present: bool,
    config: CoverageConfig,
) -> CoverageResult:
    """Decide whether to score or withhold (FR-6). Pure; never raises, never guesses."""
    ran_fraction = (ran_count / expected_count) if expected_count > 0 else 0.0

    if expected_count <= 0:
        return CoverageResult(
            False, 0.0, standard_present,
            "no expected calculations for this bridge — nothing to score",
        )

    if config.require_standard_present and not standard_present:
        return CoverageResult(
            False, ran_fraction, standard_present,
            "applicable engineering standard not available — score withheld",
        )

    if not config.meets_floor(ran_fraction):
        floor = config.coverage_floor
        floor_text = "unconfigured" if config.floor_is_todo else f"{floor:.0%}"
        return CoverageResult(
            False, ran_fraction, standard_present,
            f"calculation coverage {ran_fraction:.0%} below the floor ({floor_text}) "
            f"— score withheld, routed to human review",
        )

    return CoverageResult(True, ran_fraction, standard_present, None)
