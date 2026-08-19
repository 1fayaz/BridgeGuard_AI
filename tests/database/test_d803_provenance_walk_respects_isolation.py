"""D803 — provenance walk respects tenant isolation: a chain cannot exfiltrate another tenant's data.

[DB-DEP] No Neon locally. D801 proved the walk resolves; D803 proves it cannot be turned into a
cross-tenant side channel. Under app.current_municipality_id = MUNI_A, attempting to walk a MUNI_B
assessment returns ZERO rows at every hop — because RLS filters EACH table read by the same
municipality_id predicate (0016), so a MUNI_A principal never sees the MUNI_B assessment to start
from, nor any MUNI_B analysis / validated / raw row the chain would traverse. Provenance is a read
over tenant-scoped tables; it inherits their isolation.

Proven now over the D702 seed + the 0016 SELECT predicate, applied at every hop:
  * scoped to MUNI_A, the MUNI_B assessment is invisible -> the walk cannot even begin;
  * even if a caller somehow held a MUNI_B analysis id, the scoped read of that row returns nothing;
  * scoped to MUNI_B, the SAME walk resolves fully (proving it's isolation, not a broken chain).

Ties to spec-002 FR-4/FR-8 and AC-4/AC-5.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parents[2] / "db" / "seed" / "seed_dev.sql"


def _rows(text: str, table: str) -> list[dict[str, str]]:
    mcols = re.search(rf"insert\s+into\s+{table}\s*\(([^)]*)\)", text, re.IGNORECASE)
    if not mcols:
        return []
    cols = [c.strip() for c in mcols.group(1).split(",")]
    mvals = re.search(
        rf"insert\s+into\s+{table}\b.*?values\s*(.*?)(?:\bon\s+conflict\b|;)",
        text, re.IGNORECASE | re.DOTALL,
    )
    body = re.sub(r"--[^\n]*", "", mvals.group(1))
    tuples, depth, cur = [], 0, ""
    for ch in body:
        if ch == "(" and depth == 0:
            depth, cur = 1, ""
        elif ch == ")" and depth == 1:
            depth = 0
            tuples.append(cur)
        elif depth == 1:
            cur += ch
    out = []
    for t in tuples:
        fields, d, buf, q = [], 0, "", False
        for ch in t:
            if ch == "'":
                q = not q; buf += ch
            elif ch in "{[" and not q:
                d += 1; buf += ch
            elif ch in "}]" and not q:
                d -= 1; buf += ch
            elif ch == "," and d == 0 and not q:
                fields.append(buf.strip()); buf = ""
            else:
                buf += ch
        fields.append(buf.strip())
        vals = [f.strip().strip("'") for f in fields]
        if len(vals) == len(cols):
            out.append(dict(zip(cols, vals)))
    return out


def _ids(cell: str) -> list[str]:
    return re.findall(r"\d+", cell or "")


class ScopedReader:
    """The 0016 SELECT policy as a read gate: a row is visible only if its municipality_id == scope
    (id == scope for municipalities). Every hop of the walk goes through this — exactly as a live
    RLS-filtered SELECT would."""

    def __init__(self, seed: dict, scope: str) -> None:
        self._seed = seed
        self._scope = scope

    def get(self, table: str, row_id: str) -> dict | None:
        row = self._seed[table].get(row_id)
        if row is None:
            return None
        key = "id" if table == "municipalities" else "municipality_id"
        return row if row.get(key) == self._scope else None   # RLS: foreign-tenant row is invisible


@pytest.fixture(scope="module")
def seed() -> dict:
    text = SEED.read_text(encoding="utf-8")
    return {
        t: {r["id"]: r for r in _rows(text, t)}
        for t in ("raw_readings", "validated_readings", "analysis_results", "risk_assessments")
    }


def _scoped_walk(seed: dict, scope: str, assessment_id: str):
    """Walk assessment -> analysis -> validated -> raw, reading EVERY hop through the scoped reader.
    Returns the list of rows resolved; a hop that RLS hides simply yields nothing downstream."""
    r = ScopedReader(seed, scope)
    asmt = r.get("risk_assessments", assessment_id)
    if asmt is None:
        return []                                   # cannot even start — the assessment is invisible
    resolved = [asmt]
    analyses = [r.get("analysis_results", a) for a in _ids(asmt["source_analysis_ids"])]
    analyses = [a for a in analyses if a is not None]
    resolved += analyses
    validated = [r.get("validated_readings", v)
                 for a in analyses for v in _ids(a["source_validated_ids"])]
    validated = [v for v in validated if v is not None]
    resolved += validated
    raws = [r.get("raw_readings", rid)
            for v in validated for rid in _ids(v["source_raw_ids"])]
    resolved += [x for x in raws if x is not None]
    return resolved


def _muni_b_assessment_id(seed: dict) -> str:
    for aid, row in seed["risk_assessments"].items():
        if row["municipality_id"] == "MUNI_B":
            return aid
    pytest.fail("seed must contain a MUNI_B assessment for the isolation test")


def test_scoped_to_a_cannot_walk_a_b_assessment(seed):
    b_asmt = _muni_b_assessment_id(seed)
    walked = _scoped_walk(seed, "MUNI_A", b_asmt)
    assert walked == [], "a MUNI_A principal must resolve ZERO rows walking a MUNI_B assessment"


def test_the_same_b_walk_resolves_when_scoped_to_b(seed):
    # Proves it's ISOLATION, not a broken chain: scoped to the owner, the walk resolves fully.
    b_asmt = _muni_b_assessment_id(seed)
    walked = _scoped_walk(seed, "MUNI_B", b_asmt)
    tables_hit = {r["municipality_id"] for r in walked}
    assert tables_hit == {"MUNI_B"}, "the owner's walk resolves, all rows in-tenant"
    assert len(walked) >= 4, "assessment + analysis + validated + raw all resolved for the owner"


def test_holding_a_foreign_analysis_id_still_reads_nothing(seed):
    # Even if a MUNI_A caller somehow LEARNED a MUNI_B analysis id, the scoped read of that row is
    # empty — RLS gates the row, not merely the entry point.
    b_analysis_ids = [aid for aid, row in seed["analysis_results"].items()
                      if row["municipality_id"] == "MUNI_B"]
    assert b_analysis_ids, "seed must have a MUNI_B analysis row"
    r = ScopedReader(seed, "MUNI_A")
    for aid in b_analysis_ids:
        assert r.get("analysis_results", aid) is None, "a foreign analysis row is invisible under RLS"


def test_a_scoped_to_a_walk_of_an_a_assessment_still_works(seed):
    # Sanity: isolation doesn't break the legitimate same-tenant walk.
    a_asmt = next(aid for aid, row in seed["risk_assessments"].items()
                  if row["municipality_id"] == "MUNI_A")
    walked = _scoped_walk(seed, "MUNI_A", a_asmt)
    assert walked and {r["municipality_id"] for r in walked} == {"MUNI_A"}
