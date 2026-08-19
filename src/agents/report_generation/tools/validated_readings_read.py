"""Read port — get_validated_readings(source_validated_ids, *, max_rows) (G303) — read-only.

Reads the DCA validated_readings (0002) named by the SA rows' `source_validated_ids`, for the
report's time-series tables/charts + raw-data appendix. Bounded to `max_rows` — the appendix depth
bound from ReportConfig — so a giant appendix cannot exhaust memory. The agent renders these
numbers verbatim; it never recomputes them (FR-1, Principle III). Read-only; a missing set returns
a structured section-gap signal (FR-6), never a raise. Truncation to the bound is FLAGGED (with an
honest full count), never silent — so the report can print "showing N of M".

[DB-DEP] The live source is the DCA's validated_readings table (0002) + Neon, neither of which
exists locally. The read is written against a source PROTOCOL so it runs against an in-memory fake
now.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Protocol


class ValidatedReadingsSource(Protocol):
    """The read port this tool needs — implemented by the fake now, Neon later."""

    def validated_readings_by_ids(self, ids: tuple[int, ...]) -> list[dict[str, Any]]:
        ...


@dataclass(frozen=True, slots=True)
class ValidatedReadingsReadResult:
    """Structured result: the (possibly capped) readings, the honest full count, and any gap.

    `available` is True when every requested id was found and at least one id was requested —
    truncation to the appendix bound does NOT make a section unavailable (the data exists; it is
    merely capped for presentation). `truncated`/`total_available` let the report state "N of M".
    """

    available: bool
    readings: tuple[dict[str, Any], ...]
    missing_ids: tuple[int, ...]
    truncated: bool
    total_available: int


def get_validated_readings(
    source_validated_ids: tuple[int, ...],
    source: ValidatedReadingsSource,
    *,
    max_rows: int,
) -> ValidatedReadingsReadResult:
    """Read the DCA readings the SA rows referenced, capped to max_rows (G303). Never raises."""
    requested = tuple(source_validated_ids)
    rows = source.validated_readings_by_ids(requested)
    # Deep-copy so a caller mutating a reading cannot corrupt the store's row.
    found = [copy.deepcopy(r) for r in rows]

    found_ids = {r["id"] for r in found}
    missing = tuple(i for i in requested if i not in found_ids)

    total = len(found)
    capped = tuple(found[: max(0, max_rows)])
    truncated = len(capped) < total

    # Available only when something was requested AND nothing referenced is missing. Truncation is
    # a presentation cap, not a gap — it does not clear availability.
    available = bool(requested) and not missing
    return ValidatedReadingsReadResult(
        available=available,
        readings=capped,
        missing_ids=missing,
        truncated=truncated,
        total_available=total,
    )
