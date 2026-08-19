"""In-memory analysis-results store (D202+) — mirrors the 0005 schema guarantees for tests.

FakeAnalysisStore stands in for the Neon-backed `analysis_results` table (migration 0005) until a
live instance exists ([DB-DEP]), the same way the DCA/Risk/Report/Alert fakes mirror their tables.
It enforces, in Python, exactly the shape guarantees the 0005 CHECK constraints enforce in the DB:

  * outcome is a closed set (RAN | SKIPPED | ERROR); calculation is the closed Calculation enum;
  * a RAN carries a result (a finite scalar `value` OR an `fft_peaks` set) — a non-finite value is
    NEVER a RAN (it is SKIPPED/DEGENERATE_RESULT), so a NaN can never reach Risk as a real number
    (SA FR-13);
  * a SKIPPED carries exactly one reason_code from the closed taxonomy and no value/peaks/error;
  * an ERROR carries error_detail and no value/peaks/reason.

The correct-by-supersede triggers + the idempotency partial-unique index are D203; this module adds
insert + shape enforcement (D203 will add supersede/delete + duplicate-current rejection).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

from agents.structural_analysis.config.calculations import Calculation

_OUTCOMES = frozenset({"RAN", "SKIPPED", "ERROR"})
_SKIP_REASONS = frozenset(
    {"NO_CHANGE", "NO_CALC", "LIMIT_NOT_CONFIGURED", "NO_REFERENCE", "DEGENERATE_RESULT"}
)
_CALCS = frozenset(c.value for c in Calculation)


class InvalidResultShape(Exception):
    """Raised when a result's fields are incoherent for its outcome — the 0005 CHECK constraints."""


class DuplicateAnalysisResultError(Exception):
    """Raised on a second CURRENT result for the same (sensor, calc, block, input_version) — the
    0005 partial-unique idempotency index (FR-10). A same-input-version re-trigger is a no-op."""


class AnalysisResultImmutableError(Exception):
    """Raised on any attempt to overwrite a stored result in place (correct-by-append, FR-7)."""


class AnalysisResultDeleteBlocked(Exception):
    """Raised on any delete attempt — result history is permanent (Constitution VI)."""


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """One structured SA result (mirrors an analysis_results row's writable fields)."""

    sensor_id: str
    calculation: str
    block_id: str
    input_version: str
    outcome: str
    config_version: str
    reason_code: str | None = None
    error_detail: str | None = None
    value: float | None = None
    limit_value: float | None = None
    ratio: float | None = None
    passed: bool | None = None
    fft_peaks: dict | None = None
    source_validated_ids: tuple[int, ...] = ()
    constants_used: dict | None = None
    interpolated_input: bool = False
    clock_drift: bool = False
    rate_mismatch: bool = False
    abnormal_quiet: bool = False


@dataclass(frozen=True, slots=True)
class StoredAnalysisResult:
    """A persisted result: the value plus its store-assigned id and supersession link."""

    id: int
    result: AnalysisResult
    superseded_by: int | None = None


def _validate_shape(r: AnalysisResult) -> None:
    """Enforce the 0005 closed vocabularies + shape-coherence CHECKs. Raises InvalidResultShape."""
    if r.outcome not in _OUTCOMES:
        raise InvalidResultShape(f"unknown outcome {r.outcome!r} (RAN|SKIPPED|ERROR)")
    if r.calculation not in _CALCS:
        raise InvalidResultShape(f"unknown calculation {r.calculation!r} (Calculation enum)")

    if r.outcome == "RAN":
        # must carry a result: a scalar value OR an fft peak set.
        if r.value is None and r.fft_peaks is None:
            raise InvalidResultShape("a RAN result must carry a value or fft_peaks")
        # a scalar value, when present, must be finite — never a RAN NaN/Inf (FR-13).
        if r.value is not None and not math.isfinite(r.value):
            raise InvalidResultShape(
                "a non-finite value is never RAN — emit SKIPPED/DEGENERATE_RESULT (FR-13)"
            )
        if r.reason_code is not None or r.error_detail is not None:
            raise InvalidResultShape("a RAN carries no reason_code / error_detail")

    elif r.outcome == "SKIPPED":
        if r.reason_code is None:
            raise InvalidResultShape("a SKIPPED result must carry a reason_code")
        if r.reason_code not in _SKIP_REASONS:
            raise InvalidResultShape(f"unknown reason_code {r.reason_code!r}")
        if r.value is not None or r.fft_peaks is not None or r.error_detail is not None:
            raise InvalidResultShape("a SKIPPED result carries no value/fft_peaks/error_detail")

    elif r.outcome == "ERROR":
        if not r.error_detail:
            raise InvalidResultShape("an ERROR result must carry error_detail")
        if r.value is not None or r.fft_peaks is not None or r.reason_code is not None:
            raise InvalidResultShape("an ERROR result carries no value/fft_peaks/reason_code")


