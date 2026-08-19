# Findings: Data Collection Agent as an OpenAI Agents SDK Agent

**Type:** Research findings — NOT a design. No final architecture, no code.
**Date:** 2026-06-20
**Anchors:** `skills/bridgeguard-skills-README.md` (`iot-sensor-ingestion`, `data-refinement`);
existing Spec 001 (deterministic-Python plan); CLAUDE.md (Agents SDK stack — this
conflicted with `.specify/memory/constitution.md` v1.0.0 when written; **RECONCILED at
constitution v2.1.0**: Neon/Postgres, standard B-tree only, no TimescaleDB).

> Scope note: the README's two skills define the *what* (ingestion validates IDs/
> timestamps/units, flags nulls/dropouts/spikes; refinement does dedup→Z-score(±3σ)→
> Butterworth→interpolate→normalize/resample, and flags permanent-fail vs temp-dropout).
> This doc only investigates how that maps onto an Agents-SDK agent. It does not decide.

---

## 1. Tool vs. pre-processing (the "state-and-trust" frame)

**What exists.** The Agents SDK gives three places logic can live: (a) **before the agent**
as plain Python (input pipeline), (b) an **input guardrail** that runs before the model
and can tripwire, (c) a **`@function_tool`** the model chooses to call. Guardrails are
explicitly framed as "fast validation before the expensive/side-effecting part starts."

**Options.**
- **Pre-processing (agent never sees raw):** validate/clean deterministically, hand the
  agent only trustworthy data. Matches the README's pipeline ordering and our existing
  Spec 001 (validation runs on a cycle, before analysis). Agent reasons over *clean* state.
- **Tool the agent calls:** expose `validate_reading()` / `clean_window()` as
  `@function_tool`; the model decides when to call them. More "agentic," but it puts a
  deterministic, safety-critical check behind a model's discretion.
- **Hybrid:** deterministic clean as pre-processing/guardrail; reserve the *agent* for the
  genuinely ambiguous calls (permanent-fail vs temp-dropout classification, risk framing).

**Trust framing.** Validation/cleaning is deterministic and must run **every** reading —
that argues for pre-processing or a guardrail, not a model-chosen tool. The README's
own pipeline is a fixed ordered sequence, not a reasoning loop. **Unknown:** where exactly
the agent boundary sits — does the agent consume already-clean data (most likely), or is
it handed raw and expected to orchestrate cleaning tools?

---

## 2. Four checks: deterministic `@function_tool` vs. model reasoning

**What exists.** Strong, consistent guidance from SDK docs/community: **rule-based checks
are faster, cheaper, predictable** — preferred for format/range/keyword validation; reserve
the LLM for things needing reasoning. This matches our constitution's Principle IV exactly.

**Per-check read (options + trade-offs):**
| Check | Deterministic fn (wrapped or pre-proc) | Model reasons turn-by-turn |
|-------|----------------------------------------|----------------------------|
| Liveness (last-seen > threshold) | Trivial, exact, testable. **Clear win.** | No upside; non-deterministic, costs a turn. |
| Range (phys min/max) | Pure comparison; auditable reason string. **Clear win.** | Risk of hallucinated bounds. |
| Z-score spike (±3σ, README) | NumPy/SciPy; exact; the "confirmed by next 2–3" logic is stateful but deterministic. **Win.** | Model is bad at precise σ math; unreliable. |
| Gap-fill (linear interp, cap 2) | `numpy.interp`; exact, provenance-clean. **Win.** | Model "guessing" values violates traceability. |

**The genuinely ambiguous bit.** The README's *"permanently failed sensor vs. temporary
dropout"* call is the one place judgment may add value — but even that is often a
deterministic rule (N consecutive cycles offline). **Trade-off of wrapping as
`@function_tool` anyway:** you gain SDK tracing of each call for free, at the cost of the
model being able to *skip* a safety check. **Unknown:** do we want these as callable tools
(traced, but discretionary) or as non-skippable pre-processing/guardrails (safer, but the
"agent" does less)?

---

## 3. Fit into the planned stack (Supabase/Postgres, MQTT → n8n → trigger)

**What exists (per CLAUDE.md / README stack table).** MQTT (Mosquitto) ingestion →
**n8n** as workflow glue → triggers the agent; **Supabase/Postgres** is the system of
record. README confirms Python + NumPy/SciPy/Pandas for processing.

