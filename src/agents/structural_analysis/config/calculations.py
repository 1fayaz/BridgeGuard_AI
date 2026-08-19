"""The closed set of calculation kinds (S102).

v1 ACTIVE calcs are wired into the pipeline. The three DEFERRED kinds are declared
here so the vocabulary is complete and stable, but they are deliberately NOT mapped to
any sensor type in v1 (FR-10 fatigue, FR-11 modal, crack-rate) — a build that emits one
of them fails its acceptance. Declaring-but-not-wiring keeps the enum a closed set the
schema (S203) and results (S701) can rely on, the same way the DCA's reading_status is a
fixed enum.
"""
from __future__ import annotations

from enum import Enum


class Calculation(str, Enum):
    """Every calculation this agent can name. Mirrors the analysis_results SQL enum (S203)."""

    # --- v1 active ---
    RMS = "RMS"                          # per-block vibration severity (FR-5)
    FFT = "FFT"                          # per-block frequency spectrum, top-N peaks (FR-6)
    DEFLECTION_LIMIT = "DEFLECTION_LIMIT"  # displacement vs L/800 (FR-9)
    THRESHOLD = "THRESHOLD"              # generic scalar value vs design limit (FR-9)

    # --- v1 DEFERRED (declared, NOT mapped to any type — must emit nothing in v1) ---
    FATIGUE = "FATIGUE"                  # Miner's Rule, needs cumulative state + S-N curve (FR-10)
    MODAL = "MODAL"                      # natural-frequency, needs geometry/k/m (FR-11)
    CRACK_RATE = "CRACK_RATE"            # crack-growth trend, deferred (FR-9 note)


# The calcs that v1 may actually run. Anything outside this set must not be emitted.
ACTIVE_CALCULATIONS: frozenset[Calculation] = frozenset(
    {
        Calculation.RMS,
        Calculation.FFT,
        Calculation.DEFLECTION_LIMIT,
        Calculation.THRESHOLD,
    }
)

# Declared but intentionally unbuilt in v1 (FR-10 / FR-11 / crack-rate).
DEFERRED_CALCULATIONS: frozenset[Calculation] = frozenset(
    {
        Calculation.FATIGUE,
        Calculation.MODAL,
        Calculation.CRACK_RATE,
    }
)
