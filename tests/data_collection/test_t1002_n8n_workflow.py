"""T1002 — n8n workflow definition (glue only).

Acceptance (tasks.md T1002): the workflow doc/export exists; the MQTT topic -> batch ->
invoke path is described; it explicitly contains NO validation logic (Const. III — n8n
is glue). [DB/MQTT live verification deferred — no broker locally.]
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "n8n" / "data_collection_ingestion.workflow.json"
README = ROOT / "n8n" / "README.md"

# Words that would indicate validation LOGIC leaked into n8n (it must not).
VALIDATION_LOGIC_TERMS = (
    "phys_min", "phys_max", "zscore", "z-score", "interpolat", "baseline",
    "offline_after", "confirm_count", "spike detect", "range check",
)


@pytest.fixture(scope="module")
def workflow() -> dict:
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_export_exists_and_is_valid_json(workflow: dict):
    assert WORKFLOW.is_file()
    assert "nodes" in workflow and "connections" in workflow


def test_readme_exists():
    assert README.is_file()


def test_mqtt_to_batch_to_invoke_path_present(workflow: dict):
    node_types = {n["type"] for n in workflow["nodes"]}
    assert "n8n-nodes-base.mqttTrigger" in node_types       # subscribe MQTT
    assert "n8n-nodes-base.aggregate" in node_types          # batch per cycle
    assert "n8n-nodes-base.httpRequest" in node_types        # invoke the service

    # The connection chain MQTT -> Batch -> Invoke exists.
    conns = workflow["connections"]
    assert "MQTT Trigger (Mosquitto)" in conns
    assert "Batch Per Cycle" in conns
    assert "Invoke Data Collection Agent (T1001)" in conns


def test_invoke_targets_the_service_entrypoint(workflow: dict):
    http = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.httpRequest")
    url = http["parameters"]["url"]
    assert "run-cycle" in url
    # Retries the trigger/invoke on failure (Const. IV reliability).
    assert http["parameters"]["options"]["retry"]["maxTries"] >= 1


def test_contains_no_validation_logic(workflow: dict):
    blob = json.dumps(workflow).lower()
    for term in VALIDATION_LOGIC_TERMS:
        assert term.lower() not in blob, f"validation logic leaked into n8n: {term!r}"


def test_self_declares_glue_only(workflow: dict):
    meta = workflow.get("meta", {})
    assert meta.get("validation_logic", "").strip().lower().startswith("none")


def test_branches_only_on_cycle_ok_not_per_sensor_verdict(workflow: dict):
    # The IF node keys on the structured `ok` flag, not on any reading status.
    if_node = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.if")
    cond = json.dumps(if_node["parameters"]).lower()
    assert "ok" in cond
    for verdict in ("corrupt", "spike", "no_data", "offline", "interpolated"):
        assert verdict not in cond
