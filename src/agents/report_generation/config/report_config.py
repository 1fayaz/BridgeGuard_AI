"""Report presentation configuration (G101) — configuration, not code.

A ReportConfig carries the presentation + bound constants the deterministic report assembler
needs: which template/letterhead to lay the report out with, how deep the raw-data appendix may
go, and how exactly a printed number must match its source (the fidelity tolerance). None of
these are recomputed at runtime; the assembler only reads them.

Discipline (same as the Risk ScoreConfig and the DCA's SensorProfile): a value a human must still
supply is a loudly-flagged TODO sentinel, never silently defaulted to a plausible number. We do
NOT guess a raw-data depth bound or a government letterhead. Two fields are legitimately concrete:
`report_template_version` (a non-physical audit stamp — WHICH template a report used, for
reproducibility) and `fidelity_tolerance`, whose 0.0 default is the *safe* value (exact match —
the strictest anti-drift setting), so it does not gate `is_fully_configured`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

# Sentinel marking a value a human must still supply. Not 0/None-for-numbers: those are plausible
# real values and would hide an unset field (same choice as the Risk / DCA / SA configs).
TODO: Final[float] = float("nan")


def _is_todo(value: float) -> bool:
    return value != value  # NaN is the only value not equal to itself


@dataclass(frozen=True, slots=True)
class ReportConfig:
    """Immutable presentation/bound configuration for an assembled report.

    `report_template_version` is the one always-present field (an audit stamp, not a safety
    number). `fidelity_tolerance` keeps a safe 0.0 default. The appendix bound and the
    template/letterhead references stay TODO until a human supplies them.
    """

    # Audit stamp — WHICH template this config represents (non-physical; always present).
    report_template_version: str

    # --- Fidelity gate tolerance (FR-5): how far a printed number may differ from its source.
    #     0.0 = exact match, the fail-safe. This is a real safe default, NOT a TODO — the
    #     strictest anti-drift setting — so it does not gate is_fully_configured. ---
    fidelity_tolerance: float = 0.0

    # --- Appendix raw-data depth bound (FR-6 / research §5): max raw rows the appendix prints,
    #     so a giant appendix cannot exhaust memory. Unset until a human decides the bound. ---
    appendix_max_rows: float = TODO

    # --- Template / letterhead references (presentation): the report layout + government
    #     letterhead. Unset (None) until supplied — we do not guess a gov artifact's chrome. ---
    letterhead_ref: str | None = None
    template_ref: str | None = None

    # ------------------------------------------------------------------ helpers ---
    @property
    def tolerance_is_todo(self) -> bool:
        """True if the fidelity tolerance was blanked to NaN (safe default removed)."""
        return _is_todo(self.fidelity_tolerance)

    @property
    def appendix_bound_is_todo(self) -> bool:
        """True if the raw-data depth bound is unset."""
        return _is_todo(self.appendix_max_rows)

    @property
    def template_refs_are_todo(self) -> bool:
        """True if either the template or the letterhead reference is unset."""
        return self.letterhead_ref is None or self.template_ref is None

    @property
    def is_fully_configured(self) -> bool:
        """True only when every value a human must supply is set.

        The audit version alone is never enough: the template refs and the appendix bound must be
        set, and the fidelity tolerance must not have been blanked from its safe default.
        """
        return not (
            self.template_refs_are_todo
            or self.appendix_bound_is_todo
            or self.tolerance_is_todo
        )
