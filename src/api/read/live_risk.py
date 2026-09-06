"""Live risk projection — a derived view over a bridge's most recent raw readings.

This is a deliberate demo extension beside P501: the overview reads only audited
`risk_assessments` (the Risk Agent's verdict), while this projection computes a score
on the fly from the newest `raw_readings` rows so the dashboard reacts within seconds
of a gateway sending data, instead of waiting for the agent cycle. Every number is
derived from real raw rows (Constitution II traceability); what it does not have is an
audited assessment row behind it — that remains the pipeline's job.

Scoring calibration (matches the dashboard's severity bands):

    avg_rms < 0.5  -> score = int(avg_rms * 40)
    avg_rms >= 0.5 -> score = min(100, int(avg_rms * 30))
    >= 81 CRITICAL / >= 61 WARNING / >= 31 WATCH / else SAFE

The formula is piecewise by design: the safe band amplifies small movements (0.4 -> 16)
while the elevated band saturates toward 100, so a danger-mode simulator run at
RMS ~2.8 lands in CRITICAL, not WARNING.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Final, Mapping, Sequence

from pydantic import BaseModel, ConfigDict

# How many newest readings feed the average. Small enough to react in one simulator
# cycle, large enough that a single noisy sample cannot swing the band.
READINGS_WINDOW: Final = 10

_SEVERITY_BANDS: Final = ((81, "CRITICAL"), (61, "WARNING"), (31, "WATCH"))
_DEFAULT_SEVERITY: Final = "SAFE"

EXPLANATIONS: Final[dict[str, str]] = {
    "SAFE": (
        "Vibration RMS is stable and within safe limits. No structural anomalies "
        "detected in the most recent readings."
    ),
    "WATCH": (
        "Minor vibration elevation above the normal baseline. Pattern is being "
        "monitored; no immediate action required."
    ),
    "WARNING": (
        "Repeated peak vibration exceeds the warning threshold. Manual inspection "
        "within 48 hours is recommended."
    ),
    "CRITICAL": (
        "Sustained high-amplitude vibration detected. Immediate engineering review "
        "and potential load restriction advised."
    ),
}

NO_DATA_EXPLANATION: Final = (
    "No sensor data yet. Awaiting first reading from bridge."
)


class LiveRisk(BaseModel):
    """One bridge's computed risk from live readings, plus the inputs it came from.

    `avg_rms`, `sample_count`, and `last_reading_at` expose the derivation so a
    dashboard can show the WHY next to the score rather than trusting a bare number.
    """

    model_config = ConfigDict(extra="forbid")

    bridge_id: str
    risk_score: int
    severity: str
    explanation: str
    review_status: str
    assessed_at: datetime
    last_reading_at: datetime | None
    sample_count: int
    avg_rms: float | None


class SensorReading(BaseModel):
    """One raw accelerometer reading as the dashboard chart consumes it."""

    model_config = ConfigDict(extra="forbid")

    sensor_time: datetime
    value: float


def _score_for(avg_rms: float) -> int:
    if avg_rms < 0.5:
        return int(avg_rms * 40)
    return min(100, int(avg_rms * 30))


def _severity_for(score: int) -> str:
    for threshold, severity in _SEVERITY_BANDS:
        if score >= threshold:
            return severity
    return _DEFAULT_SEVERITY


def _latest_reading_time(rows: Sequence[Mapping[str, object]]) -> datetime | None:
    times = [row["sensor_time"] for row in rows if row.get("sensor_time") is not None]
    if not times:
        return None
    return max(times)  # type: ignore[arg-type, return-value]


def compute_live_risk(bridge_id: str, rows: Sequence[Mapping[str, object]]) -> LiveRisk:
    """Project the newest readings for one bridge onto a LiveRisk verdict.

    `rows` are the bridge's newest accelerometer readings (any order; the projection
    does not trust the caller's sort). With no readings at all the verdict is score 0 /
    SAFE with the explicit awaiting-data explanation — an honest "not known", never a
    fabricated 0 that reads the same as a measured 0.
    """
    values = [float(row["value"]) for row in rows if row.get("value") is not None]

    if not values:
        return LiveRisk(
            bridge_id=bridge_id,
            risk_score=0,
            severity=_DEFAULT_SEVERITY,
            explanation=NO_DATA_EXPLANATION,
            review_status="FINAL",
            assessed_at=datetime.now(UTC),
            last_reading_at=None,
            sample_count=0,
            avg_rms=None,
        )

    avg_rms = sum(values) / len(values)
    score = _score_for(avg_rms)
    severity = _severity_for(score)

    return LiveRisk(
        bridge_id=bridge_id,
        risk_score=score,
        severity=severity,
        explanation=EXPLANATIONS[severity],
        review_status="FINAL",
        assessed_at=datetime.now(UTC),
        last_reading_at=_latest_reading_time(rows),
        sample_count=len(values),
        avg_rms=round(avg_rms, 3),
    )
