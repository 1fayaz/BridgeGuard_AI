"""D201 — the analysis_results column manifest names every SA FR-13 output field + the closed
vocabularies, so D202 builds to a signed-off shape (not a guess).

D201 has no SQL; its deliverable is `specs/database/analysis_results_manifest.md`. Rather than grade
prose, these tests assert the manifest names the REAL fields the SA output contract (spec §383-391 /
FR-6/FR-9/FR-12/FR-13/FR-16/FR-17) requires and the REAL `Calculation` enum members the column
mirrors — so the manifest cannot silently omit a field the migration must carry. Same discipline as
the alert-agent A1201 docs test (assert docs name real symbols/values).

Ties to spec-002 FR-5 (the SA table completes the contract).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.structural_analysis.config.calculations import Calculation

MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "specs" / "database" / "analysis_results_manifest.md"
)


@pytest.fixture(scope="module")
def manifest() -> str:
    return MANIFEST.read_text(encoding="utf-8")


def test_manifest_exists():
    assert MANIFEST.is_file() and MANIFEST.read_text(encoding="utf-8").strip()


def test_names_the_outcome_vocabulary(manifest: str):
    # FR-13: outcome is a closed set RAN | SKIPPED | ERROR.
    for outcome in ("RAN", "SKIPPED", "ERROR"):
        assert outcome in manifest, f"manifest missing outcome {outcome}"


def test_names_the_closed_skip_reason_taxonomy(manifest: str):
    # FR-6/FR-9/FR-12/FR-13: the five closed skip reasons.
    for reason in ("NO_CHANGE", "NO_CALC", "LIMIT_NOT_CONFIGURED", "NO_REFERENCE", "DEGENERATE_RESULT"):
        assert reason in manifest, f"manifest missing skip reason {reason}"


def test_names_every_calculation_enum_member(manifest: str):
    # The calculation column mirrors the Calculation enum (active + declared-deferred).
    for calc in Calculation:
        assert calc.value in manifest, f"manifest missing Calculation.{calc.value}"


def test_names_the_result_value_fields(manifest: str):
    # FR-5/FR-6/FR-9: scalar value + limit + ratio + pass/fail, and FFT peaks.
    for field in ("value", "limit_value", "ratio", "passed", "fft_peaks"):
        assert field in manifest, f"manifest missing result field {field}"


def test_names_the_provenance_and_reproducibility_fields(manifest: str):
    # FR-13/FR-16/FR-17: the traceable chain + reproducibility.
    for field in ("source_validated_ids", "input_version", "config_version", "constants_used"):
        assert field in manifest, f"manifest missing provenance field {field}"


def test_names_the_four_result_flags(manifest: str):
    # FR-2/FR-6/FR-13/FR-14: the co-existing flags.
    for flag in ("interpolated_input", "clock_drift", "rate_mismatch", "abnormal_quiet"):
        assert flag in manifest, f"manifest missing flag {flag}"


def test_names_the_correction_chain_column(manifest: str):
    # FR-8 / spec-002 FR-7: correct-by-append.
    assert "superseded_by" in manifest


def test_declares_the_grain(manifest: str):
    # One row per (sensor, calculation, block, input_version).
    lower = manifest.lower()
    assert "sensor" in lower and "calculation" in lower and "block" in lower and "input_version" in lower


def test_soft_provenance_and_hard_selfref_stated(manifest: str):
    lower = manifest.lower()
    assert "soft" in lower, "manifest must state source_validated_ids is a SOFT reference (no hard FK)"
    # tenancy FK is deferred to 0015, not inline in 0005.
    assert "0015" in manifest, "manifest must defer the tenant FK to 0015"


def test_idempotency_key_over_current_rows(manifest: str):
    lower = manifest.lower()
    assert "input_version" in lower
    assert "superseded_by is null" in lower, "idempotency is a partial-unique over current rows"


def test_no_timescaledb(manifest: str):
    lower = manifest.lower()
    assert "no timescaledb" in lower
    assert "hypertable" not in lower


def test_is_this_repos_migration_0005_not_s203(manifest: str):
    # SA docs call it S203; in this repo it is migration 0005 (additive, fills the gap).
    assert "0005" in manifest
