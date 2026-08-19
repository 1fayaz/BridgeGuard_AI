"""Severity->headline lookup (G102) — configuration, not code.

The report copies the Risk Agent's explanation VERBATIM (FR-2). The ONLY sentence in the whole
document that is not copied from an upstream row is a fixed exec-summary headline chosen by the
assessment's severity band. This is a pure dictionary lookup — no model, no computed phrase — so
the report stays deterministic and reproducible.

Discipline (same as ReportConfig / the Risk ScoreConfig): an unconfigured band returns a loudly
flagged sentinel, never a plausible-looking phrase. We do NOT invent headline wording for a
government safety report; a structural/comms owner supplies each phrase.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from agents.risk_reasoning.statuses import Severity

# Sentinel returned for any band (or the withheld case) whose phrase a human has not supplied.
# A visible, non-plausible marker — never mistaken for real report wording.
TODO_HEADLINE: Final[str] = "TODO-UNSET-HEADLINE"


@dataclass(frozen=True, slots=True)
class HeadlineTable:
    """Immutable severity->headline phrase table for the exec-summary line.

    `phrases` maps each severity band to its fixed headline; `withheld_phrase` is the distinct
    headline used when the assessment withheld its score (no severity). Anything unset resolves to
    TODO_HEADLINE.
    """

    # (severity, headline) pairs. Empty until a human supplies the wording.
    phrases: tuple[tuple[Severity, str], ...] = ()

    # Distinct headline for a score-withheld report (no severity band). None until supplied.
    withheld_phrase: str | None = None

    # ------------------------------------------------------------------ lookup ---
    def headline_for(self, severity: Severity) -> str:
        """Return the configured headline for a band, or TODO_HEADLINE if unset.

        Pure lookup: the same severity always yields the same phrase, and an unconfigured band is
        never guessed.
        """
        for sev, phrase in self.phrases:
            if sev == severity:
                return phrase
        return TODO_HEADLINE

    def withheld_headline(self) -> str:
        """Return the withheld-report headline, or TODO_HEADLINE if unset."""
        return self.withheld_phrase if self.withheld_phrase is not None else TODO_HEADLINE

    # ------------------------------------------------------------------ helpers ---
    @property
    def is_fully_configured(self) -> bool:
        """True only when every severity band AND the withheld case have a supplied phrase."""
        configured = {sev for sev, _ in self.phrases}
        if any(self.headline_for(sev) == TODO_HEADLINE for sev in Severity):
            return False
        if configured != set(Severity):
            return False
        return self.withheld_phrase is not None
