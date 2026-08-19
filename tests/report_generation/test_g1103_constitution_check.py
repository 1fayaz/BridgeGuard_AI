"""G1103 — Constitution check (Const. I / II / III / IV / VI).

Asserts, at the whole-agent level, the constitutional guarantees a reviewer reads directly against
`.specify/memory/constitution.md` v2.1.0:
  * never-crash — malformed/partial input -> a structured summary, not a raise (Principle V, FR-12);
  * reads never mutate the Risk/SA/DCA sources — the agent writes only its OWN report_artifacts;
  * every printed number traces to a source value (FR-5) — a fabricated number withholds;
  * the whole path is PURE deterministic code — no LLM/SDK import ANYWHERE in the agent's import
    graph (Principle IV: report generation is Option A, never a model call);
  * no needs_approval / dispatch tool present — the publication gate is a downstream agent (FR-13).

Structural assertions (import graph, package scan) are used where a behavioural test cannot see the
invariant. Mirrors the Risk R1103 gate.
"""
from __future__ import annotations

import ast
from pathlib import Path

from _report_harness import (
    CONFIG,
    HEADLINES,
    RENDERED_AT,
    HarnessSources,
    all_cases,
    run_case,
)
from agents.report_generation.render.fake_renderer import FakeRenderer
from agents.report_generation.report_statuses import ReportOutcome
from agents.report_generation.service import AssessmentScope, run_report
from agents.report_generation.store import FakeReportStore

SRC = Path(__file__).resolve().parents[2] / "src" / "agents" / "report_generation"

# Third-party model/SDK roots this deterministic agent must NOT depend on (Principle IV).
_MODEL_ROOTS = {"openai", "anthropic", "agents_sdk"}


def _imported_roots(module_path: Path) -> set[str]:
    """Top-level import roots of a module (AST — no execution, no substring false-matches)."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


def _assessment(**over):
    base = dict(
        id=1001, bridge_id="b", cycle_id="c", assessment_version=3,
        risk_score=48, severity="WARNING", review_status="FINAL",
        recommendation="Schedule inspection.", explanation="Deflection elevated at pier 3.",
        source_analysis_ids=[11], standard_code="AASHTO", standard_version="2020", superseded_by=None,
    )
    base.update(over)
    return base


def _analyses():
    return [{"id": 11, "result": {"ratio": 0.62}, "source_validated_ids": [110]}]


def _readings():
    return [{"id": 110, "value": 1.1}]


# --- Principle IV: the whole agent is deterministic code, no model anywhere ---------------------
def test_no_module_in_the_agent_imports_a_model_or_sdk():
    offenders = {}
    for path in SRC.rglob("*.py"):
        hit = _imported_roots(path) & _MODEL_ROOTS
        if hit:
            offenders[path.name] = hit
    assert not offenders, f"model/SDK imports leaked into the report agent: {offenders}"


def test_service_path_is_pure_and_deterministic():
    a = _assessment()
    s1 = run_report(AssessmentScope("b", "c"), sources=HarnessSources([a], _analyses(), _readings()),
                    store=FakeReportStore(), config=CONFIG, headlines=HEADLINES,
                    renderer=FakeRenderer(), rendered_at=RENDERED_AT)
    s2 = run_report(AssessmentScope("b", "c"), sources=HarnessSources([a], _analyses(), _readings()),
                    store=FakeReportStore(), config=CONFIG, headlines=HEADLINES,
                    renderer=FakeRenderer(), rendered_at=RENDERED_AT)
    assert (s1.outcome, s1.artifact_ref) == (s2.outcome, s2.artifact_ref)


# --- Principle II / VI / FR-5: every printed number traces to a source --------------------------
def test_a_fabricated_number_withholds_never_publishes():
    # The OFF_BOOK scenario injects a source value that drifts between assembly and the fidelity
    # index -> the fabricated value fails the gate -> WITHHELD/PROVENANCE_MISMATCH, no artifact.
    case = next(c for c in all_cases() if c.name == "OFF_BOOK")
    summary = run_case(case)
    assert summary.outcome is ReportOutcome.WITHHELD
    assert summary.artifact_ref is None


# --- Principle III / FR-3: reads never mutate the upstream sources ------------------------------
def test_render_does_not_mutate_the_source_rows():
    a = _assessment()
    analyses = _analyses()
    readings = _readings()
    before = (
        [dict(a)],
        [dict(r) for r in analyses],
        [dict(r) for r in readings],
    )
    src = HarnessSources([a], analyses, readings)
    run_report(AssessmentScope("b", "c"), sources=src, store=FakeReportStore(), config=CONFIG,
               headlines=HEADLINES, renderer=FakeRenderer(), rendered_at=RENDERED_AT)
    # the originals the caller passed in are unchanged (the agent read copies, never wrote back)
    assert [a] == before[0]
    assert analyses == before[1]
    assert readings == before[2]


# --- Principle IV / V / FR-12: never crashes — every scenario yields a structured status --------
def test_no_scenario_raises_every_result_is_structured():
    for case in all_cases():
        summary = run_case(case)
        assert summary is not None
        if not summary.ok:
            # withheld or error must carry a structured reason/error, never a bare crash
            assert summary.withheld_reason is not None or summary.error is not None or \
                summary.outcome is ReportOutcome.WITHHELD


def test_malformed_scope_is_structured_not_a_raise():
    case = next(c for c in all_cases() if c.name == "MALFORMED")
    summary = run_case(case)
    assert summary.ok is False
    assert summary.outcome in (ReportOutcome.WITHHELD, ReportOutcome.ERROR)


# --- Principle I / FR-13: no real-world-action gate here; the chokepoint is downstream ----------
def test_no_needs_approval_or_dispatch_tool_in_the_agent():
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8").lower()
        assert "needs_approval" not in text, f"{path.name} has a needs_approval gate (it is downstream)"
        assert "def publish" not in text and "def dispatch" not in text, (
            f"{path.name} defines a publication/dispatch tool (FR-13: downstream)")
