# Feature Specification: Data Collection Agent

**Feature Branch:** `001-data-collection-agent`
**Created:** 2026-06-20
**Status:** Draft — awaiting clarifications
**Constitution:** v1.0.0 (see `.specify/memory/constitution.md`)

## Summary

The Data Collection Agent is the first validation checkpoint for all incoming
IoT sensor data from bridges, sitting upstream of any analysis or risk scoring.
It runs continuously on a fixed cycle (1–5 minutes), validates every sensor
reading against deterministic rules, detects offline sensors, distinguishes
transient noise (spikes) from genuine sustained change, bridges short data gaps
via interpolation, and emits only trustworthy data plus an explicit per-sensor
status. Every rejection, flag, and transformation is logged with a reason for
later audit.

This agent exists to prevent two failure modes that are both dangerous on
safety-critical infrastructure: (a) bad data corrupting a downstream risk score
(missing a real danger or crying wolf), and (b) a silently-failed sensor being
mistaken for "no news is good news."

## Constitution Alignment (Constitution Check)

| Principle | How this feature complies |
|-----------|---------------------------|
| I. Safety First | Agent produces validated data + status only; takes no physical action. Status reasons are human-readable WHY, not bare codes. |
| II. Data Integrity | Raw readings are preserved append-only; interpolated/cleaned values are stored as derived records alongside — never overwriting raw. Every transform (interpolation, rejection, flag) is logged with a reason traceable to source. |
| III. Modularity | Standalone module with an explicit input (sensor readings) / output (validated reading + status) contract. Downstream agents consume only via that contract. |
| IV. Reliability Over Cleverness | All validation here is deterministic (range, liveness, statistical thresholds). **No LLM is used in this agent.** Malformed input returns a status, never an unhandled exception. |
| V. Testability | Spec defines the four mandatory scenarios (normal / missing / corrupt / offline) as acceptance criteria. |
| VI. Auditability | Every flag, rejection, interpolation, and status change is logged with timestamp + causing input. |
| VII. Tech Stack | Consumes MQTT ingestion; persists to PostgreSQL/TimescaleDB. (Implementation detail deferred to plan.) |

## User Scenarios & Testing

### User Stories

1. **As a downstream agent (Structural Analysis Agent),** I only want to receive
   sensor readings that are validated, so my calculations aren't corrupted by
   sensor noise or hardware faults.
2. **As a government engineer,** I want to know immediately if a sensor has gone
   offline, so I recognize a monitoring blind spot instead of assuming silence
   means safety.
3. **As a safety auditor,** I want every rejected or flagged reading logged with
   a reason, so I can review why any data point was excluded if a bridge incident
   is later investigated.
4. **As the system operator,** I want short sensor dropouts (1–2 missed readings)
   handled gracefully via interpolation, but longer dropouts (3+) clearly marked
   as "no data" rather than guessed at.

### Acceptance Criteria

- **AC-1 (Offline detection):** Given a sensor that has not reported in over 5
  minutes, the agent marks it `OFFLINE`, and this status is visible to engineers
  within one processing cycle.
- **AC-2 (Corrupt rejection):** Given a reading outside the physically possible
  range for that sensor type, the agent rejects it as `CORRUPT` and logs the
  reason (the value and the violated bound).
- **AC-3 (Spike detection):** Given a single-point statistical outlier (>3
  standard deviations from recent history) that is NOT confirmed by the next 2–3
  readings, the agent flags it as a `SPIKE` (likely noise) rather than passing it
  through as real.
- **AC-4 (Real signal pass-through):** Given a sustained shift in readings
  confirmed across multiple consecutive data points, the agent passes it through
  as a real signal, not a spike — this could be genuine structural change.
- **AC-5 (Short-gap interpolation):** Given 1–2 consecutive missing readings, the
  agent fills the gap via linear interpolation between the surrounding good
  values, marking the result as interpolated (not raw).
- **AC-6 (Long-gap no-data):** Given 3+ consecutive missing readings, the agent
  does NOT interpolate and instead marks the period as `NO_DATA`.
- **AC-7 (Crash safety):** The agent never crashes on malformed input; it always
  returns a structured status.

## Functional Requirements

