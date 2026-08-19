"""G101 — ReportConfig shape (config-level acceptance).

Acceptance (tasks.md G101): constructs; the non-physical audit field `report_template_version`
is concrete; `fidelity_tolerance` defaults to 0.0 (exact-match — the fail-safe, a real safe
default, not a TODO); `appendix_max_rows` and the template/letterhead references are clearly
flagged TODO sentinels a reviewer can see are unset; `is_fully_configured` is False while any is
unset. We do NOT guess a raw-data depth bound or a letterhead for a government artifact.

Mirrors the Risk ScoreConfig discipline: an unset value is loudly flagged, never silently
defaulted to a plausible number. The one difference: `fidelity_tolerance`'s 0.0 default is the
*safe* value (exact match), so it does not gate `is_fully_configured`.
"""
from __future__ import annotations

import math

from agents.report_generation.config.report_config import ReportConfig


def test_constructs_with_concrete_template_version_only():
    # Constructible from just the audit version; presentation/bound fields default to TODO.
    c = ReportConfig(report_template_version="v0-unset")
    assert c.report_template_version == "v0-unset"


def test_template_version_is_concrete_not_a_sentinel():
    # Stamps WHICH template a report used (non-physical audit field); always present, never NaN.
    c = ReportConfig(report_template_version="2026-06-gov-template-rev2")
    assert isinstance(c.report_template_version, str)
    assert c.report_template_version  # non-empty


def test_fidelity_tolerance_defaults_to_exact_match():
    # 0.0 is the fail-safe: every printed number must equal a source value. This is a real safe
    # default (not a TODO) — the strictest possible anti-drift setting.
    c = ReportConfig(report_template_version="v0-unset")
    assert c.fidelity_tolerance == 0.0


def test_appendix_bound_and_template_refs_are_todo_sentinels_by_default():
    # The raw-data depth bound and the letterhead/template refs must be SEEN as unset, not guessed.
    c = ReportConfig(report_template_version="v0-unset")
    assert math.isnan(c.appendix_max_rows), "appendix bound was given a non-TODO default"
    assert c.letterhead_ref is None
    assert c.template_ref is None


def test_unconfigured_is_not_fully_configured():
    c = ReportConfig(report_template_version="v0-unset")
    assert c.appendix_bound_is_todo is True
    assert c.template_refs_are_todo is True
    assert c.is_fully_configured is False


def test_partial_config_is_still_not_fully_configured():
    # Supplying the appendix bound but leaving the template refs TODO must NOT pass.
    c = ReportConfig(
        report_template_version="rev1",
        appendix_max_rows=500,
    )
    assert c.appendix_bound_is_todo is False
    assert c.template_refs_are_todo is True
    assert c.is_fully_configured is False


def test_a_nan_tolerance_is_treated_as_unset():
    # An explicitly-NaN tolerance (engineer blanked the safe default) must not pass as configured.
    c = ReportConfig(
        report_template_version="rev1",
        fidelity_tolerance=float("nan"),
        appendix_max_rows=500,
        letterhead_ref="gov-letterhead.png",
        template_ref="report_template.html",
    )
    assert c.tolerance_is_todo is True
    assert c.is_fully_configured is False


def test_fully_supplied_config_is_fully_configured():
    # Once template refs + appendix bound are supplied (tolerance keeps its safe default), usable.
    c = ReportConfig(
        report_template_version="2026-06-gov-template-rev2",
        appendix_max_rows=500,
        letterhead_ref="gov-letterhead.png",
        template_ref="report_template.html",
    )
    assert c.appendix_bound_is_todo is False
    assert c.template_refs_are_todo is False
    assert c.tolerance_is_todo is False
    assert c.is_fully_configured is True
