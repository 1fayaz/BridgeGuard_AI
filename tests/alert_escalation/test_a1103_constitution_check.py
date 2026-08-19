"""A1103 — constitution check (Const. I/II/III/IV/VI — the INVERTED chokepoint).

The spec-level constitution gate for the Alert & Escalation Agent, the mirror of the Report agent's
G1103 purity check. Where G1103 proves the Report agent has NO dispatch / needs_approval (the
chokepoint is downstream — here), A1103 proves the OPPOSITE for the Alert agent:

  I    Safety first / human signs off:  the needs_approval gate EXISTS in this package and is the
       SINGLE un-bypassable dispatch point in the whole system (reuses the A602 cross-repo scan).
  II   Data integrity / traceable:      reads never mutate the verdict; every dispatched band binds
       exactly to the source verdict (the consistency gate, FR-9); rows pin version + trace_id.
  III  Modularity:                       reads the Risk verdict by identity via the shared read tool;
       no other agent package defines a dispatch/notify path.
  IV   Reliability over cleverness:      NO model in ANY path — the whole package's import graph
       pulls in no openai / anthropic / agents_sdk root (ast check, mirroring G1103).
  VI   Auditability + never-crash:       malformed/partial input yields a structured summary, never
       a raise; the store is append-only + DELETE-blocked.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from _alert_harness import POLICY, TEMPLATES, NOW, HarnessSource
from agents.alert_escalation.consistency import consistency_check
from agents.alert_escalation.message import assemble_message
from agents.alert_escalation.service import AssessmentScope, run_alert
from agents.alert_escalation.store import FakeAlertStore
from agents.alert_escalation.dispatch.fake_notifier import FakeNotifier
from agents.alert_escalation.statuses import AlertOutcome, WithheldReason

AGENTS = Path(__file__).resolve().parents[2] / "src" / "agents"
ALERT = AGENTS / "alert_escalation"
_MODEL_ROOTS = {"openai", "anthropic", "agents_sdk"}


def _verdict(**over):
    base = dict(
        id=1001, bridge_id="b", cycle_id="c", assessment_version=3,
        risk_score=48, severity="WARNING", review_status="FINAL",
        recommendation="Schedule inspection.", explanation="Deflection ratio elevated at pier 3.",
        trace_id="trace-xyz", superseded_by=None,
    )
    base.update(over)
    return base


def _import_roots(path: Path) -> set[str]:
    """The top-level import roots of a module (AST — no substring false-matches)."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


# ------------------------------------------------------------------ IV — NO model in any path ---
def test_iv_no_model_import_anywhere_in_the_package():
    offenders: dict[str, set[str]] = {}
    for path in ALERT.rglob("*.py"):
        hits = _import_roots(path) & _MODEL_ROOTS
        if hits:
            offenders[path.name] = hits
    assert not offenders, f"a model/SDK import leaked into the Alert agent (Principle IV): {offenders}"


def test_iv_service_and_decision_modules_import_no_model():
    for name in ("service.py", "tiering.py", "message.py", "consistency.py",
                 "approval.py", "escalation.py"):
        assert not (_import_roots(ALERT / name) & _MODEL_ROOTS), f"{name} imports a model root"


# ------------------------------------------------------------------ I — the gate exists + is single ---
def test_i_the_approval_gate_exists_here():
    assert (ALERT / "approval.py").is_file()
    names = {
        n.name for n in ast.walk(ast.parse((ALERT / "approval.py").read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef)
    }
    assert "approval_gate" in names


def test_i_single_chokepoint_no_other_dispatch_path():
    # Reuses the A602 invariant: no non-Alert agent package defines a dispatch/notify path.
    dispatch_defs = ("def dispatch", "def publish", "def send", "def notify")
    others = ("data_collection", "structural_analysis", "risk_reasoning", "report_generation")
    offenders: dict[str, list[str]] = {}
    for pkg in others:
        pkg_dir = AGENTS / pkg
        if not pkg_dir.is_dir():
            continue
        for path in pkg_dir.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            hits = [d for d in dispatch_defs if d in text]
            if hits:
                offenders.setdefault(pkg, []).extend(f"{path.name}:{h}" for h in hits)
    assert not offenders, f"a non-Alert agent defines a dispatch path — chokepoint not single: {offenders}"


# ------------------------------------------------------------------ II — traceable / no re-judge ---
def test_ii_dispatched_band_binds_to_the_source_verdict():
    # The consistency gate is the alert-layer traceability control: a message must match its verdict.
    v = _verdict()
    msg = assemble_message(v, TEMPLATES)
    assert consistency_check(msg, v).passed is True       # honest assembly binds to the verdict
    # a mismatched band fails closed
    from agents.alert_escalation.message import AssembledMessage
    bad = AssembledMessage(band="SAFE", risk_score=48, recommendation="x", explanation="y",
                           review_status="FINAL", body="z", sources={})
    assert consistency_check(bad, v).passed is False


def test_ii_read_does_not_mutate_the_verdict():
    v = _verdict()
    snapshot = dict(v)
    run_alert(AssessmentScope("b", "c"), sources=HarnessSource([v]), store=FakeAlertStore(),
              policy=POLICY, templates=TEMPLATES, notifier=FakeNotifier(deliver_on_send=("email",)),
              now=NOW, approval=("APPROVED", "r@gov"))
    assert v == snapshot


# ------------------------------------------------------------------ VI — never crash + audit ---
def test_vi_malformed_input_is_structured_never_raises():
    s = run_alert(AssessmentScope(None, None), sources=HarnessSource([]),  # type: ignore[arg-type]
                  store=FakeAlertStore(), policy=POLICY, templates=TEMPLATES,
                  notifier=FakeNotifier(), now=NOW)
    assert s.outcome in (AlertOutcome.WITHHELD, AlertOutcome.ERROR)
    assert s.ok is False


def test_vi_store_is_append_only_and_delete_blocked():
    from agents.alert_escalation.store import (
        FakeAlertStore as Store,
        DispatchDeleteBlocked,
        DispatchImmutableError,
    )
    store = Store()
    run_alert(AssessmentScope("b", "c"),
              sources=HarnessSource([_verdict(severity="WATCH", risk_score=45)]),
              store=store, policy=POLICY, templates=TEMPLATES,
              notifier=FakeNotifier(deliver_on_send=("email",)), now=NOW)
    rid = store.rows[0].id
    with pytest.raises(DispatchImmutableError):
        store.overwrite(rid, store.rows[0].result)
    with pytest.raises(DispatchDeleteBlocked):
        store.delete(rid)


# ------------------------------------------------------------------ III — reads Risk by identity ---
def test_iii_reuses_the_shared_risk_read_not_a_fork():
    # The Alert verdict read re-exports the Risk/Report shared read tool — one reader, no fork (III).
    from agents.alert_escalation.tools import verdict_read
    from agents.report_generation.tools import risk_assessment_read
    assert verdict_read.get_risk_assessment is risk_assessment_read.get_risk_assessment
