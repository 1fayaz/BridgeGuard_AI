"""G102 — HeadlineTable (severity->headline lookup, FR-2 headline half).

The report's exec summary copies the risk explanation VERBATIM (FR-2). The ONLY non-copied text
in the whole document is a fixed severity->headline phrase — a pure config lookup, no model, no
computed sentence.

Acceptance (tasks.md G102): every band maps to exactly its configured phrase (or a flagged TODO
sentinel while unset); the same severity always yields the same headline (deterministic); no
model/computation is involved (pure dict lookup); an unknown/absent severity is not guessed;
withheld (no severity) returns a distinct withheld-headline sentinel. We do NOT invent a headline
phrase for a government safety report.
"""
from __future__ import annotations

from agents.report_generation.config.headline_table import (
    TODO_HEADLINE,
    HeadlineTable,
)
from agents.risk_reasoning.statuses import Severity


def test_unset_table_returns_todo_sentinel_for_every_band():
    # Empty table: every band's headline is the clearly-unset sentinel, never a plausible phrase.
    t = HeadlineTable()
    for sev in Severity:
        assert t.headline_for(sev) == TODO_HEADLINE


def test_unset_table_is_not_fully_configured():
    t = HeadlineTable()
    assert t.is_fully_configured is False


def test_each_band_maps_to_exactly_its_configured_phrase():
    t = HeadlineTable(
        phrases=(
            (Severity.SAFE, "Structure operating within normal parameters."),
            (Severity.WATCH, "Minor anomalies observed; continued monitoring advised."),
            (Severity.WARNING, "Elevated readings; engineering review recommended."),
            (Severity.CRITICAL, "Severe indicators; immediate engineering attention required."),
        ),
        withheld_phrase="Score withheld pending human review.",
    )
    assert t.headline_for(Severity.SAFE) == "Structure operating within normal parameters."
    assert t.headline_for(Severity.WATCH) == "Minor anomalies observed; continued monitoring advised."
    assert t.headline_for(Severity.WARNING) == "Elevated readings; engineering review recommended."
    assert t.headline_for(Severity.CRITICAL) == "Severe indicators; immediate engineering attention required."


def test_lookup_is_deterministic():
    # Same severity -> same headline on repeated calls (no model, no randomness).
    t = HeadlineTable(phrases=((Severity.WARNING, "Elevated readings."),))
    assert t.headline_for(Severity.WARNING) == t.headline_for(Severity.WARNING) == "Elevated readings."


def test_headline_changes_only_with_config_not_data():
    # The headline depends ONLY on the configured table, not on any score/data value.
    a = HeadlineTable(phrases=((Severity.SAFE, "All clear."),))
    b = HeadlineTable(phrases=((Severity.SAFE, "Nominal."),))
    assert a.headline_for(Severity.SAFE) == "All clear."
    assert b.headline_for(Severity.SAFE) == "Nominal."


def test_partially_configured_band_falls_back_to_sentinel_not_a_guess():
    # Only SAFE configured; the other bands must return the TODO sentinel, never an invented phrase.
    t = HeadlineTable(phrases=((Severity.SAFE, "All clear."),))
    assert t.headline_for(Severity.SAFE) == "All clear."
    assert t.headline_for(Severity.CRITICAL) == TODO_HEADLINE
    assert t.is_fully_configured is False


def test_withheld_headline_is_distinct_and_todo_by_default():
    # A score-withheld report has no severity; its headline is a distinct sentinel until supplied.
    t = HeadlineTable()
    assert t.withheld_headline() == TODO_HEADLINE
    configured = HeadlineTable(
        phrases=tuple((s, f"phrase-{s.value}") for s in Severity),
        withheld_phrase="Score withheld pending human review.",
    )
    assert configured.withheld_headline() == "Score withheld pending human review."
    # withheld is not conflated with any band headline
    assert configured.withheld_headline() != configured.headline_for(Severity.CRITICAL)


def test_fully_supplied_table_is_fully_configured():
    t = HeadlineTable(
        phrases=tuple((s, f"phrase-{s.value}") for s in Severity),
        withheld_phrase="Score withheld pending human review.",
    )
    assert t.is_fully_configured is True
