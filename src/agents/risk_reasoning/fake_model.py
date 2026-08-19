"""FakeReasoningModel (R702) — deterministic test stub for the reasoning step.

The real reasoning step calls a frontier model to draft the explanation. That is the only
[LLM-DEP] part of the agent; everything around it (scorer, guardrail loop, coverage gate,
persistence) is deterministic and must be testable without a live model. This stub stands in for
the model: it returns canned drafts keyed by scenario so R703+ can exercise every control-flow
branch deterministically.

It implements the same `draft(attempt, context)` shape the guardrail loop (R604) and orchestrator
(R703) call, so swapping in the real model changes only the draft TEXT, never the control flow.
Determinism is structural (no randomness, no clock) — required so tests and workflow-resume are
reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Scenario(str, Enum):
    """Which canned behaviour this stub plays out."""

    CLEAN = "CLEAN"                          # every draft traces -> emits first try
    ONE_BAD_THEN_CLEAN = "ONE_BAD_THEN_CLEAN"  # attempt 0 fabricates, attempt 1 clean
    TWO_BAD = "TWO_BAD"                      # both attempts fabricate -> fail closed
    CONFLICTING = "CONFLICTING"             # a valid narrative naming opposing factors


# A number that appears in NO test input, so a draft citing it tripwires the guardrail.
_FABRICATED = "Deflection was 48 mm, which the model asserts is beyond the limit."


def _clean_draft(context: dict[str, Any]) -> str:
    score = context.get("score")
    if score is not None:
        return f"The overall risk score is {score}, driven by the retrieved factors."
    return "The bridge is stable with no notable change since the last assessment."


@dataclass
class FakeReasoningModel:
    """Deterministic model stand-in. `draft(attempt, context)` returns the canned text for that
    attempt under the configured scenario, and records the attempt indices in `calls`."""

    scenario: Scenario
    calls: list[int] = field(default_factory=list)

    def draft(self, attempt: int, context: dict[str, Any]) -> str:
        self.calls.append(attempt)

        if self.scenario is Scenario.CLEAN:
            return _clean_draft(context)

        if self.scenario is Scenario.ONE_BAD_THEN_CLEAN:
            return _FABRICATED if attempt == 0 else _clean_draft(context)

        if self.scenario is Scenario.TWO_BAD:
            return _FABRICATED

        if self.scenario is Scenario.CONFLICTING:
            # A valid conflicting-signals narrative: vibration rose, deflection stayed low.
            return (
                "Vibration rose and pushed risk upward, while deflection stayed comfortably "
                "low and pulled the other way; the score reconciles the two."
            )

        raise ValueError(f"unknown scenario: {self.scenario}")  # pragma: no cover
