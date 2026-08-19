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

## Reconciliation (READ — two governing docs disagree)

This file and `.specify/memory/constitution.md` (v1.0.0, ratified earlier this
session) prescribe **different stacks**. Until a human resolves this, treat the
conflict as open, not settled:

| Area | constitution.md v1.0.0 | this CLAUDE.md |
|------|------------------------|----------------|
| Agent reasoning | Claude API, used sparingly | **OpenAI Agents SDK** |
| Backend | Flask / FastAPI | Python (Agents SDK) + **n8n** glue |
| Datastore | PostgreSQL + **TimescaleDB** | **Neon**/Postgres (no TimescaleDB) |
| Dashboard | React + Tailwind | **TypeScript / Next.js** |
| Tool layer | (unspecified) | **MCP** |

The constitution's own governance says a stack change requires a recorded
**amendment + version bump**, not a second doc. Already-built code also diverges:
`frontend/` is **Vite + React** (not Next.js); `src/api/` is **FastAPI**; Agent 001
is deterministic Python (no Agents SDK). **Decision needed:** amend the constitution
to this stack (and migrate/justify the existing code), or keep the constitution's
stack and treat this CLAUDE.md as agent-framework guidance only. Do not build new
work on the new stack until this is resolved.
