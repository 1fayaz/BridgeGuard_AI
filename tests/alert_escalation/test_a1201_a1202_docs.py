"""A1201 / A1202 — module docs match the implemented contract.

A1201 acceptance: README present; documents the inputs (the finalized verdict read by identity), the
outputs (the dispatch + the closed decision/delivery/escalation/approval vocabulary + the
alert_dispatches provenance), the notify-not-re-judge invariant, the settled severity->approval
table, the single un-bypassable needs_approval chokepoint, the consistency gate (fail-closed), the
severity-dependent escalation close, the async fire-and-notify trigger (downstream of Risk), and
explicit out-of-scope. Matches the implemented contract.

A1202 acceptance: the change guide describes config-only steps (roster/escalation order, per-band
channels, retry/backoff/timeout, authority set, severity->templates) with NO tiering/gate/dispatch/
escalation/service code change — validating "policy + safety numbers are config, not code", staying
TODO until supplied.

Rather than grade prose, these tests assert the docs name the REAL symbols/values the code uses, so
the docs cannot silently drift from the implementation.
"""
from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from agents.alert_escalation.config.alert_policy import AlertPolicy
from agents.alert_escalation.statuses import (
    ApprovalState,
    DeliveryState,
    DispatchDecision,
    EscalationState,
    WithheldReason,
)

MODULE = Path(__file__).resolve().parents[2] / "src" / "agents" / "alert_escalation"
README = MODULE / "README.md"
GUIDE = MODULE / "CONFIGURING.md"


@pytest.fixture(scope="module")
def readme() -> str:
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


# --- A1201: README ------------------------------------------------------------------------------
def test_readme_exists(readme: str):
    assert README.is_file() and readme.strip()


def test_readme_documents_the_closed_vocabularies(readme: str):
    for d in DispatchDecision:
        assert d.value in readme, f"README missing dispatch decision {d.value}"
    for s in DeliveryState:
        assert s.value in readme, f"README missing delivery state {s.value}"
    for e in EscalationState:
        assert e.value in readme, f"README missing escalation state {e.value}"
    for a in ApprovalState:
        assert a.value in readme, f"README missing approval state {a.value}"
    for r in WithheldReason:
        assert r.value in readme, f"README missing withheld reason {r.value}"


def test_readme_documents_the_read_by_identity_input(readme: str):
    assert "risk_assessments" in readme
    assert "get_risk_assessment" in readme
    lower = readme.lower()
    assert "identity" in lower or "by identity" in lower


def test_readme_documents_the_notify_not_rejudge_invariant(readme: str):
    lower = readme.lower()
    assert "notify" in lower
    assert "re-judge" in lower or "never re-judge" in lower or "does not re-judge" in lower


def test_readme_documents_the_settled_severity_to_approval_table(readme: str):
    # The four bands and their settled decisions must all appear.
    for band in ("SAFE", "WATCH", "WARNING", "CRITICAL"):
        assert band in readme, f"README missing band {band}"
    assert "DASHBOARD_ONLY" in readme and "AUTO_FIRE" in readme and "NEEDS_APPROVAL" in readme


def test_readme_documents_the_single_chokepoint(readme: str):
    lower = readme.lower()
    assert "chokepoint" in lower
    assert "needs_approval" in lower
    assert "single" in lower or "un-bypassable" in lower or "unbypassable" in lower


def test_readme_documents_the_consistency_gate(readme: str):
    lower = readme.lower()
    assert "consistency" in lower
    assert "fail-closed" in lower or "fail closed" in lower


def test_readme_documents_the_severity_dependent_close(readme: str):
    lower = readme.lower()
    # SAFE/WATCH close on DELIVERED; WARNING/CRITICAL only on ACK.
    assert "delivered" in lower and ("ack" in lower or "acknowledg" in lower)


def test_readme_documents_the_trigger_contract(readme: str):
    lower = readme.lower()
    assert "fire-and-notify" in lower or "async" in lower
    assert "run_alert" in readme                          # the service entrypoint n8n hits
    assert "risk" in lower                                # downstream of the Risk Agent


def test_readme_names_the_provenance_and_migrations(readme: str):
    for field in ("assessment_id", "assessment_version", "trace_id"):
        assert field in readme, f"README missing provenance field {field}"
    assert "alert_dispatches" in readme and "decision_log" in readme


def test_readme_states_out_of_scope(readme: str):
    lower = readme.lower()
    assert "out of scope" in lower
    # it does NOT re-judge (Risk owns the verdict) and does NOT author the report (Report owns that)
    assert "report" in lower and "risk" in lower


def test_readme_notes_no_model(readme: str):
    lower = readme.lower()
    assert "no model" in lower or "deterministic" in lower


# --- A1202: CONFIGURING guide -------------------------------------------------------------------
def test_guide_exists(guide: str):
    assert GUIDE.is_file() and guide.strip()


def test_guide_names_every_real_config_field(guide: str):
    for f in fields(AlertPolicy):
        assert f.name in guide, f"CONFIGURING.md missing AlertPolicy.{f.name}"


def test_guide_is_config_only(guide: str):
    lower = guide.lower()
    assert "alertpolicy" in lower and "messagetemplatetable" in lower
    assert "config only" in lower or "config, not code" in lower or "no code change" in lower


def test_guide_warns_against_guessing(guide: str):
    lower = guide.lower()
    assert "todo" in lower
    assert "do not guess" in lower or "not guess" in lower


def test_guide_lists_the_unchanged_logic_files(guide: str):
    for mod in ("tiering.py", "consistency.py", "approval.py", "escalation.py", "service.py"):
        assert mod in guide, f"CONFIGURING.md should name the unchanged module {mod}"


def test_guide_covers_the_config_knobs(guide: str):
    lower = guide.lower()
    assert "roster" in lower                              # contact roster / escalation order
    assert "channel" in lower                            # per-band channel
    assert "retry" in lower and "backoff" in lower       # retry/backoff/timeout
    assert "authority" in lower                          # authority-recipient set
    assert "template" in lower                            # severity->message templates
