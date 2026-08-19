# Data Collection Agent — Technical Plan

**Status:** Draft for review (interview Q1–Q4 settled; constitution reconciled)
**Date:** 2026-06-21
**Spec:** `specs/data-collection-agent/spec.md` (behaviour-only, Q1–Q4 incorporated)
**Constitution:** `CLAUDE.md` + `.specify/memory/constitution.md` **v2.0.0** (now agree)
**Research:** `specs/data-collection-agent/research-agents-sdk.md`

> Planning under the **CLAUDE.md stack** (OpenAI Agents SDK, MCP, Supabase/Postgres,
> n8n, Next.js). As of 2026-06-21 `.specify/memory/constitution.md` was amended to
> **v2.0.0** to match this stack — the two governing docs no longer conflict.
>
> **Settled in interview (now baked in below):** per-type fixed cadence (Q1); per-type
> offline = **3 missed reports** (Q2/Q3); OFFLINE (sensor-status) and NO_DATA
> (reading-status) **co-exist** (Q4); spike **confirm-count = 3**; PENDING **timeout =
> 3× the sensor type's expected interval**. Remaining placeholders (σ-baseline window
> size; per-type physical bounds + exact cadence values) flagged in Open Items.

---

## 1. Is the Data Collection Agent an Agent, or is validation pre-processing?

**Recommendation: validation is a deterministic PRE-PROCESSING pipeline that runs
*before* any Agent sees the data. The four checks are NOT `@function_tool`s.**

Rationale (matches constitution Principle IV — rule-based over LLM where deterministic):
- Liveness, range, ±3σ spike, and gap-fill are all exact, testable computations. The
  research found unanimous SDK guidance that such checks belong in deterministic code,
  not model reasoning, and that a safety check the *model can choose to skip* is the
  wrong shape for a mandatory gate.
- The README's `data-refinement` pipeline is a **fixed ordered sequence**
  (dedup→sort→outlier→filter→interpolate→normalize), not a reasoning loop.
- Every reading must be checked **every cycle** — that is the definition of
  pre-processing, not an agent's discretionary tool call.

**Where (if anywhere) an SDK Agent appears.** Two honest options for review:
- **Option A (v1, recommended): no model-calling Agent in the Data Collection Agent at
  all.** It is a deterministic service. "Agent" here means *Digital FTE* (a unit of
  autonomous work that a human oversees), not *an LLM loop*. This is the simplest thing
  that satisfies the spec and is fully testable.
- **Option B (later): a minimal Agent for the one genuinely ambiguous judgment** the
  README names — *"permanently failed sensor vs. temporary dropout."* Even this is often
  a deterministic rule (N consecutive offline cycles), so it is a candidate for an Agent
  **only if** that classification proves to need judgment. If added, the deterministic
  results become its read-only *input context*, never something it can overrule silently.

