"""D903 — the FK-strategy note records the soft-provenance / hard-tenancy decision + [DB-DEP] rationale.

The schema uses TWO deliberately different foreign-key strategies, and a reader who doesn't know why
would "fix" the soft ones into hard FKs and break the design. This test guards that
`db/migrations/FK-STRATEGY.md` states the rule and its four reasons, and explains what `[DB-DEP]`
defers and how the fakes stand in.

The rule (plan §5, research §3/§4):
  * SOFT (plain BIGINT[] arrays, NO FK): the provenance links source_raw_ids / source_validated_ids /
    source_analysis_ids;
  * HARD (real FK + NOT NULL): the tenancy chain (sensor_id -> sensors -> bridges -> municipalities)
    and the self-referential superseded_by.

The four reasons soft provenance is soft:
  1. agent independence (no cross-agent write coupling);
  2. no cascade on safety data (a delete upstream must not vanish downstream audit);
  3. survive supersession (a pinned old version stays referenceable);
  4. arrays can't be FKs (Postgres has no array-element FK).

Ties to plan §5 and research §3/§4.
"""
from __future__ import annotations

from pathlib import Path

import pytest

NOTE = Path(__file__).resolve().parents[2] / "db" / "migrations" / "FK-STRATEGY.md"


@pytest.fixture(scope="module")
def low() -> str:
    return NOTE.read_text(encoding="utf-8").lower()


def test_note_exists():
    assert NOTE.is_file(), f"missing {NOTE}"


def test_states_the_soft_vs_hard_rule(low: str):
    assert "soft" in low and "hard" in low
    # the soft targets: the provenance arrays.
    for arr in ("source_raw_ids", "source_validated_ids", "source_analysis_ids"):
        assert arr in low, f"the soft-provenance array {arr} must be named"
    # the hard targets: the tenancy chain + superseded_by.
    assert "superseded_by" in low
    assert "sensors" in low and "bridges" in low and "municipalities" in low


def test_lists_all_four_reasons(low: str):
    # 1. agent independence
    assert "independen" in low or "coupling" in low
    # 2. no cascade on safety data
    assert "cascade" in low
    # 3. survive supersession
    assert "supersed" in low
    # 4. arrays can't be FKs
    assert "array" in low and ("cannot" in low or "can't" in low or "no array" in low)


def test_explains_db_dep_and_the_fakes(low: str):
    assert "[db-dep]" in low or "db-dep" in low
    # what it defers (live enforcement) and how the fakes stand in.
    assert "fake" in low
    assert "neon" in low or "live" in low


def test_names_which_guarantees_are_live_vs_fake_verified(low: str):
    # The acceptance: state which guarantees are live-verified vs fake-verified.
    assert "live" in low
    assert "fake" in low
