"""Structural Analysis Agent (Agent 002) — the calculation layer.

Deterministic service (plan Option A, no model loop): consumes the Data Collection
Agent's validated readings and runs engineering calculations (RMS, FFT, deflection /
scalar threshold) when configured trigger conditions are met. Emits one structured
result per (sensor, calculation, block) with a closed outcome vocabulary, never a
danger verdict (that is the Risk Reasoning Agent's job).
"""
