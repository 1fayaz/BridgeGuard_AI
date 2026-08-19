"""P503 — the API layer reads bands. It never computes them.

`severity_for` in `agents/risk_reasoning/band.py` is the one place a 0-100 score becomes a band,
and it will not even do that until the cut-points are configured — it raises `BandNotConfigured`
rather than guess, because a boundary nobody signed off on is not a boundary. Every band that
reaches a human came from there, was written to `risk_assessments`, and was audited.

**A copy of that mapping in the API would be a second authority.** Not a wrong one, at first: it
would be written by reading the same numbers, and it would agree. It stops agreeing the day the
cut-points are retuned — a municipality's engineers decide 61 is too eager and move WARNING to 65
— and then the dashboard shows WARNING for a bridge whose audited verdict says WATCH. Both are
"the band", neither is a bug anyone can see, and the stored row and the screen disagree with no
error anywhere. That is the failure this task exists to make structurally impossible (Principle
III, INV-6).

**So the check is structural, not behavioural.** A behavioural test can only show that today's
copy agrees with today's source, which is exactly what a divergent copy also shows. The tests
below assert on the shape of the code instead: no band vocabulary in `src/api/`, no comparison of
a score against a number, no import of the mapping, no lookup table from ranges to bands.

**Scans run on the AST with docstrings stripped, and are comparison-based, not literal-based.**
Both matter and both have bitten before. Prose in this very layer discusses the 0-30/31-60 bands,
so a naive text scan fails on the explanation of the rule. And `src/api/` legitimately contains
the number 60 twice — an SQL-snippet truncation length and a `Retry-After` default — so a scan for
bare threshold numbers flags two lines that have nothing to do with risk. What is actually banned
is the *derivation*: a score compared to a constant, not a constant.

Ties to tasks.md P503, spec Principle III, plan §6, INV-6.
"""
from __future__ import annotations

import ast
from pathlib import Path

from api.read.bridges import project_overview

from tests.api.test_p501_bridges_overview import joined_row

API_ROOT = Path(__file__).resolve().parents[2] / "src" / "api"

BAND_NAMES = ("SAFE", "WATCH", "WARNING", "CRITICAL")

# Names that mean "the risk number" wherever they appear. A comparison between one of these and a
# numeric constant is a band decision regardless of what the resulting variable is called.
SCORE_WORDS = ("score", "risk", "severity", "band")


