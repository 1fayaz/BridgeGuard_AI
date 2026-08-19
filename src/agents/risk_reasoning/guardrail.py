"""Numeric-provenance output guardrail (R601+) — FR-7, mandated requirement #2.

The highest-value safety control in this agent: before an explanation is emitted, EVERY numeric
claim in it must match a value actually returned by one of the three data sources this run. An
invented number in a government report is the system's worst failure mode.

R601 is the first half: `extract_numbers` pulls every numeric literal out of a draft so each can
later be checked against the legitimate set (R602) by the guardrail decision (R603). You cannot
verify a number you did not extract — so extraction must be thorough across the shapes a narrative
uses: plain ints/decimals, percentages, unit-suffixed values, thousands-separated counts, negative
and leading-dot decimals.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from agents.risk_reasoning.assessment import ContributingFactor
from agents.risk_reasoning.tools.calculation_results import AnalysisResultRow
from agents.risk_reasoning.tools.engineering_standard import EngineeringStandard

# A numeric literal, trying each shape left-to-right at every position:
#   1,250 / 1,250.5  thousands-grouped (comma + exactly 3 digits, so "90, 30" is NOT one number)
#   3.14             decimal with leading digits
#   .84              decimal without a leading zero
#   72               integer
_NUMBER_RE = re.compile(
    r"-?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\.\d+|\d+)"
)


@dataclass(frozen=True, slots=True)
class NumberToken:
    """One number found in a draft: its parsed `value` (for tolerance comparison, R603) and the
    `raw` token as it appeared (for naming the offending number in a tripwire message)."""

    value: float
    raw: str


def extract_numbers(text: str) -> tuple[NumberToken, ...]:
    """Pull every numeric literal from a draft explanation (FR-7). Pure; never raises.

    Thousands separators are stripped for the value (`1,250` -> 1250.0); a trailing `%` is kept in
    `raw` (so a tripwire can echo "84%") but does not change the value. A draft with no numbers
    yields an empty tuple.
    """
    tokens: list[NumberToken] = []
    for m in _NUMBER_RE.finditer(text):
        token = m.group(0)
        value = float(token.replace(",", ""))
        raw = token
        # Keep a trailing percent sign in the raw token for a clearer tripwire message.
        tail = text[m.end():m.end() + 1]
        if tail == "%":
            raw = token + "%"
        tokens.append(NumberToken(value=value, raw=raw))
    return tuple(tokens)


def _numbers_in(payload: Any) -> list[float]:
    """Recursively collect every finite number in a result payload (scalars, lists, dict values).

    SA result payloads vary in shape (an RMS scalar, FFT top-N peaks as [freq, amp] pairs, a
    threshold's value/limit/ratio), so we walk the structure rather than assume a flat dict.
    """
    out: list[float] = []
    if isinstance(payload, bool):
        return out  # bools are ints in Python; a pass/fail flag is not a cited number
    if isinstance(payload, (int, float)):
        out.append(float(payload))
    elif isinstance(payload, dict):
        for v in payload.values():
            out.extend(_numbers_in(v))
    elif isinstance(payload, (list, tuple)):
        for v in payload:
            out.extend(_numbers_in(v))
    return out


@dataclass(frozen=True, slots=True)
class LegitimateSet:
    """The numbers an explanation is ALLOWED to cite (FR-7).

    Membership is tolerant: `contains(n)` is True when some legitimate value is within `tolerance`
    of `n`, so a rounded "48.0" matches a real 48.004 but a fabricated number matches nothing.
    """

    values: tuple[float, ...]
    tolerance: float

    def contains(self, n: float) -> bool:
        return any(abs(n - v) <= self.tolerance for v in self.values)


def build_legitimate_set(
    ran_results: list[AnalysisResultRow],
    score: int | float | None,
    factors: list[ContributingFactor],
    standard: EngineeringStandard | None,
    tolerance: float,
) -> LegitimateSet:
    """Assemble the numbers the explanation may cite (FR-7). Pure.

    Sources: every number in each RAN result's payload; the deterministic score (in the set by
    construction — R302 computed it); each factor's value/limit/ratio/weight/contribution; and the
    pinned standard's limits. A number outside this set (within tolerance) is unverifiable and
    tripwires the guardrail (R603).
    """
    values: list[float] = []

    if score is not None:
        values.append(float(score))

    for r in ran_results:
        values.extend(_numbers_in(r.result))

    for f in factors:
        values.extend((f.value, f.limit, f.ratio, f.weight, f.contribution))

    if standard is not None and standard.available:
        values.extend(_numbers_in(standard.limits))

    return LegitimateSet(values=tuple(values), tolerance=tolerance)


@dataclass(frozen=True, slots=True)
class GuardrailResult:
    """The guardrail verdict on one draft (FR-7).

    `passed` True -> every cited number traces to a real input; the draft may be emitted.
    `passed` False -> `offending` names each number that matched no input (within tolerance), so a
    tripwire message / audit row can echo exactly what failed. The control flow around this
    (regenerate once, then fail closed) is R603's caller, R703/R604.
    """

    passed: bool
    offending: tuple[NumberToken, ...]


def provenance_guardrail(draft: str, legitimate: LegitimateSet) -> GuardrailResult:
    """Verify every numeric claim in a draft traces to a real input (FR-7, AC-7). Pure.

    Extracts every number (R601) and checks each against the legitimate set (R602) under its
    configured tolerance. Any number that matches nothing is an untraceable claim -> tripwire. A
    draft with no numbers passes vacuously (there is nothing unverifiable to emit).
    """
    offending = tuple(
        tok for tok in extract_numbers(draft) if not legitimate.contains(tok.value)
    )
    return GuardrailResult(passed=not offending, offending=offending)


# The number of REGENERATIONS allowed after the first draft before failing closed. One, per
# mandate #2 / FR-7: "regenerate the explanation once; if it still cites an untraceable number,
# fail closed." Bounded — never an unbounded retry loop.
MAX_REGENERATIONS: int = 1


@dataclass(frozen=True, slots=True)
class GuardrailLoopResult:
    """Outcome of the regenerate-once-then-fail-closed loop (FR-7).

    `emitted` True -> `draft` passed the guardrail and may be emitted.
    `failed_closed` True -> every attempt (initial + one regeneration) tripwired; `draft` is None
    (the untraceable text is NEVER emitted) and `offending` names the last failure's numbers, so
    the caller (R703) can write a withheld PENDING_HUMAN_REVIEW assessment + a RISK_GUARDRAIL_FAIL
    audit row. `attempts` counts drafts generated (1 = clean first try; 2 = one regeneration).
    """

    emitted: bool
    failed_closed: bool
    draft: str | None
    attempts: int
    offending: tuple[NumberToken, ...]


def run_guardrail_loop(
    generate: Callable[[int], str],
    legitimate: LegitimateSet,
) -> GuardrailLoopResult:
    """Draft -> check -> (regenerate once) -> emit or fail closed (FR-7, mandate #2).

    `generate(attempt)` returns the draft for a 0-based attempt index; the loop calls it for the
    initial draft (0) and, on a tripwire, exactly once more (1). If the regenerated draft still
    tripwires, the loop fails closed WITHOUT emitting the untraceable text — the caller turns that
    into a withheld PENDING_HUMAN_REVIEW assessment. The retry is hard-bounded by
    MAX_REGENERATIONS; it never loops unboundedly.
    """
    last_offending: tuple[NumberToken, ...] = ()
    for attempt in range(MAX_REGENERATIONS + 1):  # attempt 0, then at most 1 regeneration
        draft = generate(attempt)
        verdict = provenance_guardrail(draft, legitimate)
        if verdict.passed:
            return GuardrailLoopResult(
                emitted=True, failed_closed=False, draft=draft,
                attempts=attempt + 1, offending=(),
            )
        last_offending = verdict.offending

    return GuardrailLoopResult(
        emitted=False, failed_closed=True, draft=None,
        attempts=MAX_REGENERATIONS + 1, offending=last_offending,
    )
