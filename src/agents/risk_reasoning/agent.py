"""Reasoning agent definition (R701) — FR-2 / FR-3 / FR-5 / FR-9.

This is the one BridgeGuard agent that genuinely IS a model-calling Agent (Principle IV reserves
the LLM for exactly this compound, ambiguous judgment). Its job is to EXPLAIN a score that was
already computed deterministically (R302) — never to invent the number.

The live OpenAI Agents SDK `Agent(...)` is NOT constructed here. Two reasons: the SDK is not
installed in this environment, and its top-level import name `agents` collides with this repo's own
`agents` package (resolved first via `pythonpath=["src"]`). Resolving that is a packaging decision
for when the SDK is wired (an adapter that imports the SDK under an alias, or renaming this repo's
package). Until then, `build_agent_definition` returns an INERT declaration that pins the
safety-critical shape — exactly the three read-only tools, no dispatch tool, frontier tier, and a
prompt that frames the score as a fixed input — so that shape is testable without the SDK.

FR-5: this agent owns NO tool that can take or gate a real-world action; the needs_approval gate
lives downstream on the Alert Agent. FR-9: the model id/tier is recorded so each assessment can
pin it.
"""
from __future__ import annotations

from dataclasses import dataclass


# The three read-only data-source tools (FR-3). Exactly these — no dispatch/action tool.
RISK_TOOL_NAMES: tuple[str, ...] = (
    "get_calculation_results",
    "get_historical_baseline",
    "get_engineering_standard",
)

# The system prompt frames the deterministic score as a FIXED input to explain (FR-2) and forbids
# citing any number not present in the retrieved inputs (mandate #2). It does not compute anything.
_SYSTEM_PROMPT = """\
You are BridgeGuard's Risk Reasoning agent. A whole-bridge risk score (0-100) has ALREADY been
computed deterministically from the Structural Analysis results. Your job is to EXPLAIN that
score for a government engineer: which factors raised or lowered it, how they compare to the
applicable engineering standard, the trend versus the historical baseline, and any conflicts or
uncertainties.

Rules you must not break:
- The score is a fixed, already-computed input. Do NOT invent, re-estimate, or change the number.
- Every number you cite in your explanation MUST come from the retrieved inputs (calculation
  results, historical baseline, or the engineering standard). Do NOT introduce any number that is
  not present in those inputs.
- Retrieve your inputs through the three read-only tools; reason only over what you retrieved.
- You produce a recommendation and an explanation only. You never dispatch an alert, change
  signage, or take any real-world action.
"""


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """An inert, SDK-free declaration of the reasoning agent's shape (R701).

    Holds everything an adapter needs to construct the live SDK Agent later — the tool set, the
    system prompt, and the pinned model — while being fully inspectable/testable now. Deliberately
    exposes no live SDK object.
    """

    model_id: str
    model_tier: str
    tool_names: tuple[str, ...]
    system_prompt: str
    has_needs_approval: bool


def build_agent_definition(model_id: str) -> AgentDefinition:
    """Build the inert reasoning-agent declaration (R701). No SDK import; frontier tier.

    `model_id` is the pinned frontier model (recorded per assessment for audit, FR-9). The
    definition carries exactly the three read-only tools and no dispatch tool (FR-5), and no
    needs_approval (the gate is downstream on the Alert Agent).
    """
    return AgentDefinition(
        model_id=model_id,
        model_tier="frontier",
        tool_names=RISK_TOOL_NAMES,
        system_prompt=_SYSTEM_PROMPT,
        has_needs_approval=False,
    )
