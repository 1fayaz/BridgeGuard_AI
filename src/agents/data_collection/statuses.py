"""Shared status vocabulary for the Data Collection Agent.

These mirror the Postgres enums in db/migrations (0002, 0003) so the Python logic and
the schema speak the same language. Three INDEPENDENT axes (see CLAUDE.md / spec):

  * SensorHealth   — is the DEVICE reporting?      (this is sensor_status, owned by liveness)
  * ReadingStatus  — is the VALUE trustworthy?     (validated_readings.status)
  * clock_drift    — is the TIMING trustworthy?    (a bool flag, NOT an enum value)

The clock_drift flag is deliberately absent here: it co-exists with any status, so it
is a boolean on the result, never a member of either enum (decision G4).
"""
from __future__ import annotations

from enum import Enum


class SensorHealth(str, Enum):
    """Device-health axis. Mirrors the sensor_health SQL enum (0003)."""

    LIVE = "LIVE"
    OFFLINE = "OFFLINE"


class ReadingStatus(str, Enum):
    """Value/timeline axis. Mirrors the reading_status SQL enum (0002)."""

    OK = "OK"
    INTERPOLATED = "INTERPOLATED"
    SPIKE = "SPIKE"
    CORRUPT = "CORRUPT"
    NO_DATA = "NO_DATA"
    PENDING = "PENDING"
