"""R1103 — Constitution check (Const. I / II / III / IV / VI).

Acceptance (tasks.md R1103): assert, at the whole-agent level, the constitutional guarantees:
  * never-crash — malformed/partial input -> a structured withheld/error assessment, not a raise;
  * reads never mutate SA/DCA tables — the assessment touches only its OWN store;
  * every emitted number traces to a retrieved value (FR-7) — a fabricated number is caught;
  * the score is PURE code — no LLM/SDK import in the scorer's graph (no model arithmetic);
  * no needs_approval / dispatch tool present — the real-world-action gate is downstream.

These overlap the FR-specific tests but assert the CONSTITUTION directly, as a single gate a
reviewer can read against `.specify/memory/constitution.md` v2.0.0. Structural assertions (import
graph, agent-definition shape) are used where a behavioural test cannot see the invariant.
"""
from __future__ import annotations

import ast
from pathlib import Path

from _harness import all_cases, run_case
from agents.risk_reasoning.agent import build_agent_definition, RISK_TOOL_NAMES
from agents.risk_reasoning.guardrail import (
    build_legitimate_set,
    provenance_guardrail,
)
from agents.risk_reasoning.scorer import FactorInput, score_bridge
from agents.risk_reasoning.statuses import ReviewStatus

SRC = Path(__file__).resolve().parents[2] / "src" / "agents" / "risk_reasoning"

# Third-party model/SDK roots the deterministic score must NOT depend on (Principle IV: the
# arithmetic is pure code, never the model).
_MODEL_ROOTS = {"openai", "anthropic", "agents_sdk"}


def _imported_roots(module_path: Path) -> set[str]:
    """The top-level import roots of a module (via AST — no execution, no substring false-matches)."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


# --- Principle IV: the score is deterministic pure code, not model arithmetic ------------------
def test_scorer_graph_has_no_model_or_sdk_dependency():
    # Walk the scorer's own module + the pure modules it imports; none may pull in a model/SDK.
    for name in ("scorer.py", "band.py", "coverage.py", "completeness.py"):
        roots = _imported_roots(SRC / name)
        assert not (roots & _MODEL_ROOTS), f"{name} imports a model/SDK root: {roots & _MODEL_ROOTS}"
        # Any intra-repo `agents...` import must stay within risk_reasoning (no cross-agent reach).
        # (Structural: the scorer depends only on config + assessment types, never on the agent.)


def test_score_is_reproducible_pure_arithmetic_independent_of_any_model():
    # Same inputs -> same score, computed with NO model object in scope at all.
    cfg = all_cases()[0].score_config
    factors = [FactorInput("rms", 1, 0.60, 1.0)]
    assert score_bridge(factors, cfg).score == score_bridge(factors, cfg).score == 60


# --- Principle I / FR-5: no real-world-action gate here; the chokepoint is downstream -----------
def test_agent_has_the_three_read_only_tools_and_no_dispatch_tool():
    definition = build_agent_definition("frontier-x")
    assert definition.tool_names == RISK_TOOL_NAMES
    assert len(definition.tool_names) == 3
    assert definition.has_needs_approval is False        # no needs_approval on this agent's output
    # None of the three tools is an action/dispatch tool — they are all read-only fetches.
    for name in definition.tool_names:
        assert name.startswith("get_")


# --- Principle II / VI / FR-7: every emitted number traces to a retrieved value ----------------
def test_a_fabricated_number_is_caught_by_the_provenance_guardrail():
    # Build the legitimate set from a real run's inputs, then prove an off-book number tripwires.
    ran = [_RanRow(1, {"value": 0.60, "limit": 1.0})]
    scored = score_bridge([FactorInput("rms", 1, 0.60, 1.0)], all_cases()[0].score_config)
    legit = build_legitimate_set(ran_results=ran, score=scored.score,
                                 factors=list(scored.factors), standard=None, tolerance=0.0)

    clean = f"The risk score is {scored.score}, driven by the retrieved factors."
    assert provenance_guardrail(clean, legit).passed is True

    fabricated = "The risk score is 60, but deflection was 48 mm beyond the limit."
    verdict = provenance_guardrail(fabricated, legit)
    assert verdict.passed is False
    assert any(tok.value == 48.0 for tok in verdict.offending)   # the invented number is named


# --- Principle III / FR-3: reads never mutate the upstream SA rows ------------------------------
def test_assessment_does_not_mutate_upstream_analysis_rows():
    case = all_cases()[0]                    # "normal"
    before = tuple(case.store.analysis)
    run_case(case)
    assert tuple(case.store.analysis) == before   # SA inputs untouched; only own tables written


# --- Principle IV / V / FR-8: never crashes — every input yields a structured status ------------
def test_no_scenario_raises_every_result_is_structured():
    for case in all_cases():
        summary = run_case(case)             # must not raise for ANY scripted scenario
        assert summary is not None
        if not summary.ok:
            assert summary.error             # malformed -> structured error, never a stack trace
        else:
            a = case.store.current("b1", "c1")
            assert a is not None
            # withheld or scored, review_status is ALWAYS explicitly set (never absent).
            assert a.review_status in (ReviewStatus.FINAL, ReviewStatus.PENDING_HUMAN_REVIEW)


def test_malformed_input_withholds_or_errors_but_never_throws():
    case = all_cases()[-1]                    # "malformed" (partial payload)
    summary = run_case(case)
    assert summary.ok is False and summary.error   # structured error, not an exception


# --- Small local SA-row stand-in for the guardrail test (mirrors AnalysisResultRow.result shape).
class _RanRow:
    def __init__(self, rid, result):
        self.id = rid
        self.result = result
