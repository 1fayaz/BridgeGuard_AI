"""Verdict read (A301) — REUSE the Report agent's risk_assessment_read, do not fork.

The Alert agent consumes exactly the finalized risk_assessments verdict (0006) the Report agent
already reads by identity — the current (non-superseded) row a scope key resolves to, read-only,
with a structured ASSESSMENT_NOT_FOUND signal instead of a raise. Rather than duplicate that read
(two copies to drift apart), the Alert agent REUSES the one implementation and simply exposes it
under its own namespace, so the service imports from `alert_escalation.tools.verdict_read` and
never reaches into `report_generation` internals at its call sites (Principle III modular contract).

This single re-export is the documented coupling point (plan §3a / Open Item 7): if the
report -> alert import direction is rejected at review, the tool lifts to a shared
`agents/_shared/` module and only THIS file changes — no call site does.
"""
from __future__ import annotations

from agents.report_generation.tools.risk_assessment_read import (
    ASSESSMENT_NOT_FOUND,
    AssessmentScope,
    AssessmentSource,
    RiskAssessmentReadResult,
    get_risk_assessment,
)

__all__ = [
    "ASSESSMENT_NOT_FOUND",
    "AssessmentScope",
    "AssessmentSource",
    "RiskAssessmentReadResult",
    "get_risk_assessment",
]
