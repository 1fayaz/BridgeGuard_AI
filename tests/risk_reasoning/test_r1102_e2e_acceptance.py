"""R1102 — end-to-end: every spec AC manifests in risk_assessments + audit (AC-1…AC-12).

Acceptance (tasks.md R1102): drive assessments through the REAL service entrypoint (R1002) via the
R1101 harness, and assert each acceptance criterion shows up in the persisted `risk_assessments`
row + `decision_log` audit — not merely in a return value. This is the whole-agent proof: the
scorer, the three read-only tools, the guardrail loop, the coverage gate, review-status, caveats,
persistence, and provenance all cooperating on scripted inputs.

Each test names its AC. The harness (`_harness.py`) supplies the scenarios; here we assert the
outcomes against the store. Determinism is structural — no clock, no randomness — so this is
replayable. [DB-DEP/LLM-DEP: runs against the in-memory fake store + fake model; live Supabase +
frontier-model verification deferred, as everywhere in this build.]
"""
from __future__ import annotations

from _harness import all_cases, run_case, collect_case_caveats
from agents.risk_reasoning.band import severity_for
from agents.risk_reasoning.scorer import FactorInput, score_bridge
from agents.risk_reasoning.statuses import ReviewStatus, Severity


def _by_name():
    return {c.name: c for c in all_cases()}


class DownstreamConsumer:
    """Models how a downstream agent (e.g. the Alert Agent) MUST treat an assessment: it may act on
    a FINAL verdict but must HOLD a PENDING_HUMAN_REVIEW one until a human clears it (mandate #3)."""

    def consider(self, assessment) -> str:
        if assessment.review_status is ReviewStatus.PENDING_HUMAN_REVIEW:
            return "HELD"
        return "ACTED"


# --- AC-1: score + explanation are one deliverable ---------------------------------------------
def test_ac1_score_and_explanation_emitted_together():
    case = _by_name()["normal"]
    run_case(case)
    a = case.store.current("b1", "c1")
    assert a.risk_score is not None and a.severity is not None   # both present...
    assert a.explanation and a.explanation.strip()               # ...and the WHY is not empty
    # The dataclass invariant (R202) makes a bare score unconstructable — a defect cannot be emitted.


# --- AC-2: deterministic, reproducible score ---------------------------------------------------
def test_ac2_score_is_the_deterministic_weighted_result_and_reproducible():
    case = _by_name()["normal"]
    run_case(case)
    stored = case.store.current("b1", "c1").risk_score

    # Recompute the score in pure code from the SAME pinned inputs -> identical value (not a model
    # estimate). value 0.60 / limit 1.0, weight rms 1.0 -> 60.
    ran = [r for r in case.store.analysis if r.outcome == "RAN"]
    factors = [FactorInput(r.calculation.lower(), r.id, float(r.result["value"]),
                           float(r.result["limit"])) for r in ran]
    recomputed = score_bridge(factors, case.score_config).score
    assert recomputed == stored == 60


# --- AC-3: three read-only fetches, mutate nothing upstream ------------------------------------
def test_ac3_upstream_analysis_rows_are_not_mutated():
    case = _by_name()["normal"]
    before = tuple(case.store.analysis)          # frozen AnalysisResultRow snapshot
    run_case(case)
    after = tuple(case.store.analysis)
    assert before == after                       # the SA inputs are untouched by the assessment
    # (the only writes are to risk_assessments/decision_log — this agent's OWN tables.)


# --- AC-4: severity from the fixed band table --------------------------------------------------
def test_ac4_every_scored_case_maps_score_to_its_band():
    for case in all_cases():
        s = run_case(case)
        if s.withheld or not s.ok:
            continue
        a = case.store.current("b1", "c1")
        expected = severity_for(a.risk_score, case.score_config).severity
        assert a.severity is expected            # band is the config mapping, not model-chosen


# --- AC-5: recommendation only; no action, gate is downstream ----------------------------------
def test_ac5_critical_is_a_recommendation_not_an_action():
    case = _by_name()["critical"]
    run_case(case)
    a = case.store.current("b1", "c1")
    assert a.severity is Severity.CRITICAL
    assert "closure" in a.recommendation.lower()             # it recommends...
    # ...and carries no dispatch/gate: the assessment simply flows on, held for review downstream.
    assert DownstreamConsumer().consider(a) == "HELD"


# --- AC-6: degraded / withhold path ------------------------------------------------------------
def test_ac6_below_floor_and_missing_standard_withhold_not_crash():
    for name, gap in (("below_floor", "coverage"), ("standard_missing", "standard")):
        case = _by_name()[name]
        s = run_case(case)
        a = case.store.current("b1", "c1")
        assert a.risk_score is None and a.severity is None       # no fabricated number
        assert a.review_status is ReviewStatus.PENDING_HUMAN_REVIEW
        assert gap in a.explanation.lower()                      # names the gap
        assert s.ok is True                                      # a structured status, not a crash


