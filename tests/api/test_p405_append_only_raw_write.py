"""P405 — raw readings are appended and never touched again, structurally.

Principle II is the one BridgeGuard principle that cannot be recovered from. A wrong risk score
gets re-assessed on the next cycle; a lost report gets regenerated. But an overwritten raw
reading is gone, and with it the traceability of every number downstream that was derived from
it. An engineer looking at a strain series six months after a closure decision has to be able
to see what the sensor actually reported, not what a later correction thought it should have
said.

So the guarantee here is not "we are careful not to update raw data." It is that **there is no
code that could**. Three layers, and the structural one is the point:

**Structural.** An AST scan over `src/api/` finds no UPDATE or DELETE against a raw table, no
call to a mutating store method, and no store object that offers one. A rule enforced by review
lasts until the reviewer is on holiday; a rule enforced by the absence of a method survives
being forgotten.

**Behavioural.** The fake's appends are observable, and a duplicate append lands as a second
row rather than replacing the first.

**Database.** Migration 0001 blocks UPDATE and DELETE with both a REVOKE and a trigger, so the
API's discipline is belt-and-braces rather than the only defence. [DB-DEP] — asserted here by
reading the migration text, since there is no live Neon instance.

The duplicate case deserves its own note, because "de-duplicate on write" reads like an
obvious improvement. It is not: a Pi retrying after a network failure sends the same readings
again, and two rows with two different ingest times is the honest record of what happened.
Collapsing them makes the API decide which arrival was real, which is a judgment (Principle III)
and one the DCA makes on its own cycle with the full series in view.

Ties to tasks.md P405, Principle II, spec §1, plan §4.
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
from api.ingest.processor import process_batch
from api.ingest.raw_store import FakeRawStore

API_ROOT = Path(__file__).resolve().parents[2] / "src" / "api"
MIGRATION = Path(__file__).resolve().parents[2] / "db" / "migrations" / "0001_raw_readings.sql"

RAW_TABLES = ("raw_readings",)

GOOD = {
    "sensor_id": "S_OURS",
    "sensor_type": "strain",
    "value": 12.5,
    "unit": "microstrain",
    "sensor_time": "2026-08-05T10:00:00Z",
}


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


def _api_sources() -> list[tuple[str, str]]:
    out = []
    for path in sorted(API_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        out.append((path.relative_to(API_ROOT).as_posix(), path.read_text(encoding="utf-8")))
    return out


def _executable_lines(sql_or_py: str) -> str:
    """Strip comment lines before scanning.

    Without this the scan matches the module's own prose. A file that *documents* the mutation
    it refuses to perform would fail a naive text scan, and — the more dangerous direction — a
    file whose prose mentions every table it guards can satisfy a presence check with the guard
    deleted.
    """
    lines = []
    for line in sql_or_py.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or stripped.startswith("#"):
            continue
        lines.append(line)
    return "\n".join(lines)


# ------------------------------------------------------ structural: no mutation exists ---
def test_no_api_module_writes_an_update_or_delete_against_a_raw_table():
    """The headline scan. A raw-table UPDATE anywhere in this layer is a Principle II breach."""
    offenders = []
    for rel, src in _api_sources():
        body = _executable_lines(src).lower()
        for table in RAW_TABLES:
            if table not in body:
                continue
            for verb in ("update ", "delete ", "truncate", "insert or replace", "upsert",
                         "on conflict"):
                if verb in body:
                    offenders.append(f"{rel}: {verb.strip()!r} near {table}")
    assert not offenders, f"mutation of raw data found in src/api: {offenders}"


def test_no_api_module_calls_a_mutating_store_method():
    """Method names, not SQL: the fake and the live repository are both reached by name."""
    banned = {
        "update", "delete", "remove", "overwrite", "replace", "truncate", "clear",
        "purge", "drop", "set_value", "upsert",
    }
    offenders = []
    for rel, src in _api_sources():
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in banned:
                    offenders.append(f"{rel}: .{node.func.attr}()")
    assert not offenders, f"mutating store calls in src/api: {offenders}"


def test_the_raw_store_offers_no_mutation_method():
    """Absence is the enforcement.

    A store with an `update` method is one autocomplete away from being called. Not having one
    means a mutation cannot be written, not merely that it should not be.
    """
    for banned in ("update", "delete", "remove", "clear", "truncate", "overwrite", "replace",
                   "pop", "purge", "set_row"):
        assert not hasattr(FakeRawStore, banned), f"FakeRawStore exposes {banned}"


def test_the_raw_store_exposes_exactly_one_way_in():
    """One append, three reads. A second write path is a second thing to audit."""
    public = {n for n in dir(FakeRawStore) if not n.startswith("_")}
    assert public == {"append", "rows", "count", "for_sensor"}


def test_the_processor_only_ever_appends():
    """Read as source: the ingest path's sole interaction with raw storage."""
    src = inspect.getsource(__import__("api.ingest.processor", fromlist=["x"]))
    calls = [
        node.func.attr
        for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name) and node.func.value.id == "store"
    ]
    assert calls == ["append"], f"the processor touches raw storage other than by append: {calls}"


def test_the_rows_view_hands_back_a_copy(store: FakeRawStore):
    """Otherwise a caller holding `rows` can mutate the log through the back door."""
    run([GOOD], store)
    snapshot = store.rows
    snapshot[0]["value"] = 999.0
    snapshot.clear()
    assert store.count() == 1
    assert store.rows[0]["value"] == 12.5


def test_a_stored_row_cannot_be_edited_through_a_later_read(store: FakeRawStore):
    run([GOOD], store)
    store.for_sensor("S_OURS")[0]["sensor_id"] = "TAMPERED"
    assert store.rows[0]["sensor_id"] == "S_OURS"


