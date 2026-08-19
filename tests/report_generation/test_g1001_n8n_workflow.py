"""G1001 — n8n workflow definition (glue only, downstream of Risk).

Acceptance (tasks.md G1001): the workflow export exists; risk-assessment-available -> invoke path
is described per bridge; the invoke carries the scope key + retries the trigger; it branches only on
the structured `ok` (never on marks/outcome internals); it contains NO assembly/render/judgment
logic (Const. III — n8n is glue); fire-and-notify (does not block for the render). Mirrors the
DCA/Risk glue workflows. [n8n/Neon live verification deferred — none locally.]
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "n8n" / "report_generation.workflow.json"

# Words that would indicate ASSEMBLY / RENDER / JUDGMENT logic leaked into n8n (it must not).
REPORT_LOGIC_TERMS = (
    "assemble", "fidelity", "render", "reportlab", "matplotlib", "slot",
    "provenance", "verbatim", "headline", "section_unavailable", "not_final",
)


@pytest.fixture(scope="module")
def workflow() -> dict:
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_export_exists_and_is_valid_json(workflow: dict):
    assert WORKFLOW.is_file()
    assert "nodes" in workflow and "connections" in workflow


def test_triggers_on_risk_assessment_available_then_invokes(workflow: dict):
    node_types = {n["type"] for n in workflow["nodes"]}
    # Fires on a risk-assessment-available signal (a webhook/trigger), then HTTP-invokes the report.
    assert "n8n-nodes-base.httpRequest" in node_types
    assert any(t in node_types for t in ("n8n-nodes-base.webhook", "n8n-nodes-base.executeWorkflowTrigger"))


def test_invoke_targets_the_report_service_entrypoint(workflow: dict):
    http = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest")
    url = http["parameters"]["url"]
    assert "report" in url.lower()
    # Retries the trigger/invoke on transport failure (Const. IV reliability).
    assert http["parameters"]["options"]["retry"]["maxTries"] >= 1


def test_invoke_passes_the_scope_key(workflow: dict):
    # The trigger carries the scope (bridge_id + cycle_id); n8n forwards, derives nothing.
    http = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest")
    body = json.dumps(http["parameters"]).lower()
    assert "bridge_id" in body
    assert "cycle_id" in body


def test_contains_no_assembly_or_render_logic(workflow: dict):
    blob = json.dumps(workflow).lower()
    for term in REPORT_LOGIC_TERMS:
        assert term.lower() not in blob, f"report logic leaked into n8n: {term!r}"


def test_self_declares_glue_only(workflow: dict):
    meta = workflow.get("meta", {})
    assert meta.get("assembly_logic", "").strip().lower().startswith("none")


def test_is_fire_and_notify_not_blocking(workflow: dict):
    # Fire-and-notify: the workflow declares it does not block for the (5-30s) render.
    meta = workflow.get("meta", {})
    mode = (meta.get("mode", "") + meta.get("purpose", "")).lower()
    assert "fire-and-notify" in mode or "does not block" in mode or "async" in mode


def test_branches_only_on_ok_not_on_marks_or_outcome(workflow: dict):
    # If it branches, it keys on the structured `ok` flag, never on a document mark / outcome.
    if_nodes = [n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.if"]
    for node in if_nodes:
        cond = json.dumps(node["parameters"]).lower()
        for internal in ("rendered", "withheld", "historical", "score_withheld", "provenance_mismatch"):
            assert internal not in cond


def test_downstream_of_risk_described(workflow: dict):
    # The workflow's purpose states it fires downstream of the Risk Agent, per bridge.
    meta = workflow.get("meta", {})
    text = (meta.get("purpose", "") + meta.get("upstream", "")).lower()
    assert "risk" in text and "bridge" in text


def test_no_publication_step_here(workflow: dict):
    # FR-13: publication/dispatch is a downstream gated agent, NOT this glue workflow.
    blob = json.dumps(workflow).lower()
    for term in ("publish", "dispatch", "email", "sms", "municipal"):
        assert term not in blob, f"publication leaked into the render glue: {term!r}"
