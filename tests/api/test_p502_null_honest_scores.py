"""P502 — a missing score is served as `null`, never as a number that reads as good news.

Three states reach this projection and they are routinely collapsed into two:

1. **No assessment.** Nobody has scored this bridge.
2. **Withheld assessment.** The Risk Agent looked, could not put a number on it, and said why
   (0006 FR-6/FR-7: `risk_score` and `severity` NULL together, `explanation` still NOT NULL,
   `review_status` held at PENDING_HUMAN_REVIEW).
3. **Scored assessment.** A number and a band.

The failure this task exists to prevent is state 1 or 2 arriving on a screen as `0`. Zero is not a
neutral placeholder on a 0-100 risk scale — it is the *safest possible bridge*, so the substitution
converts "we do not know" into "this one is fine" at exactly the moment a human is deciding where
not to go. The same applies to `"SAFE"` standing in for an absent band, and to `0.0`, `-1`, and
`"UNKNOWN"`: any in-band-looking value invented here is a number with no audited row behind it
(INV-6).

**Absence must survive serialization, not just construction.** A model can hold `None` correctly
and still ship a response body with the key missing, if anything on the way out sets
`exclude_none`. A missing key is read by a dashboard as `undefined`, and `undefined` renders as
whatever the frontend's fallback is — which is exactly the fabricated-zero failure again, arrived at
by a different route. So the tests below assert on `model_dump()` and on the JSON text, not on
attributes.

**The withheld reason is served verbatim.** It is the entire content of a withheld verdict: it
names what was missing, which is what makes the withholding actionable rather than merely
frustrating. Summarising, truncating, or replacing it with a fixed string ("score unavailable")
destroys the one fact the row carries (AC-8, INV-6).

Ties to tasks.md P502, spec AC-8, INV-6.
"""
from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path

from api.read.bridges import BridgeOverview, CurrentRisk, project_overview
from api.schemas.null_honest import NullHonestModel

from tests.api.test_p501_bridges_overview import (
    joined_row,
    unassessed_row,
    withheld_row,
)

API_ROOT = Path(__file__).resolve().parents[2] / "src" / "api"
READ_ROOT = API_ROOT / "read"

T2 = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)

WITHHELD_TEXT = (
    "Withheld: pier-3 strain gauge reported 6 of 8 cycles missing between 2026-07-28 and\n"
    "2026-08-03.  No score can be justified on 2 samples.  "
)