class FakeAnalysisStore:
    """In-memory analysis_results store. Not thread-safe; tests are serial."""

    def __init__(self) -> None:
        self._rows: list[StoredAnalysisResult] = []
        self._next_id = 1

    def insert(self, result: AnalysisResult) -> int:
        """Insert a new current result after validating its shape; returns its store-assigned id.

        Rejects a duplicate CURRENT result for the same (sensor, calc, block, input_version) — the
        0005 partial-unique idempotency index (FR-10). A same-input-version re-trigger is a no-op.
        """
        _validate_shape(result)
        if self._current_row(result) is not None:
            raise DuplicateAnalysisResultError(
                f"a current result already exists for "
                f"({result.sensor_id!r}, {result.calculation!r}, {result.block_id!r}, "
                f"{result.input_version!r})"
            )
        rid = self._next_id
        self._rows.append(StoredAnalysisResult(id=rid, result=result))
        self._next_id += 1
        return rid

    def insert_superseding(self, old_id: int, result: AnalysisResult) -> int:
        """Append a new result and link the old one to it (a late-arrival recompute, FR-8). The old
        result is retained unchanged; only its superseded_by is stamped."""
        _validate_shape(result)
        new_id = self._next_id
        self._rows.append(StoredAnalysisResult(id=new_id, result=result))
        self._next_id += 1
        for i, row in enumerate(self._rows):
            if row.id == old_id:
                self._rows[i] = replace(row, superseded_by=new_id)
                break
        return new_id

    def overwrite(self, row_id: int, result: AnalysisResult) -> None:
        """Always blocked: a stored result is correct-by-append, never edited in place (FR-7)."""
        raise AnalysisResultImmutableError(
            "analysis_results is correct-by-append: mutating a stored result is blocked "
            "(insert_superseding instead)"
        )

    def delete(self, row_id: int) -> None:
        """Always blocked: result history is permanent (Constitution VI)."""
        raise AnalysisResultDeleteBlocked("analysis_results history is permanent: DELETE blocked")

    def get(self, row_id: int) -> StoredAnalysisResult:
        """Fetch a stored row by id; raises KeyError if absent."""
        for row in self._rows:
            if row.id == row_id:
                return row
        raise KeyError(row_id)

    def current(
        self, sensor_id: str, calculation: str, block_id: str, input_version: str
    ) -> AnalysisResult | None:
        """The current (non-superseded) result for an idempotency key, or None."""
        for row in self._rows:
            r = row.result
            if (r.sensor_id == sensor_id and r.calculation == calculation
                    and r.block_id == block_id and r.input_version == input_version
                    and row.superseded_by is None):
                return r
        return None

    def _current_row(self, result: AnalysisResult) -> StoredAnalysisResult | None:
        for row in self._rows:
            r = row.result
            if (r.sensor_id == result.sensor_id and r.calculation == result.calculation
                    and r.block_id == result.block_id and r.input_version == result.input_version
                    and row.superseded_by is None):
                return row
        return None

    @property
    def rows(self) -> list[StoredAnalysisResult]:
        return list(self._rows)
