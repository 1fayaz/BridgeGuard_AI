"""D504 — the overview read model: "current risk per bridge for a municipality" is index-served, no
history scan.

[DB-DEP] No Neon locally, so the actual EXPLAIN/query-plan assertion (indexes only, no seq-scan of
historical rows) runs in D601 against a seeded set. What is verifiable now:

  1. The two indexes that back the read exist (plan §4):
       * idx_risk_assessments_municipality — (municipality_id), added in 0015 part C (D304): narrows
         the scan to the ONE tenant's rows (the RLS predicate / overview filter);
       * uq_risk_current_bridge_cycle — (bridge_id, cycle_id) WHERE superseded_by IS NULL (D503):
         gives the latest CURRENT row per bridge WITHOUT scanning superseded history.
     Together: filter by municipality_id (index), take current rows only (partial index) — no
     raw/historical scan.

  2. The read-model BEHAVIOUR, mirrored over the fakes: composing the tenant store's
     bridge -> municipality mapping with the risk store's current-per-bridge read returns exactly the
     current assessment for each bridge OF THAT MUNICIPALITY, and NEVER a superseded (historical) row
     or another tenant's bridge. That "current-only, tenant-scoped" semantics is what the two indexes
     make fast; the fake proves the semantics, D601 proves the plan.

Ties to spec-002 FR-12 and AC-11 (backend AC-2 dependency).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from agents.risk_reasoning.store import FakeRiskStore
from agents.risk_reasoning.assessment import RiskAssessment
from agents.risk_reasoning.statuses import Severity, ReviewStatus
from db.tenant_store import FakeTenantStore

MIG_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def _norm(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8").lower())


# --- 1. the two backing indexes exist -----------------------------------------------------------
def test_municipality_filter_index_present():
    # 0015 part C (D304): the (municipality_id) index that narrows the overview to one tenant.
    wiring = _norm(MIG_DIR / "0015_tenant_columns_and_fks.sql")
    assert re.search(
        r"create index (if not exists )?\w+ on risk_assessments \(municipality_id\)", wiring
    ), "the overview needs idx_risk_assessments_municipality (D304) to filter by tenant"


def test_current_per_bridge_partial_index_present():
    # 0006 / D503: the partial-unique-current index that yields the latest current row per bridge
    # without touching superseded history.
    risk = _norm(MIG_DIR / "0006_risk_assessments.sql")
    assert re.search(
        r"create unique index (if not exists )?\w+ on risk_assessments \(bridge_id, cycle_id\) "
        r"where superseded_by is null",
        risk,
    ), "the overview needs the (bridge_id, cycle_id) WHERE superseded_by IS NULL partial index"


# --- 2. the read-model behaviour, over the fakes ------------------------------------------------
def _assessment(bridge_id: str, cycle_id: str, score: int) -> RiskAssessment:
    return RiskAssessment(
        bridge_id=bridge_id, cycle_id=cycle_id, risk_score=score, severity=Severity.WATCH,
        recommendation="Increase inspection frequency.",
        explanation="within band; monitoring.", contributing_factors=(),
        confidence=0.9, data_completeness=0.95, review_status=ReviewStatus.FINAL,
        source_analysis_ids=(1,), baseline_ref=None, standard_code="IRC:6",
        standard_version="2017", score_weights_version="w1", model_id="m", model_version="1",
        trace_id=f"trace-{bridge_id}-{cycle_id}",
    )


def _overview(tenant: FakeTenantStore, risk: FakeRiskStore, municipality_id: str) -> dict[str, RiskAssessment]:
    """The overview read model, mirrored: current risk per bridge for one municipality.

    Semantics the two indexes serve: filter to the tenant's bridges (idx_risk_assessments_municipality),
    then take the current (non-superseded) row per bridge (uq_risk_current_bridge_cycle) — no history.
    """
    bridges = {b for b, br in tenant._bridges.items() if br.municipality_id == municipality_id}
    out: dict[str, RiskAssessment] = {}
    for sa in risk.rows:
        if sa.superseded_by is not None:            # skip history — the partial index excludes these
            continue
        a = sa.assessment
        if a.bridge_id in bridges:                  # tenant scope — the municipality_id index narrows here
            out[a.bridge_id] = a
    return out


def _seed():
    tenant = FakeTenantStore()
    tenant.add_municipality("MUNI_A", name="Alpha City")
    tenant.add_municipality("MUNI_B", name="Beta Town")
    tenant.add_bridge("BRIDGE_A1", municipality_id="MUNI_A", name="North Span")
    tenant.add_bridge("BRIDGE_A2", municipality_id="MUNI_A", name="South Span")
    tenant.add_bridge("BRIDGE_B1", municipality_id="MUNI_B", name="East Span")

    risk = FakeRiskStore()
    # BRIDGE_A1: an OLD assessment that gets superseded by a corrected one (history must not surface).
    old = risk.insert(_assessment("BRIDGE_A1", "c1", 30))
    risk.insert_superseding(old, _assessment("BRIDGE_A1", "c2", 55))
    # BRIDGE_A2: a single current assessment.
    risk.insert(_assessment("BRIDGE_A2", "c1", 40))
    # BRIDGE_B1: another tenant's bridge — must never appear in MUNI_A's overview.
    risk.insert(_assessment("BRIDGE_B1", "c1", 90))
    return tenant, risk


def test_overview_returns_current_row_per_bridge():
    tenant, risk = _seed()
    view = _overview(tenant, risk, "MUNI_A")
    assert set(view) == {"BRIDGE_A1", "BRIDGE_A2"}, "one current row per bridge of the municipality"
    # BRIDGE_A1's row is the CORRECTED (current) one, not the superseded original.
    assert view["BRIDGE_A1"].risk_score == 55
    assert view["BRIDGE_A2"].risk_score == 40


def test_overview_excludes_superseded_history():
    tenant, risk = _seed()
    view = _overview(tenant, risk, "MUNI_A")
    # the superseded score-30 original is never surfaced (no history scan).
    assert all(a.risk_score != 30 for a in view.values())


def test_overview_is_tenant_scoped():
    tenant, risk = _seed()
    view_a = _overview(tenant, risk, "MUNI_A")
    assert "BRIDGE_B1" not in view_a, "MUNI_A overview must not include MUNI_B's bridge"
    view_b = _overview(tenant, risk, "MUNI_B")
    assert set(view_b) == {"BRIDGE_B1"} and view_b["BRIDGE_B1"].risk_score == 90
