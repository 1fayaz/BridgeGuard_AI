"""Output payload (G202) — the typed ReportResult + the ReportSummary the service returns.

`ReportResult` is the one record this agent emits per run (spec output contract): what happened to
the render, the sign-off marks the document carries, and the pinned provenance that makes it
reproducible (FR-9/FR-11). `ReportSummary` is the plain, serialisable shape the service hands back
to n8n, which branches on `ok` (fire-and-notify) — it carries the outcome/marks/reason, never the
artifact bytes.

Like the Risk `RiskAssessment`, the coherent shapes are enforced at construction so an invalid
output cannot exist as an object:
  - RENDERED ⇒ an artifact_ref is present and NO withheld_reason (a produced document cannot also
    claim a no-document reason).
  - WITHHELD ⇒ exactly one withheld_reason, artifact_ref is None, and NO document marks (no
    document ⇒ no document marks).
  - ERROR ⇒ neither an artifact_ref nor a reason nor marks (a structured failure, FR-12).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.report_generation.report_statuses import (
    DocumentMark,
    ReportOutcome,
    WithheldReason,
)


@dataclass(frozen=True, slots=True)
class ReportResult:
    """One report render result (spec output contract). Validated at construction."""

    bridge_id: str
    cycle_id: str

    # --- Which finalized assessment this report renders (identity + version, FR-4/FR-11) ---
    assessment_id: int
    assessment_version: int

    # --- What happened (FR-12 closed vocabulary) ---
    outcome: ReportOutcome
    marks: tuple[DocumentMark, ...]
    withheld_reason: WithheldReason | None

    # --- The produced artifact (a ref/URL, never the bytes) — None unless RENDERED ---
    artifact_ref: str | None

    # --- Pinned provenance (FR-9/FR-11: reproducible from exactly these) ---
    source_analysis_ids: tuple[int, ...]
    standard_code: str | None
    standard_version: str | None
    template_version: str
    rendered_at: str            # timestamp seam (passed in; no clock in the assembler)

    def __post_init__(self) -> None:
        if self.outcome is ReportOutcome.RENDERED:
            if not self.artifact_ref:
                raise ValueError("a RENDERED result must carry an artifact_ref (FR-9)")
            if self.withheld_reason is not None:
                raise ValueError(
                    "a RENDERED result must not carry a withheld_reason (a produced document "
                    "cannot also claim a no-document reason)"
                )
        elif self.outcome is ReportOutcome.WITHHELD:
            if self.withheld_reason is None:
                raise ValueError("a WITHHELD result must carry exactly one withheld_reason")
            if self.artifact_ref is not None:
                raise ValueError("a WITHHELD result must not carry an artifact_ref (no document)")
            if self.marks:
                raise ValueError("a WITHHELD result must not carry document marks (no document)")
        else:  # ERROR
            if self.artifact_ref is not None:
                raise ValueError("an ERROR result must not carry an artifact_ref")
            if self.withheld_reason is not None:
                raise ValueError("an ERROR result must not carry a withheld_reason")
            if self.marks:
                raise ValueError("an ERROR result must not carry document marks")


@dataclass(frozen=True, slots=True)
class ReportSummary:
    """The plain shape the service returns to n8n (fire-and-notify). n8n branches on `ok`.

    Carries the outcome/marks/reason and (for a rendered report) the artifact ref — never the
    artifact bytes. `ok` is True only for a RENDERED outcome.
    """

    ok: bool
    outcome: ReportOutcome
    marks: tuple[DocumentMark, ...] = ()
    withheld_reason: WithheldReason | None = None
    artifact_ref: str | None = None
    error: str | None = None

    @classmethod
    def from_result(cls, result: ReportResult) -> "ReportSummary":
        return cls(
            ok=result.outcome is ReportOutcome.RENDERED,
            outcome=result.outcome,
            marks=result.marks,
            withheld_reason=result.withheld_reason,
            artifact_ref=result.artifact_ref,
            error=None,
        )

    @classmethod
    def from_error(cls, message: str) -> "ReportSummary":
        return cls(ok=False, outcome=ReportOutcome.ERROR, error=message)

    def as_dict(self) -> dict[str, Any]:
        """A plain JSON-serialisable dict (enum values unwrapped to their strings)."""
        return {
            "ok": self.ok,
            "outcome": self.outcome.value,
            "marks": [m.value for m in self.marks],
            "withheld_reason": self.withheld_reason.value if self.withheld_reason else None,
            "artifact_ref": self.artifact_ref,
            "error": self.error,
        }
