"""Severity band mapping (R103) — FR-4.

A 0-100 risk score maps to exactly one of SAFE | WATCH | WARNING | CRITICAL via the fixed config
cut-points (`ScoreConfig.watch_min/warning_min/critical_min`). The mapping is pure and
deterministic; the model never chooses a band. A score on a cut-point belongs to the HIGHER band
(>=), matching `CoverageConfig.meets_floor`.

The `near_boundary` flag surfaces that a score sits within `band_near_margin` of a cut-point so a
human reads a borderline verdict with that context — but it NEVER moves the band (Edge
"borderline"). When the margin is unset (TODO), no score is flagged near: we do not guess "how
close is near" for a safety output.

If the band cut-points are not configured, `severity_for` raises `BandNotConfigured` rather than
inventing a band (Principle IV / FR-4: no ad-hoc or model-chosen boundaries).
"""
from __future__ import annotations

from dataclasses import dataclass

from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.statuses import Severity


class BandNotConfigured(Exception):
    """Raised when a band mapping is attempted before the cut-points are supplied (FR-4)."""


@dataclass(frozen=True, slots=True)
class BandResult:
    """The band a score maps to, plus whether it sits near a cut-point (annotation only)."""

    severity: Severity
    near_boundary: bool


def _is_todo(value: float) -> bool:
    return value != value  # NaN is the only value not equal to itself


def severity_for(score: float, config: ScoreConfig) -> BandResult:
    """Map a 0-100 score to its severity band (FR-4). Raises BandNotConfigured if unset."""
    if config.bands_are_todo:
        raise BandNotConfigured(
            "band cut-points are TODO; a severity band must not be guessed (FR-4)"
        )

    if score >= config.critical_min:
        severity = Severity.CRITICAL
    elif score >= config.warning_min:
        severity = Severity.WARNING
    elif score >= config.watch_min:
        severity = Severity.WATCH
    else:
        severity = Severity.SAFE

    near = False
    if not _is_todo(config.band_near_margin):
        margin = config.band_near_margin
        near = any(
            abs(score - cut) <= margin
            for cut in (config.watch_min, config.warning_min, config.critical_min)
        )

    return BandResult(severity=severity, near_boundary=near)
