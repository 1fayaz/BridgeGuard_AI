# Adding a new sensor type — **config only, no code change** (T1202)

A core design rule (spec edge-case rule, Constitution III): adding a new sensor type is
**data, not logic**. You add config entries and fill in physical constants — you never
edit a validation check. If you find yourself changing `checks/*.py` to support a new
type, something is wrong.

This guide adds a hypothetical 8th type, `humidity_sensor` (unit `%RH`), end to end.

---

## Step 1 — add a `SensorProfile` entry

In `config/sensor_profiles.py`, add one line to `_SEED_PROFILES`:

```python
_SEED_PROFILES: tuple[SensorProfile, ...] = (
    SensorProfile("accelerometer",     "m/s^2",       cadence_s=TODO, phys_min=TODO, phys_max=TODO),
    ...
    SensorProfile("displacement_lvdt", "mm",          cadence_s=TODO, phys_min=TODO, phys_max=TODO),
    SensorProfile("humidity_sensor",   "%RH",         cadence_s=TODO, phys_min=TODO, phys_max=TODO),  # NEW
)
```

That is the only change needed for `get_profile("humidity_sensor")` to return a real
profile instead of the `UnknownSensorType` signal. The behavioural constants
(`offline_after_n=3`, `zscore_threshold=3.0`, baseline `100`/`24h`, `confirm_count=3`,
`pending_timeout_mult=3`, `interp_cap=2`) are inherited as defaults — only the **per-type
physical constants** differ.

## Step 2 — fill in the per-type constants (structural engineer)

Replace the four `TODO` sentinels with real, engineer-supplied values:

```python
SensorProfile(
    "humidity_sensor", "%RH",
    cadence_s=300.0,                 # one reading every 5 minutes
    phys_min=0.0, phys_max=100.0,    # relative humidity is physically 0–100 %RH
    clock_drift_tolerance_s=30.0,    # acceptable sensor/ingest skew
)
```

> **Do not guess these numbers.** Until a structural engineer supplies them they MUST
> stay `TODO` (the `float('nan')` sentinel). An unset bound is *loudly* flagged —
> `profile.is_fully_configured` is `False`, and any reading is held `CORRUPT` with a
> "bounds unset" reason — rather than silently validated against a plausible-looking but
> wrong limit. For a safety-critical system, failing loudly beats failing silently.

`%RH` is not in the canonical `iot-sensor-ingestion` list — confirm the unit string with
the skills README before shipping a real type.

## Step 3 — register the physical sensors

A profile describes a *type*; the registry lists the *devices* expected to report. In
`config/registry.py` (or your deployment's registry seeding), add each unit:

```python
DEFAULT_REGISTRY.add(ExpectedSensor("hum-01", "humidity_sensor", "bridge-04"))
DEFAULT_REGISTRY.add(ExpectedSensor("hum-02", "humidity_sensor", "bridge-07"))
```

Now the orchestrator iterates these, so a silent humidity sensor is evaluated → `OFFLINE`
instead of vanishing.

## Step 4 — (DB) no migration needed

The schema is type-agnostic: `sensor_type` is a `TEXT` column, not an enum. A new type
needs **no migration**. Just ensure raw payloads for it are appended like any other.

---

## What you did NOT touch

- `checks/liveness.py`, `range_check.py`, `spike.py`, `gap_fill.py`, `pending.py`,
  `clock_drift.py`, `late_arrival.py` — **unchanged**.
- `agent.py` (`process_cycle`) — **unchanged**.
- `db/migrations/` — **unchanged**.

The new type flows through liveness, range, spike, gap-fill, PENDING, late-arrival,
clock-drift, and dedup automatically, parameterised entirely by its `SensorProfile`.

## Verify

```bash
python -m pytest tests/data_collection/ -q
```

A new type added per this guide requires **only config edits** — which is exactly the
"config, not code" guarantee `test_t103_lookup.py::test_adding_a_type_is_config_only`
asserts for every registered type.
