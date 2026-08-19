"""Deterministic scorer (R301+) — FR-2.

The risk score is computed here, in pure code, NOT by the model: each Structural Analysis result's
value/limit ratio is normalised to a 0-100 factor contribution, the contributions are weighted and
combined, and the result is the whole-bridge score the model then EXPLAINS (Principle IV — keep the
arithmetic out of the LLM; research §4).

R301 is the first piece: `normalise_ratio` maps one result's value/limit ratio onto 0-100 via the
two configured bounds, linearly and clamped. It never raises and never leaks NaN: a missing/zero
limit, a non-finite value, or unconfigured bounds yield a structured "not scorable" signal that the
combine step (R302) and gap handling (R303) treat as an absent factor — never a guessed number.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from agents.risk_reasoning.assessment import ContributingFactor, FactorDirection
from agents.risk_reasoning.config.score_config import ScoreConfig


def _is_todo(value: float) -> bool:
    return value != value  # NaN is the only value not equal to itself


@dataclass(frozen=True, slots=True)
class RatioScore:
    """The normalised 0-100 contribution for one result's value/limit ratio.

    `scorable` is False when the input cannot be turned into a trustworthy number (missing/zero
    limit, non-finite value, or unconfigured normalisation bounds); then `score` is None and
    `reason` says why. A scorable result always carries a finite `score` in [0, 100].
    """

    scorable: bool
    score: float | None
    ratio: float | None
    reason: str | None = None


def normalise_ratio(value: float, limit: float, config: ScoreConfig) -> RatioScore:
    """Map a value/limit ratio onto 0-100 (FR-2), linear between the configured bounds, clamped.

    Not scorable (structured signal, never a raise / NaN) when:
      - the normalisation bounds are unconfigured (TODO),
      - the limit is missing (NaN) or zero (would divide by zero),
      - the value is non-finite.
    """
    if config.normalisation_is_todo:
        return RatioScore(False, None, None, "normalisation bounds are unconfigured (TODO)")

    if not math.isfinite(value):
        return RatioScore(False, None, None, "value is not finite")

    if _is_todo(limit) or not math.isfinite(limit) or limit == 0.0:
        return RatioScore(False, None, None, "limit is missing or zero (not scorable)")

    ratio = value / limit

    lo = config.ratio_at_zero_score
    hi = config.ratio_at_full_score
    if hi == lo:
        # Degenerate config (zero-width band) — refuse rather than divide by zero.
        return RatioScore(False, None, ratio, "normalisation bounds are degenerate (zero width)")

    fraction = (ratio - lo) / (hi - lo)
    score = max(0.0, min(100.0, fraction * 100.0))  # clamp to [0, 100]
    return RatioScore(True, score, ratio)


@dataclass(frozen=True, slots=True)
class FactorInput:
    """One Structural Analysis result to be folded into the whole-bridge score (FR-2).

    `value` is the SA result's measured value; `limit` is the standard/design limit it is
    compared against. `factor_name` selects this input's weight from the ScoreConfig.
    """

    factor_name: str
    source_analysis_id: int
    value: float
    limit: float


@dataclass(frozen=True, slots=True)
class BridgeScore:
    """The deterministic whole-bridge score plus the factors it was built from (FR-2).

    `scorable` is False when no factor could be scored (or weights are unconfigured); then
    `score` is None. `gaps` names every input that was present but could not be folded in
    (no weight, or not scorable) — recorded, never silently dropped or guessed.
    """

    scorable: bool
    score: int | None
    factors: tuple[ContributingFactor, ...]
    gaps: tuple[str, ...]


def _direction(factor_score: float, combined: float) -> FactorDirection:
    if factor_score > combined:
        return FactorDirection.RAISED
    if factor_score < combined:
        return FactorDirection.LOWERED
    return FactorDirection.NEUTRAL


def score_bridge(inputs: list[FactorInput], config: ScoreConfig) -> BridgeScore:
    """Combine SA results into one 0-100 whole-bridge score (FR-2). Pure and deterministic.

    Each input's value/limit ratio is normalised to 0-100 (R301), weighted by the factor's
    configured weight, and combined as a weighted average over the SCORABLE, WEIGHTED factors.
    Inputs with no configured weight, or that are not scorable, are recorded in `gaps` and
    excluded — never guessed. The model is not involved (Principle IV).
    """
    weights = {name: w for name, w in config.weights if not _is_todo(w)}

    # First pass: normalise each scorable, weighted factor and gather (id, name, weight, score).
    scored: list[tuple[FactorInput, float, float]] = []  # (input, weight, normalised score)
    gaps: list[str] = []
    for inp in inputs:
        weight = weights.get(inp.factor_name)
        if weight is None:
            gaps.append(f"{inp.factor_name}: no configured weight")
            continue
        rs = normalise_ratio(inp.value, inp.limit, config)
        if not rs.scorable:
            gaps.append(f"{inp.factor_name}: {rs.reason}")
            continue
        scored.append((inp, weight, rs.score))

    total_weight = sum(w for _, w, _ in scored)
    if not scored or total_weight == 0.0:
        return BridgeScore(False, None, (), tuple(gaps))

    combined = sum(w * s for _, w, s in scored) / total_weight
    final_score = round(combined)

    factors = tuple(
        ContributingFactor(
            factor_name=inp.factor_name,
            source_analysis_id=inp.source_analysis_id,
            value=inp.value,
            limit=inp.limit,
            ratio=inp.value / inp.limit,
            weight=weight,
            contribution=weight * s,
            direction=_direction(s, combined),
        )
        for inp, weight, s in scored
    )
    return BridgeScore(True, final_score, factors, tuple(gaps))
