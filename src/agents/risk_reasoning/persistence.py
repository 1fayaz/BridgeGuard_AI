"""Assessment persistence (R902) — FR-9 / AC-9 [DB-DEP].

`persist_assessment` writes one assessment (scored, withheld, or guardrail-fail) to the store and
appends the matching audit-log entry, so the structured record alone answers what/when/on-what-data
(AC-9). It stores the explanation VERBATIM and pins every provenance field (FR-9/FR-10), and it is
idempotent by scope: re-persisting the same (bridge_id, cycle_id) SUPERSEDES the prior row rather
than crashing on the uniqueness constraint (a re-assessment appends + links, never overwrites).

Audit-kind selection mirrors the R204 decision_kind extension:
  scored (not withheld)              -> RISK_ASSESSMENT
  withheld, guardrail_failed=False   -> RISK_WITHHELD
  withheld, guardrail_failed=True    -> RISK_GUARDRAIL_FAIL

[DB-DEP] Runs against FakeRiskStore now; the live Supabase write is deferred (no instance locally).
"""
from __future__ import annotations

from agents.risk_reasoning.assessment import RiskAssessment
from agents.risk_reasoning.store import FakeRiskStore


def _audit_kind(assessment: RiskAssessment, guardrail_failed: bool) -> str:
    if not assessment.is_withheld:
        return "RISK_ASSESSMENT"
    return "RISK_GUARDRAIL_FAIL" if guardrail_failed else "RISK_WITHHELD"


def persist_assessment(
    store: FakeRiskStore,
    assessment: RiskAssessment,
    guardrail_failed: bool = False,
) -> int:
    """Persist one assessment + its audit entry (FR-9). Returns the new row id.

    If a current assessment already exists for this (bridge_id, cycle_id), the new one supersedes
    it (append + link); otherwise it is a fresh insert. Idempotent by scope — a redelivered trigger
    or a re-assessment never duplicates or crashes.
    """
    existing = store.current(assessment.bridge_id, assessment.cycle_id)
    if existing is not None:
        old_id = next(
            sa.id for sa in store.rows
            if sa.assessment is existing and sa.superseded_by is None
        )
        row_id = store.insert_superseding(old_id, assessment)
    else:
        row_id = store.insert(assessment)

    store.append_audit(
        assessment.bridge_id,
        assessment.cycle_id,
        _audit_kind(assessment, guardrail_failed),
        assessment.explanation,
    )
    return row_id
