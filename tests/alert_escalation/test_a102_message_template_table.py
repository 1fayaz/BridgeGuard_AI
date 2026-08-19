"""A102 — MessageTemplateTable (severity->message template lookup, FR-1 assembly half).

The alert copies the Risk Agent's verdict VERBATIM (FR-1 notify-not-re-judge). The only non-copied
text in an alert is a fixed per-band message template — the wrapper that frames the verbatim
verdict (score / severity / recommendation / explanation) for a human. This is a pure dictionary
lookup — no model, no generated prose — so alerts stay deterministic and reproducible.

Acceptance (tasks.md A102): every band maps to exactly its configured template (or a flagged TODO
sentinel while unset); the same severity always yields the same template (deterministic); no
model/computation is involved (pure dict lookup); an unknown/absent severity is not guessed. We do
NOT invent alert wording for a safety-critical notification.

Mirrors the Report HeadlineTable discipline: an unconfigured band returns a loudly-flagged
sentinel, never a plausible-looking phrase.
"""
from __future__ import annotations

from agents.alert_escalation.config.message_template_table import (
    TODO_TEMPLATE,
    MessageTemplateTable,
)
from agents.risk_reasoning.statuses import Severity


def test_unset_table_returns_todo_sentinel_for_every_band():
    # Empty table: every band's template is the clearly-unset sentinel, never a plausible phrase.
    t = MessageTemplateTable()
    for sev in Severity:
        assert t.template_for(sev) == TODO_TEMPLATE


def test_unset_table_is_not_fully_configured():
    t = MessageTemplateTable()
    assert t.is_fully_configured is False


def test_each_band_maps_to_exactly_its_configured_template():
    t = MessageTemplateTable(
        templates=(
            (Severity.SAFE, "Routine status for {bridge_id}: {explanation}"),
            (Severity.WATCH, "Watch on {bridge_id}: {explanation} (score {risk_score})"),
            (Severity.WARNING, "WARNING {bridge_id}: {recommendation} — {explanation}"),
            (Severity.CRITICAL, "CRITICAL {bridge_id}: {recommendation} — {explanation}"),
        ),
    )
    assert t.template_for(Severity.SAFE) == "Routine status for {bridge_id}: {explanation}"
    assert t.template_for(Severity.WATCH) == "Watch on {bridge_id}: {explanation} (score {risk_score})"
    assert t.template_for(Severity.WARNING) == "WARNING {bridge_id}: {recommendation} — {explanation}"
    assert t.template_for(Severity.CRITICAL) == "CRITICAL {bridge_id}: {recommendation} — {explanation}"


def test_lookup_is_deterministic():
    # Same severity -> same template on repeated calls (no model, no randomness).
    t = MessageTemplateTable(templates=((Severity.WARNING, "WARNING: {explanation}"),))
    assert t.template_for(Severity.WARNING) == t.template_for(Severity.WARNING) == "WARNING: {explanation}"


def test_template_changes_only_with_config_not_data():
    # The template depends ONLY on the configured table, not on any score/data value.
    a = MessageTemplateTable(templates=((Severity.SAFE, "All clear: {explanation}"),))
    b = MessageTemplateTable(templates=((Severity.SAFE, "Nominal: {explanation}"),))
    assert a.template_for(Severity.SAFE) == "All clear: {explanation}"
    assert b.template_for(Severity.SAFE) == "Nominal: {explanation}"


def test_partially_configured_band_falls_back_to_sentinel_not_a_guess():
    # Only SAFE configured; the other bands must return the TODO sentinel, never an invented phrase.
    t = MessageTemplateTable(templates=((Severity.SAFE, "All clear: {explanation}"),))
    assert t.template_for(Severity.SAFE) == "All clear: {explanation}"
    assert t.template_for(Severity.CRITICAL) == TODO_TEMPLATE
    assert t.is_fully_configured is False


def test_fully_supplied_table_is_fully_configured():
    t = MessageTemplateTable(
        templates=tuple((s, f"template-{s.value}: {{explanation}}") for s in Severity),
    )
    assert t.is_fully_configured is True
