"""Read port — get_risk_assessment(scope, *, historical=False) (G301) — read-only.

The report's spine: read the ONE finalized risk_assessments row (0006) a scope key resolves to.
By default it reads the CURRENT (non-superseded) assessment for a bridge+cycle; with
historical=True it reads a specific SUPERSEDED row by its id (a regulatory re-print, FR-4/AC-4a).
The agent ASSEMBLES from this row — it never re-decides the verdict (FR-1). Read-only; a missing
assessment returns a structured ASSESSMENT_NOT_FOUND signal, never a raise (FR-12).

[DB-DEP] The live source is the risk_assessments table (0006) + Neon, neither of which exists
locally. The read is written against a small source PROTOCOL so it runs against an in-memory fake
now and a real Neon-backed source later with no logic change.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

# The one structured "no row" signal this port emits (mirrors report_statuses.WithheldReason,
# without importing it — the port stays a thin read that names the miss; the service maps it to
# the WITHHELD outcome).
ASSESSMENT_NOT_FOUND = "ASSESSMENT_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class AssessmentScope:
    """What the trigger carries: enough to resolve exactly one assessment row.

    (bridge_id, cycle_id) resolves the CURRENT assessment (the 0006 partial-unique index makes
    that exactly one). `assessment_id` names a specific row and is REQUIRED for a historical read.
    """

    bridge_id: str
    cycle_id: str
    assessment_id: int | None = None


class AssessmentSource(Protocol):
    """The read port this tool needs — implemented by the fake now, Neon later."""

    def current_assessment_for(self, bridge_id: str, cycle_id: str) -> dict[str, Any] | None:
        ...

    def assessment_by_id(self, assessment_id: int) -> dict[str, Any] | None:
        ...


@dataclass(frozen=True, slots=True)
class RiskAssessmentReadResult:
    """Structured result: either the finalized row, or a named miss. Never both."""

    found: bool
    assessment: dict[str, Any] | None = None
    not_found_reason: str | None = None

    @classmethod
    def hit(cls, row: dict[str, Any]) -> "RiskAssessmentReadResult":
        return cls(found=True, assessment=dict(row), not_found_reason=None)

    @classmethod
    def miss(cls) -> "RiskAssessmentReadResult":
        return cls(found=False, assessment=None, not_found_reason=ASSESSMENT_NOT_FOUND)


def get_risk_assessment(
    scope: AssessmentScope,
    source: AssessmentSource,
    *,
    historical: bool = False,
) -> RiskAssessmentReadResult:
    """Read the finalized assessment the scope resolves to (G301). Read-only; never raises.

    historical=False -> the current (non-superseded) row for (bridge_id, cycle_id).
    historical=True  -> the specific row named by scope.assessment_id (a superseded re-print).
    A missing row -> a structured ASSESSMENT_NOT_FOUND result.
    """
    if historical:
        # A historical re-print must name the exact row; without an id there is nothing to fetch.
        if scope.assessment_id is None:
            return RiskAssessmentReadResult.miss()
        row = source.assessment_by_id(scope.assessment_id)
    else:
        row = source.current_assessment_for(scope.bridge_id, scope.cycle_id)

    if row is None:
        return RiskAssessmentReadResult.miss()
    return RiskAssessmentReadResult.hit(row)