**Implications / options.**
- **Trigger boundary:** n8n likely batches MQTT messages and invokes the agent per cycle
  (echoes Spec 001's 1–5 min cycle) rather than per-message. The agent run is the unit
  n8n schedules.
- **System of record:** raw append-only lands in Postgres (constitution II).
  **RESOLVED (constitution v2.1.0):** the datastore is **Neon/Postgres with standard B-tree
  indexes only — no TimescaleDB, no Supabase**. The time-series pattern is served by a
  composite `(sensor_id, sensor_time)` index. (When written, this was an open tension
  between the constitution's TimescaleDB and CLAUDE.md's Supabase.)
- **Tracing:** CLAUDE.md mandates SDK tracing on every run from day one — n8n-triggered
  runs included. Need to confirm traces export correctly from an n8n-invoked context.
- **State:** SDK **sessions** could hold per-sensor rolling state (history window, last-seen,
  gap counter), OR that state lives in Postgres and the agent is stateless per run. **Unknown.**

**Unknowns.** Exact n8n→agent contract (payload shape, batch vs single); whether n8n or the
agent owns the append-to-raw write; how SDK sessions and Postgres divide state ownership.

---

## 4. Failure modes

**What exists / known behavior.**
- **Malformed data:** Agents-SDK `@function_tool` supports a `failure_error_function` so a
  raising tool returns a structured error to the model instead of crashing — aligns with
  constitution IV ("always return a status, never throw"). Deterministic pre-proc can also
  catch-and-tag (our Spec 001 `safe_parse` already does this). Either way malformed → a
  logged status, not a crash. **Question:** does the model *see* malformed-handling (tool)
  or is it filtered before the agent (pre-proc)?
- **MQTT broker drops messages:** This is the **QoS** question. MQTT QoS 0 = fire-and-forget
  (drops possible), QoS 1 = at-least-once (dupes possible), QoS 2 = exactly-once (costlier).
  A dropped reading is indistinguishable from a sensor dropout at the agent layer → it
  manifests as a gap, handled by gap-fill (≤2) / NO_DATA (≥3). **Unknown:** broker QoS
  level; whether n8n adds its own retry/ack; how "broker drop" is told apart from "sensor
  offline" (maybe it isn't, and both are just gaps).
- **Out-of-order arrival:** MQTT ordering is only guaranteed per-topic per-QoS; n8n batching
  and network jitter can reorder. The README pipeline's **first step is "dedup & sort by
  timestamp,"** which directly addresses this — *if* late readings are still within the
  processing window. **Trade-off / unknown:** a reading arriving *after* its cycle already
  closed — does it get appended late (raw is append-only, so yes) and the derived value
  recomputed, or is it dropped from derived output? Idempotency/late-arrival policy is
  undefined. Dedup key (sensor_id + timestamp?) also undefined.

---

## Cross-cutting unknown: Python SDK HITL maturity

CLAUDE.md leans on `needs_approval`. Web research shows it is **well-supported in the JS
SDK**, but a GitHub issue (#2401) reports **HITL not yet available in Python SDK v0.7**.
Since our stack is Python, the maturity of `needs_approval` in the Python SDK is an
**open risk to verify** before committing to it as the approval mechanism. (Note: the Data
Collection Agent itself takes *no physical action*, so it may not need `needs_approval` at
all — that gate belongs to closure/alert/publish tools downstream.)

---

## Summary

| | Status |
|---|---|
| **What exists** | SDK primitives (guardrails, `@function_tool` + `failure_error_function`, sessions, tracing, HITL); README defines the exact validation/refinement pipeline; Spec 001 already has a deterministic design. |
| **Main options** | Deterministic checks as pre-processing/guardrails (safer, non-skippable, matches Principle IV) vs. as agent-called tools (traced but discretionary) vs. hybrid (deterministic clean + agent only for permanent-vs-temporary judgment). |
| **Biggest unknowns** | (1) where the agent boundary sits (raw vs clean); (2) n8n→agent contract + who owns the raw write; (3) session-vs-Postgres state ownership; (4) MQTT QoS + late-arrival/idempotency policy; (5) Python-SDK `needs_approval` maturity; (6) ~~unreconciled stack conflict~~ **RESOLVED at constitution v2.1.0 — Neon/Postgres, standard B-tree only, no TimescaleDB**. |

**Sources:** see chat — OpenAI Agents SDK docs (tools, guardrails, human-in-the-loop),
GitHub issue #2401 (Python HITL), AI Agent Factory guardrails guide.