def _read_sources() -> list[tuple[str, str]]:
    return [
        (path.name, path.read_text(encoding="utf-8"))
        for path in sorted(READ_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


def _code_only(src: str) -> str:
    """Strip docstrings so prose about zeros cannot pass or fail a scan about zeros."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    body.pop(0)
    return ast.unparse(tree)


# ------------------------------------------------- an unassessed bridge carries no number ---
def test_an_unassessed_bridge_serializes_current_risk_as_null():
    """Asserted on the dumped body, not the attribute: the wire is where this can go wrong."""
    blob = project_overview([unassessed_row()])[0].model_dump()
    assert blob["current_risk"] is None


def test_an_unassessed_bridge_never_serializes_a_zero_anywhere():
    """0 on a 0-100 risk scale is the safest possible bridge, not a neutral placeholder."""
    blob = project_overview([unassessed_row()])[0].model_dump()
    assert 0 not in _numbers(blob)


def test_an_unassessed_bridge_never_invents_a_band():
    """"SAFE" would be the same lie in words. So would "UNKNOWN": an out-of-vocabulary band
    is a value this layer decided, and deciding bands is not this layer's job (P503)."""
    blob = project_overview([unassessed_row()])[0].model_dump()
    assert "SAFE" not in _strings(blob)
    assert "UNKNOWN" not in _strings(blob)


def test_the_current_risk_key_is_present_and_null_not_omitted():
    """A missing key reads as `undefined` in the dashboard and renders as its fallback —
    the fabricated-zero failure reached by a different route."""
    blob = project_overview([unassessed_row()])[0].model_dump()
    assert "current_risk" in blob


def test_the_null_survives_json_serialization():
    body = project_overview([unassessed_row()])[0].model_dump_json()
    assert json.loads(body)["current_risk"] is None


def test_exclude_none_cannot_quietly_drop_the_absence():
    """The one dump mode that turns a correct None into a missing key.

    If a router ever sets it — for terseness, for payload size — the absence stops being
    visible on the wire while every attribute-level test here still passes. Pinning it means
    the change has to be deliberate.
    """
    blob = project_overview([unassessed_row()])[0].model_dump(exclude_none=True)
    assert "current_risk" in blob, "an absent verdict was dropped from the response entirely"


# ----------------------------------------- a withheld assessment carries null, and its reason ---
def test_a_withheld_score_serializes_as_null():
    blob = project_overview([withheld_row()])[0].model_dump()
    assert blob["current_risk"]["risk_score"] is None


def test_a_withheld_severity_serializes_as_null():
    """0006's `score_has_band` makes score and severity NULL together. The response says the
    same thing, rather than half-answering with a band for a score that does not exist."""
    blob = project_overview([withheld_row()])[0].model_dump()
    assert blob["current_risk"]["severity"] is None


def test_a_withheld_score_is_never_zero():
    blob = project_overview([withheld_row()])[0].model_dump()
    assert blob["current_risk"]["risk_score"] != 0
    assert 0 not in _numbers(blob["current_risk"])


def test_the_withheld_keys_are_present_not_omitted():
    """Both nulls must be visible. A body carrying an explanation and no `risk_score` key at
    all is indistinguishable from a serialization bug."""
    risk = project_overview([withheld_row()])[0].model_dump(exclude_none=True)["current_risk"]
    assert "risk_score" in risk
    assert "severity" in risk


def test_the_withheld_reason_is_carried_byte_for_byte():
    """Whitespace, newlines, and double spaces included. The stored text is the served text —
    a summary would be a new statement nothing audited."""
    row = withheld_row() | {"explanation": WITHHELD_TEXT}
    blob = project_overview([row])[0].model_dump()
    assert blob["current_risk"]["explanation"] == WITHHELD_TEXT


def test_the_withheld_reason_survives_json_round_trip():
    row = withheld_row() | {"explanation": WITHHELD_TEXT}
    body = project_overview([row])[0].model_dump_json()
    assert json.loads(body)["current_risk"]["explanation"] == WITHHELD_TEXT


def test_a_withheld_verdict_is_never_replaced_by_a_fixed_phrase():
    """The reason names *what was missing*. "Score unavailable" names nothing and cannot be
    acted on, so an operator has no way to know a gauge needs replacing."""
    blob = project_overview([withheld_row()])[0].model_dump()
    text = blob["current_risk"]["explanation"]
    assert "pier-3" in text or "pier 3" in text


def test_a_row_missing_the_optional_columns_yields_nulls_not_substitutes():
    """The projection reads the nullable columns with `.get`, so a row that omits them entirely
    takes a different path from a row that carries them as None.

    Both must land in the same place. A default supplied at the `.get` — `row.get("severity",
    "SAFE")` — is invisible to every fixture that spells the key out, and fabricates a band only
    on the one path nobody wrote a test for.
    """
    row = {k: v for k, v in withheld_row().items() if k not in ("risk_score", "severity")}
    blob = project_overview([row])[0].model_dump()
    assert blob["current_risk"]["risk_score"] is None
    assert blob["current_risk"]["severity"] is None


def test_a_withheld_verdict_still_names_its_assessment():
    """INV-6: even a verdict with no number is traceable to the row that declined to give one."""
    blob = project_overview([withheld_row()])[0].model_dump()
    assert blob["current_risk"]["assessment_id"] == 501


def test_a_withheld_verdict_still_reports_pending_review():
    """0006's `withheld_is_pending_review` in response form: a withheld row cannot read as
    settled, because settled is the state it is constitutionally forbidden from being in."""
    blob = project_overview([withheld_row()])[0].model_dump()
    assert blob["current_risk"]["review_status"] == "PENDING_HUMAN_REVIEW"


# ---------------------------------------------------- the three states stay three states ---
def test_unassessed_and_withheld_serialize_differently():
    """The property, stated on the wire format rather than on the objects.

    Collapsing them loses the fact that a human already looked — which is the difference
    between "chase the Risk Agent" and "chase the gauge".
    """
    items = project_overview([unassessed_row(bridge_id="B1"), withheld_row(bridge_id="B2")])
    never, withheld = (i.model_dump() for i in items)
    assert never["current_risk"] is None
    assert withheld["current_risk"] is not None
    assert withheld["current_risk"]["risk_score"] is None


def test_all_three_states_are_mutually_distinguishable():
    rows = [
        unassessed_row(bridge_id="B1"),
        withheld_row(bridge_id="B2"),
        joined_row(bridge_id="B3"),
    ]
    never, withheld, scored = (i.model_dump() for i in project_overview(rows))
    assert never["current_risk"] is None
    assert withheld["current_risk"]["risk_score"] is None
    assert scored["current_risk"]["risk_score"] == 72


def test_a_real_zero_score_is_still_served_as_zero():
    """The mirror-image failure, and the reason the fix is never "reject all zeros".

    A bridge the Risk Agent genuinely scored 0 is a real audited verdict. Suppressing it to
    null to satisfy the rule above would erase a real number — the same class of lie in the
    other direction.
    """
    blob = project_overview([joined_row() | {"risk_score": 0, "severity": "SAFE"}])[0].model_dump()
    assert blob["current_risk"]["risk_score"] == 0
    assert blob["current_risk"]["severity"] == "SAFE"


def test_a_genuine_zero_and_a_withheld_score_are_distinguishable():
    rows = [
        joined_row(bridge_id="B1") | {"risk_score": 0, "severity": "SAFE"},
        withheld_row(bridge_id="B2"),
    ]
    zero, withheld = (i.model_dump() for i in project_overview(rows))
    assert zero["current_risk"]["risk_score"] == 0
    assert withheld["current_risk"]["risk_score"] is None


# ------------------------------------------------------------------ structural guarantees ---
def test_the_score_field_has_no_default():
    """A default is how a fabricated value gets in without anyone writing one.

    `risk_score: int | None = 0` would satisfy every construction-site test that passes a row
    explicitly, and quietly produce a zero on any path that does not.
    """
    for field in ("risk_score", "severity"):
        assert CurrentRisk.model_fields[field].is_required(), f"{field} has a default"


def test_the_risk_object_field_has_no_default():
    assert BridgeOverview.model_fields["current_risk"].is_required()


def test_the_read_layer_never_coalesces_a_missing_value():
    """`x or 0` and `x if x else 0` are how a fabricated value arrives looking like care.

    Matched on the AST, not on source text. A string scan for `"risk_score or 0"` misses the
    real thing that gets written — `row.get("risk_score") or 0` — because the field name and the
    `or` are separated by a paren. The mechanism being banned is the fallback expression itself,
    so that is what to look for.
    """
    for name, src in _read_sources():
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                for value in node.values[1:]:
                    assert not isinstance(value, ast.Constant), (
                        f"{name} falls back to a literal: {ast.unparse(node)}"
                    )
            if isinstance(node, ast.IfExp) and isinstance(node.orelse, ast.Constant):
                assert node.orelse.value is None, (
                    f"{name} substitutes a literal for a missing value: {ast.unparse(node)}"
                )


def test_the_read_layer_defaults_no_column_read_to_a_number():
    """`row.get("risk_score", 0)` is the same fabrication with the fallback moved inside.

    `.get(key)` with one argument is fine — it yields None, which is the honest answer. A second
    positional argument is where an invented value gets supplied.
    """
    for name, src in _read_sources():
        for node in ast.walk(ast.parse(src)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) > 1
            ):
                assert isinstance(node.args[1], ast.Constant) and node.args[1].value is None, (
                    f"{name} defaults a column read: {ast.unparse(node)}"
                )


def test_the_read_layer_sets_no_exclude_none():
    """Asserted across the layer, not just the model: this is a router-side temptation."""
    for name, src in _read_sources():
        body = _code_only(src)
        assert "exclude_none" not in body, f"{name} may drop nulls from a response: {name}"


def test_no_module_under_the_api_asks_to_exclude_nulls():
    """The base model forces the flag off, so this scan is not what makes the guarantee hold.

    It is what keeps the *intent* visible. Code that asks for `exclude_none=True` and silently
    does not get it is code whose author believed something false about the response, and the
    next reader has no way to tell which belief the surrounding logic was built on.

    `null_honest.py` is the one place the name may appear — it is where the flag is pinned off.
    """
    for path in sorted(API_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "null_honest.py":
            continue
        body = _code_only(path.read_text(encoding="utf-8"))
        for flag in ("exclude_none", "response_model_exclude_none"):
            assert flag not in body, f"{path.name} asks to drop nulls from a response: {flag}"


# ------------------------------------------------- the base model that pins the flag off ---
def test_the_verdict_models_inherit_the_null_honest_base():
    """Stated as inheritance, so a new response model gets the guarantee by being written the
    ordinary way rather than by its author remembering this rule."""
    assert issubclass(CurrentRisk, NullHonestModel)
    assert issubclass(BridgeOverview, NullHonestModel)


def test_the_base_model_ignores_a_request_to_exclude_nulls():
    """Overridden rather than rejected, on purpose.

    Raising would turn a payload-tidying change into a 500 at request time on the safety-critical
    path. Serving the nulls anyway fails towards the answer that is true; the pressure to notice
    belongs in review, which is what the scan above provides.
    """

    class _Sample(NullHonestModel):
        value: int | None

    assert _Sample(value=None).model_dump(exclude_none=True) == {"value": None}
    assert json.loads(_Sample(value=None).model_dump_json(exclude_none=True)) == {"value": None}


def test_the_base_model_still_honours_unrelated_dump_options():
    """The override pins one flag, not the whole method. Blanketing the kwargs would break
    `by_alias`, `mode="json"`, and `include`/`exclude` for every response in the layer."""

    class _Sample(NullHonestModel):
        kept: int | None
        dropped: int | None

    dumped = _Sample(kept=1, dropped=2).model_dump(include={"kept"})
    assert dumped == {"kept": 1}


def test_the_base_model_is_frozen_and_closed():
    """Inherited by every response model, so the two properties are stated once here rather
    than re-asserted at each subclass."""
    assert NullHonestModel.model_config.get("frozen") is True
    assert NullHonestModel.model_config.get("extra") == "forbid"


def test_no_module_in_the_read_layer_names_a_placeholder_band():
    """`UNKNOWN`/`N/A` are not in 0006's severity enum. Inventing one here would put a band on
    a screen that no assessment ever wrote."""
    for name, src in _read_sources():
        body = _code_only(src)
        for placeholder in ("UNKNOWN", "N/A", "NOT_ASSESSED", "PENDING_SCORE"):
            assert placeholder not in body, f"{name} invents a band: {placeholder}"


def _numbers(blob) -> list:
    """Every int/float reachable in a dumped body, so a fabricated 0 cannot hide in a nest."""
    found = []
    if isinstance(blob, dict):
        for value in blob.values():
            found += _numbers(value)
    elif isinstance(blob, list):
        for value in blob:
            found += _numbers(value)
    elif isinstance(blob, bool):
        pass
    elif isinstance(blob, (int, float)):
        found.append(blob)
    return found


def _strings(blob) -> list[str]:
    found = []
    if isinstance(blob, dict):
        for value in blob.values():
            found += _strings(value)
    elif isinstance(blob, list):
        for value in blob:
            found += _strings(value)
    elif isinstance(blob, str):
        found.append(blob)
    return found
