"""Review-status rule (R801) — FR-11, mandated requirement #3.

`apply_review_status` is the single source of truth for an assessment's finality: a CRITICAL-band
verdict, or any withheld (score-suppressed) verdict, is held PENDING_HUMAN_REVIEW so no downstream
agent treats it as final on this agent's say-so alone; everything else is FINAL. The flag is ALWAYS
set explicitly — an assessment never lacks a finality state.

Withhold takes precedence over severity: a withheld assessment is always pending review even if a
severity is somehow supplied, so a suppressed verdict can never leak out as FINAL.
"""
from __future__ import annotations

from agents.risk_reasoning.statuses import ReviewStatus, Severity


def apply_review_status(severity: Severity | None, *, is_withheld: bool) -> ReviewStatus:
    """Decide an assessment's finality (FR-11). Pure; always returns a concrete ReviewStatus."""
    if is_withheld or severity is Severity.CRITICAL:
        return ReviewStatus.PENDING_HUMAN_REVIEW
    return ReviewStatus.FINAL
