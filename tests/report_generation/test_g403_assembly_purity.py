"""G403 — assembly copies-not-computes + no-model (FR-1/FR-2, AC-1/AC-2/AC-2a, Principle IV).

Strengthens G402 with the two guarantees a per-value test cannot express on its own:
  * copies-not-computes — every populated slot value is findable, unchanged, in the finalized
    inputs (or is the fixed headline lookup); a build that altered/derived a value would show a
    slot value that appears in NO source;
  * no model — the whole assembly import graph (model, assembler, headline table, read ports)
    pulls in NO model/SDK root (AST walk, mirroring Risk R1103). Report generation is Option A:
    deterministic templating, never a model call (Principle IV).

No new production code — this is an acceptance gate over G401/G402.
"""
from __future__ import annotations

import ast
from pathlib import Path

from agents.report_generation.assembler import assemble_report
from agents.report_generation.config.headline_table import HeadlineTable
from agents.report_generation.config.report_config import ReportConfig
from agents.report_generation.tools.analysis_results_read import AnalysisResultsReadResult
from agents.report_generation.tools.validated_readings_read import ValidatedReadingsReadResult
from agents.risk_reasoning.statuses import Severity

SRC = Path(__file__).resolve().parents[2] / "src" / "agents" / "report_generation"

# Third-party model/SDK roots this deterministic agent must NOT depend on (Principle IV).
_MODEL_ROOTS = {"openai", "anthropic", "agents_sdk"}


def _imported_roots(module_path: Path) -> set[str]:
    """Top-level import roots of a module (via AST — no execution, no substring false-matches)."""
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


# ---- shared fixtures (mirror G402) --------------------------------------------------------------
HEADLINES = HeadlineTable(
    phrases=tuple((s, f"HEADLINE::{s.value}") for s in Severity),
    withheld_phrase="HEADLINE::WITHHELD",
)
CONFIG = ReportConfig(
    report_template_version="rev2", appendix_max_rows=500,
    letterhead_ref="lh.png", template_ref="t.html",
)


def _assessment(**over):
    base = dict(
        id=1001, bridge_id="bridge-7", cycle_id="cycle-42", assessment_version=3,
        risk_score=48, severity="WARNING", recommendation="Schedule inspection within 30 days.",
        explanation="Deflection ratio elevated at pier 3; within limit but trending up.",
        review_status="FINAL", source_analysis_ids=[11], standard_code="AASHTO",
        standard_version="2020", superseded_by=None,
    )
    base.update(over)
    return base


def _analysis():
    return AnalysisResultsReadResult(
        available=True,
        results=({"id": 11, "result": {"ratio": 0.62}, "source_validated_ids": [110]},),
        missing_ids=(),
    )


def _readings():
    return ValidatedReadingsReadResult(
        available=True, readings=({"id": 110, "value": 1.1},),
        missing_ids=(), truncated=False, total_available=1,
    )


# --- copies-not-computes (AC-1) ------------------------------------------------------------------
def test_every_populated_slot_value_traces_to_a_source_or_the_headline():
    a = _assessment()
    m = assemble_report(a, _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")

    # The complete set of legitimate copied values from the finalized inputs.
    source_values = {
        a["risk_score"], a["severity"], a["recommendation"], a["explanation"],
        _analysis().results[0]["result"].__repr__(),   # nested payload compared structurally below
        _readings().readings[0]["value"],
    }
    # The one legitimately-non-copied value is the fixed headline for the band.
    allowed_headline = HEADLINES.headline_for(Severity(a["severity"]))

    for slot in m.all_slots():
        if slot.source_ref.startswith("headline_table:"):
            assert slot.value == allowed_headline
        elif slot.source_ref.startswith("analysis_results:"):
            # copied verbatim: identical object content to the source payload
            assert slot.value == _analysis().results[0]["result"]
        else:
            assert slot.value in source_values, (
                f"slot {slot.source_ref} has value {slot.value!r} found in NO source — "
                "assembly computed/derived it (FR-1 violation)"
            )


def test_explanation_is_never_reworded():
    a = _assessment()
    m = assemble_report(a, _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    expl = next(s for s in m.all_slots() if s.source_ref.endswith(":explanation"))
    assert expl.value == a["explanation"]      # exact bytes, not a paraphrase


def test_headline_is_config_derived_only_changes_with_band():
    warn = assemble_report(_assessment(), _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    crit = assemble_report(_assessment(severity="CRITICAL", review_status="PENDING_HUMAN_REVIEW"),
                           _analysis(), _readings(), CONFIG, HEADLINES, rendered_at="T")
    wh = next(s.value for s in warn.all_slots() if s.source_ref.startswith("headline_table:"))
    ch = next(s.value for s in crit.all_slots() if s.source_ref.startswith("headline_table:"))
    assert wh == "HEADLINE::WARNING"
    assert ch == "HEADLINE::CRITICAL"


# --- no model in the assembly graph (Principle IV) ----------------------------------------------
def test_assembly_graph_has_no_model_or_sdk_dependency():
    for name in ("model.py", "assembler.py", "report_result.py", "report_statuses.py",
                 "config/headline_table.py", "config/report_config.py",
                 "tools/risk_assessment_read.py", "tools/analysis_results_read.py",
                 "tools/validated_readings_read.py"):
        roots = _imported_roots(SRC / name)
        assert not (roots & _MODEL_ROOTS), f"{name} imports a model/SDK root: {roots & _MODEL_ROOTS}"


def test_no_module_in_the_package_imports_a_model_sdk():
    # Belt-and-braces: scan every .py in the package, not just the known assembly graph.
    for path in SRC.rglob("*.py"):
        roots = _imported_roots(path)
        assert not (roots & _MODEL_ROOTS), f"{path.name} imports a model/SDK root: {roots & _MODEL_ROOTS}"
