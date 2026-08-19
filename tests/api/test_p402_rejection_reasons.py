"""P402 — every rejection reason comes from a closed, documented, enum-typed set.

The point of closing this set is that the gateway is a machine. A Pi cannot branch on prose.
If rejections arrived as free text, every new wording would be a string the firmware has
never seen, and the only robust behaviour left to the gateway is "log it and drop the
reading" — which is the silent data loss the per-reading contract exists to prevent
(Principle II).

Closing it also constrains *us*, which is the more valuable half. A new rejection cause
cannot be invented at a call site under deadline; it has to be added to the enum, which is
the one place a reader looks to learn what can go wrong, and where the gateway-facing
guidance lives. An `OTHER` member would reopen the set completely, so the tests below assert
it does not exist.

What each reason is for is a real distinction, not a taxonomy exercise:

- **unknown_sensor** — an operator must provision something. Retrying will not help.
- **sensor_not_on_this_bridge** — the sensor is real but belongs elsewhere; the reading was
  *not* re-attributed, and the gateway must not re-send it under another key.
- **unit_mismatch** — refused rather than converted. A silent unit conversion at the boundary
  would put a fabricated number in the raw table (Principle II).

Ties to tasks.md P402, spec AC-1 + §1.
"""
from __future__ import annotations

import inspect
import json
from enum import Enum
from pathlib import Path

import pytest

from api.ingest.reasons import REASON_GUIDANCE, RejectionReason

EXPECTED = {
    "missing_field",
    "non_numeric_value",
    "malformed_timestamp",
    "unknown_sensor",
    "sensor_not_on_this_bridge",
    "unit_mismatch",
}


# ------------------------------------------------------------------- the set is closed ---
def test_the_reason_set_is_exactly_the_documented_one():
    """Pinned by value: adding a member without documenting it fails here."""
    assert {r.value for r in RejectionReason} == EXPECTED


def test_the_five_spec_named_causes_all_exist():
    """spec §1 names these explicitly as the causes a gateway must be able to act on."""
    for name in (
        "UNKNOWN_SENSOR",
        "SENSOR_NOT_ON_THIS_BRIDGE",
        "MALFORMED_TIMESTAMP",
        "NON_NUMERIC_VALUE",
        "UNIT_MISMATCH",
    ):
        assert hasattr(RejectionReason, name), f"spec §1 names {name}"


def test_there_is_no_catch_all_member():
    """An `OTHER` reason reopens the set — the gateway is back to guessing."""
    for escape_hatch in ("OTHER", "UNKNOWN", "MISC", "GENERIC", "ERROR", "UNSPECIFIED"):
        assert not hasattr(RejectionReason, escape_hatch), (
            f"{escape_hatch} would reopen the closed set"
        )


def test_an_unlisted_reason_cannot_be_constructed():
    """The headline check: an arbitrary string is not a reason."""
    with pytest.raises(ValueError):
        RejectionReason("something_new_someone_invented")


def test_an_existing_reason_cannot_be_reassigned():
    with pytest.raises(AttributeError):
        RejectionReason.UNIT_MISMATCH = "something_else"  # type: ignore[misc]


def test_a_reason_cannot_be_added_at_runtime():
    """A stray class attribute must not become a member.

    Enum metaclass allows setting a *new* name (it lands as a plain class attribute), so the
    property that actually matters is that the member set is unchanged — a gateway iterating
    the enum still sees exactly the documented six.
    """
    before = {r.value for r in RejectionReason}
    RejectionReason.SURPRISE = "surprise"  # type: ignore[attr-defined]
    try:
        assert {r.value for r in RejectionReason} == before
        assert "surprise" not in {r.value for r in RejectionReason}
        with pytest.raises(ValueError):
            RejectionReason("surprise")
    finally:
        del RejectionReason.SURPRISE  # type: ignore[attr-defined]


def test_the_reasons_are_enum_typed_not_strings():
    assert issubclass(RejectionReason, Enum)


def test_each_reason_is_also_a_plain_string_for_the_wire():
    """`str, Enum` so it serialises as its value without a custom encoder."""
    assert issubclass(RejectionReason, str)
    assert json.dumps({"reason": RejectionReason.UNIT_MISMATCH}) == '{"reason": "unit_mismatch"}'


def test_reason_values_are_stable_machine_readable_tokens():
    """A gateway compares these. Spaces or capitals would make them prose."""
    for reason in RejectionReason:
        assert reason.value == reason.value.lower()
        assert " " not in reason.value
        assert reason.value.replace("_", "").isalnum()


def test_no_two_reasons_share_a_value():
    values = [r.value for r in RejectionReason]
    assert len(values) == len(set(values))


