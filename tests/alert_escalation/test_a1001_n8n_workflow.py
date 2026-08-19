"""A1001 — n8n workflow definition (glue only, downstream of Risk).

Acceptance (tasks.md A1001): the workflow export exists; risk-assessment-available -> invoke path is
described per bridge; the invoke carries the scope key + retries the trigger; it branches only on the
structured `ok` (never on tier/state internals); it routes delivery/ack callbacks back to advance
`delivery_state`; it contains NO tiering/gate/dispatch/judgment logic (Const. III — n8n is glue, the
Python service owns every decision). Mirrors the DCA/Risk/Report glue workflows. [n8n/Neon live
verification deferred — none locally.]
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "n8n" / "alert_escalation.workflow.json"

# Words that would indicate DECISION logic leaked into n8n (tiering / gate / consistency / escalate).
# The alert's judgment must live ONLY in the Python service (A401/A502/A601/A703), never in glue.
ALERT_LOGIC_TERMS = (
    "tiering", "decide_tier", "auto_fire", "needs_approval", "dashboard_only",
    "consistency", "contradiction", "approval_gate", "escalate to", "failover",
    "retry_max", "backoff", "severity", "band", "roster",
)


@pytest.fixture(scope="module")
def workflow() -> dict:
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_export_exists_and_is_valid_json(workflow: dict):
    assert WORKFLOW.is_file()
    assert "nodes" in workflow and "connections" in workflow


def test_triggers_on_risk_assessment_available_then_invokes(workflow: dict):
    node_types = {n["type"] for n in workflow["nodes"]}
    assert "n8n-nodes-base.httpRequest" in node_types
    assert any(t in node_types for t in ("n8n-nodes-base.webhook", "n8n-nodes-base.executeWorkflowTrigger"))


def test_invoke_targets_the_alert_service_entrypoint(workflow: dict):
    https = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"]
    urls = " ".join(n["parameters"]["url"].lower() for n in https)
    assert "alert" in urls
    # Retries the trigger/invoke on transport failure (Const. IV reliability).
    assert any(n["parameters"]["options"].get("retry", {}).get("maxTries", 0) >= 1 for n in https)


def test_invoke_passes_the_scope_key(workflow: dict):
    # The trigger carries the scope (bridge_id + cycle_id); n8n forwards, derives nothing.
    http = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest")
    blob = json.dumps([n["parameters"] for n in workflow["nodes"]]).lower()
    assert "bridge_id" in blob
    assert "cycle_id" in blob


def test_contains_no_tiering_gate_or_dispatch_logic(workflow: dict):
    # Whole-word scan: "band" as its own token is a decision-logic leak, but "out-of-band" (a
    # transport term) is not — so match on word boundaries, not bare substrings.
    blob = json.dumps(workflow).lower()
    for term in ALERT_LOGIC_TERMS:
        assert not re.search(rf"(?<![\w-]){re.escape(term.lower())}(?![\w-])", blob), (
            f"alert decision logic leaked into n8n: {term!r}"
        )


def test_self_declares_glue_only(workflow: dict):
    meta = workflow.get("meta", {})
    assert meta.get("decision_logic", "").strip().lower().startswith("none")


def test_is_fire_and_notify_not_blocking(workflow: dict):
    meta = workflow.get("meta", {})
    mode = (meta.get("mode", "") + meta.get("purpose", "")).lower()
    assert "fire-and-notify" in mode or "does not block" in mode or "async" in mode


def test_branches_only_on_ok_not_on_tier_or_state(workflow: dict):
    # If it branches, it keys on the structured `ok` flag, never on a tier / delivery / escalation state.
    if_nodes = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.if"]
    assert if_nodes, "expected a branch on the structured ok flag"
    for node in if_nodes:
        cond = json.dumps(node["parameters"]).lower()
        assert "ok" in cond
        for internal in ("auto_fire", "needs_approval", "delivered", "acknowledged", "escalated"):
            assert internal not in cond


def test_routes_delivery_ack_callbacks_back(workflow: dict):
    # The workflow routes provider receipt / human-ack callbacks back to advance delivery_state
    # (the out-of-band reconciliation the service consumes). This is glue transport, not judgment.
    blob = json.dumps(workflow).lower()
    assert "delivery_state" in blob or "callback" in blob or "receipt" in blob


def test_downstream_of_risk_described(workflow: dict):
    meta = workflow.get("meta", {})
    text = (meta.get("purpose", "") + meta.get("upstream", "")).lower()
    assert "risk" in text and "bridge" in text


def test_single_chokepoint_note_present(workflow: dict):
    # The alert IS the system's single real-world-action chokepoint; the glue must not add a second
    # un-gated dispatch path of its own — it only invokes the gated service.
    meta = workflow.get("meta", {})
    text = json.dumps(meta).lower()
    assert "chokepoint" in text or "gated service" in text or "no un-gated" in text