# --- AC-7: numeric-provenance guardrail (regenerate-once-then-fail-closed) ---------------------
def test_ac7_regenerate_once_then_emit():
    case = _by_name()["regenerate_once"]
    run_case(case)
    a = case.store.current("b1", "c1")
    assert case.model.calls == [0, 1]                # exactly one regeneration
    assert not a.is_withheld and a.risk_score is not None   # the clean 2nd draft was emitted


def test_ac7_two_bad_drafts_fail_closed_with_guardrail_audit():
    case = _by_name()["fail_closed"]
    run_case(case)
    a = case.store.current("b1", "c1")
    assert a.risk_score is None                       # score withheld — fabrication never emitted
    assert a.review_status is ReviewStatus.PENDING_HUMAN_REVIEW
    kinds = [r.decision for r in case.store.audit_rows]
    assert "RISK_GUARDRAIL_FAIL" in kinds             # the tripwire is audited as such


# --- AC-8: caveat propagation ------------------------------------------------------------------
def test_ac8_all_four_flags_are_carried_as_caveats():
    case = _by_name()["all_flags"]
    run_case(case)
    caveats = collect_case_caveats(case)
    assert {c.flag for c in caveats} == {
        "clock_drift", "interpolated_input", "rate_mismatch", "abnormal_quiet",
    }
    # (The echo of these caveats into the explanation TEXT is proven in R802 with an echo model;
    # here we assert none of the four SA data-quality flags is dropped on the way into reasoning.)


# --- AC-9: dual audit (structured row + verbatim explanation + provenance + trace) -------------
def test_ac9_structured_row_answers_what_when_on_what_data():
    case = _by_name()["normal"]
    summary = run_case(case)
    a = case.store.current("b1", "c1")

    # what was decided
    assert a.risk_score is not None and a.severity is not None and a.recommendation
    # on the basis of what data (provenance pinned)
    assert a.source_analysis_ids == (1,)
    assert a.standard_code == "IRC:6" and a.standard_version == "2017"
    assert a.score_weights_version == "harness-rev1"
    assert a.model_id == "frontier-x" and a.model_version == "2026-05"
    assert a.trace_id == "trace:b1:c1"               # links the row to the forensic trace
    assert a.contributing_factors                    # the machine-checkable backing
    # the verbatim explanation is in the audit log, not a summary of it
    audit = [r for r in case.store.audit_rows if r.decision == "RISK_ASSESSMENT"]
    assert audit and audit[-1].reason == a.explanation


# --- AC-10: reproducible + supersede -----------------------------------------------------------
def test_ac10_reassessment_supersedes_and_stays_reproducible():
    case = _by_name()["reassessment"]
    run_case(case)                                   # first delivery
    run_case(case)                                   # re-assessment, same (bridge, cycle)

    rows = sorted(case.store.rows, key=lambda sa: sa.id)
    assert len(rows) == 2                            # history preserved
    assert rows[0].superseded_by == rows[1].id       # old linked, not overwritten
    assert rows[1].superseded_by is None             # new is current

    # Reproducible: recompute from the current row's pinned inputs -> its stored score.
    current = case.store.current("b1", "c1")
    ran = [r for r in case.store.analysis if r.outcome == "RAN"]
    factors = [FactorInput(r.calculation.lower(), r.id, float(r.result["value"]),
                           float(r.result["limit"])) for r in ran]
    assert score_bridge(factors, case.score_config).score == current.risk_score


# --- AC-11: never-crash across the four-scenario constitution test -----------------------------
def test_ac11_normal_missing_corrupt_offline_never_throw():
    # normal / missing-standard / malformed(corrupt) / below-floor(offline-ish) — all structured.
    for name in ("normal", "standard_missing", "malformed", "below_floor"):
        case = _by_name()[name]
        s = run_case(case)                           # must not raise
        assert s is not None
        # ok=True carries a persisted assessment; ok=False carries a structured error — never a throw.
        if s.ok:
            assert case.store.current("b1", "c1") is not None
        else:
            assert s.error


# --- AC-12: Critical not-final until reviewed; non-Critical explicitly FINAL -------------------
def test_ac12_critical_pending_and_downstream_holds():
    case = _by_name()["critical"]
    run_case(case)
    a = case.store.current("b1", "c1")
    assert a.severity is Severity.CRITICAL
    assert a.review_status is ReviewStatus.PENDING_HUMAN_REVIEW
    assert DownstreamConsumer().consider(a) == "HELD"


def test_ac12_non_critical_is_explicitly_final_and_actionable():
    case = _by_name()["normal"]
    run_case(case)
    a = case.store.current("b1", "c1")
    assert a.severity is Severity.WARNING
    assert a.review_status is ReviewStatus.FINAL          # explicitly set, never absent
    assert DownstreamConsumer().consider(a) == "ACTED"
