"""Closed status vocabulary for the Alert & Escalation Agent (A201).

Mirrors the Report/Risk/DCA/SA `statuses.py` style: small closed enums the output contract (A202),
the schema (A203/A204), and persistence (A801/A802) all rely on. `str, Enum` so values round-trip
cleanly to/from the DB enums and JSON.

The severity band + finality vocabularies belong to the Risk agent (Agent 003). This agent IMPORTS
`Severity` and `ReviewStatus` from `agents.risk_reasoning.statuses` and re-exports them for
convenience — it never forks its own copy (one closed set of bands across the whole system).

The spec's output vocabulary in six new enums:
  * DispatchDecision — the resolved dispatch tier (FR-2/FR-3): auto-fire, held for approval, or
    dashboard-only (no push).
  * DeliveryState    — where a dispatch is on the wire (FR-7). SENT (provider accepted) is NOT
    DELIVERED (receipt confirmed) is NOT ACKNOWLEDGED (a human confirmed) — three distinct states.
  * EscalationState  — where the escalation ladder is (FR-6): open, escalated to the next contact,
    or closed (delivery for SAFE/WATCH, ack for WARNING/CRITICAL).
  * ApprovalState    — the human sign-off on a gated dispatch (FR-5).
  * AlertOutcome     — what happened overall: dispatched, deliberately withheld, or an unexpected
    (structured) error — never a crash (FR-12).
  * WithheldReason   — the deliberately narrow set of no-dispatch cases.
"""
from __future__ import annotations

from enum import Enum

# Re-export the Risk agent's band + finality vocabularies. IMPORTED, never redeclared — the Alert
# agent reasons over exactly the Severity/ReviewStatus the verdict carries.
from agents.risk_reasoning.statuses import ReviewStatus, Severity

__all__ = [
    "Severity",
    "ReviewStatus",
    "DispatchDecision",
    "DeliveryState",
    "EscalationState",
    "ApprovalState",
    "AlertOutcome",
    "WithheldReason",
]


class DispatchDecision(str, Enum):
    """The resolved dispatch tier for a verdict (FR-2/FR-3). Closed set of three."""

    AUTO_FIRE = "AUTO_FIRE"            # dispatch without human approval (SAFE/WATCH, internal, FINAL)
    NEEDS_APPROVAL = "NEEDS_APPROVAL"  # blocked until a human approves (WARNING/CRITICAL, authority, pending)
    DASHBOARD_ONLY = "DASHBOARD_ONLY"  # no outbound push at all (SAFE — dashboard/timeline only)


class DeliveryState(str, Enum):
    """Where a single dispatch is on the wire (FR-7). SENT != DELIVERED != ACKNOWLEDGED."""

    QUEUED = "QUEUED"              # accepted locally, not yet handed to the provider
    SENT = "SENT"                 # the provider accepted it (NOT proof a human received it)
    DELIVERED = "DELIVERED"       # a provider delivery receipt confirmed delivery
    FAILED = "FAILED"             # the provider reported failure (drives retry/failover)
    ACKNOWLEDGED = "ACKNOWLEDGED" # a human explicitly acknowledged (closes WARNING/CRITICAL)


class EscalationState(str, Enum):
    """Where the escalation ladder is for an alert (FR-6). Closed set of three."""

    OPEN = "OPEN"            # dispatched, awaiting its close condition
    ESCALATED = "ESCALATED"  # advanced to the next contact / on-call (no timely delivery/ack)
    CLOSED = "CLOSED"        # close condition met (DELIVERED for SAFE/WATCH, ACK for WARNING/CRITICAL)


class ApprovalState(str, Enum):
    """The human sign-off on a NEEDS_APPROVAL dispatch (FR-5). Closed set of three."""

    AWAITING_APPROVAL = "AWAITING_APPROVAL"  # gated, no approval recorded yet — dispatch blocked
    APPROVED = "APPROVED"                    # a human approved — dispatch may proceed
    REJECTED = "REJECTED"                    # a human declined — no dispatch, recorded


class AlertOutcome(str, Enum):
    """What happened to an alert run overall. Closed set of three."""

    DISPATCHED = "DISPATCHED"  # a notification was dispatched (possibly still escalating/awaiting ack)
    WITHHELD = "WITHHELD"      # no dispatch, on purpose (carries a WithheldReason)
    ERROR = "ERROR"            # an unexpected failure — structured, never a crash (FR-12)


class WithheldReason(str, Enum):
    """The only cases where dispatching NOTHING is correct.

    Everything else (any band, pending or final, escalating) proceeds to a dispatch decision.
    """

    ASSESSMENT_NOT_FOUND = "ASSESSMENT_NOT_FOUND"   # the scope key resolves to no verdict row
    CONSISTENCY_MISMATCH = "CONSISTENCY_MISMATCH"   # the message contradicts the verdict (FR-9)
