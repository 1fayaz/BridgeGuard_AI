"""P401 — the ingest batch input contract: shape-check per reading, cap the batch.

Two rules pull in opposite directions here, and the split between them is the task.

**Batch-level failures reject the whole call.** An oversized batch is refused outright
with a documented status, because the alternative — accept it and process the first N — is
the one thing Principle II forbids. A gateway that gets a 200 back stops retrying. Dropping
the tail would lose sensor readings from a bridge silently, which is a data-integrity
failure wearing a success code. So the cap is enforced *before* any reading is examined,
and the refusal is explicit so the Pi knows to resend a smaller batch.

**Per-reading failures are collected, never raised.** One malformed reading must not reject
its neighbours (AC-1). A Pi is a field device with a flaky sensor or two; if a single bad
value discarded the batch, one broken sensor would blind the whole bridge. So shape-checking
returns *outcomes* — a positional result per reading — rather than throwing on the first
problem.

The shape check is deliberately shallow: `sensor_id`, `sensor_type`, `value`, `unit`,
`sensor_time` present and of the right kind. It is **not** validation. Whether a value is
physically plausible, whether a sensor is drifting, whether a reading should be interpolated
— all of that is the DCA's job on its own cycle (Principle III, plan §4). The API asks only
"can this be stored as raw data?", and the honest answer to that is structural.

Ties to tasks.md P401, spec AC-1 + §1, plan §8.
"""
from __future__ import annotations

import inspect
import math

import pytest

from api.ingest.batch import (
    MAX_SENSOR_ID_LENGTH,
    IngestBatch,
    ReadingInput,
    check_shape,
    parse_batch,
)
from api.ingest.reasons import RejectionReason
from api.status_policy import ApiError, Failure

GOOD = {
    "sensor_id": "SENSOR_1",
    "sensor_type": "strain",
    "value": 12.5,
    "unit": "microstrain",
    "sensor_time": "2026-08-03T10:00:00Z",
}


def reading(**overrides) -> dict:
    return {**GOOD, **overrides}


# ------------------------------------------------------------------ a well-formed batch ---
def test_a_well_formed_batch_parses():
    batch = parse_batch({"readings": [reading(), reading(sensor_id="SENSOR_2")]})
    assert isinstance(batch, IngestBatch)
    assert len(batch.readings) == 2


def test_the_five_contract_fields_survive_parsing():
    batch = parse_batch({"readings": [reading()]})
    r = batch.readings[0]
    assert r.sensor_id == "SENSOR_1"
    assert r.sensor_type == "strain"
    assert r.value == 12.5
    assert r.unit == "microstrain"
    assert r.sensor_time is not None


def test_a_parsed_reading_keeps_its_position():
    batch = parse_batch({"readings": [reading(sensor_id=f"S{i}") for i in range(5)]})
    assert [r.sensor_id for r in batch.readings] == ["S0", "S1", "S2", "S3", "S4"]


def test_an_integer_value_is_accepted():
    """A Pi sending 12 rather than 12.0 is not an error."""
    assert check_shape(ReadingInput(**reading(value=12))) is None


def test_a_negative_value_is_accepted():
    """Plausibility is the DCA's judgment. A tilt sensor legitimately reads negative."""
    assert check_shape(ReadingInput(**reading(value=-3.2))) is None


def test_an_empty_batch_parses_to_zero_readings():
    """Nothing to store is not an error — a Pi with no new samples is normal traffic."""
    assert parse_batch({"readings": []}).readings == []


# --------------------------------------------------- the cap rejects the batch as a whole ---
def test_an_oversized_batch_is_rejected_as_a_whole():
    """The headline batch-level rule. Truncating would lose readings behind a 200."""
    payload = {"readings": [reading() for _ in range(2001)]}
    with pytest.raises(ApiError) as exc:
        parse_batch(payload, max_readings=2000)
    assert exc.value.failure is Failure.VALIDATION


def test_the_oversize_rejection_uses_the_documented_status():
    payload = {"readings": [reading() for _ in range(11)]}
    with pytest.raises(ApiError) as exc:
        parse_batch(payload, max_readings=10)
    assert exc.value.status_code == 422


def test_a_batch_exactly_at_the_cap_is_accepted():
    """Off-by-one here silently costs a gateway one reading per batch, forever."""
    payload = {"readings": [reading() for _ in range(10)]}
    assert len(parse_batch(payload, max_readings=10).readings) == 10


def test_an_oversized_batch_is_never_truncated():
    """Principle II: backpressure rejects a retryable request; it never drops readings."""
    payload = {"readings": [reading(sensor_id=f"S{i}") for i in range(12)]}
    with pytest.raises(ApiError):
        parse_batch(payload, max_readings=10)


