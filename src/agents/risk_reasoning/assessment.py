"""Output payload (R202) — the typed risk assessment + its contributing factors.

A `RiskAssessment` is the one record this agent emits per run (spec output contract). It carries
the deterministic score, its band, the plain-language explanation, the structured factors the
score was built from, the provenance needed to reproduce it (FR-9/FR-10), and the finality flag
(FR-11).

The dataclass enforces the spec's hard invariants at construction (so an invalid output cannot
exist as an object):
  - FR-1 / mandate #1: a score and its explanation are inseparable — a scored assessment must
    carry a non-empty explanation AND a severity band; a withheld assessment (score None) must
    still carry an explanation.
  - FR-11 / mandate #3: a CRITICAL-band assessment must be PENDING_HUMAN_REVIEW, never FINAL.

The score itself is computed deterministically elsewhere (R301/R302); this module only holds and
validates the result.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from agents.risk_reasoning.statuses import ReviewStatus, Severity


class FactorDirection(str, Enum):
    """Which way a contributing factor pushed the whole-bridge score."""

    RAISED = "RAISED"      # pushed risk up
    LOWERED = "LOWERED"    # pulled risk down (e.g. a comfortably in-limit factor)
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True, slots=True)
class ContributingFactor:
    """One factor the deterministic score was built from — the machine-checkable backing for a
    number cited in the narrative (FR-2 factor, FR-9 provenance)."""

    factor_name: str
    source_analysis_id: int     # which SA analysis_results row this came from (provenance)
    value: float                # the SA result's value
    limit: float                # the standard/design limit it was compared against
    ratio: float                # value / limit (the normalised-score input, FR-2)
    weight: float               # this factor's weight in the combine (FR-2)
    contribution: float         # weighted 0..100 contribution to the score
    direction: FactorDirection


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    """One whole-bridge risk assessment (spec output contract). Validated at construction."""

    bridge_id: str
    cycle_id: str

    # --- The verdict (FR-1: score + band + WHY are one deliverable) ---
    risk_score: int | None              # 0-100, or None when withheld (FR-6/FR-7)
    severity: Severity | None           # band, or None when withheld
    recommendation: str
    explanation: str                    # the WHY — first-class safety output, never empty

    # --- Structured backing + annotation ---
    contributing_factors: tuple[ContributingFactor, ...]
    confidence: float                   # annotation only (FR-6a), does not move the score
    data_completeness: float

    # --- Finality (FR-11) ---
    review_status: ReviewStatus

    # --- Provenance (FR-9 / FR-10: reproducible from exactly these) ---
    source_analysis_ids: tuple[int, ...]
    baseline_ref: str | None
    standard_code: str | None
    standard_version: str | None
    score_weights_version: str
    model_id: str
    model_version: str
    trace_id: str

    def __post_init__(self) -> None:
        # FR-1 / mandate #1: the WHY is part of every output, scored or withheld.
        if not self.explanation or not self.explanation.strip():
            raise ValueError(
                "explanation is required (FR-1: a score/assessment without its WHY is a defect)"
            )

        if self.risk_score is None:
            # Withheld: no band may be claimed, and it must be held for review.
            if self.severity is not None:
                raise ValueError("a withheld assessment (risk_score=None) must have severity=None")
            if self.review_status is not ReviewStatus.PENDING_HUMAN_REVIEW:
                raise ValueError(
                    "a withheld assessment must be PENDING_HUMAN_REVIEW (FR-6/FR-7)"
                )
        else:
            # Scored: a numeric score must carry its band (FR-1 — score+severity inseparable).
            if self.severity is None:
                raise ValueError("a scored assessment must carry a severity band (FR-1)")
            # FR-11 / mandate #3: CRITICAL is never final on this agent's say-so alone.
            if self.severity is Severity.CRITICAL and self.review_status is not ReviewStatus.PENDING_HUMAN_REVIEW:
                raise ValueError(
                    "a CRITICAL assessment must be PENDING_HUMAN_REVIEW, not FINAL (FR-11)"
                )

    @property
    def is_withheld(self) -> bool:
        """True when no score was emitted (degraded/guardrail-fail path, FR-6/FR-7)."""
        return self.risk_score is None
