"""A602 — the inverted constitution gate: the needs_approval chokepoint EXISTS here and is SINGLE.

The OPPOSITE of the Report agent's G1103 purity check (which asserts NO needs_approval / dispatch
exists there, because the chokepoint is downstream — here). For the Alert agent:

  (a) the alert package DEFINES the needs_approval gate, and it ENFORCES — a NEEDS_APPROVAL
      decision without a recorded approval is held (no dispatch);
  (b) there is no code path that lets a gated dispatch proceed un-approved (the pure gate has no
      bypass; the service-level path is additionally exercised by A901 / A1102);
  (c) NO OTHER agent package (data_collection, structural_analysis, risk_reasoning,
      report_generation) defines a notify/dispatch-to-authority path — so this is the system's
      SINGLE un-bypassable real-world-action gate (Principle I; closes Risk 003 §2 + Report plan #12).

Structural (AST/text) assertions are used where a behavioural test cannot see the invariant.
"""
from __future__ import annotations

import ast
from pathlib import Path

from agents.alert_escalation.approval import approval_gate
from agents.alert_escalation.statuses import DispatchDecision

AGENTS = Path(__file__).resolve().parents[2] / "src" / "agents"
ALERT = AGENTS / "alert_escalation"

# The real-world-action verbs a dispatch path would define. Only the Alert agent may own these.
_DISPATCH_DEFS = ("def dispatch", "def publish", "def send", "def notify")

# Every other agent package — none of these may define a dispatch-to-the-outside-world path.
_OTHER_AGENT_PACKAGES = (
    "data_collection",
    "structural_analysis",
    "risk_reasoning",
    "report_generation",
)


def _def_names(path: Path) -> set[str]:
    """All function/method def names in a module (AST — no substring false-matches)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


# ------------------------------------------------------------------ (a) the gate EXISTS + ENFORCES ---
def test_the_alert_package_defines_the_approval_gate():
    # The gate is present in this package (the chokepoint is HERE, not downstream).
    assert (ALERT / "approval.py").is_file()
    names = _def_names(ALERT / "approval.py")
    assert "approval_gate" in names


def test_gated_dispatch_without_approval_is_held():
    r = approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=None)
    assert r.may_dispatch is False


def test_gated_dispatch_only_proceeds_when_approved():
    approved = approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=("APPROVED", "reviewer@gov"))
    assert approved.may_dispatch is True


# ------------------------------------------------------------------ (b) no bypass in the pure gate ---
def test_no_bypass_only_approved_dispatches():
    for approval in (None, ("AWAITING_APPROVAL", None), ("REJECTED", "r@gov")):
        assert approval_gate(DispatchDecision.NEEDS_APPROVAL, approval=approval).may_dispatch is False


# ------------------------------------------------------------------ (c) SINGLE chokepoint ---
def test_no_other_agent_package_defines_a_dispatch_path():
    offenders: dict[str, list[str]] = {}
    for pkg in _OTHER_AGENT_PACKAGES:
        pkg_dir = AGENTS / pkg
        if not pkg_dir.is_dir():
            continue
        for path in pkg_dir.rglob("*.py"):
            text = path.read_text(encoding="utf-8").lower()
            hits = [d for d in _DISPATCH_DEFS if d in text]
            if hits:
                offenders.setdefault(pkg, []).extend(f"{path.name}:{h}" for h in hits)
    assert not offenders, (
        f"a non-Alert agent defines a dispatch/notify path — the chokepoint must be single: {offenders}"
    )


def test_no_other_agent_package_has_a_needs_approval_gate():
    # Only the Alert agent enforces needs_approval. Others may DOCUMENT it (comments/README/a
    # has_needs_approval=False flag), but none may define an ENFORCING gate function.
    offenders: dict[str, list[str]] = {}
    for pkg in _OTHER_AGENT_PACKAGES:
        pkg_dir = AGENTS / pkg
        if not pkg_dir.is_dir():
            continue
        for path in pkg_dir.rglob("*.py"):
            names = _def_names(path)
            gate_defs = [n for n in names if "approval_gate" in n or n == "approval_gate"]
            if gate_defs:
                offenders.setdefault(pkg, []).extend(f"{path.name}:{n}" for n in gate_defs)
    assert not offenders, f"a non-Alert agent defines an approval gate: {offenders}"
