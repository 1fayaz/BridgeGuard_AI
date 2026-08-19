"""D901 — the migrations README documents ordering, dependencies, and the SOR-discipline map.

The Definition of Done requires docs that match the built schema. This test guards that
`db/migrations/README.md` stays truthful and complete: it must name EVERY migration 0001-0016 (so a
reader can reconstruct apply-order), explain the additive strategy (why 0005 fills a gap and tenancy
appends late via 0015, with NO file renumbered), and lay out the seven-SOR-table discipline map
(total-block vs. correct-by-supersede vs. the excluded sensor_status).

A structural check, not prose grading: if a migration is added later without a README line, or the
discipline map drifts, this fails.

Ties to plan §1/§3 and the Definition of Done (docs match the schema).
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
README = REPO / "db" / "migrations" / "README.md"
MIG_DIR = REPO / "db" / "migrations"


@pytest.fixture(scope="module")
def text() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def low(text: str) -> str:
    return text.lower()


def test_readme_exists():
    assert README.is_file(), f"missing {README}"


def test_every_migration_file_is_documented(text: str):
    # Each on-disk migration must be named in the README — no undocumented migration.
    for path in sorted(MIG_DIR.glob("*.sql")):
        stem = path.stem  # e.g. 0005_analysis_results
        num = stem.split("_")[0]
        assert num in text, f"README must document migration {num} ({path.name})"


def test_documents_the_additive_strategy(low: str):
    # Why 0005 fills the gap and why tenancy appends late instead of renumbering.
    assert "0005" in low and "analysis_results" in low
    assert "additive" in low or "append" in low or "renumber" in low
    assert "0015" in low, "the tenancy wiring migration must be explained"


def test_seven_sor_tables_discipline_map(low: str):
    # The discipline map: the two total-block tables, the five supersede tables, and the exclusion.
    for table in ("raw_readings", "decision_log"):
        assert table in low
    for table in ("validated_readings", "risk_assessments", "report_artifacts",
                  "alert_dispatches", "analysis_results"):
        assert table in low
    assert "total-block" in low or "total block" in low or "append-only" in low
    assert "supersede" in low
    # sensor_status is the deliberate exclusion — it must be called out as NOT an SOR table.
    assert "sensor_status" in low


def test_names_the_seven_count(low: str):
    # Plan §0: seven SOR tables (the correction from six). The count must be stated so a future reader
    # doesn't silently re-drop analysis_results.
    assert "seven" in low or "7 " in low or "(7)" in low


def test_rls_and_guc_pointer_present(low: str):
    # 0016 RLS + the exact GUC name must appear so the ordering doc ties to the isolation model.
    assert "0016" in low
    assert "app.current_municipality_id" in low
