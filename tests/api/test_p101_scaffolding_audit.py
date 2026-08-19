"""P101 — the scaffolding audit note is complete and truthful.

Phase 1 reconciles the Spec-003 scaffolding already in `src/api/` against the
current `specs/api/spec.md` rather than rebuilding it. That reconciliation is only
useful if it is *exhaustive*: a module that exists on disk but is missing from the
note is a module nobody decided about, and an undecided module is how a stale
Spec-003 assumption survives into the new layer unnoticed.

So this is a structural check, not prose grading:
  - every module under `src/api/` appears in the note;
  - every one of them carries an explicit KEEP / MODIFY / REPLACE verdict;
  - the note names the envelope-field gap (`detail`) and defers it to P103;
  - the note states that P101 itself changes no behaviour.

Ties to tasks.md P101 and plan §0 (relationship to Spec 003).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
API_DIR = REPO / "src" / "api"
NOTE = REPO / "specs" / "api" / "audit-p101.md"

VERDICTS = ("KEEP", "MODIFY", "REPLACE")


@pytest.fixture(scope="module")
def text() -> str:
    return NOTE.read_text(encoding="utf-8")


# The Spec-003 scaffolding as it stood when P101 ran. Frozen deliberately: P101 was a
# one-time reconciliation of code that predated `specs/api/spec.md`, not a running
# inventory of `src/api/`. Discovering modules dynamically would make every later phase
# fail this test for the crime of adding a file the audit could not have covered.
# Modules built by later tasks are covered by their own task's checks (and P1004/P1007
# sweep `src/api/` as a whole at the end).
AUDITED_AT_P101 = (
    "__init__.py",
    "main.py",
    "errors.py",
    "settings.py",
    "routers/health.py",
    "schemas/common.py",
    "schemas/errors.py",
)


def _existing_modules() -> list[Path]:
    """The audited Spec-003 modules — each must still exist and still carry a verdict."""
    out = []
    for rel in AUDITED_AT_P101:
        path = API_DIR / rel
        assert path.is_file(), f"audited module {rel} has vanished; the note is now stale"
        out.append(path)
    return out


def test_note_exists():
    assert NOTE.is_file(), f"missing P101 audit note at {NOTE}"


def test_every_existing_module_is_named(text: str):
    # An unnamed module is an undecided module.
    for path in _existing_modules():
        rel = path.relative_to(REPO).as_posix()
        short = path.relative_to(API_DIR).as_posix()
        assert rel in text or short in text, (
            f"audit note must name the existing module {rel}"
        )


def test_every_named_module_has_a_verdict(text: str):
    # Each module's line must carry exactly one of KEEP / MODIFY / REPLACE.
    for path in _existing_modules():
        short = path.relative_to(API_DIR).as_posix()
        lines = [ln for ln in text.splitlines() if short in ln]
        assert lines, f"no line mentions {short}"
        assert any(v in ln for ln in lines for v in VERDICTS), (
            f"{short} is named but carries no KEEP/MODIFY/REPLACE verdict"
        )


def test_envelope_detail_gap_is_identified_and_deferred_to_p103(text: str):
    # The built envelope is {error, code, correlation_id}; the spec requires `detail`.
    assert "detail" in text, "the missing `detail` envelope field must be called out"
    assert "P103" in text, "the envelope gap must be deferred to P103, not fixed here"
    # The gap must be stated against the concrete module that has it.
    envelope_lines = [
        ln for ln in text.splitlines()
        if "schemas/errors.py" in ln or "errors.py" in ln
    ]
    assert any("detail" in ln or "MODIFY" in ln for ln in envelope_lines), (
        "the envelope gap must be attached to the error module's line"
    )


def test_note_declares_no_behaviour_change(text: str):
    low = text.lower()
    assert "no behaviour change" in low or "no behavior change" in low, (
        "P101 is audit-only; the note must say so explicitly"
    )


def test_missing_surface_is_listed(text: str):
    # The spec needs 13 endpoints; only health exists. The note must say what is absent,
    # otherwise "reusable" reads as "sufficient".
    low = text.lower()
    assert "missing" in low or "absent" in low
    for required in ("auth", "scope", "device_credentials"):
        assert required in low, f"the note must flag `{required}` as not yet present"


def test_verdict_counts_are_stated(text: str):
    # A summary line so a reviewer can check the arithmetic against the file list.
    assert re.search(r"\b\d+\s+(module|file)", text, re.IGNORECASE), (
        "the note should state how many modules were audited"
    )
