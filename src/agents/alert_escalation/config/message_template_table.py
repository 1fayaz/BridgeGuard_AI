"""Severity->message template lookup (A102) — configuration, not code.

The alert copies the Risk Agent's verdict VERBATIM (FR-1 notify-not-re-judge). The only text in an
alert that is not copied from the upstream row is a fixed per-band message template — the wrapper
that frames the verbatim verdict (score / severity / recommendation / explanation) for a human.
This is a pure dictionary lookup — no model, no generated prose — so alerts stay deterministic and
reproducible.

Discipline (same as the Report HeadlineTable / the Risk ScoreConfig): an unconfigured band returns
a loudly-flagged sentinel, never a plausible-looking phrase. We do NOT invent alert wording for a
safety-critical notification; a comms/ops owner supplies each template.

The template is a format string referencing verdict fields (e.g. {bridge_id}, {risk_score},
{recommendation}, {explanation}); the assembler (A501) fills it by COPYING those values verbatim,
never by recomputing or rewording them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from agents.risk_reasoning.statuses import Severity

# Sentinel returned for any band whose template a human has not supplied. A visible, non-plausible
# marker — never mistaken for real alert wording.
TODO_TEMPLATE: Final[str] = "TODO-UNSET-TEMPLATE"


@dataclass(frozen=True, slots=True)
class MessageTemplateTable:
    """Immutable severity->message template table for the alert body.

    `templates` maps each severity band to its fixed message template. Anything unset resolves to
    TODO_TEMPLATE.
    """

    # (severity, template) pairs. Empty until a human supplies the wording.
    templates: tuple[tuple[Severity, str], ...] = ()

    # ------------------------------------------------------------------ lookup ---
    def template_for(self, severity: Severity) -> str:
        """Return the configured template for a band, or TODO_TEMPLATE if unset.

        Pure lookup: the same severity always yields the same template, and an unconfigured band is
        never guessed.
        """
        for sev, template in self.templates:
            if sev == severity:
                return template
        return TODO_TEMPLATE

    # ------------------------------------------------------------------ helpers ---
    @property
    def is_fully_configured(self) -> bool:
        """True only when every severity band has a supplied template."""
        configured = {sev for sev, _ in self.templates}
        if any(self.template_for(sev) == TODO_TEMPLATE for sev in Severity):
            return False
        return configured == set(Severity)
