"""T1201 / T1202 — module docs match the implemented contract.

T1201 acceptance: README present; documents inputs, outputs (both status axes + flags),
the pipeline order, the four checks, and the cross-cutting rules; matches the contract.
T1202 acceptance: the add-a-type guide describes config-only steps (profile + registry +
constants), no check-code change — validating the "config, not code" decision.

Rather than grade prose, these tests assert the docs name the REAL symbols/values the
code uses, so the docs can't silently drift from the implementation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from agents.data_collection.statuses import ReadingStatus, SensorHealth

MODULE = Path(__file__).resolve().parents[2] / "src" / "agents" / "data_collection"
README = MODULE / "README.md"
GUIDE = MODULE / "ADD_SENSOR_TYPE.md"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def test_readme_exists(readme: str):
    assert README.is_file() and readme.strip()


def test_readme_documents_both_status_axes(readme: str):
    # Every reading-status the enum defines must appear in the README.
    for status in ReadingStatus:
        assert status.value in readme, f"README missing reading status {status.value}"
    # And both device-health values.
    for health in SensorHealth:
        assert health.value in readme


def test_readme_documents_the_flags(readme: str):
    assert "clock_drift" in readme
    assert "is_interpolated" in readme


def test_readme_documents_inputs(readme: str):
    for field in ("sensor_id", "sensor_type", "sensor_time", "value", "ingest_time"):
        assert field in readme


def test_readme_documents_pipeline_and_four_checks(readme: str):
    lower = readme.lower()
    for stage in ("safe-parse", "dedup", "liveness", "range", "spike", "gap",
                  "pending", "late arrival", "clock drift"):
        assert stage in lower, f"README missing pipeline stage: {stage}"


def test_readme_states_out_of_scope(readme: str):
    lower = readme.lower()
    assert "out of scope" in lower
    # The three explicitly-excluded responsibilities.
    assert "fft" in lower or "frequency" in lower
    assert "alert" in lower
    assert "score" in lower or "danger" in lower or "risk" in lower


def test_readme_names_the_migrations(readme: str):
    for table in ("raw_readings", "validated_readings", "sensor_status", "decision_log"):
        assert table in readme


def test_guide_exists(guide: str):
    assert GUIDE.is_file() and guide.strip()


def test_guide_is_config_only(guide: str):
    lower = guide.lower()
    # Names the three config touch-points...
    assert "sensorprofile" in lower
    assert "expectedsensor" in lower or "registry" in lower
    # ...and explicitly asserts no check-code change.
    assert "no code change" in lower or "config only" in lower or "config, not code" in lower


def test_guide_warns_against_guessing_bounds(guide: str):
    lower = guide.lower()
    assert "todo" in lower
    assert "do not guess" in lower or "not guess" in lower


def test_guide_lists_unchanged_check_files(guide: str):
    # The guide should reassure that the check modules are untouched.
    assert "liveness" in guide and "range_check" in guide and "spike" in guide
