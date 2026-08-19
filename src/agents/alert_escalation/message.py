"""assemble_message(...) (A501) — the pure "notify, never re-judge" assembly (FR-1).

Builds an AssembledMessage by COPYING the finalized verdict into a fixed per-band template (A102).
The contract that makes this agent safe: every message field is a verbatim copy of a verdict field
(its source_ref names the row+field), and the body is the fixed template filled with those copied
values — nothing here recomputes, re-maps, or rewords the verdict (that would create a new,
ungoverned statement that never passed the Risk Agent's numeric-provenance guardrail).

The `field_source(...)` map lets the consistency gate (A502) verify that every field the alert
states traces back to the verdict. Pure function: reads its inputs, returns an AssembledMessage,
mutates nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agents.alert_escalation.config.message_template_table import (
    TODO_TEMPLATE,
    MessageTemplateTable,
)
from agents.risk_reasoning.statuses import Severity


@dataclass(frozen=True, slots=True)
class AssembledMessage:
    """The assembled alert: verbatim verdict fields + their source_refs + the filled template body."""

    band: str | None                 # copied from verdict.severity (None on a withheld-score verdict)
    risk_score: int | None           # copied from verdict.risk_score
    recommendation: str              # copied from verdict.recommendation
    explanation: str                 # copied byte-for-byte from verdict.explanation
    review_status: str               # copied from verdict.review_status (finality, for A502)
    body: str                        # the fixed template filled with the copied values
    sources: dict[str, str]          # field name -> "risk_assessments:{id}:{field}" provenance

    def field_source(self, field: str) -> str | None:
        """The source_ref a message field was copied from, or None if it has none (a red flag)."""
        return self.sources.get(field)


def assemble_message(verdict: dict[str, Any], templates: MessageTemplateTable) -> AssembledMessage:
    """Assemble an alert message from a finalized verdict by copying (A501). Pure; mutates nothing."""
    aid = verdict["id"]
    severity_value = verdict.get("severity")

    # Every stated field is a verbatim copy; its source_ref names the exact verdict field.
    sources = {
        "band": f"risk_assessments:{aid}:severity",
        "risk_score": f"risk_assessments:{aid}:risk_score",
        "recommendation": f"risk_assessments:{aid}:recommendation",
        "explanation": f"risk_assessments:{aid}:explanation",
    }

    # The template is the fixed A102 lookup keyed on the band. A withheld-score verdict (no band)
    # has no band template; the loud TODO sentinel is used for an unconfigured band — never guessed.
    if severity_value is None:
        template = TODO_TEMPLATE
    else:
        template = templates.template_for(Severity(severity_value))

    body = _fill(template, verdict)

    return AssembledMessage(
        band=severity_value,
        risk_score=verdict.get("risk_score"),
        recommendation=verdict["recommendation"],
        explanation=verdict["explanation"],
        review_status=verdict["review_status"],
        body=body,
        sources=sources,
    )


def _fill(template: str, verdict: dict[str, Any]) -> str:
    """Fill a template's {field} placeholders with verbatim verdict values.

    Only known verdict fields are substituted; an unknown placeholder is left as-is rather than
    raising, so a misconfigured template degrades visibly instead of crashing the dispatch (FR-12).
    """
    fields = {
        "bridge_id": verdict.get("bridge_id", ""),
        "cycle_id": verdict.get("cycle_id", ""),
        "risk_score": verdict.get("risk_score", ""),
        "severity": verdict.get("severity", ""),
        "recommendation": verdict.get("recommendation", ""),
        "explanation": verdict.get("explanation", ""),
    }
    out = template
    for key, value in fields.items():
        out = out.replace("{" + key + "}", str(value))
    return out
