"""D702 — shallow downstream seed: end-to-end provenance + one current risk row per bridge.

[DB-DEP] No Neon locally. D701 seeded the tenancy chain (municipalities/bridges/sensors). This adds a
MINIMAL slice of the data tables so the provenance-walk (D801/AC-5) and overview (D504/AC-11) tests
have real end-to-end rows — the agents' own harnesses generate richer data, this is just enough to
walk the chain:

    raw_readings --(source_raw_ids)--> validated_readings --(source_validated_ids)-->
    analysis_results --(source_analysis_ids)--> risk_assessments

and one CURRENT risk_assessments row per seeded bridge for the overview.

What this seed must satisfy:
  * every provenance array element points at a row the seed actually defines (no dangling id);
  * every data row's denormalized (bridge_id, municipality_id) is consistent with its sensor's chain
    (the 0015 consistency guard would reject drift) — so a seed that mis-attributes a row fails live;
  * each seeded bridge has exactly one current (superseded_by IS NULL) risk_assessments row.

Structural + mirrored-through-the-fakes verification only (no execution). Ties to spec-002
FR-8/FR-12, AC-5/AC-11; enables D801 and the live D504.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parents[2] / "db" / "seed" / "seed_dev.sql"


@pytest.fixture(scope="module")
def raw() -> str:
    return SEED.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def norm(raw: str) -> str:
    return re.sub(r"\s+", " ", raw.lower())


def _rows(text: str, table: str) -> list[list[str]]:
    """Pull the (…)-tuples out of `INSERT INTO <table> ... VALUES ...;`, ignoring an ON CONFLICT tail
    and line comments. Fields are stripped of quotes; array/json literals are kept as raw text."""
    m = re.search(
        rf"insert\s+into\s+{table}\b(.*?)values\s*(.*?)(?:\bon\s+conflict\b|;)",
        text, re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return []
    body = re.sub(r"--[^\n]*", "", m.group(2))
    # split top-level (...) tuples, tolerating nested {} / [] / '' inside a field.
    tuples, depth, cur = [], 0, ""
    for ch in body:
        if ch == "(" and depth == 0:
            depth = 1
            cur = ""
        elif ch == ")" and depth == 1:
            depth = 0
            tuples.append(cur)
        elif depth == 1:
            cur += ch
    out = []
    for t in tuples:
        # split on commas not inside quotes/braces/brackets.
        fields, d, buf, q = [], 0, "", False
        for ch in t:
            if ch == "'" :
                q = not q
                buf += ch
            elif ch in "{[" and not q:
                d += 1; buf += ch
            elif ch in "}]" and not q:
                d -= 1; buf += ch
            elif ch == "," and d == 0 and not q:
                fields.append(buf.strip())
                buf = ""
            else:
                buf += ch
        fields.append(buf.strip())
        out.append([f.strip().strip("'") for f in fields])
    return out


def _cols(text: str, table: str) -> list[str]:
    m = re.search(rf"insert\s+into\s+{table}\s*\(([^)]*)\)", text, re.IGNORECASE)
    assert m, f"seed must name columns for {table}"
    return [c.strip() for c in m.group(1).split(",")]


def _dicts(text: str, table: str) -> list[dict[str, str]]:
    cols = _cols(text, table)
    return [dict(zip(cols, r)) for r in _rows(text, table) if len(r) == len(cols)]


# --- the four data tables are seeded ------------------------------------------------------------
@pytest.mark.parametrize("table", ["raw_readings", "validated_readings", "analysis_results", "risk_assessments"])
def test_data_table_seeded(norm: str, table: str):
    assert f"insert into {table}" in norm, f"D702 must seed {table}"


# --- provenance resolves with no dangling id ----------------------------------------------------
def test_validated_source_raw_ids_resolve(raw: str):
    raw_ids = {r["id"] for r in _dicts(raw, "raw_readings")}
    for v in _dicts(raw, "validated_readings"):
        refs = re.findall(r"\d+", v["source_raw_ids"])
        assert refs, f"validated row {v['id']} must cite a raw id"
        for rid in refs:
            assert rid in raw_ids, f"validated {v['id']} cites missing raw id {rid}"


def test_analysis_source_validated_ids_resolve(raw: str):
    validated_ids = {r["id"] for r in _dicts(raw, "validated_readings")}
    for a in _dicts(raw, "analysis_results"):
        refs = re.findall(r"\d+", a["source_validated_ids"])
        assert refs, f"analysis row {a['id']} must cite a validated id"
        for vid in refs:
            assert vid in validated_ids, f"analysis {a['id']} cites missing validated id {vid}"


def test_risk_source_analysis_ids_resolve(raw: str):
    analysis_ids = {r["id"] for r in _dicts(raw, "analysis_results")}
    for a in _dicts(raw, "risk_assessments"):
        refs = re.findall(r"\d+", a["source_analysis_ids"])
        assert refs, f"assessment {a['id']} must cite an analysis id"
        for aid in refs:
            assert aid in analysis_ids, f"assessment {a['id']} cites missing analysis id {aid}"


# --- tenant attribution is consistent with the sensor's chain (0015 guard would reject drift) ---
def test_sensor_keyed_rows_are_consistently_attributed(raw: str):
    # sensor -> bridge -> municipality, per the D701 seed.
    sensor_bridge = {s["id"]: s["bridge_id"] for s in _dicts(raw, "sensors")}
    bridge_muni = {b["id"]: b["municipality_id"] for b in _dicts(raw, "bridges")}
    for table in ("raw_readings", "validated_readings", "analysis_results"):
        for row in _dicts(raw, table):
            sid = row["sensor_id"]
            assert row["bridge_id"] == sensor_bridge[sid], (
                f"{table} row for {sid}: bridge_id drifts from the sensor's bridge"
            )
            assert row["municipality_id"] == bridge_muni[sensor_bridge[sid]], (
                f"{table} row for {sid}: municipality_id drifts from the chain"
            )


def test_risk_rows_are_consistently_attributed(raw: str):
    bridge_muni = {b["id"]: b["municipality_id"] for b in _dicts(raw, "bridges")}
    for row in _dicts(raw, "risk_assessments"):
        assert row["municipality_id"] == bridge_muni[row["bridge_id"]], (
            f"risk row {row['id']}: municipality_id drifts from its bridge"
        )


# --- one current risk row per seeded bridge (the overview needs this) ----------------------------
def test_one_current_risk_row_per_bridge(raw: str):
    rows = _dicts(raw, "risk_assessments")
    current = [r for r in rows if r.get("superseded_by", "null").lower() in ("null", "")]
    bridges = [r["bridge_id"] for r in current]
    assert len(bridges) == len(set(bridges)), "at most one CURRENT risk row per bridge"
    # every bridge that has any risk row has a current one.
    assert set(bridges) == {r["bridge_id"] for r in rows}, "each seeded bridge has a current risk row"
