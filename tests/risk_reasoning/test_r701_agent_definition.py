"""R701 — reasoning agent definition (frontier tier, three read-only tools, no dispatch).

[LLM-DEP] The OpenAI Agents SDK is not installed, and its top-level import name `agents` collides
with this repo's own `agents` package — so the live SDK Agent is constructed behind an adapter
(R701 defines the DECLARATION; the adapter is wired when the SDK is present). What is verifiable
now, without the SDK, is the safety-critical SHAPE of the agent:

  * exactly the THREE read-only tools (calc results, baseline, standard) — FR-3;
  * NO dispatch / action / needs_approval tool present — FR-5 (the gate is downstream);
  * frontier model tier, with the model id recorded for audit — FR-9 / research §3;
  * the prompt instructs the model to EXPLAIN the already-computed score, never to invent it — FR-2.
"""
from __future__ import annotations

from agents.risk_reasoning.agent import build_agent_definition, RISK_TOOL_NAMES


def test_exactly_the_three_readonly_tools():
    d = build_agent_definition(model_id="frontier-model-x")
    assert set(d.tool_names) == set(RISK_TOOL_NAMES)
    assert len(d.tool_names) == 3
    assert d.tool_names == (
        "get_calculation_results",
        "get_historical_baseline",
        "get_engineering_standard",
    )


def test_no_dispatch_or_action_tool_present():
    # FR-5 / mandate: this agent emits recommendations only; it must own NO tool that could take or
    # gate a real-world action. Guard against any alert/dispatch/close/notify/approval capability.
    d = build_agent_definition(model_id="frontier-model-x")
    forbidden = ("alert", "dispatch", "notify", "close", "signage", "approve", "approval",
                 "publish", "send")
    for name in d.tool_names:
        low = name.lower()
        assert not any(f in low for f in forbidden), f"forbidden action-capable tool: {name}"


def test_no_needs_approval_on_this_agent():
    # FR-5 / research §2: the needs_approval gate lives on the Alert Agent, never here.
    d = build_agent_definition(model_id="frontier-model-x")
    assert d.has_needs_approval is False


def test_frontier_model_id_is_recorded_for_audit():
    # FR-9: the model id + tier is pinned on the definition so each assessment can record it.
    d = build_agent_definition(model_id="frontier-model-x")
    assert d.model_id == "frontier-model-x"
    assert d.model_tier == "frontier"


def test_prompt_frames_score_as_fixed_input_to_explain_not_invent():
    # FR-2 / Principle IV: the score is deterministic; the model's job is the WHY. The system
    # prompt must make that explicit so the model never free-estimates the number.
    d = build_agent_definition(model_id="frontier-model-x")
    p = d.system_prompt.lower()
    assert "explain" in p
    assert "deterministic" in p or "already computed" in p or "do not invent" in p
    # And it must forbid citing numbers not in the inputs (mandate #2 framing).
    assert "number" in p


def test_definition_is_inert_without_the_sdk():
    # Building the DECLARATION must not require importing the SDK (which would fail / collide).
    # This proves the shape is testable now; the live Agent is constructed later by the adapter.
    d = build_agent_definition(model_id="frontier-model-x")
    assert d.tool_names            # populated
    assert d.system_prompt         # populated
    # No live SDK object is claimed here.
    assert not hasattr(d, "sdk_agent")