def _api_modules() -> list[tuple[str, ast.Module]]:
    return [
        (str(path.relative_to(API_ROOT)), ast.parse(path.read_text(encoding="utf-8")))
        for path in sorted(API_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
    ]


def _strip_docstrings(tree: ast.Module) -> ast.Module:
    """Prose about thresholds is not a threshold.

    This module's own docstring names every band and several cut-points, and so do several
    modules under `src/api/`. Scanning raw text would fail on the documentation of the rule —
    which teaches the next person to delete the explanation to make the test pass.
    """
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    body.pop(0)
    return tree


def _mentions_score(node: ast.AST) -> bool:
    text = ast.unparse(node).lower()
    return any(word in text for word in SCORE_WORDS)


# ------------------------------------------------------- no band vocabulary in this layer ---
def test_no_module_under_the_api_writes_a_band_name():
    """A band name as a *string literal* is the layer deciding what to call something.

    Deliberately narrowed to string constants: `logging.WARNING` is an attribute, not a literal,
    and banning the word outright would collide with ordinary logging for no safety gain.
    """
    for name, tree in _api_modules():
        for node in ast.walk(_strip_docstrings(tree)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert node.value not in BAND_NAMES, f"{name} writes the band {node.value!r}"


def test_no_module_under_the_api_declares_a_band_enum():
    """A local enum would be a second copy of the vocabulary, free to drift from 0006's."""
    for name, tree in _api_modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                members = {
                    t.id
                    for stmt in node.body
                    if isinstance(stmt, ast.AnnAssign) and isinstance(t := stmt.target, ast.Name)
                }
                members |= {
                    t.id
                    for stmt in node.body
                    if isinstance(stmt, ast.Assign)
                    for t in stmt.targets
                    if isinstance(t, ast.Name)
                }
                overlap = members & set(BAND_NAMES)
                assert not overlap, f"{name}.{node.name} redeclares bands: {sorted(overlap)}"


# ------------------------------------------------------------ no score-to-number comparison ---
def test_no_module_under_the_api_compares_a_score_to_a_number():
    """The derivation itself, in the form it is actually written.

    Matched as "an operand mentioning a score, compared against a numeric constant" rather than
    as the specific numbers, because the numbers are the part that is allowed to change. A
    re-tuned cut-point must not be able to slip past this by not being 61 any more.
    """
    for name, tree in _api_modules():
        for node in ast.walk(_strip_docstrings(tree)):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            numeric = [
                o
                for o in operands
                if isinstance(o, ast.Constant) and isinstance(o.value, (int, float))
                and not isinstance(o.value, bool)
            ]
            if numeric and any(_mentions_score(o) for o in operands):
                assert False, f"{name} derives from a score: {ast.unparse(node)}"


def test_no_module_under_the_api_bins_a_score():
    """`bisect`/`bucketize` is the same mapping wearing a library's name."""
    for name, tree in _api_modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("bisect"), f"{name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("bisect"), f"{name} imports {node.module}"


def test_no_module_under_the_api_maps_numbers_to_labels():
    """A literal pairing a number with a string is a lookup table, in either spelling.

    Both shapes are checked because the dict is only the *first* way this gets written.
    `{81: "CRITICAL", 61: "WARNING"}` and `((81, "CRITICAL"), (61, "WARNING"))` are the same
    table, and a scan that knows only about dicts is one refactor from silent. Neither the
    numbers nor the labels are named here: what is banned is the pairing.
    """
    for name, tree in _api_modules():
        for node in ast.walk(_strip_docstrings(tree)):
            if isinstance(node, ast.Dict):
                pairs = [
                    (k, v) for k, v in zip(node.keys, node.values) if k is not None
                ]
            elif isinstance(node, (ast.Tuple, ast.List)):
                pairs = [
                    (el.elts[0], el.elts[1])
                    for el in node.elts
                    if isinstance(el, (ast.Tuple, ast.List)) and len(el.elts) == 2
                ]
            else:
                continue
            for key, value in pairs:
                numeric_key = (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, (int, float))
                    and not isinstance(key.value, bool)
                )
                string_value = isinstance(value, ast.Constant) and isinstance(value.value, str)
                assert not (numeric_key and string_value), (
                    f"{name} maps a number to a label: {ast.unparse(node)[:80]}"
                )


def test_no_sql_under_the_api_derives_a_band():
    """SQL is the blind spot every scan above shares.

    The checks for comparisons, tables, and band literals all walk the AST, and to the AST a
    query is one opaque string constant. A `CASE WHEN ra.risk_score >= 81 THEN 'CRITICAL'` is
    therefore invisible to all of them while being the *most* likely place this gets written —
    it looks like query authoring rather than like business logic, and it runs on the database
    where nobody reviewing Python will see it.

    So string constants are searched as text, for the two things a derivation needs: a
    conditional, and a band name it can produce.
    """
    for name, tree in _api_modules():
        for node in ast.walk(_strip_docstrings(tree)):
            if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                continue
            text = node.value.upper()
            if "CASE" not in text and "IIF" not in text and "COALESCE" not in text:
                continue
            for band in BAND_NAMES:
                assert band not in text, f"{name} derives a band in SQL: {band}"


def test_no_sql_under_the_api_compares_a_score_column_to_a_number():
    """The same derivation with the band names factored out into a join or a mapping table.

    Catches the arithmetic rather than the vocabulary, so it holds for a query that produces
    a number-shaped verdict — a tier, a rank, an urgency — with no band word anywhere in it.
    """
    import re

    pattern = re.compile(r"(risk_score|score|severity)\s*(>=|<=|>|<|between)\s*\d", re.I)
    for name, tree in _api_modules():
        for node in ast.walk(_strip_docstrings(tree)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                found = pattern.search(node.value)
                assert not found, f"{name} compares a score in SQL: {found.group(0)!r}"


# -------------------------------------------------- the mapping is not imported either ---
def test_no_module_under_the_api_imports_the_band_mapping():
    """Importing `severity_for` would be *correct* — it is the real authority — and is still
    wrong here.

    Recomputing a band the row already carries means the served band comes from re-running the
    mapping over a score, not from the audited row. The two agree until a row is corrected or a
    cut-point moves, and then the screen shows a band that no assessment ever recorded (INV-6).
    """
    banned = ("severity_for", "BandResult", "BandNotConfigured", "ScoreConfig", "Severity")
    for name, tree in _api_modules():
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("agents"), f"{name} imports {node.module}"
                for alias in node.names:
                    assert alias.name not in banned, f"{name} imports {alias.name}"
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("agents"), f"{name} imports {alias.name}"


def test_no_module_under_the_api_reads_a_band_config():
    """The cut-points live in the Risk Agent's config. Reaching for them from here is the
    import ban restated for the path where the numbers arrive as data rather than code."""
    for name, tree in _api_modules():
        for node in ast.walk(_strip_docstrings(tree)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for setting in ("watch_min", "warning_min", "critical_min", "band_near_margin"):
                    assert setting not in node.value, f"{name} reads a cut-point: {setting}"
            if isinstance(node, ast.Attribute):
                assert node.attr not in (
                    "watch_min", "warning_min", "critical_min", "band_near_margin",
                ), f"{name} reads a cut-point: {ast.unparse(node)}"


# ------------------------------------------------------------------- severity is pass-through ---
def test_every_band_survives_the_projection_unchanged():
    for band in BAND_NAMES:
        item = project_overview([joined_row() | {"severity": band}])[0]
        assert item.current_risk.severity == band


def test_a_band_the_api_does_not_recognise_is_still_served_unchanged():
    """The positive statement of the same rule, and the reason `severity` is typed `str`.

    Validating against a hardcoded set would *be* band knowledge, and would fail closed on the
    day 0006's enum gains a value — the API would start rejecting rows the database considers
    valid, for a vocabulary it was never supposed to know.
    """
    item = project_overview([joined_row() | {"severity": "SEVERE"}])[0]
    assert item.current_risk.severity == "SEVERE"


def test_the_band_is_not_recomputed_from_the_score():
    """A row whose stored band disagrees with its stored score is served as stored.

    This cannot happen in a healthy database — 0006's constraints and `severity_for` see to
    that. Its value is as a detector: any implementation that derives the band returns the
    derived one here, and the assertion catches it without needing to know which numbers were
    used.
    """
    item = project_overview([joined_row() | {"risk_score": 95, "severity": "WATCH"}])[0]
    assert item.current_risk.severity == "WATCH"
    assert item.current_risk.risk_score == 95


def test_the_projection_never_adds_a_field_the_row_did_not_carry():
    """A derived verdict has to land somewhere, and it will not necessarily be called a band.

    `needs_attention`, `is_urgent`, `alert_level` — any of them is the same act: the API forming
    an opinion about a score and putting it on a screen next to the audited one. Pinning the
    served keys at *both* levels catches it whatever it is named, which is the only way to catch
    a name nobody has thought of yet.
    """
    item = project_overview([joined_row()])[0].model_dump()
    assert set(item) == {"bridge_id", "name", "location", "current_risk"}
    assert set(item["current_risk"]) == {
        "assessment_id",
        "risk_score",
        "severity",
        "explanation",
        "review_status",
        "assessed_at",
    }
