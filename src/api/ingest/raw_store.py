"""In-memory `raw_readings` (P405) — append-only, mirroring migration 0001.

[DB-DEP] There is no Neon instance locally, so this fake stands in for `raw_readings` in the
logic tests. 0001 is a **total-block** table: no UPDATE, no DELETE, ever, enforced by both a
`REVOKE` and a trigger. A row is immutable the instant it lands (Constitution II).

This fake mirrors that by *not having the methods*. There is no `update`, no `delete`, no
`clear`, and `rows` hands back a copy — so a test cannot accidentally demonstrate a mutation
path that production does not have. Absence is the mirror of a blocked trigger: code written
against this fake cannot compile a mutation it would be denied at the database.

A duplicate append is a new row, not an overwrite. A Pi retrying after a network failure
sends the same readings again (P406), and the honest record of that is two rows with two
ingest times — the arrival history is itself data. De-duplicating here would be the API
deciding which reading was "real", which is the DCA's call on its own cycle, not the
boundary's.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class FakeRawStore:
    """Append-only in-memory raw readings. Not thread-safe; tests are serial."""

    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    def append(self, row: dict[str, Any]) -> None:
        """Add one raw reading. There is deliberately no counterpart that removes one."""
        stored = dict(row)
        stored.setdefault("ingest_time", datetime.now(UTC))
        self._rows.append(stored)

    @property
    def rows(self) -> list[dict[str, Any]]:
        """A copy: a caller holding this list must not be able to mutate the store."""
        return [dict(r) for r in self._rows]

    def count(self) -> int:
        return len(self._rows)

    def for_sensor(self, sensor_id: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rows if r.get("sensor_id") == sensor_id]
