"""D902 — the RLS operator note documents the isolation model for whoever runs BridgeGuard.

RLS is only as safe as its operation: the API must set the session scope on EVERY transaction, and an
operator must understand that FORCE + fail-closed are load-bearing, not optional. This test guards
that `db/migrations/RLS.md` states the model truthfully:

  * the single role `bridgeguard_service` owns the tables and connects the app;
  * FORCE ROW LEVEL SECURITY (not just ENABLE) — so the owner role is itself subject to RLS;
  * the EXACT GUC name `app.current_municipality_id` (no spelling drift — the policies key on it);
  * how the API sets it per transaction (SET LOCAL) and the fail-closed behaviour when it is unset;
  * that the auth seam (who maps a request to a municipality) is OUT OF SCOPE (a separate spec).

Ties to spec-002 FR-4 / §Out-of-Scope and plan §2.
"""
from __future__ import annotations

from pathlib import Path

import pytest

NOTE = Path(__file__).resolve().parents[2] / "db" / "migrations" / "RLS.md"


@pytest.fixture(scope="module")
def low() -> str:
    return NOTE.read_text(encoding="utf-8").lower()


def test_note_exists():
    assert NOTE.is_file(), f"missing {NOTE}"


def test_names_the_service_role(low: str):
    assert "bridgeguard_service" in low


def test_documents_force_not_just_enable(low: str):
    assert "force" in low
    assert "enable" in low
    # the WHY: FORCE binds the owner too.
    assert "owner" in low or "bypass" in low


def test_states_the_exact_guc_name(low: str):
    assert "app.current_municipality_id" in low


def test_documents_how_the_api_sets_the_scope(low: str):
    # SET LOCAL (per-transaction) is the sanctioned mechanism; the note must show it.
    assert "set local" in low or "set_config" in low
    assert "transaction" in low


def test_states_fail_closed_semantics(low: str):
    assert "fail-closed" in low or "fail closed" in low
    assert "zero rows" in low or "no rows" in low or "nothing" in low


def test_marks_auth_seam_out_of_scope(low: str):
    assert "out of scope" in low or "out-of-scope" in low or "separate spec" in low
    assert "auth" in low
