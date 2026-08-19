"""A503 — assembly-verbatim + consistency fail-closed + no-model (FR-1/FR-9, AC-1/AC-8).

Drives A501/A502 together over fake verdicts to assert the spec-level behaviour a reviewer reads:
  * the assembled message equals the source (assemble-only) and the explanation is byte-identical;
  * a deliberately INJECTED contradicting band (message says "SAFE" over a WARNING verdict) trips
    the consistency gate -> the alert would be withheld (CONSISTENCY_MISMATCH), never dispatched;
  * a clean message passes;
  * NO model anywhere in the assembly/consistency import graph (Principle IV — this is Option A,
    the same ast import-root check the Report agent's G403/G1103 uses).
"""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

from agents.alert_escalation.config.message_template_table import MessageTemplateTable
from agents.alert_escalation.consistency import consistency_check
from agents.alert_escalation.message import assemble_message
from agents.risk_reasoning.statuses import Severity

SRC = Path(__file__).resolve().parents[2] / "src" / "agents" / "alert_escalation"
_MODEL_ROOTS = {"openai", "anthropic", "agents_sdk"}

TEMPLATES = MessageTemplateTable(
    templates=tuple((s, f"{s.value} {{bridge_id}}: {{recommendation}} — {{explanation}}") for s in Severity),
)


def _verdict(**over):
    base = dict(
        id=1001, bridge_id="bridge-7", cycle_id="cycle-42", assessment_version=3,
        risk_score=70, severity="WARNING",
        recommendation="Schedule inspection within 30 days.",
        explanation="Deflection ratio elevated at pier 3; within limit but trending up.",
        review_status="FINAL", trace_id="trace-xyz",
    )
    base.update(over)
    return base


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


# ------------------------------------------------------------------ assemble-only / verbatim ---
def test_message_is_assembled_from_the_source_not_computed():
    v = _verdict()
    m = assemble_message(v, TEMPLATES)
    assert m.band == v["severity"]
    assert m.risk_score == v["risk_score"]
    assert m.recommendation == v["recommendation"]


def test_explanation_is_byte_for_byte_identical():
    v = _verdict(explanation="Precise WHY, 48.0mm measured at pier 3 vs 50mm limit.")
    m = assemble_message(v, TEMPLATES)
    assert m.explanation == "Precise WHY, 48.0mm measured at pier 3 vs 50mm limit."


# ------------------------------------------------------------------ consistency fail-closed ---
def test_injected_contradicting_band_trips_the_gate():
    v = _verdict(severity="WARNING")
    m = assemble_message(v, TEMPLATES)
    off_book = replace(m, band="SAFE")           # inject a contradiction
    verdict = consistency_check(off_book, v)
    assert verdict.passed is False               # -> service would WITHHELD/CONSISTENCY_MISMATCH
    assert verdict.contradiction is not None


def test_clean_message_passes_the_gate():
    v = _verdict()
    assert consistency_check(assemble_message(v, TEMPLATES), v).passed is True


# ------------------------------------------------------------------ no model (Principle IV) ---
def test_no_module_in_the_assembly_or_gate_imports_a_model_or_sdk():
    offenders = {}
    for name in ("message.py", "consistency.py", "tiering.py"):
        hit = _imported_roots(SRC / name) & _MODEL_ROOTS
        if hit:
            offenders[name] = hit
    assert not offenders, f"model/SDK imports leaked into the alert assembly/gate: {offenders}"
