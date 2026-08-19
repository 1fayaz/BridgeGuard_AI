"""P402 — the closed set of per-reading rejection reasons.

An enum rather than a string, because a gateway author has to branch on these. A free-text
reason means every rejection is a new string the Pi's firmware has never seen, so the only
robust gateway behaviour left is "log it and drop the reading" — which is exactly the silent
data loss the per-reading contract exists to prevent.

Being closed also constrains us: a new rejection cause cannot be invented at a call site
under deadline. It has to be added here, which is where a reader looks to find out what can
go wrong, and where the documented-for-gateway-authors table lives.

Each reason is phrased as *what the gateway can do about it*, since that is the only reason
to tell a machine why something failed.
"""
from __future__ import annotations

from enum import Enum
from typing import Final


class RejectionReason(str, Enum):
    """Why one reading was not appended. The complete set — there is no 'other'."""

    MISSING_FIELD = "missing_field"
    NON_NUMERIC_VALUE = "non_numeric_value"
    MALFORMED_TIMESTAMP = "malformed_timestamp"
    UNKNOWN_SENSOR = "unknown_sensor"
    SENSOR_NOT_ON_THIS_BRIDGE = "sensor_not_on_this_bridge"
    UNIT_MISMATCH = "unit_mismatch"


# Gateway-facing documentation, kept next to the enum so the two cannot drift. Every member
# must appear here (asserted structurally in the P402 tests).
REASON_GUIDANCE: Final[dict[RejectionReason, str]] = {
    RejectionReason.MISSING_FIELD: (
        "A required field was absent or blank. Fix the payload; retrying unchanged will "
        "fail identically."
    ),
    RejectionReason.NON_NUMERIC_VALUE: (
        "The value was absent, non-numeric, or not finite. A sensor reporting NaN is a "
        "device fault, not a transient one — retrying unchanged will fail identically."
    ),
    RejectionReason.MALFORMED_TIMESTAMP: (
        "sensor_time was absent or unparseable. Send an ISO-8601 timestamp; a reading "
        "with no trustworthy time cannot be placed in a series."
    ),
    RejectionReason.UNKNOWN_SENSOR: (
        "No sensor with this id is registered. An operator must provision the sensor "
        "before its readings can be stored."
    ),
    RejectionReason.SENSOR_NOT_ON_THIS_BRIDGE: (
        "The sensor exists but belongs to a different bridge than this gateway's key. "
        "Do not re-send under another key; the reading was not re-attributed."
    ),
    RejectionReason.UNIT_MISMATCH: (
        "The unit does not match the unit registered for this sensor. Sending a value in "
        "the wrong unit would corrupt the series, so it is refused rather than converted."
    ),
}
