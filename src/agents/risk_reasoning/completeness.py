"""Data-completeness / confidence annotation (R402) — FR-6a.

`data_completeness` is a deterministic measure of how much of the expected input was present and
clean. It ANNOTATES an assessment and feeds the FR-6 degraded/withhold decision, but it does NOT
move the `risk_score`: the score stays a pure function of the present factors (R302), preserving
FR-2's determinism and FR-10's reproducibility. Keeping this in its own module — never imported by
the scorer — makes that separation structural, not a matter of discipline.

Completeness is the present-and-clean fraction of expected inputs: a flagged-but-RAN result
(clock_drift / interpolated_input / rate_mismatch) still counts toward coverage (R401) but is
discounted here, because a number resting on a drifted or interpolated block is less trustworthy.
"""
from __future__ import annotations

from agents.risk_reasoning.config.coverage_config import CoverageConfig


def data_completeness(
    ran_count: int,
    expected_count: int,
    flagged_count: int,
    config: CoverageConfig,
) -> float:
    """Fraction of expected inputs that arrived clean (FR-6a). Pure; clamped to [0, 1]; never /0.

    The `config` carries the completeness-formula params; in v1 the formula is the clean fraction
    (`completeness_full_fraction` scales what counts as fully complete — TODO until supplied, in
    which case it does not scale). Annotation only: the scorer never sees this value.
    """
    if expected_count <= 0:
        return 0.0

    clean = max(0, ran_count - flagged_count)
    completeness = clean / expected_count
    return max(0.0, min(1.0, completeness))
