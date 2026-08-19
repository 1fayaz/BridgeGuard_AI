# Data Collection Agent — Specification

**Status:** Draft (interview Q1–Q4 incorporated)
**Date:** 2026-06-21
**Anchors:** `CLAUDE.md` (constitution), `skills/bridgeguard-skills-README.md`
(`iot-sensor-ingestion`, `data-refinement`),
`specs/data-collection-agent/research-agents-sdk.md` (research).

> **Behaviour only.** This spec describes WHAT the agent does and WHY — no databases,
> frameworks, SDK classes, or file layout. Those are design decisions made later.

---

## Goal

This agent is the **first checkpoint** for all incoming bridge sensor data. It exists
to stop corrupted, noisy, or unreliable readings from ever reaching the agents that
calculate structural risk — because a bad number fed to the risk engine could hide a
real danger or raise a false alarm, and this is safety-critical infrastructure. It
either passes a reading forward as trustworthy, or marks exactly why it could not.

---

## Core Concepts (settled in interview)

- **Reporting cadence is per-sensor-type, fixed, and configured — never inferred.** Each
  sensor type has a known expected interval (e.g. an accelerometer streams fast; a crack
  sensor reports slowly). "A reading is missing" is meaningful only relative to that
  type's configured interval. All counting rules below ("3 missed reports", "1–2 gap")
  are counted in *expected readings for that type*, not in absolute time.
- **Two independent status axes — they co-exist, neither replaces the other:**
  - **Sensor-status (device health):** `LIVE` or `OFFLINE`. Describes the *device* —
    "is sensor A3 reporting?" Engineer-facing blind-spot signal.
  - **Reading-status (timeline/value):** `OK | INTERPOLATED | SPIKE | CORRUPT | NO_DATA
    | PENDING`. Describes a *value or period* — "what do we have for 10:00–10:30?"
  - A sensor that misses 3 expected readings becomes **OFFLINE** (device) **and** its
    missing period is marked **NO_DATA** (timeline) at the same time. They answer
    different questions and are emitted together, not in competition.

---

## User Scenarios

- **Normal reading** — A sensor sends a valid, in-range reading; it passes through
  cleanly to the next stage, marked trustworthy (`OK`, sensor `LIVE`).
- **Sensor goes silent** — A sensor misses **3 consecutive expected readings** for its
  type; the device is flagged **OFFLINE** so engineers see a known blind spot, rather
  than silently showing nothing (silence must never be mistaken for safety). *(The "5
  minutes" from early discussion was only an example for a medium-cadence sensor; there
  is no absolute time ceiling — offline is always "3 missed reports" for the type.)*
- **Physically impossible value** — A sensor reports a value outside what is physically
  possible for its type; the reading is **rejected** (`CORRUPT`) with a logged reason and
  never passed downstream.
- **Unconfirmed spike** — A single reading jumps sharply but the **next 3 readings** do
  not confirm it; it is flagged as **noise (`SPIKE`)**, not treated as a real change.
- **Confirmed shift** — A sharp change **is** sustained across the next 3 readings; it
  passes through as a **real signal** (`OK`), because it may be genuine structural change.
- **Short gap** — 1–2 consecutive readings are missing; the gap is **filled by
  interpolation** (`INTERPOLATED`) between the surrounding good values, marked as
  interpolated (not raw). The sensor stays **LIVE** (it has not hit 3 missed reports).
- **Long gap** — 3 or more consecutive readings are missing; the period is marked
  **NO_DATA** (not interpolated) **and** the device is flagged **OFFLINE**.

---

## Functional Requirements

A build that ignores any of these should **visibly fail** a corresponding test.

- **FR-1 — Liveness check (per-type, 3 missed reports).** For every expected sensor, the
  agent counts consecutive missed reports against that sensor type's **configured
  expected interval**. When a sensor has missed **3 consecutive expected readings**, its
  sensor-status becomes **OFFLINE**, visible within one processing cycle. The threshold
  is per-type (it scales with cadence); there is **no global absolute-time ceiling**. A
  build using a flat wall-clock rule for all types, or that never flags a silent sensor,
  fails.
- **FR-2 — Range check.** Every reading is checked against the physically possible
  minimum and maximum **for its sensor type** (per the `iot-sensor-ingestion` supported
  types: accelerometer, strain gauge, crack sensor, load cell, temperature, tiltmeter,
  displacement/LVDT — each with its own unit and bounds). A value outside those bounds
  is **rejected as CORRUPT** with a logged reason naming the value, the bound, and the
  unit. A build that lets an out-of-range value pass downstream fails.
- **FR-3 — Outlier / spike check (±3σ, confirmed by next 3).** A reading that deviates
  more than **±3 standard deviations** from the sensor's recent history is treated as a
  *candidate* and written as **PENDING** (withheld from downstream until resolved). If
  the **next 3 readings do not sustain** the deviation, it is finalised as **SPIKE**
  (noise) and stays withheld. If the deviation **is sustained across those 3 confirming
  readings**, it is finalised as a **real signal (`OK`)** and released downstream. A
  build that passes an unconfirmed >3σ jump through as real — or suppresses a confirmed
  sustained change — fails.