- **FR-1:** The agent MUST run continuously on a fixed cycle, configurable within
  the 1–5 minute range. [NEEDS CLARIFICATION: is the cycle a single global value,
  or per-sensor based on each sensor's expected reporting rate?]
- **FR-2:** The agent MUST maintain a registry of which sensors are *expected* to
  be reporting, so absence can be distinguished from a sensor that was never
  installed. [NEEDS CLARIFICATION: is there an authoritative sensor inventory the
  agent reads from, and who maintains it?]
- **FR-3:** For each reading, the agent MUST perform a **liveness check** and emit
  `OFFLINE` when the last reading is older than the offline threshold (default >5
  min). [NEEDS CLARIFICATION: is the 5-minute offline threshold global, or
  per-sensor-type, given different sensors may report at different rates?]
- **FR-4:** For each reading, the agent MUST perform a deterministic **range
  check** against the physically possible bounds for that sensor type, emitting
  `CORRUPT` on violation. [NEEDS CLARIFICATION: the set of sensor types and their
  physical min/max bounds is not yet defined — see Open Questions.]
- **FR-5:** The agent MUST perform **spike detection** using a >3σ deviation from
  recent history, deferring the spike-vs-real decision until confirmation readings
  arrive. [NEEDS CLARIFICATION: how many readings define "recent history" for the
  mean/σ baseline? Is the confirmation window 2 or 3 readings?]
- **FR-6:** The agent MUST classify a >3σ deviation as a real signal (pass through)
  when it is sustained across consecutive confirmation readings, and as a `SPIKE`
  when it is not. [NEEDS CLARIFICATION: how many consecutive points constitute a
  confirmed "sustained shift"?]
- **FR-7:** The agent MUST interpolate linearly across gaps of 1–2 consecutive
  missing readings, using the nearest good values on each side, and MUST mark the
  produced value as `INTERPOLATED`.
- **FR-8:** The agent MUST mark gaps of 3+ consecutive missing readings as
  `NO_DATA` and MUST NOT interpolate across them.
- **FR-9:** The agent MUST preserve every raw reading append-only, and store any
  derived value (interpolated or otherwise) as a separate record linked to its
  raw source(s). The agent MUST NOT overwrite or delete raw data.
- **FR-10:** The agent MUST log every rejection, flag, interpolation, and status
  change with a timestamp, the causing input, and a human-readable reason.
- **FR-11:** The agent MUST always return a structured status for every sensor it
  processes; it MUST NOT raise an unhandled exception on malformed, missing, or
  out-of-range input.
- **FR-12:** The agent MUST expose per-sensor status in a form the engineer
  dashboard can consume. [NEEDS CLARIFICATION: does the agent push status to the
  dashboard, or does the dashboard read status from the datastore the agent
  writes? Defer transport to plan, but confirm the contract direction.]
- **FR-13 (Calibration drift):** [NEEDS CLARIFICATION: the WHY section mentions
  sensors "drift out of calibration," but no acceptance criterion covers drift
  detection. Is slow drift detection IN SCOPE for this agent, or deferred to the
  Structural Analysis / Risk agents?]

### Status Taxonomy (proposed)

The agent emits exactly one status per sensor per cycle. Proposed set:

- `VALID` — reading passed all checks, passed through as real.
- `INTERPOLATED` — value reconstructed across a 1–2 reading gap (derived, not raw).
- `SPIKE` — single-point >3σ outlier, unconfirmed; withheld as likely noise.
- `CORRUPT` — out-of-physical-range; rejected.
- `NO_DATA` — 3+ reading gap; not interpolated.
- `OFFLINE` — no report beyond the liveness threshold.

[NEEDS CLARIFICATION: is `PENDING`/`UNCONFIRMED` needed as a transient state while
a >3σ reading awaits its confirmation window, since the spike-vs-real verdict
cannot be issued until 2–3 later readings arrive?]

## Key Entities

- **Sensor** — a physical device on a bridge. Has an identity, a type, an expected
  reporting rate, and physical-range bounds. Belongs to a bridge/structure.
- **Raw Reading** — an immutable, append-only record: sensor id, timestamp, value,
  (and possibly unit / quality flags from the device).
- **Validated Reading** — a derived record: the value passed downstream (or null),
  its status, links to the raw source record(s), and the reason.
- **Validation Log Entry** — timestamp, sensor id, causing input, decision, and
  human-readable reason. Required for audit.
- **Sensor State** — rolling per-sensor context the agent needs across cycles:
  recent-history window (for σ baseline), last-seen timestamp (for liveness),
  consecutive-missing counter (for gap handling), and any pending unconfirmed spike.

## Out of Scope (handled by other agents)

- Deciding whether a reading indicates structural **danger** — Risk Reasoning Agent.
- Running FFT, fatigue, or other engineering **calculations** — Structural Analysis Agent.
- Sending **alerts or notifications** — Alert Agent.

## Review Checklist

- [ ] All [NEEDS CLARIFICATION] markers resolved before `/sp.plan`.
- [ ] Sensor types + physical ranges supplied (FR-4).
- [ ] Statistical-window and confirmation-window sizes fixed (FR-5, FR-6).
- [ ] Calibration-drift scope decided (FR-13).
- [ ] Status/dashboard contract direction confirmed (FR-12).
- [ ] No implementation/tech detail leaked into requirements (deferred to plan).
