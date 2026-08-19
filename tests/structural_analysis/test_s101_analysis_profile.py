"""S101 — AnalysisProfile shape (function-level acceptance).

Acceptance (tasks.md S101): constructs with all fields; non-physical defaults present
(clock_drift_policy='run-but-flag', a calc list); every PHYSICAL constant is a clearly-
flagged TODO/NaN sentinel a reviewer can see is unset (config-TODO decision — do NOT
invent safety-critical numbers). Adding analysis for a type = one config entry.
"""
from __future__ import annotations

import math

from agents.structural_analysis.config.analysis_profiles import AnalysisProfile
from agents.structural_analysis.config.calculations import Calculation


def test_constructs_with_only_type_and_calcs():
    # A profile is constructible from just its identity + calc mapping; every physical
    # constant defaults to the TODO sentinel (nothing invented).
    p = AnalysisProfile("accelerometer", calcs=(Calculation.RMS, Calculation.FFT))
    assert p.sensor_type == "accelerometer"
    assert p.calcs == (Calculation.RMS, Calculation.FFT)


def test_non_physical_defaults_are_concrete():
    # The two NON-physical fields are meant to be set: the calc list (behaviour mapping)
    # and the drift policy (run-but-flag, FR-14). These are NOT TODO.
    p = AnalysisProfile("displacement_lvdt", calcs=(Calculation.DEFLECTION_LIMIT,))
    assert p.clock_drift_policy == "run-but-flag"
    assert p.calcs  # mapping present


def test_every_physical_constant_is_a_todo_sentinel_by_default():
    # Every safety/physical constant must be an unset NaN sentinel by default — a reviewer
    # must be able to see they are unset, not silently defaulted to a plausible number.
    p = AnalysisProfile("accelerometer", calcs=(Calculation.RMS, Calculation.FFT))
    physical = [
        p.sample_rate_hz, p.block_len_n, p.block_completeness_floor, p.window_min_blocks,
        p.rms_k_sigma, p.rms_sigma_floor, p.rms_ceiling, p.baseline_window_n,
        p.baseline_window_age_h, p.fft_top_n, p.fft_peak_prominence,
        p.design_limit, p.reference_zero,
    ]
    assert all(math.isnan(v) for v in physical), "a physical constant was given a non-TODO default"


def test_block_sensor_with_todo_block_config_is_not_fully_configured():
    p = AnalysisProfile("accelerometer", calcs=(Calculation.RMS, Calculation.FFT))
    assert p.is_block_sensor is True
    assert p.block_config_is_todo is True
    assert p.is_fully_configured is False


def test_threshold_type_only_needs_its_limit_not_block_config():
    # A strain gauge runs only THRESHOLD; it must NOT be held back for lacking FFT/block
    # constants it never uses — only its design limit matters.
    p = AnalysisProfile("strain_gauge", calcs=(Calculation.THRESHOLD,))
    assert p.is_block_sensor is False
    assert p.runs_threshold is True
    assert p.is_fully_configured is False          # limit is TODO
    configured = AnalysisProfile("strain_gauge", calcs=(Calculation.THRESHOLD,),
                                 design_limit=500.0, limit_basis="microstrain max")
    assert configured.is_fully_configured is True  # block constants irrelevant here


def test_deflection_type_requires_reference_zero():
    # Displacement deflection needs BOTH a limit and a reference zero (delta = value - ref).
    with_limit_only = AnalysisProfile("displacement_lvdt",
                                      calcs=(Calculation.DEFLECTION_LIMIT,),
                                      design_limit=50.0, limit_basis="L/800 live")
    assert with_limit_only.reference_zero_is_todo is True
    assert with_limit_only.is_fully_configured is False
    full = AnalysisProfile("displacement_lvdt", calcs=(Calculation.DEFLECTION_LIMIT,),
                           design_limit=50.0, limit_basis="L/800 live", reference_zero=0.0)
    assert full.is_fully_configured is True


def test_unmapped_type_is_trivially_configured():
    # A type with no mapped calc (e.g. temperature, context-only) has nothing to configure.
    p = AnalysisProfile("temperature", calcs=())
    assert p.is_fully_configured is True