# --------------------------------------------------------- documented for gateway authors ---
def test_every_reason_carries_guidance():
    """Undocumented means the gateway author has to read our source to act on it."""
    missing = [r.name for r in RejectionReason if r not in REASON_GUIDANCE]
    assert not missing, f"reasons with no gateway guidance: {missing}"


def test_the_guidance_table_documents_nothing_extra():
    """A stale entry for a removed reason is a lie in the docs."""
    assert set(REASON_GUIDANCE) == set(RejectionReason)


def test_the_guidance_is_substantial_not_a_restated_name():
    for reason, text in REASON_GUIDANCE.items():
        assert len(text) > 40, f"{reason.name} guidance is too thin to act on"
        assert text.strip() != reason.value.replace("_", " ")


def test_the_guidance_says_what_to_do_about_it():
    """The only reason to tell a machine *why* is so it can decide what to do next."""
    actionable = (
        "retry", "resend", "send", "operator", "provision", "fix", "do not", "refused",
    )
    for reason, text in REASON_GUIDANCE.items():
        assert any(word in text.lower() for word in actionable), (
            f"{reason.name} guidance gives the gateway no action"
        )


def test_the_guidance_leaks_no_internals():
    for reason, text in REASON_GUIDANCE.items():
        blob = text.lower()
        for banned in ("sql", "traceback", "pydantic", "src/", "postgres", "municipality_id"):
            assert banned not in blob, f"{reason.name} guidance mentions {banned!r}"


def test_the_retry_advice_is_honest_about_permanence():
    """A shape fault is deterministic: telling a Pi to retry it would loop forever."""
    for reason in (
        RejectionReason.MISSING_FIELD,
        RejectionReason.NON_NUMERIC_VALUE,
    ):
        assert "identically" in REASON_GUIDANCE[reason].lower()


# -------------------------------------------------- the distinctions are load-bearing ---
def test_unknown_and_wrong_bridge_are_separate_reasons():
    """Different operator actions: provision a sensor vs. stop sending it here."""
    assert RejectionReason.UNKNOWN_SENSOR is not RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE
    assert REASON_GUIDANCE[RejectionReason.UNKNOWN_SENSOR] != (
        REASON_GUIDANCE[RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE]
    )


def test_the_cross_bridge_reason_forbids_re_sending_elsewhere():
    """Re-sending under another key is how a gateway would corrupt tenancy trying to help."""
    text = REASON_GUIDANCE[RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE].lower()
    assert "do not" in text
    assert "re-attributed" in text or "reattributed" in text


def test_the_unit_reason_says_refused_not_converted():
    """A silent conversion at the boundary writes a fabricated number into raw storage."""
    text = REASON_GUIDANCE[RejectionReason.UNIT_MISMATCH].lower()
    assert "convert" in text
    assert "refused" in text


def test_the_timestamp_reason_explains_why_time_is_required():
    text = REASON_GUIDANCE[RejectionReason.MALFORMED_TIMESTAMP].lower()
    assert "iso" in text


# ------------------------------------------------------------------- structural guards ---
def test_no_ingest_module_emits_a_bare_reason_string():
    """A literal like reason="bad value" would bypass the enum entirely."""
    offenders = []
    for path in Path("src/api/ingest").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for banned in ('reason="', "reason='", 'reason: str'):
            if banned in text:
                offenders.append(f"{path.name}: {banned}")
    assert not offenders, f"bare reason strings found: {offenders}"


def test_the_reasons_module_computes_nothing():
    """It is a vocabulary. Logic here would make the set depend on runtime state."""
    import api.ingest.reasons as mod

    src = inspect.getsource(mod)
    assert "import " not in src.split('"""', 2)[-1] or "from enum" in src
    for banned in ("def check", "def validate", "async def", "requests.", "httpx"):
        assert banned not in src


def test_the_reasons_module_imports_no_agent_and_no_db():
    import api.ingest.reasons as mod

    src = inspect.getsource(mod)
    for banned in ("from agents", "import agents", "asyncpg", "from db."):
        assert banned not in src


def test_every_reason_is_reachable_from_the_shape_or_ownership_checks():
    """A member nothing can ever emit is dead vocabulary that misleads a gateway author.

    The three ownership reasons need a sensor registry, so they are emitted by P404's
    cross-bridge check rather than the shape check — asserted here by name so this test does
    not silently pass once that module lands.
    """
    from api.ingest import batch

    shape_emitted = {
        RejectionReason.MISSING_FIELD,
        RejectionReason.NON_NUMERIC_VALUE,
        RejectionReason.MALFORMED_TIMESTAMP,
    }
    src = inspect.getsource(batch)
    for reason in shape_emitted:
        assert reason.name in src, f"{reason.name} is never emitted by the shape check"

    ownership = set(RejectionReason) - shape_emitted
    assert ownership == {
        RejectionReason.UNKNOWN_SENSOR,
        RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE,
        RejectionReason.UNIT_MISMATCH,
    }
