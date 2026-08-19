"""R1201 / R1202 — module docs match the implemented contract.

R1201 acceptance: README present; documents the three read-only inputs, the output contract
(score+explanation, the closed severity/review-status vocabulary, contributing factors, provenance),
the deterministic-score-the-model-explains split, the guardrail (regenerate-once-then-fail-closed),
the coverage gate, the trigger contract, and explicit out-of-scope. Matches the contract.

R1202 acceptance: the tuning guide describes config-only steps (ScoreConfig weights/normalisation,
CoverageConfig floor, band table) with NO scorer/agent code change — validating "safety numbers are
config, not code", and that they stay TODO until an engineer supplies them.

Rather than grade prose, these tests assert the docs name the REAL symbols/values the code uses, so
the docs cannot silently drift from the implementation.
"""
from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from agents.risk_reasoning.config.coverage_config import CoverageConfig
from agents.risk_reasoning.config.score_config import ScoreConfig
from agents.risk_reasoning.statuses import ReviewStatus, Severity

MODULE = Path(__file__).resolve().parents[2] / "src" / "agents" / "risk_reasoning"
README = MODULE / "README.md"
GUIDE = MODULE / "TUNING.md"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


# --- R1201: README ------------------------------------------------------------------------------
def test_readme_exists(readme: str):
    assert README.is_file() and readme.strip()


def test_readme_documents_the_closed_vocabularies(readme: str):
    # Every severity band and both review statuses must appear (the output contract's closed sets).
    for sev in Severity:
        assert sev.value in readme, f"README missing severity {sev.value}"
    for rs in ReviewStatus:
        assert rs.value in readme, f"README missing review status {rs.value}"


def test_readme_documents_the_three_read_only_tools(readme: str):
    for tool in ("get_calculation_results", "get_historical_baseline", "get_engineering_standard"):
        assert tool in readme, f"README missing input tool {tool}"


def test_readme_documents_the_score_explain_split(readme: str):
    lower = readme.lower()
    assert "score_bridge" in readme                 # the deterministic scorer named
    assert "deterministic" in lower and "explain" in lower
    # the model must be described as explaining a fixed number, not inventing it
    assert "never invent" in lower or "not invent" in lower or "fixed" in lower


def test_readme_documents_the_guardrail(readme: str):
    lower = readme.lower()
    assert "regenerate" in lower and "fail" in lower and "closed" in lower
    assert "provenance" in lower or "traceable" in lower or "trace" in lower


def test_readme_documents_the_coverage_gate(readme: str):
    lower = readme.lower()
    assert "coverage" in lower and ("floor" in lower or "withhold" in lower)


def test_readme_documents_the_trigger_contract(readme: str):
    lower = readme.lower()
    assert "sa-cycle-complete" in lower or "sa cycle" in lower or "per bridge" in lower
    assert "run_assessment" in readme               # the service entrypoint n8n hits


def test_readme_names_the_provenance_and_migrations(readme: str):
    for field in ("source_analysis_ids", "standard_version", "score_weights_version",
                  "model_version", "trace_id"):
        assert field in readme, f"README missing provenance field {field}"
    assert "risk_assessments" in readme and "decision_log" in readme


def test_readme_states_out_of_scope(readme: str):
    lower = readme.lower()
    assert "out of scope" in lower
    assert "alert agent" in lower                    # the gate lives downstream
    assert "needs_approval" in lower or "gate" in lower


# --- R1202: TUNING guide ------------------------------------------------------------------------
def test_guide_exists(guide: str):
    assert GUIDE.is_file() and guide.strip()


def test_guide_names_every_real_config_field(guide: str):
    # Every non-property field of both configs should be documented, so the guide can't drift.
    for f in fields(ScoreConfig):
        assert f.name in guide, f"TUNING.md missing ScoreConfig.{f.name}"
    for f in fields(CoverageConfig):
        assert f.name in guide, f"TUNING.md missing CoverageConfig.{f.name}"


def test_guide_is_config_only(guide: str):
    lower = guide.lower()
    assert "scoreconfig" in lower and "coverageconfig" in lower
    assert "config only" in lower or "config, not code" in lower or "no code change" in lower


def test_guide_warns_against_guessing_safety_numbers(guide: str):
    lower = guide.lower()
    assert "todo" in lower
    assert "do not guess" in lower or "not guess" in lower


def test_guide_lists_the_unchanged_logic_files(guide: str):
    # The guide must reassure that the deterministic logic modules stay untouched.
    for mod in ("scorer.py", "band.py", "coverage.py", "guardrail.py"):
        assert mod in guide, f"TUNING.md should name the unchanged module {mod}"


def test_guide_covers_the_three_headline_knobs(guide: str):
    lower = guide.lower()
    assert "weight" in lower                          # weights
    assert "coverage_floor" in guide                  # floor
    assert "watch_min" in guide and "critical_min" in guide   # band table
