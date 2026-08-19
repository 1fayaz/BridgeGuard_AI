"""The consistency gate (A502) — the alert-layer contradiction control (FR-9).

Before an alert is dispatched, verify the assembled message does not CONTRADICT the verdict it
claims to relay. Two contradictions are fatal:

  * band mismatch — the message's band label must equal the verdict's severity (a message reading
    "routine/SAFE" over a WARNING verdict would mislead an engineer at the worst moment); and
  * false finality — the message must not present a PENDING_HUMAN_REVIEW verdict as settled/final
    (FR-11: a not-yet-final verdict must never be relayed as actionable).

A contradiction TRIPWIRES the gate; the service then withholds (CONSISTENCY_MISMATCH) and
dispatches nothing. Fail-closed: an alert that misstates the record never reaches a human. This is
the Report agent's fidelity-gate analogue — plain code, no SDK, no model.

Pure function: it reads the assembled message + the verdict and returns a verdict; it mutates
nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.alert_escalation.message import AssembledMessage
from agents.risk_reasoning.statuses import ReviewStatus


@dataclass(frozen=True, slots=True)
class ConsistencyVerdict:
    """The gate's result: passed, plus a named contradiction when it fails (None when it passes)."""

    passed: bool
    contradiction: str | None = None


def consistency_check(message: AssembledMessage, verdict: dict[str, Any]) -> ConsistencyVerdict:
    """Verify the message does not contradict the verdict (A502). Pure; fail-closed."""
    source_band = verdict.get("severity")

    # --- Band fidelity: the message's stated band must equal the verdict's severity exactly. ---
    if message.band != source_band:
        return ConsistencyVerdict(
            passed=False,
            contradiction=(
                f"message band {message.band!r} contradicts verdict severity {source_band!r}"
            ),
        )

    # --- Finality fidelity: a PENDING verdict must never be relayed as settled/final (FR-11). ---
    verdict_pending = verdict.get("review_status") == ReviewStatus.PENDING_HUMAN_REVIEW.value
    message_claims_final = message.review_status == ReviewStatus.FINAL.value
    if verdict_pending and message_claims_final:
        return ConsistencyVerdict(
            passed=False,
            contradiction=(
                "message presents a PENDING_HUMAN_REVIEW verdict as FINAL (settled) — forbidden (FR-11)"
            ),
        )

    return ConsistencyVerdict(passed=True, contradiction=None)
