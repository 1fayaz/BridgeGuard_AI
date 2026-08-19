"""P407 — the ack says "stored", never "valid", and it wakes nobody up.

Two guarantees that look unrelated and are the same guarantee seen from two sides.

**The response promises durability, not validity.** A 200 from ingest means the readings are in
`raw_readings` and will survive a restart. It does not mean the numbers are trustworthy. That
distinction matters because of who is reading it: a Pi's firmware, and eventually a dashboard
built by someone who read our OpenAPI schema. If the ack carried anything that *looked* like a
verdict — a `valid` flag, a quality score, an anomaly hint — then somewhere downstream a human
would end up looking at a boundary's structural opinion and believing a bridge had been
assessed. The API is not qualified to have that opinion; the DCA is, on its own cycle, with the
sensor's history in view (Principle III).

**Nothing is enqueued and no agent is called.** Decision 2: the DCA is picked up by its own 1–5
minute scheduler tick, and there is deliberately no "raw arrived" signal. A per-batch trigger
would either duplicate that tick or make the agent's cadence a function of gateway traffic — so
a chatty Pi would drive validation frequency, and a silent one would stall it. Worse, an ingest
call that awaits an agent has coupled a field device's uplink timeout to a model's latency.

The accepted consequence is that a reading can be up to one scheduler period old before it is
validated. That is inherent to the DCA's design, not introduced here (plan §4).

This file is mostly structural, and that is on purpose. "We remembered not to call the agent"
is not a property; "no code in this layer can" is.

Ties to tasks.md P407, plan §4 + decision 2, Principle III.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from api.audit import FakeAuditLog
from api.auth.principal import Principal
from api.ingest.batch import parse_batch
from api.ingest.ownership import SensorRegistry
from api.ingest.processor import IngestOutcome, ReadingResult, process_batch
from api.ingest.raw_store import FakeRawStore

API_ROOT = Path(__file__).resolve().parents[2] / "src" / "api"
INGEST_ROOT = API_ROOT / "ingest"

GOOD = {
    "sensor_id": "S_OURS",
    "sensor_type": "strain",
    "value": 12.5,
    "unit": "microstrain",
    "sensor_time": "2026-08-05T10:00:00Z",
}
IMPLAUSIBLE = {**GOOD, "value": 9.0e12}


class _OurBridge:
    def has_sensor(self, sensor_id: str) -> bool:
        return True

    def bridge_of_sensor(self, sensor_id: str) -> str:
        return "BRIDGE_1"

    def get_sensor(self, sensor_id: str):
        return _Unconfigured()


class _Unconfigured:
    config: dict = {}


@pytest.fixture
def store() -> FakeRawStore:
    return FakeRawStore()


def run(payloads: list[dict], store: FakeRawStore):
    return process_batch(
        parse_batch({"readings": payloads}),
        store=store,
        principal=Principal.for_device(municipality_id="MUNI_A", bridge_id="BRIDGE_1"),
        registry=SensorRegistry(_OurBridge()),
        audit=FakeAuditLog(),
    )


def _ingest_sources() -> list[tuple[str, str]]:
    out = []
    for path in sorted(INGEST_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        out.append((path.relative_to(INGEST_ROOT).as_posix(), path.read_text(encoding="utf-8")))
    return out


def _code_only(src: str) -> str:
    """Strip comments and docstrings before scanning.

    Otherwise this file's own honest prose about what it refuses to do — "never validates",
    "invokes no agent" — trips the scans that look for those words.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    body.pop(0)
    return ast.unparse(tree)


# --------------------------------------------------- the ack carries no validation verdict ---
def test_the_outcome_exposes_no_validity_field(store: FakeRawStore):
    outcome = run([GOOD], store)
    for banned in ("valid", "validated", "validation", "quality", "confidence", "anomaly",
                   "anomalies", "flagged", "severity", "risk", "score", "band"):
        assert not hasattr(outcome, banned), f"the ack carries a verdict: {banned}"


def test_a_per_reading_result_exposes_no_validity_field(store: FakeRawStore):
    outcome = run([GOOD], store)
    for banned in ("valid", "quality", "confidence", "anomaly", "flag", "severity", "score",
                   "plausible", "suspect", "drift"):
        assert not hasattr(outcome.results[0], banned), f"a result carries a verdict: {banned}"


def test_the_result_contract_is_exactly_four_fields():
    """Pinned, so a verdict cannot be added without this failing."""
    assert set(ReadingResult.model_fields) == {"index", "sensor_id", "accepted", "reason"}


def test_the_outcome_contract_is_exactly_two_fields():
    """`accepted_count`/`rejected_count` are derived properties, not stored fields (P403)."""
    assert set(IngestOutcome.model_fields) == {"batch_id", "results"}


def test_accepted_means_stored_not_plausible(store: FakeRawStore):
    """A strain reading of 9e12 is physically absurd and still `accepted`.

    Refusing it here would be the API forming a judgment about a bridge — with none of the
    sensor's history, calibration, or context that judgment requires (Principle III).
    """
    outcome = run([IMPLAUSIBLE], store)
    assert outcome.results[0].accepted is True
    assert store.count() == 1


def test_a_future_timestamp_is_accepted_too(store: FakeRawStore):
    """Clock skew on a field Pi is real. What to do about it is the DCA's call."""
    outcome = run([{**GOOD, "sensor_time": "2099-01-01T00:00:00Z"}], store)
    assert outcome.results[0].accepted is True


