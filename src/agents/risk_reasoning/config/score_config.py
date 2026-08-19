"""Deterministic score configuration (R101) — configuration, not code.

A ScoreConfig carries every constant the deterministic scorer needs to turn the Structural
Analysis Agent's value/limit ratios into a 0-100 whole-bridge risk score and a severity band:
the per-factor weights, the ratio->0..100 normalisation params, and the band cut-points. The
score is a PURE function of these + the retrieved ratios (FR-2); the model never invents it.

Discipline (same as the DCA's SensorProfile and the SA's AnalysisProfile): every SAFETY number
is a `TODO`/`NaN` sentinel until a structural engineer supplies it. We do NOT invent weights,
normalisation bounds, or band boundaries for a safety-critical system — an unset value is loudly
flagged (`is_fully_configured`) rather than silently defaulted to a plausible number. Only the
NON-physical audit field is concrete here: `score_weights_version`, which stamps WHICH weights an
assessment used so the result stays reproducible (FR-10).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Sentinel marking a value a structural engineer must still supply. Not 0/None: those are
# plausible real values and would hide an unset field (same choice as the DCA / SA configs).
TODO: Final[float] = float("nan")


def _is_todo(value: float) -> bool:
    return value != value  # NaN is the only value not equal to itself


@dataclass(frozen=True, slots=True)
class ScoreConfig:
    """Immutable deterministic-score configuration for the whole-bridge risk score.

    `score_weights_version` is the one field meant to be set concretely (it is an audit stamp,
    not a safety number). Everything numeric below is a per-factor / band safety constant and
    stays TODO until an engineer supplies it.
    """

    # Audit stamp — WHICH weight set this config represents (non-physical; always present).
    score_weights_version: str

    # --- Per-factor weights (FR-2): tuple of (factor_name, weight). Empty until supplied. ---
    weights: tuple[tuple[str, float], ...] = ()

    # --- Ratio -> 0..100 normalisation (FR-2): the value/limit ratio mapped onto the score. ---
    ratio_at_zero_score: float = TODO   # ratio that maps to a 0 contribution
    ratio_at_full_score: float = TODO   # ratio that maps to a 100 contribution

    # --- Severity band cut-points (FR-4): minimum score for each band above SAFE. ---
    watch_min: float = TODO             # score >= this -> at least WATCH
    warning_min: float = TODO           # score >= this -> at least WARNING
    critical_min: float = TODO          # score >= this -> CRITICAL

    # --- Near-boundary annotation (FR-4 / Edge "borderline"): how close to a cut-point counts
    #     as "near". Annotation-only — it NEVER moves the band and does NOT gate
    #     is_fully_configured (like confidence, FR-6a). When TODO, no score is flagged near. ---
    band_near_margin: float = TODO

    # ------------------------------------------------------------------ helpers ---
    @property
    def weights_are_todo(self) -> bool:
        """True if no factor weights are supplied, or any supplied weight is still NaN."""
        if not self.weights:
            return True
        return any(_is_todo(w) for _, w in self.weights)

    @property
    def normalisation_is_todo(self) -> bool:
        """True if either ratio->score normalisation bound is unset."""
        return _is_todo(self.ratio_at_zero_score) or _is_todo(self.ratio_at_full_score)

    @property
    def bands_are_todo(self) -> bool:
        """True if any severity band cut-point is unset."""
        return (
            _is_todo(self.watch_min)
            or _is_todo(self.warning_min)
            or _is_todo(self.critical_min)
        )

    @property
    def is_fully_configured(self) -> bool:
        """True only when every safety number the scorer needs is supplied.

        The audit version alone is never enough: weights, the ratio normalisation, and the band
        table must all be set before a real score may be computed (FR-2 / FR-4).
        """
        return not (self.weights_are_todo or self.normalisation_is_todo or self.bands_are_todo)
