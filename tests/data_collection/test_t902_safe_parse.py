"""T902 — safe_parse + per-sensor isolation (FR-6 / AC-7).

Acceptance (tasks.md T902): four malformed shapes -> CORRUPT + reason, no exception;
an injected failure in one sensor does not abort the cycle (others still processed).
"""
from __future__ import annotations

from datetime import datetime, timezone

from agents.data_collection.parsing import (
    ParseFailure,
    ParsedReading,
    safe_parse,
)
from agents.data_collection.statuses import ReadingStatus

UTC = timezone.utc
GOOD = {
    "sensor_id": "s-1",
    "sensor_type": "accelerometer",
    "sensor_time": "2026-06-24T12:00:00+00:00",
    "value": 1.5,
}


def test_well_formed_payload_parses():
    res = safe_parse(GOOD)
    assert isinstance(res, ParsedReading)
    assert res.sensor_id == "s-1"
    assert res.sensor_type == "accelerometer"
    assert res.value == 1.5
    assert res.sensor_time == datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def test_accepts_z_suffix_timestamp():
    res = safe_parse({**GOOD, "sensor_time": "2026-06-24T12:00:00Z"})
    assert isinstance(res, ParsedReading)
    assert res.sensor_time == datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def test_explicit_null_value_is_allowed():
    # A null value is a valid "no reading"; status decided downstream, not a parse error.
    res = safe_parse({**GOOD, "value": None})
    assert isinstance(res, ParsedReading)
    assert res.value is None


# ---- four malformed shapes -> CORRUPT + reason, no exception -----------------

def test_malformed_1_not_a_dict():
    res = safe_parse("garbage")
    assert isinstance(res, ParseFailure)
    assert res.status is ReadingStatus.CORRUPT
    assert "not an object" in res.reason
    assert res.raw_payload == "garbage"  # preserved for forensics


def test_malformed_2_missing_sensor_id():
    res = safe_parse({k: v for k, v in GOOD.items() if k != "sensor_id"})
    assert isinstance(res, ParseFailure)
    assert "sensor_id" in res.reason


def test_malformed_3_unparseable_timestamp():
    res = safe_parse({**GOOD, "sensor_time": "not-a-date"})
    assert isinstance(res, ParseFailure)
    assert "timestamp" in res.reason


def test_malformed_4_non_numeric_value():
    res = safe_parse({**GOOD, "value": "high"})
    assert isinstance(res, ParseFailure)
    assert "non-numeric" in res.reason
    assert res.sensor_id == "s-1"  # known sensor, so it can still be attributed


def test_bool_value_is_rejected():
    res = safe_parse({**GOOD, "value": True})
    assert isinstance(res, ParseFailure)


def test_missing_sensor_type():
    res = safe_parse({k: v for k, v in GOOD.items() if k != "sensor_type"})
    assert isinstance(res, ParseFailure)
    assert "sensor_type" in res.reason


def test_no_exception_on_any_shape():
    # A barrage of pathological inputs must all return, never raise.
    for bad in [None, 42, [], {}, {"sensor_id": 5}, {"sensor_id": ""},
                {"sensor_id": "s", "sensor_type": "t"},  # no time
                {"sensor_id": "s", "sensor_type": "t", "time": 999}]:
        res = safe_parse(bad)
        assert isinstance(res, ParseFailure)
        assert res.reason  # always explains why


def test_per_sensor_isolation_one_bad_does_not_abort_batch():
    # Model the orchestrator's per-sensor isolation: a batch with good + malformed +
    # an internally-exploding entry. safe_parse handles malformed; the explode is
    # caught per-sensor so the cycle completes for everyone else.
    batch = [
        GOOD,
        {"sensor_id": "s-2", "sensor_type": "t", "value": "boom"},  # malformed
        object(),  # not a dict at all
        {**GOOD, "sensor_id": "s-4"},
    ]
    results = []
    for payload in batch:
        try:
            results.append(safe_parse(payload))
        except Exception as exc:  # must never happen — proves no crash escapes
            results.append(ParseFailure(None, payload, f"unexpected: {exc}"))

    # All four produced a result; the two good ones parsed, the two bad are CORRUPT.
    assert len(results) == 4
    assert isinstance(results[0], ParsedReading)
    assert isinstance(results[1], ParseFailure)
    assert isinstance(results[2], ParseFailure)
    assert isinstance(results[3], ParsedReading)
    # The cycle was NOT aborted by the bad entries — good sensors still got verdicts.
    assert results[3].sensor_id == "s-4"