def test_the_caller_cannot_mutate_a_row_it_already_handed_over(store: FakeRawStore):
    """The store copies on the way in as well as out.

    A caller that keeps a reference to the dict it appended could otherwise rewrite a stored
    reading after the fact — the same overwrite, arriving from the other direction.
    """
    payload = {"sensor_id": "S_OURS", "value": 1.0}
    store.append(payload)
    payload["value"] = 999.0
    assert store.rows[0]["value"] == 1.0


# ------------------------------------------------------------ behavioural: appends land ---
def test_an_accepted_reading_is_observable_in_the_store(store: FakeRawStore):
    run([GOOD], store)
    assert store.count() == 1
    assert store.rows[0]["sensor_id"] == "S_OURS"


def test_every_accepted_reading_appends_its_own_row(store: FakeRawStore):
    run([GOOD] * 7, store)
    assert store.count() == 7


def test_appends_preserve_arrival_order(store: FakeRawStore):
    """The append log is a history; reordering it would falsify what arrived when."""
    run([{**GOOD, "value": float(i)} for i in range(5)], store)
    assert [row["value"] for row in store.rows] == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_each_stored_row_records_when_it_arrived(store: FakeRawStore):
    """`ingest_time` is ours; `sensor_time` is the Pi's. Both are needed to reconstruct a
    retry, and only one of them can be trusted to be honest about clock skew."""
    run([GOOD], store)
    row = store.rows[0]
    assert row["ingest_time"] is not None
    assert row["sensor_time"] == GOOD["sensor_time"]


def test_a_stored_row_carries_its_tenancy(store: FakeRawStore):
    run([GOOD], store)
    assert store.rows[0]["municipality_id"] == "MUNI_A"
    assert store.rows[0]["bridge_id"] == "BRIDGE_1"


# ------------------------------------------- a duplicate appends, it does not overwrite ---
def test_re_appending_an_identical_reading_does_not_overwrite(store: FakeRawStore):
    """The acceptance criterion. Two arrivals of the same measurement are two facts."""
    run([GOOD], store)
    run([GOOD], store)
    assert store.count() == 2


def test_a_redelivered_batch_leaves_the_first_rows_intact(store: FakeRawStore):
    run([GOOD, {**GOOD, "value": 20.0}], store)
    first = store.rows
    run([GOOD, {**GOOD, "value": 20.0}], store)
    assert store.rows[:2] == first


def test_a_duplicate_is_not_collapsed_into_one_row(store: FakeRawStore):
    """De-duplicating here would make the API decide which arrival was real — a judgment,
    and the DCA's to make with the full series in view (Principle III)."""
    run([GOOD] * 3, store)
    assert len(store.for_sensor("S_OURS")) == 3


def test_the_store_does_no_deduplication_at_all():
    """Structural: a de-dup would need to compare against what is already stored."""
    import api.ingest.raw_store as mod

    src = _executable_lines(inspect.getsource(mod)).lower()
    for banned in ("dedup", "seen", "distinct", "if row in", "already", "exists"):
        assert banned not in src, f"the raw store appears to deduplicate: {banned!r}"


# ------------------------------------------------- the database enforces it too [DB-DEP] ---
@pytest.mark.parametrize("grantee", ["public", "bridgeguard_service"])
def test_the_migration_revokes_mutation_from_every_grantee(grantee: str):
    """Asserted as the statement, not as the word.

    A looser check (`"update" in sql`) is satisfied by the trigger definition further down, so
    it would still pass with both REVOKEs deleted. Revoking from PUBLIC alone is not enough
    either — the service role holds its own grants.
    """
    sql = _executable_lines(MIGRATION.read_text(encoding="utf-8")).lower()
    assert f"revoke update, delete, truncate on raw_readings from {grantee}" in sql


def test_the_service_role_is_granted_only_insert_and_select():
    """The positive half. A role with UPDATE has it whatever the REVOKE above said."""
    sql = _executable_lines(MIGRATION.read_text(encoding="utf-8")).lower()
    grants = [line for line in sql.splitlines() if "grant" in line and "raw_readings" in line]
    assert grants, "no GRANT on raw_readings — the service role could not even insert"
    for line in grants:
        assert "insert" in line and "select" in line
        for banned in ("update", "delete", "truncate", "all privileges"):
            assert banned not in line, f"GRANT hands out {banned}: {line.strip()!r}"


def test_the_migration_backs_the_revoke_with_a_trigger():
    """A REVOKE is bypassed by the table owner or a superuser path; a trigger is not.

    Asserted on the trigger's event clause, so deleting `OR DELETE` — leaving a trigger that
    blocks only UPDATE — fails here rather than passing on the word "trigger".
    """
    sql = _executable_lines(MIGRATION.read_text(encoding="utf-8")).lower()
    assert "create trigger" in sql
    assert "before update or delete on raw_readings" in sql
    assert "raise exception" in sql


def test_the_blocking_trigger_fires_per_row_and_has_no_escape_condition():
    """A `WHEN` clause on this trigger would be a documented hole in append-only."""
    sql = _executable_lines(MIGRATION.read_text(encoding="utf-8")).lower()
    trigger = sql.split("create trigger", 1)[1].split(";", 1)[0]
    assert "for each row" in trigger
    assert " when " not in trigger, f"the append-only trigger is conditional: {trigger.strip()!r}"


def test_the_migration_declares_no_time_series_extension():
    """Constitution v2.1.0: standard Postgres indexes only, no TimescaleDB."""
    sql = _executable_lines(MIGRATION.read_text(encoding="utf-8")).lower()
    for banned in ("create extension", "create_hypertable", "add_dimension"):
        assert banned not in sql
