"""D202 — analysis_results migration (0005): table + enums + shape CHECKs, and FakeAnalysisStore.

[DB-DEP] No Neon/Postgres locally; the migration cannot be EXECUTED here. What is verifiable now:
the 0005 file declares the three closed enums (analysis_calc mirroring the Calculation enum,
analysis_outcome RAN|SKIPPED|ERROR, analysis_skip_reason), every column from the D201 manifest, the
source_validated_ids soft-provenance array, NO inline tenant FK (deferred to 0015), and the
shape-coherence CHECKs (RAN carries a value; SKIPPED carries a reason_code and no value; ERROR
carries detail; degenerate is SKIPPED/DEGENERATE_RESULT, never a RAN NaN). The in-memory
FakeAnalysisStore enforces those same shapes.

Scope note: the correct-by-supersede triggers + the idempotency partial-unique index are D203; this
task is the table + enums + coherent shapes. Ties to spec-002 FR-5 (SA table completes the contract)
and AC-5.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agents.structural_analysis.config.calculations import Calculation

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "db" / "migrations" / "0005_analysis_results.sql"
)


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def norm() -> str:
    return re.sub(r"\s+", " ", MIGRATION.read_text(encoding="utf-8").lower())


# --- migration structure ------------------------------------------------------------------------
def test_migration_file_exists():
    assert MIGRATION.is_file(), f"missing migration: {MIGRATION}"


def test_creates_analysis_results_table(norm: str):
    assert "create table" in norm
    assert "analysis_results" in norm


def test_outcome_enum_closed_set(sql: str):
    lower = sql.lower()
    assert "analysis_outcome" in lower
    for outcome in ("RAN", "SKIPPED", "ERROR"):
        assert f"'{outcome}'" in sql, f"analysis_outcome missing {outcome}"


def test_skip_reason_enum_closed_taxonomy(sql: str):
    lower = sql.lower()
    assert "analysis_skip_reason" in lower
    for reason in ("NO_CHANGE", "NO_CALC", "LIMIT_NOT_CONFIGURED", "NO_REFERENCE", "DEGENERATE_RESULT"):
        assert f"'{reason}'" in sql, f"analysis_skip_reason missing {reason}"


def test_calculation_enum_mirrors_python_enum(sql: str):
    # The analysis_calc SQL enum mirrors the Calculation enum (active + declared-deferred).
    assert "analysis_calc" in sql.lower()
    for calc in Calculation:
        assert f"'{calc.value}'" in sql, f"analysis_calc missing {calc.value}"


def test_result_value_columns_present(sql: str):
    for column in ("value", "limit_value", "ratio", "passed", "fft_peaks"):
        assert column in sql, f"analysis_results missing result column: {column}"


def test_provenance_columns_present(sql: str):
    for column in ("source_validated_ids", "input_version", "config_version", "constants_used"):
        assert column in sql, f"analysis_results missing provenance column: {column}"


def test_flag_columns_present(sql: str):
    for flag in ("interpolated_input", "clock_drift", "rate_mismatch", "abnormal_quiet"):
        assert flag in sql, f"analysis_results missing flag column: {flag}"


def test_source_validated_ids_is_soft_array(norm: str):
    # SOFT provenance: a BIGINT[] array, NOT a hard FK (plan §5; manifest §2e).
    assert "source_validated_ids bigint[]" in norm
    # it must not be a REFERENCES to validated_readings (soft, decoupled).
    assert "source_validated_ids bigint[] not null" in norm


def test_no_inline_tenant_fk(norm: str):
    # Tenancy (sensor_id -> sensors, municipality_id) is deferred to 0015 — sensors table is 0014.
    assert "references sensors" not in norm, "0005 must NOT add a tenant FK inline (deferred to 0015)"
    assert "references municipalities" not in norm


def test_superseded_by_self_reference(norm: str):
    # Correct-by-append self-FK (hard, internal consistency).
    assert "superseded_by bigint references analysis_results" in norm


def test_shape_checks_present(sql: str):
    lower = sql.lower()
    assert "check" in lower
    # RAN/SKIPPED/ERROR coherence encoded as CHECK constraints (named for greppability).
    assert "outcome" in lower


def test_neon_no_timescaledb_header(norm: str):
    assert "neon" in norm
    assert "no timescaledb" in norm
    # The header may say "there is no hypertable"; the hazard is an actual hypertable conversion.
    assert "create_hypertable" not in norm
    assert "[db-dep]" in norm


def test_required_identity_columns(sql: str):
    for column in ("id", "sensor_id", "calculation", "outcome", "computed_at"):
        assert column in sql, f"analysis_results missing column: {column}"


# --- FakeAnalysisStore (in-fake shape enforcement) ----------------------------------------------
def test_fake_store_accepts_a_ran_result_with_value():
    from db.analysis_store import FakeAnalysisStore, AnalysisResult

    store = FakeAnalysisStore()
    rid = store.insert(AnalysisResult(
        sensor_id="S1", calculation="THRESHOLD", block_id="b1", input_version="v1",
        outcome="RAN", value=0.42, limit_value=1.0, ratio=0.42, passed=True,
        config_version="cfg-1", source_validated_ids=(10,),
    ))
    assert isinstance(rid, int)
    stored = store.get(rid).result
    assert stored.value == 0.42 and stored.passed is True and stored.source_validated_ids == (10,)


def test_fake_store_ran_requires_a_result():
    from db.analysis_store import FakeAnalysisStore, AnalysisResult, InvalidResultShape

    store = FakeAnalysisStore()
    # a RAN scalar with no value and no fft_peaks is incoherent.
    with pytest.raises(InvalidResultShape):
        store.insert(AnalysisResult(
            sensor_id="S1", calculation="THRESHOLD", block_id="b1", input_version="v1",
            outcome="RAN", config_version="cfg-1",
        ))


def test_fake_store_skipped_requires_reason_and_no_value():
    from db.analysis_store import FakeAnalysisStore, AnalysisResult, InvalidResultShape

    store = FakeAnalysisStore()
    # a SKIPPED with a value is incoherent.
    with pytest.raises(InvalidResultShape):
        store.insert(AnalysisResult(
            sensor_id="S1", calculation="FFT", block_id="b1", input_version="v1",
            outcome="SKIPPED", reason_code="NO_CHANGE", value=0.5, config_version="cfg-1",
        ))
    # a SKIPPED with no reason_code is incoherent.
    with pytest.raises(InvalidResultShape):
        store.insert(AnalysisResult(
            sensor_id="S1", calculation="FFT", block_id="b1", input_version="v1",
            outcome="SKIPPED", config_version="cfg-1",
        ))


def test_fake_store_skipped_no_change_ok():
    from db.analysis_store import FakeAnalysisStore, AnalysisResult

    store = FakeAnalysisStore()
    rid = store.insert(AnalysisResult(
        sensor_id="S1", calculation="FFT", block_id="b1", input_version="v1",
        outcome="SKIPPED", reason_code="NO_CHANGE", config_version="cfg-1",
    ))
    assert store.get(rid).result.reason_code == "NO_CHANGE"


def test_fake_store_degenerate_is_skipped_not_ran():
    # FR-13: a non-finite result is SKIPPED/DEGENERATE_RESULT, never a RAN NaN reaching Risk.
    from db.analysis_store import FakeAnalysisStore, AnalysisResult, InvalidResultShape

    store = FakeAnalysisStore()
    # a RAN carrying a non-finite value must be rejected (it should have been SKIPPED/DEGENERATE).
    with pytest.raises(InvalidResultShape):
        store.insert(AnalysisResult(
            sensor_id="S1", calculation="RMS", block_id="b1", input_version="v1",
            outcome="RAN", value=float("nan"), config_version="cfg-1",
        ))
    # the correct representation is accepted.
    rid = store.insert(AnalysisResult(
        sensor_id="S1", calculation="RMS", block_id="b1", input_version="v1",
        outcome="SKIPPED", reason_code="DEGENERATE_RESULT", config_version="cfg-1",
    ))
    assert store.get(rid).result.reason_code == "DEGENERATE_RESULT"


def test_fake_store_error_carries_detail_no_value():
    from db.analysis_store import FakeAnalysisStore, AnalysisResult, InvalidResultShape

    store = FakeAnalysisStore()
    rid = store.insert(AnalysisResult(
        sensor_id="S1", calculation="RMS", block_id="b1", input_version="v1",
        outcome="ERROR", error_detail="unexpected: matrix singular", config_version="cfg-1",
    ))
    assert "singular" in store.get(rid).result.error_detail
    # an ERROR carrying a value is incoherent.
    with pytest.raises(InvalidResultShape):
        store.insert(AnalysisResult(
            sensor_id="S1", calculation="RMS", block_id="b2", input_version="v1",
            outcome="ERROR", error_detail="x", value=1.0, config_version="cfg-1",
        ))


def test_fake_store_rejects_unknown_outcome_and_calc():
    from db.analysis_store import FakeAnalysisStore, AnalysisResult, InvalidResultShape

    store = FakeAnalysisStore()
    with pytest.raises(InvalidResultShape):
        store.insert(AnalysisResult(
            sensor_id="S1", calculation="THRESHOLD", block_id="b1", input_version="v1",
            outcome="MAYBE", value=1.0, config_version="cfg-1",
        ))
    with pytest.raises(InvalidResultShape):
        store.insert(AnalysisResult(
            sensor_id="S1", calculation="NONSENSE", block_id="b1", input_version="v1",
            outcome="RAN", value=1.0, config_version="cfg-1",
        ))