def test_accepted_readings_are_stored_unflagged(store: FakeRawStore):
    """No quality column sneaks in on the write path either."""
    run([IMPLAUSIBLE], store)
    row = store.rows[0]
    for banned in ("valid", "quality", "confidence", "anomaly", "flag", "severity", "score",
                   "status", "processed"):
        assert banned not in row, f"the stored raw row carries a verdict: {banned}"


def test_the_stored_row_holds_the_value_verbatim(store: FakeRawStore):
    """Not clipped, not normalised, not rounded. Principle II: raw means raw."""
    run([IMPLAUSIBLE], store)
    assert store.rows[0]["value"] == 9.0e12


def test_the_ingest_path_names_no_validation_concept():
    """Structural, over code with docstrings stripped."""
    for rel, src in _ingest_sources():
        body = _code_only(src).lower()
        for banned in ("def validate", "is_valid", "quality_score", "interpolat", "def clean",
                       "is_anomal", "def flag", "plausib", "calibrat", "def normalise",
                       "def normalize"):
            assert banned not in body, f"{rel} performs validation: {banned}"


# ------------------------------------------------- nothing is enqueued, no agent is called ---
def test_no_ingest_module_imports_an_agent():
    """The repo's own `agents` package, and the SDK behind its adapter alias."""
    for rel, src in _ingest_sources():
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("agents"), f"{rel} imports {alias.name}"
                    assert "openai_agents" not in alias.name, f"{rel} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("agents"), f"{rel} imports from {node.module}"
                assert "openai_agents" not in node.module, f"{rel} imports from {node.module}"


def test_no_ingest_module_imports_a_queue():
    """Decision 2: there is no enqueue on this path. Arq belongs to the report jobs (P701+)."""
    for rel, src in _ingest_sources():
        tree = ast.parse(src)
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                root = name.split(".")[0]
                assert root not in {"arq", "celery", "rq", "redis", "kombu", "aio_pika",
                                    "kafka", "confluent_kafka"}, f"{rel} imports {name}"


def test_the_ingest_path_makes_no_enqueue_call():
    """Call-site names, since a queue can arrive by dependency injection rather than import."""
    banned = {"enqueue", "enqueue_job", "publish", "send_task", "delay", "apply_async",
              "dispatch", "trigger", "notify", "emit", "schedule", "kickoff"}
    offenders = []
    for rel, src in _ingest_sources():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call):
                name = None
                if isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    name = node.func.id
                if name in banned:
                    offenders.append(f"{rel}: {name}()")
    assert not offenders, f"the ingest path signals downstream work: {offenders}"


def test_the_ingest_path_makes_no_outbound_network_call():
    """An agent reached over HTTP is still an agent invocation."""
    for rel, src in _ingest_sources():
        body = _code_only(src).lower()
        for banned in ("httpx", "requests.", "aiohttp", "urllib", "http.client", "websocket"):
            assert banned not in body, f"{rel} calls out to the network: {banned}"


def test_the_ingest_path_runs_no_subprocess_and_starts_no_thread():
    """The other two ways to make ingest await work that is not ingest's."""
    for rel, src in _ingest_sources():
        body = _code_only(src).lower()
        for banned in ("subprocess", "threading", "multiprocessing", "create_task",
                       "run_in_executor", "spawn"):
            assert banned not in body, f"{rel} starts out-of-band work: {banned}"


def test_process_batch_takes_no_queue_or_agent_dependency():
    """A parameter is the polite way to smuggle one in. Its absence is checkable.

    `audit` (P408) is a sink, not a signal: it records that the call happened, and nothing
    downstream reads it to decide when to run. Pinning the exact set is what keeps the
    distinction honest — a queue could not be added under a plausible name without failing here.
    """
    params = set(inspect.signature(process_batch).parameters)
    assert params == {"batch", "store", "principal", "registry", "audit"}


def test_process_batch_is_synchronous():
    """Not a style point.

    An `async def` here is the shape that awaits something, and the only things left to await
    on this path are the agent or the queue that P407 forbids. Staying sync makes that
    impossible rather than merely discouraged.
    """
    assert not inspect.iscoroutinefunction(process_batch)


def test_the_processor_touches_nothing_but_the_store_and_the_registry():
    """Whitelist rather than blacklist: an unexpected collaborator fails here by default."""
    src = inspect.getsource(inspect.getmodule(process_batch))
    receivers = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                receivers.add(node.func.value.id)
    assert receivers <= {"store", "registry", "audit", "uuid", "reading", "self", "results",
                         "text", "value", "config"}, f"unexpected collaborators: {receivers}"


def test_a_batch_of_readings_leaves_no_trace_beyond_the_store(store: FakeRawStore):
    """Behavioural companion to the scans: the store is the only thing that changed."""
    outcome = run([GOOD] * 3, store)
    assert store.count() == 3
    assert outcome.accepted_count == 3


# ----------------------------------------------------- the docs cannot promise validity ---
def test_the_ingest_docstrings_do_not_promise_validation():
    """OpenAPI descriptions come from these. A gateway author reads them as the contract."""
    for rel, src in _ingest_sources():
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            doc = (ast.get_docstring(node) or "").lower()
            for phrase in ("readings are validated", "validates the reading",
                           "confirms the reading is valid", "guarantees validity"):
                assert phrase not in doc, f"{rel}:{node.name} promises validation"