def test_the_cap_is_checked_before_any_reading_is_examined():
    """A hostile 50k-reading batch must cost one comparison, not 50k parses.

    Proven by making the per-reading path *observably* expensive: if the cap were checked
    after parsing, every element would be visited before the refusal. The counter stays at
    zero only if the size check comes first.
    """
    visited = []

    class Tracked(dict):
        def keys(self):  # ReadingInput(**item) has to read the keys to parse it
            visited.append(1)
            return super().keys()

    payload = {"readings": [Tracked(GOOD) for _ in range(50)]}
    with pytest.raises(ApiError) as exc:
        parse_batch(payload, max_readings=10)
    assert exc.value.failure is Failure.VALIDATION
    assert visited == [], f"{len(visited)} readings were parsed before the cap refused"


def test_the_oversize_refusal_beats_a_malformed_element():
    """Two faults, one answer: the batch is too big, which is the actionable fact.

    Reporting the broken element instead would send the gateway chasing a payload bug when
    the real instruction is 'send smaller batches'.
    """
    payload = {"readings": [GOOD] * 10 + ["not-an-object"] * 5}
    with pytest.raises(ApiError) as exc:
        parse_batch(payload, max_readings=10)
    assert "limit is 10" in exc.value.detail


def test_the_oversize_detail_names_no_internal_structure():
    payload = {"readings": [reading() for _ in range(11)]}
    with pytest.raises(ApiError) as exc:
        parse_batch(payload, max_readings=10)
    blob = exc.value.detail.lower()
    for banned in ("traceback", "pydantic", "sql", "src/", "line "):
        assert banned not in blob


def test_the_oversize_detail_tells_the_gateway_the_limit():
    """A gateway author has to be able to act on this without reading our source."""
    payload = {"readings": [reading() for _ in range(11)]}
    with pytest.raises(ApiError) as exc:
        parse_batch(payload, max_readings=10)
    assert "10" in exc.value.detail


# --------------------------------------------- malformed batch envelope (batch-level) ---
@pytest.mark.parametrize("payload", [{}, {"reading": []}, {"readings": None}])
def test_a_batch_missing_its_readings_list_is_rejected(payload):
    with pytest.raises(ApiError) as exc:
        parse_batch(payload)
    assert exc.value.status_code == 422


@pytest.mark.parametrize("payload", [{"readings": "not-a-list"}, {"readings": 5}])
def test_a_non_list_readings_field_is_rejected(payload):
    with pytest.raises(ApiError):
        parse_batch(payload)


def test_a_non_object_payload_is_rejected():
    with pytest.raises(ApiError):
        parse_batch("readings")  # type: ignore[arg-type]


def test_a_reading_that_is_not_an_object_is_a_batch_level_refusal():
    """This is a broken gateway, not a bad sample — there is no reading to report on."""
    with pytest.raises(ApiError):
        parse_batch({"readings": [reading(), "oops"]})


# ------------------------------------------- per-reading shape failures are COLLECTED ---
def test_a_missing_field_is_collected_not_raised():
    """The headline per-reading rule: no exception escapes a shape check."""
    outcome = check_shape(ReadingInput(**{k: v for k, v in GOOD.items() if k != "unit"}))
    assert outcome is RejectionReason.MISSING_FIELD


@pytest.mark.parametrize("field", ["sensor_id", "sensor_type", "unit"])
def test_a_blank_required_string_is_rejected(field: str):
    assert check_shape(ReadingInput(**reading(**{field: "   "}))) is RejectionReason.MISSING_FIELD


def test_a_missing_value_is_rejected():
    assert check_shape(ReadingInput(**reading(value=None))) is RejectionReason.NON_NUMERIC_VALUE


@pytest.mark.parametrize("bad", ["twelve", "", [], {}, True])
def test_a_non_numeric_value_is_rejected(bad):
    """A bool is not a reading. `True` would otherwise arrive as 1.0."""
    assert check_shape(ReadingInput(**reading(value=bad))) is RejectionReason.NON_NUMERIC_VALUE


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_value_is_rejected(bad: float):
    """NaN survives a numeric type check and then poisons every downstream aggregate."""
    assert check_shape(ReadingInput(**reading(value=bad))) is RejectionReason.NON_NUMERIC_VALUE


@pytest.mark.parametrize("bad", ["not-a-time", "2026-13-45", "", 12345, "tomorrow"])
def test_a_malformed_timestamp_is_rejected(bad):
    assert check_shape(ReadingInput(**reading(sensor_time=bad))) is RejectionReason.MALFORMED_TIMESTAMP


