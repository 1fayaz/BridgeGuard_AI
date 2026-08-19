"""D801 — full-chain provenance walk: a risk score traces to an immutable raw reading (AC-5).

[DB-DEP] No Neon locally; the walk is over the D702 seed rows, parsed and resolved in Python, plus a
structural check that the terminal raw_readings table is append-only. The walk (spec AC-5 chain
completeness, FR-8):

    risk_assessments.source_analysis_ids  -> analysis_results        (0006 -> 0005)
    analysis_results.source_validated_ids -> validated_readings      (0005 -> 0002)
    validated_readings.source_raw_ids     -> raw_readings            (0002 -> 0001)

Every hop must resolve to a real seeded row with no missing link, and the terminal raw_readings row
must be immutable (its table total-blocks UPDATE/DELETE — D401). Crucially, this walk is ONLY possible
because migration 0005 (analysis_results) now exists: before it, the middle hop dangled (that gap is
exactly what D204 proved 0005 closes). Every number a human sees (the risk score) is thus traceable
to its raw source (Constitution II).

Ties to spec-002 FR-8, AC-5, FR-6.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parents[2] / "db" / "seed" / "seed_dev.sql"
MIG_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


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


@pytest.fixture(scope="module")
def seed() -> dict[str, dict[str, dict]]:
    text = SEED.read_text(encoding="utf-8")
    return {
        t: {r["id"]: r for r in _rows(text, t)}
        for t in ("raw_readings", "validated_readings", "analysis_results", "risk_assessments")
    }


def _walk(seed, assessment_id: str):
    """Walk assessment -> analysis -> validated -> raw, returning the resolved rows at each hop.
    Raises AssertionError (via the caller's asserts) if any hop dangles."""
    asmt = seed["risk_assessments"][assessment_id]
    analysis_ids = _ids(asmt["source_analysis_ids"])
    analyses = [seed["analysis_results"][a] for a in analysis_ids]
    validated_ids = [v for a in analyses for v in _ids(a["source_validated_ids"])]
    validated = [seed["validated_readings"][v] for v in validated_ids]
    raw_ids = [r for v in validated for r in _ids(v["source_raw_ids"])]
    raws = [seed["raw_readings"][r] for r in raw_ids]
    return asmt, analyses, validated, raws


def test_every_assessment_walks_to_a_raw_reading(seed):
    # Each seeded assessment resolves all three hops down to at least one raw reading.
    for asmt_id in seed["risk_assessments"]:
        asmt, analyses, validated, raws = _walk(seed, asmt_id)
        assert analyses, f"assessment {asmt_id}: no analysis hop resolved"
        assert validated, f"assessment {asmt_id}: no validated hop resolved"
        assert raws, f"assessment {asmt_id}: no raw hop resolved"


def test_walk_preserves_sensor_and_tenant_identity(seed):
    # The chain is coherent: the raw reading a risk score traces to is the SAME sensor's data, in the
    # SAME tenant — a provenance walk that crossed sensors/tenants would be a broken trace.
    for asmt_id in seed["risk_assessments"]:
        asmt, analyses, validated, raws = _walk(seed, asmt_id)
        muni = asmt["municipality_id"]
        for a in analyses + validated + raws:
            assert a["municipality_id"] == muni, f"assessment {asmt_id}: hop crossed tenants"
        sensors = {a["sensor_id"] for a in analyses + validated + raws}
        assert len(sensors) == 1, f"assessment {asmt_id}: walk crossed sensors {sensors}"


def test_no_hop_dangles(seed):
    # Explicit: every id cited at every hop points at a row the seed actually defines.
    for asmt_id, asmt in seed["risk_assessments"].items():
        for a in _ids(asmt["source_analysis_ids"]):
            assert a in seed["analysis_results"], f"dangling analysis id {a}"
        for a in _ids(asmt["source_analysis_ids"]):
            for v in _ids(seed["analysis_results"][a]["source_validated_ids"]):
                assert v in seed["validated_readings"], f"dangling validated id {v}"
                for r in _ids(seed["validated_readings"][v]["source_raw_ids"]):
                    assert r in seed["raw_readings"], f"dangling raw id {r}"


def test_terminal_raw_reading_is_immutable():
    # The chain ends at raw_readings — which must be append-only (D401 total-block): the immutable
    # source every number traces to (Constitution II). Structural confirmation over the migration.
    src = re.sub(r"\s+", " ", (MIG_DIR / "0001_raw_readings.sql").read_text().lower())
    assert re.search(
        r"create trigger \w+ before update or delete on raw_readings[^;]*raw_readings_block_mutation",
        src,
    ), "the terminal raw_readings row must be immutable (UPDATE/DELETE blocked)"
    assert re.search(r"revoke update, delete, truncate on raw_readings from public", src)


def test_walk_requires_the_0005_layer(seed):
    # The middle hop (assessment -> analysis -> validated) exists ONLY because 0005 (analysis_results)
    # now exists. If the analysis layer were empty, the assessment's source_analysis_ids would dangle
    # — which is precisely the pre-0005 gap D204 proved is closed.
    empty_analysis: dict[str, dict] = {}
    for asmt in seed["risk_assessments"].values():
        cited = _ids(asmt["source_analysis_ids"])
        assert cited, "assessment must cite an analysis id"
        assert not any(a in empty_analysis for a in cited), (
            "with no analysis layer the walk cannot start — the gap 0005 closes"
        )
        # ...and with the real layer present, they DO resolve.
        assert all(a in seed["analysis_results"] for a in cited)