- **FR-4 — Gap-fill (cap 2).** A gap of **1–2 consecutive missing readings** is filled by
  **linear interpolation** between the nearest good values on each side, marked
  **INTERPOLATED**; the sensor remains **LIVE**. A gap of **3 or more** consecutive
  missing readings is marked **NO_DATA**, is NOT interpolated (**interpolation cap is
  2**), and the sensor is flagged **OFFLINE** (FR-1). A build that interpolates across a
  3+ gap, or fails to fill a 1–2 gap, fails.
- **FR-5 — PENDING resolution (event-driven + timeout).** A PENDING reading is resolved
  on whichever happens first:
  1. its **3-reading confirmation window fills** via incoming readings (→ `OK` if
     sustained, `SPIKE` if not); or
  2. the window **can no longer be filled** — specifically, the sensor goes **OFFLINE**
     (3 missed reports) **or 3× the sensor type's expected interval elapses** without
     enough confirming readings — in which case the PENDING is finalised as **SPIKE
     (unconfirmed)** and the gap handled by FR-4. A PENDING must **never remain
     unresolved indefinitely**; a build that leaves a PENDING dangling after its sensor
     goes offline or after 3× the interval fails.
- **FR-6 — Always returns a status.** For every sensor it processes, the agent returns a
  structured sensor-status and reading-status and never crashes on bad input. A build
  that throws on malformed input instead of returning a status fails. *(CLAUDE.md: no
  unhandled crashes.)*
- **FR-7 — Traceable & logged decisions.** Every rejection, flag, interpolation, and
  status change is logged with the sensor, the timestamp, the input that caused it, and a
  human-readable reason; the original raw reading is preserved unchanged. A build where a
  downstream value cannot be traced back to its raw source, or where a rejection has no
  logged reason, fails. *(CLAUDE.md: raw is append-only; every number traceable to source.)*

---

## Edge Cases & Rules

- **Malformed payload (missing fields).** A reading missing required fields (no value, no
  timestamp, no sensor id) does not crash the agent and does not silently vanish — it is
  recorded raw and marked `CORRUPT` with a reason describing what was missing.
- **Out-of-order timestamps.** Readings arriving out of chronological order are re-ordered
  by timestamp before the checks run (per `data-refinement`'s "sort by timestamp" step),
  so a late-but-recent reading is evaluated in its correct position. A reading arriving
  *after* its window was already processed is still preserved as raw; whether its derived
  result is recomputed is a **rule still to be confirmed** (see Open Items).
- **Duplicate readings.** Two readings with the same sensor and the same timestamp are
  de-duplicated so a single logical reading is evaluated once (per `data-refinement`'s
  "remove duplicates" step); the raw duplicates remain preserved.
- **Unknown sensor type.** A reading whose sensor type has no configured profile cannot be
  range-checked or cadence-checked, so it is **not passed through as trustworthy** — it is
  marked `CORRUPT`/unverifiable with a reason naming the unknown type, rather than guessed
  at. Adding a new sensor type (with its cadence + bounds) must be possible **without
  changing the validation logic** — profiles are configuration, not code.

---

## Out of Scope

- **Deciding whether a reading indicates structural danger** — Risk Reasoning Agent's job.
- **Running FFT, fatigue, or other engineering math** — Structural Analysis Agent's job.
- **Sending alerts or notifications** — Alert Agent's job.

This agent only judges whether data is **trustworthy**, never what it *means*.

---

## Acceptance Criteria

Each is testable against a scenario above.

- **AC-1.** A sensor that misses **3 consecutive expected readings** for its type is
  reported **OFFLINE** within one cycle (not blank, not silently absent), using the
  per-type cadence, with no global wall-clock rule. *(sensor goes silent)*
- **AC-2.** A reading outside its sensor type's physical range is **rejected as CORRUPT**
  with a logged reason and does **not** appear in downstream output. *(impossible value)*
- **AC-3.** A single >3σ reading not sustained by the **next 3 readings** is finalised
  **SPIKE** and withheld; a >3σ change sustained across the **next 3 readings** is
  released as a real signal (`OK`). *(unconfirmed spike / confirmed shift)*
- **AC-4.** A 1–2 reading gap is filled by linear interpolation and marked
  **INTERPOLATED** with the sensor still **LIVE**; a 3+ reading gap is marked **NO_DATA**,
  left unfilled, **and** the sensor flagged **OFFLINE**. *(short / long gap + co-existence)*
- **AC-5.** A PENDING reading whose sensor goes **OFFLINE**, or for which **3× the
  expected interval** elapses without 3 confirming readings, is finalised as **SPIKE
  (unconfirmed)** — never left dangling. *(PENDING/OFFLINE interaction)*
- **AC-6.** A normal in-range, live, non-outlier reading **passes through cleanly** as
  `OK`. *(normal reading)*
- **AC-7.** Malformed payloads, out-of-order timestamps, duplicate readings, and unknown
  sensor types are each handled by returning a structured status with a logged reason —
  **the agent never crashes and never silently drops a reading**. *(edge cases & rules)*

---

## Open Items (to resolve before design, not part of "done")

- **Late-arrival rule:** when a valid reading arrives *after* its window was already
  processed — recompute the derived result, or keep raw-only? (research §4)
- **σ-baseline window size:** the number of recent readings used to compute the mean/σ
  for the ±3σ check is not yet fixed. *(Confirm-count is settled at 3; baseline-window is
  not.)*
- **Per-sensor-type physical bounds + exact cadence values:** the min/max and expected
  interval per type are placeholders to be confirmed by a structural engineer.
