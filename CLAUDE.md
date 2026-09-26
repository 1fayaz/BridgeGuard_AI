# BridgeGuard — Project Constitution (CLAUDE.md)

BridgeGuard is an AI-powered IoT bridge monitoring system built as a set of
**Digital FTEs** (per the AI Agent Factory framework). It is safety-critical
infrastructure software: correctness can affect human life. These principles are
binding on every spec, agent, and change.

> Companion doc: `.specify/memory/constitution.md` (Spec-Kit constitution). Where the
> two overlap, see **Reconciliation** at the bottom — they must not silently diverge.

## Principles

- **Every agent is a Digital FTE.** It does real work, but a human signs off on
  anything with real-world physical consequences (e.g. recommending a bridge
  closure). No agent acts autonomously on destructive or safety-critical
  decisions — this maps to the OpenAI Agents SDK `needs_approval` pattern.
- **Raw data is immutable.** Raw sensor data is never overwritten, only appended.
  Every number shown to a human must be traceable back to its raw source.
- **Prefer SDK primitives over custom code.** Use the OpenAI Agents SDK's built-in
  sessions, guardrails, tracing, and handoffs instead of rolling your own.
- **Domain expertise is external.** It lives in `skills/bridgeguard-skills-README.md`.
  Read it before specifying or building anything that touches the
  sensor-to-report pipeline.

## Constraints

- **Stack.** Python (OpenAI Agents SDK) for agent reasoning; TypeScript/Next.js for
  the dashboard; MCP for tool connections; **Neon/Postgres** as the system of
  record (standard Postgres indexes only — no TimescaleDB; a composite index on
  `(sensor_id, sensor_time)` covers the time-series query patterns); n8n for
  workflow glue between MQTT ingestion and agent triggers.
- **Agents SDK packaging.** The SDK's top-level `agents` package collides with this
  repo's own `agents` package. Alias-import the SDK through a single adapter module
  (`import agents as openai_agents`); do not rename the repo package, and do not
  import the SDK anywhere but that adapter.
- **Trace from day one.** Tracing is on for every agent, every run — including dev.
  No exceptions.
- **Gate real-world actions.** Every tool that can cause a real-world action
  (closure recommendation, alert dispatch, report publication) must be decorated
  `needs_approval` until a human engineer has explicitly reviewed and downgraded it.

## Definition of Done

- Behaviour matches its `spec.md`, edge cases included.
- A human has reviewed the diff against the spec before merge.
- Every agent that can call a tool has a visible trace in the OpenAI tracing
  dashboard (or self-hosted equivalent) for its most recent run.

---

## Relationship to `.specify/memory/constitution.md`

Both documents prescribe the same stack. `constitution.md` (v2.1.0, last amended
2026-07-04) reconciled its Principle VII to this file's stack back at v2.0.0 —
OpenAI Agents SDK, n8n glue, MCP, Neon/Postgres with no TimescaleDB, TypeScript/
Next.js, the `agents`-package alias-import resolution, and `needs_approval` gating
are stated identically in both. There is no open stack conflict between the two
docs. `constitution.md` is the fuller document — read it for Principles I–VI
(safety, data integrity, modularity, reliability, testability, auditability), which
this file does not restate; this file is Digital-FTE / agent-framework operating
guidance layered on top.

**What's still non-conformant is the built code, not the docs** (tracked in
constitution.md's own v2.0.0 amendment note, re-verified 2026-09-25):
- `src/api/` is FastAPI, not the OpenAI Agents SDK.
- No agent — including `src/agents/data_collection/` — imports the OpenAI Agents
  SDK anywhere in the repo; every agent is deterministic Python today.
- `frontend/` **is** Next.js (`frontend/package.json` confirms `"next": "14.2.35"`).
  This section previously said Vite + React here — that was migrated since and
  this note had gone stale until now.

None of this blocks new work — it's the backlog for eventually adopting the Agents
SDK for agent reasoning, not a docs disagreement to resolve first.
