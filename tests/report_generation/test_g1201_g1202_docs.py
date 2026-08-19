"""G1201 / G1202 — module docs match the implemented contract.

G1201 acceptance: README present; documents the inputs (the finalized rows read by identity), the
outputs (the report + the closed outcome/mark vocabulary + the report_artifacts provenance), the
assemble-not-re-decide invariant, the verbatim-explanation + fixed-headline rule, the fidelity gate
(exact-match fail-closed), the async fire-and-notify trigger (downstream of Risk), and explicit
out-of-scope. Matches the implemented contract.

G1202 acceptance: the change guide describes config-only steps (ReportConfig template/appendix
bound/fidelity tolerance, HeadlineTable phrases) with NO assembly/gate/render/service code change —
validating "presentation + safety numbers are config, not code", staying TODO until supplied.

Rather than grade prose, these tests assert the docs name the REAL symbols/values the code uses, so
the docs cannot silently drift from the implementation.
"""
from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from agents.report_generation.config.report_config import ReportConfig
from agents.report_generation.report_statuses import (
    DocumentMark,
    ReportOutcome,
    WithheldReason,
)

MODULE = Path(__file__).resolve().parents[2] / "src" / "agents" / "report_generation"
README = MODULE / "README.md"
GUIDE = MODULE / "CONFIGURING.md"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


# --- G1201: README ------------------------------------------------------------------------------
def test_readme_exists(readme: str):
    assert README.is_file() and readme.strip()


def test_readme_documents_the_closed_vocabularies(readme: str):
    for o in ReportOutcome:
        assert o.value in readme, f"README missing outcome {o.value}"
    for m in DocumentMark:
        assert m.value in readme, f"README missing mark {m.value}"
    for r in WithheldReason:
        assert r.value in readme, f"README missing withheld reason {r.value}"


def test_readme_documents_the_read_by_identity_inputs(readme: str):
    for src in ("risk_assessments", "analysis_results", "validated_readings"):
        assert src in readme, f"README missing input source {src}"
    assert "get_risk_assessment" in readme


def test_readme_documents_the_assemble_not_redecide_invariant(readme: str):
    lower = readme.lower()
    assert "assemble" in lower and ("not re-decide" in lower or "never recalculat" in lower
                                    or "does not re-decide" in lower)


def test_readme_documents_verbatim_explanation_and_fixed_headline(readme: str):
    lower = readme.lower()
    assert "verbatim" in lower
    assert "headline" in lower and ("fixed" in lower or "lookup" in lower)


def test_readme_documents_the_fidelity_gate(readme: str):
    lower = readme.lower()
    assert "fidelity" in lower
    assert "exact" in lower and ("fail-closed" in lower or "fail closed" in lower)


def test_readme_documents_the_trigger_contract(readme: str):
    lower = readme.lower()
    assert "fire-and-notify" in lower or "async" in lower
    assert "run_report" in readme                       # the service entrypoint n8n hits
    assert "risk" in lower                              # downstream of the Risk Agent


def test_readme_names_the_provenance_and_migrations(readme: str):
    for field in ("assessment_id", "assessment_version", "source_analysis_ids",
                  "standard_version", "template_version"):
        assert field in readme, f"README missing provenance field {field}"
    assert "report_artifacts" in readme and "decision_log" in readme


def test_readme_states_out_of_scope(readme: str):
    lower = readme.lower()
    assert "out of scope" in lower
    # the three things this agent does NOT do
    assert "publish" in lower or "publication" in lower or "dispatch" in lower
    assert "needs_approval" in lower or "downstream" in lower


def test_readme_notes_no_model(readme: str):
    lower = readme.lower()
    assert "no model" in lower or "deterministic" in lower


# --- G1202: CONFIGURING guide -------------------------------------------------------------------
def test_guide_exists(guide: str):
    assert GUIDE.is_file() and guide.strip()


def test_guide_names_every_real_config_field(guide: str):
    for f in fields(ReportConfig):
        assert f.name in guide, f"CONFIGURING.md missing ReportConfig.{f.name}"


def test_guide_is_config_only(guide: str):
    lower = guide.lower()
    assert "reportconfig" in lower and "headlinetable" in lower
    assert "config only" in lower or "config, not code" in lower or "no code change" in lower


def test_guide_warns_against_guessing(guide: str):
    lower = guide.lower()
    assert "todo" in lower
    assert "do not guess" in lower or "not guess" in lower


def test_guide_lists_the_unchanged_logic_files(guide: str):
    for mod in ("assembler.py", "fidelity.py", "service.py"):
        assert mod in guide, f"CONFIGURING.md should name the unchanged module {mod}"


def test_guide_covers_the_headline_knobs(guide: str):
    lower = guide.lower()
    assert "headline" in lower                          # severity->headline table
    assert "fidelity_tolerance" in guide               # the anti-drift knob
    assert "appendix_max_rows" in guide                # the appendix depth bound
    assert "template_ref" in guide or "letterhead_ref" in guide
