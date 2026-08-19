"""Per-sensor-type ANALYSIS profiles (S101) — configuration, not code.

An AnalysisProfile carries every constant this agent's calculations need for one sensor
type: which calcs are mapped to the type, the block sampling parameters (for FFT/RMS),
the data-quality floors, the RMS-baseline/trigger constants, the FFT output shape, and
the scalar design limit / reference zero. Adding analysis for a new type, or re-mapping
an existing calc to it, is a config edit — never a change to calculation logic.

Discipline (same as the DCA's SensorProfile): every PHYSICAL / SAFETY constant is a
`TODO`/`NaN` sentinel until a structural engineer supplies it. We do NOT invent bounds,
floors, margins, or limits for a safety-critical system — an unset value is loudly
flagged (`is_fully_configured`) rather than silently defaulted to a plausible number.
Only NON-physical defaults are concrete here: the calc list (behaviour mapping) and the
clock-drift policy (run-but-flag, spec FR-14).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from agents.structural_analysis.config.calculations import Calculation

# Sentinel marking a value a structural engineer must still supply. Not 0/None: those
# are plausible real values and would hide an unset field (same choice as the DCA).
TODO: Final[float] = float("nan")


def _is_todo(value: float) -> bool:
    return value != value  # NaN is the only value not equal to itself


@dataclass(frozen=True, slots=True)
class AnalysisProfile:
    """Immutable analysis profile for one sensor type.

    `calcs` is the behaviour mapping (which calculations apply to this type) and is the
    one field that is meant to be set concretely. Everything numeric below is a per-type
    physical/safety constant and stays TODO until an engineer supplies it.
    """

    sensor_type: str
    # Behaviour mapping — which calculations run for this type (S102 seeds these).
    calcs: tuple[Calculation, ...] = ()

    # --- Block sampling (block sensors only; FFT/RMS need these) ---
    sample_rate_hz: float = TODO       # samples per second within a block (FR-2)
    block_len_n: float = TODO          # declared samples per block (FR-2/FR-4.1)

    # --- Data-quality floors (FR-4) ---
    block_completeness_floor: float = TODO   # min usable fraction of a block (FR-4.1)
    window_min_blocks: float = TODO          # min usable blocks for a baseline (FR-4.2)

    # --- RMS baseline + trigger (FR-6/FR-7) ---
    rms_k_sigma: float = TODO          # change margin in sigmas (FR-6)
    rms_sigma_floor: float = TODO      # min sigma for a usable baseline (FR-7)
    rms_ceiling: float = TODO          # fixed engineer-set absolute ceiling (FR-6)
    baseline_window_n: float = TODO    # max OK-blocks in the baseline window (FR-7)
    baseline_window_age_h: float = TODO  # max age of baseline blocks, hours (FR-7)

    # --- FFT output shape (FR-6) ---
    fft_top_n: float = TODO            # number of dominant peaks to emit (FR-6)
    fft_peak_prominence: float = TODO  # min prominence for a reported peak (FR-6)

    # --- Scalar threshold check (FR-9) ---
    design_limit: float = TODO         # absolute limit the value is checked against (FR-9)
    limit_basis: str = "TODO"          # human label, e.g. "L/800 live" (FR-9)
    reference_zero: float = TODO       # displacement datum: delta = value - this (FR-9)

    # --- Timing policy (FR-14): co-existing flag, run-but-flag in v1 (non-physical default) ---
    clock_drift_policy: str = "run-but-flag"

    # ------------------------------------------------------------------ helpers ---
    @property
    def is_block_sensor(self) -> bool:
        """True if this type runs block calculations (RMS/FFT) and so needs sampling config."""
        return Calculation.RMS in self.calcs or Calculation.FFT in self.calcs

    @property
    def runs_threshold(self) -> bool:
        """True if a scalar design-limit / deflection check is mapped to this type."""
        return (
            Calculation.THRESHOLD in self.calcs
            or Calculation.DEFLECTION_LIMIT in self.calcs
        )

    @property
    def block_config_is_todo(self) -> bool:
        """True if any block-sampling / floor / baseline / FFT constant is still unset."""
        return any(
            _is_todo(v)
            for v in (
                self.sample_rate_hz,
                self.block_len_n,
                self.block_completeness_floor,
                self.window_min_blocks,
                self.rms_k_sigma,
                self.rms_sigma_floor,
                self.rms_ceiling,
                self.baseline_window_n,
                self.baseline_window_age_h,
                self.fft_top_n,
                self.fft_peak_prominence,
            )
        )

    @property
    def threshold_config_is_todo(self) -> bool:
        """True if the design limit is unset (a mapped-but-unconfigured limit -> FR-9 skip)."""
        return _is_todo(self.design_limit)

    @property
    def reference_zero_is_todo(self) -> bool:
        """True if a displacement reference zero is unset (FR-9 NO_REFERENCE)."""
        return _is_todo(self.reference_zero)

    @property
    def is_fully_configured(self) -> bool:
        """True only when every constant THIS type's mapped calcs need is supplied.

        A type that runs only a scalar threshold needs the limit (and, for deflection, a
        reference zero) but NOT block-sampling config; a block sensor needs the block
        config. We only require what the mapped calcs actually use, so a fully-set
        displacement profile isn't held back for lacking FFT constants it never uses.
        """
        if not self.calcs:
            return True  # nothing mapped -> nothing to configure (NO_CALC type)
        if self.is_block_sensor and self.block_config_is_todo:
            return False
        if self.runs_threshold and self.threshold_config_is_todo:
            return False
        if Calculation.DEFLECTION_LIMIT in self.calcs and self.reference_zero_is_todo:
            return False
        return True