def test_a_missing_timestamp_is_rejected():
    assert check_shape(
        ReadingInput(**reading(sensor_time=None))
    ) is RejectionReason.MALFORMED_TIMESTAMP


def test_an_overlong_sensor_id_is_rejected():
    """An unbounded id is a memory and log-flood vector, not a plausible sensor name."""
    long_id = "S" * (MAX_SENSOR_ID_LENGTH + 1)
    assert check_shape(ReadingInput(**reading(sensor_id=long_id))) is RejectionReason.MISSING_FIELD


def test_check_shape_returns_none_for_a_good_reading():
    """None means 'no shape objection' — not 'valid'. See the module docstring."""
    assert check_shape(ReadingInput(**reading())) is None


def test_check_shape_never_raises_on_any_field_being_wrong():
    """One escaping exception would turn a per-reading problem into a lost batch."""
    hostile = [
        reading(sensor_id=None), reading(sensor_type=None), reading(value="x"),
        reading(unit=None), reading(sensor_time=object()), reading(value=[1, 2]),
        {"sensor_id": "S", "sensor_type": "t", "value": 1, "unit": "u", "sensor_time": None},
    ]
    for payload in hostile:
        outcome = check_shape(ReadingInput(**payload))
        assert outcome is None or isinstance(outcome, RejectionReason)


def test_every_shape_rejection_reason_is_from_the_closed_set():
    hostile = [reading(value="x"), reading(sensor_time="nope"), reading(unit="  ")]
    for payload in hostile:
        assert check_shape(ReadingInput(**payload)) in set(RejectionReason)


# ---------------------------------------------- shape-checking is NOT validation (III) ---
def test_the_shape_check_makes_no_plausibility_judgment():
    """A 900-tonne strain reading is the DCA's problem, not a shape failure."""
    assert check_shape(ReadingInput(**reading(value=9.0e8))) is None


def test_a_future_timestamp_is_not_a_shape_failure():
    """Clock skew on a field Pi is real; deciding what to do about it is the DCA's call."""
    assert check_shape(ReadingInput(**reading(sensor_time="2099-01-01T00:00:00Z"))) is None


def test_the_module_computes_no_verdict():
    """Principle III: the API never validates, cleans, interpolates, or flags."""
    import api.ingest.batch as mod

    src = inspect.getsource(mod).lower()
    for banned in ("def validate_reading", "interpolat", "def clean", "quality_score"):
        assert banned not in src


def test_the_module_imports_no_agent():
    import api.ingest.batch as mod

    src = inspect.getsource(mod)
    assert "from agents" not in src
    assert "import agents" not in src


# -------------------------------------------------------------------- input hygiene ---
def test_whitespace_is_stripped_from_identifiers():
    """A trailing newline from a gateway's string formatting must not fork a sensor id."""
    r = ReadingInput(**reading(sensor_id=" SENSOR_1\n"))
    assert check_shape(r) is None
    assert r.sensor_id.strip() == "SENSOR_1"


def test_an_unknown_extra_field_does_not_break_parsing():
    """A newer gateway firmware sending an extra field is not a reason to lose readings."""
    batch = parse_batch({"readings": [reading(firmware="2.1.0")]})
    assert len(batch.readings) == 1


def test_the_default_cap_is_a_real_bound_not_a_sentinel():
    """This one is memory safety, so unlike the rate limits it has a real default."""
    from api.settings import Settings, is_todo

    cap = Settings().max_ingest_batch_size
    assert isinstance(cap, int) and cap > 0
    assert not is_todo(float(cap))


def test_a_non_positive_cap_is_a_programming_error():
    """A cap of 0 would reject every batch — that is a config bug, not a policy."""
    with pytest.raises(ValueError):
        parse_batch({"readings": [reading()]}, max_readings=0)


def test_a_reading_is_held_verbatim_so_parsing_cannot_raise():
    """Coercion belongs in the append path, not here.

    If `ReadingInput` declared `value: float`, pydantic would raise on `"twelve"` — and a
    raise during parsing costs the whole batch, which is exactly what P401 forbids. So the
    model holds what arrived and `check_shape` reports on it.
    """
    r = ReadingInput(**reading(value="twelve"))
    assert r.value == "twelve"
    assert check_shape(r) is RejectionReason.NON_NUMERIC_VALUE


def test_an_accepted_value_converts_cleanly_to_a_float():
    """What the append path relies on: anything check_shape passes is float()-able."""
    for good in (12, 12.5, -3.2, 0):
        r = ReadingInput(**reading(value=good))
        assert check_shape(r) is None
        assert math.isfinite(float(r.value))