**Guardrail note:** if/when an Agent is introduced, the deterministic validator is the
natural **input guardrail** — the Agent is structurally prevented from seeing
un-validated data. `needs_approval` is **not** needed in this agent: it takes no
real-world physical action (that gate lives on the downstream closure/alert/publish
tools). This also sidesteps the open Python-SDK HITL-maturity risk (research, issue #2401).

---

## 2. Reading flow: MQTT → n8n → Python service → Supabase

End-to-end, per-cycle (cadence is **per-sensor-type, configured** — interview Q1):

```
Sensors → MQTT broker (Mosquitto)
      → n8n: subscribes, batches messages per processing cycle, triggers the service
      → Python validation service (deterministic pre-processing pipeline):
            1. parse + safe-guard each payload   (malformed → status, never crash; FR-5)
            2. APPEND every raw payload to Supabase raw table   (append-only; FR-6)
            3. dedup (sensor_id + timestamp) + sort by timestamp (edge-case rules)
            4. run the four checks against the per-type profile (cadence, bounds, σ)
            5. derive cleaned/validated values + statuses
            6. WRITE cleaned rows + status + reason + raw-source links to Supabase
      → downstream (Structural Analysis Agent) reads only trustworthy cleaned rows
```

**Responsibility split (proposed, for review):**
- **n8n owns:** MQTT subscription, batching into a cycle, invoking the service, retry of
  the *trigger*. n8n is glue, not logic.
- **The Python service owns:** the raw append, all validation, all derived writes, all
  decision logging. (So the raw-write owner question from research is answered: **the
  service writes raw**, immediately on receipt, before validation — so nothing is lost
  even if validation later errors.)

**Supabase data model (status model from spec, behaviour→tables):**
- **Raw table** — append-only; one row per received payload incl. malformed ones; never
  updated/deleted (constitution: raw immutable, traceable).
- **Cleaned/validated table** — one row per sensor per cycle: value (or null), a
  **reading-status** (`OK | INTERPOLATED | SPIKE | CORRUPT | NO_DATA | PENDING`), an
  `is_interpolated` flag, links back to the raw source row(s).
- **Sensor-status** — per-device health (`LIVE | OFFLINE`), driven by the 3-missed-reports
  rule (Q2/Q3). *This is the spec's device-vs-timeline split:* **OFFLINE is a
  sensor-status; NO_DATA is a reading-status** — they **co-exist** (Q4 confirmed),
  describing the device and the timeline respectively.
- **Decision log** — every reject/flag/interpolation with timestamp + causing input +
  human-readable reason (constitution: auditability).
- **Sensor-type profile** — per type: cadence, offline-after-N (**=3**), phys min/max,
  σ-threshold (**=3**), baseline-window (TBD), **confirm-count (=3)**, **pending-timeout
  (=3× cadence)**, interp-cap (**=2**). *Config, not code,* so a new sensor type is added
  without touching validation logic (spec edge-case rule).

[Datastore note — RESOLVED by the DB layer (Spec 002, constitution v2.1.0):
**Neon/Postgres with standard B-tree indexes only — no TimescaleDB**. The time-series
query pattern is served by a composite `(sensor_id, sensor_time)` index, not a hypertable
or a time-series extension.]

---

## 3. How PENDING readings get re-evaluated

A >3σ reading can't be judged until the confirmation readings arrive, so it is written
as **PENDING** (withheld from downstream) and resolved later. The question is the trigger.

**Decision: event-driven primary + scheduled safety-net (hybrid). Confirm-count = 3;
timeout = 3× the sensor type's expected interval.**

- **Primary — the next readings for that sensor resolve its PENDING.** A >3σ reading is
  written PENDING and judged once its **3-reading confirmation window** fills:
  - the 3 confirming readings sustain the deviation → PENDING becomes a **real signal
    (`OK`)**, released downstream;
  - they do not → PENDING becomes **`SPIKE`** (noise), stays withheld.
- **Why a safety-net is required (not optional):** if a sensor spikes and then *goes
  silent*, the 3 confirming readings never arrive and the PENDING would hang forever. So
  the **scheduled cycle** also closes out any PENDING whose window can no longer fill:
  - the sensor has crossed into **OFFLINE** (3 missed reports), **or**
  - **3× the sensor type's expected interval** has elapsed without 3 confirming readings.
  In either case the PENDING is finalised **`SPIKE` (unconfirmed)** and the gap handled
  by FR-4. This is the §3 ↔ offline-rule interaction the spec now states (FR-5/AC-5):
  they are coupled, not independent.

**Net rule (now concrete):** a PENDING resolves on whichever comes first — (a) its
**3-reading** confirmation window fills via incoming readings, or (b) the cycle observes
the window can no longer fill — sensor **OFFLINE**, or **3× cadence** elapsed — and
finalises it `SPIKE (unconfirmed)`. A PENDING is **never** left unresolved.

---

## 4. Is tracing needed here, given zero/few model calls?

**Two distinct obligations — keep them separate:**

- **Decision logging / audit trail (REQUIRED, always-on).** Constitution mandates every
  decision be reconstructable (timestamp + input + reason). This is the §2 *decision log*
  and it exists **regardless of whether any model runs** — it is deterministic-code
  logging, not SDK tracing. This is the real, load-bearing requirement for this agent.
- **OpenAI SDK tracing (applies only to Agent/model runs).** CLAUDE.md says "trace every
  agent, every run, from day one, no exceptions." Honest reading: SDK tracing instruments
  **model/agent execution**. In **Option A (no model-calling Agent), there is nothing for
  SDK tracing to trace** — the obligation is satisfied vacuously, and the *audit log* is
  what actually delivers the constitution's intent (auditability). In **Option B**, the
  moment an Agent with a model call exists, SDK tracing is switched on for it from its
  first run — no exceptions, per CLAUDE.md.

**Decision (now codified in constitution v2.0.0, Principle VII "Trace from day one"):**
wire the decision-log audit trail now (it's the constitution's real ask and it's
testable); enable SDK tracing the instant any model-calling Agent is introduced. Purely
deterministic steps satisfy auditability via the decision log, not via empty SDK traces —
the amended Principle VII states this explicitly, so it is no longer a judgment call.

---

## Constitution Check

| Principle (CLAUDE.md) | How this plan complies |
|---|---|
| Digital FTE / human signs off physical actions | DCA takes no physical action; no `needs_approval` here — gate lives downstream. |
| Raw immutable, every number traceable | Service appends raw on receipt; cleaned rows link to raw source; decision log. |
| Prefer SDK primitives over custom | Validator as input-guardrail shape; sessions/tracing reserved for any real Agent. |
| Domain expertise in README | Pipeline order, sensor types, ±3σ, interp all taken from `data-refinement`/`ingestion`. |
| Trace from day one | Audit log always-on; SDK tracing on for any model-calling Agent from first run (§4). |
| Gate real-world actions w/ needs_approval | N/A to this agent; explicitly deferred to closure/alert/publish tools. |

## Resolved since last review

- ✅ **Q4** — OFFLINE (sensor-status) and NO_DATA (reading-status) **co-exist** (spec
  Core Concepts; §2/§3).
- ✅ **Confirm-count = 3** and **PENDING timeout = 3× cadence** (§3, FR-5/AC-5).
- ✅ **Tracing** — settled by constitution v2.0.0 Principle VII (§4).
- ✅ **Spec updated** with interview Q1–Q4 (no longer says "5 minutes" as a rule).
- ✅ **Folders consolidated** into `specs/data-collection-agent/`; v0 design docs moved
  to `archive/`.
- ✅ **Constitution reconciled** to the CLAUDE.md stack → v2.0.0.

## Open Items Still To Resolve Before Build

1. **Agent presence (decision needed):** Option A (deterministic service, **no** model
   loop) for v1 — recommended — or build the Option B judgment-Agent (permanent-fail vs
   temporary-dropout) now? Everything else in this plan assumes **A**.
2. **σ-baseline window size:** how many recent readings define the mean/σ for the ±3σ
   check (confirm-count is settled at 3; the *baseline* window is not).
3. **Per-sensor-type physical bounds + exact cadence values:** placeholders pending a
   structural engineer; logic is buildable now, only the constants change.
4. **Late-arrival rule:** a valid reading arriving *after* its window was processed —
   recompute the derived result, or keep raw-only? (research §4)
5. **Stack migration follow-up (from constitution v2.0.0):** existing `src/api/`
   (FastAPI) and `frontend/` (Vite) predate the stack amendment and are now
   non-conformant — separate effort to migrate/re-justify; does not block this agent.
