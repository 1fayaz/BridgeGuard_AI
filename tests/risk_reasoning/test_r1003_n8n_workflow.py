"""R1003 — n8n workflow definition (glue only, downstream of SA).

Acceptance (tasks.md R1003): the workflow doc/export exists; SA-cycle-complete -> invoke path is
described per bridge; it contains NO scoring/judgment logic (Const. III — n8n is glue); plan §6
reflected. [n8n/Supabase live verification deferred — none locally.]
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "n8n" / "risk_reasoning.workflow.json"
README = ROOT / "n8n" / "README.md"

# Words that would indicate SCORING / JUDGMENT logic leaked into n8n (it must not).
JUDGMENT_LOGIC_TERMS = (
    "weight", "normalis", "normaliz", "coverage_floor", "severity", "band",
    "risk_score", "guardrail", "critical", "score_bridge", "threshold",
)


@pytest.fixture(scope="module")
def workflow() -> dict:
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_export_exists_and_is_valid_json(workflow: dict):
    assert WORKFLOW.is_file()
    assert "nodes" in workflow and "connections" in workflow


def test_readme_exists():
    assert README.is_file()


def test_triggers_on_sa_cycle_complete_then_invokes(workflow: dict):
    node_types = {n["type"] for n in workflow["nodes"]}
    # Fires on SA-cycle-complete (a webhook/trigger from the SA service), then HTTP-invokes Risk.
    assert "n8n-nodes-base.httpRequest" in node_types
    assert any(t in node_types for t in ("n8n-nodes-base.webhook", "n8n-nodes-base.executeWorkflowTrigger"))


def test_invoke_targets_the_risk_service_entrypoint(workflow: dict):
    http = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest")
    url = http["parameters"]["url"]
    assert "assess" in url.lower() or "risk" in url.lower()
    # Retries the trigger/invoke on transport failure (Const. IV reliability).
    assert http["parameters"]["options"]["retry"]["maxTries"] >= 1


def test_invoke_passes_bridge_and_cycle_ids(workflow: dict):
    # The trigger carries the scope (bridge_id + cycle_id); n8n forwards them, derives nothing.
    http = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest")
    body = json.dumps(http["parameters"]).lower()
    assert "bridge_id" in body
    assert "cycle_id" in body


def test_contains_no_scoring_or_judgment_logic(workflow: dict):
    blob = json.dumps(workflow).lower()
    for term in JUDGMENT_LOGIC_TERMS:
        assert term.lower() not in blob, f"judgment logic leaked into n8n: {term!r}"


def test_self_declares_glue_only(workflow: dict):
    meta = workflow.get("meta", {})
    assert meta.get("scoring_logic", "").strip().lower().startswith("none")


def test_branches_only_on_ok_not_on_severity(workflow: dict):
    # If it branches, it keys on the structured `ok` flag, never on a risk band / review status.
    if_nodes = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.if"]
    for node in if_nodes:
        cond = json.dumps(node["parameters"]).lower()
        for verdict in ("critical", "warning", "watch", "safe", "pending_human_review"):
            assert verdict not in cond


def test_one_assessment_per_bridge_per_cycle_described(workflow: dict):
    # FR-3a: the workflow's purpose states one assessment per bridge per SA cycle.
    meta = workflow.get("meta", {})
    purpose = (meta.get("purpose", "") + meta.get("invokes", "")).lower()
    assert "cycle" in purpose and "bridge" in purpose
