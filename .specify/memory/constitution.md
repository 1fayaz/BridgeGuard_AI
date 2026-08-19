<!--
SYNC IMPACT REPORT
==================
Version change: 2.0.0 → 2.1.0  (MINOR)
Amendment: Datastore change + resolution of the open SDK namespace collision. Backward
compatible — no safety/integrity/auditability guarantee is weakened (the append-only and
provenance obligations are datastore-agnostic), hence MINOR per the versioning policy.

Stack change (Principle VII) — old → new:
  - Database : Supabase / PostgreSQL (Timescale ext. optional)
              → Neon / PostgreSQL (serverless); standard Postgres indexes only —
                a composite index on (sensor_id, sensor_time) covers the time-series
                query patterns. TimescaleDB is NOT used.

Resolved (was an open landmine): the OpenAI Agents SDK top-level package name `agents`
collides with this repo's own `agents` package (exposed by pythonpath=["src"]). Decision:
alias-import via a single SDK adapter module (repo package NOT renamed). Recorded under
Principle VII; the adapter code itself is follow-up work (R701 / Agent-4 wiring), not part
of this amendment.

Unchanged: Principles I–VII intent, all other Principle VII stack entries, every other
constraint and gate.

Prior amendment (historical) — 1.0.0 → 2.0.0 (MAJOR):
Version change: 1.0.0 → 2.0.0  (MAJOR)
Amendment: Reconcile Principle VII (Tech Stack) to match CLAUDE.md, the project's
operative constitution. This is a backward-incompatible redefinition of the mandated
stack, hence a MAJOR bump per the versioning policy.

Stack change (Principle VII) — old → new:
  - Agent reasoning : Claude API            → OpenAI Agents SDK (Python)
  - Backend         : Flask / FastAPI       → Python service (OpenAI Agents SDK) + n8n glue
  - Database        : PostgreSQL+TimescaleDB → Neon / PostgreSQL (v2.1.0; was Supabase)
  - Dashboard       : React + Tailwind      → TypeScript / Next.js + Tailwind
  - Tool layer      : (unspecified)         → MCP (Model Context Protocol)
  - Ingestion       : MQTT                  → MQTT (unchanged)

Also added to Principle VII / Operational Constraints:
  - "Trace from day one" — SDK tracing on for every model-calling agent run.
  - "Gate real-world actions with needs_approval" — restated from CLAUDE.md.

Principles unchanged in intent: I–VI (numbering preserved).

Migration impact (existing code now NON-CONFORMANT, must be migrated or re-justified):
  ⚠ src/api/        — built on FastAPI (old stack); revisit vs Agents SDK + n8n.
  ⚠ frontend/       — built on Vite + React (not Next.js); revisit vs Next.js.
  ⚠ specs/003-backend-api, 004-dashboard-frontend — assume old stack; reconcile.

Templates requiring review for alignment:
  ⚠ .specify/templates/plan-template.md  — Constitution Check gate (not yet present)
  ⚠ .specify/templates/spec-template.md  — scenario coverage (not yet present)
  ⚠ .specify/templates/tasks-template.md — test-first tasks (not yet present)

Follow-up TODOs: migrate or re-justify the FastAPI/Vite code above against v2.0.0.
-->

# BridgeGuard Constitution

BridgeGuard is an AI-powered IoT bridge and infrastructure health monitoring
system. It is **safety-critical software**: the correctness of its outputs bears
on human life. The principles below are binding on every feature, every agent,
and every line of code from the moment this constitution is ratified. They are
not aspirational guidelines — they are constraints that gate what may be merged,
deployed, and operated.

## Core Principles

### I. Safety First (NON-NEGOTIABLE)

No AI agent may autonomously trigger a bridge closure or any physical, real-world
action. AI agents produce **recommendations and risk scores only**. Any action
with real-world consequences MUST be approved by a human engineer before it is
taken; the system MUST make such approval an explicit, recorded step that cannot
be bypassed in code.

Every risk score and every alert MUST include a clear, human-readable explanation
of **WHY** — the contributing factors and the reasoning — not merely a numeric
value. A score without an explanation is an incomplete output and MUST be treated
as a defect.

**Rationale:** Lives depend on correct, accountable decisions. Removing the human
from the loop on physical actions, or emitting unexplained numbers, would make the
system unsafe and its decisions unchallengeable.

### II. Data Integrity

Raw sensor data MUST never be overwritten or deleted. It is **append-only**. Every
cleaning, refinement, or transformation step MUST preserve the original raw record
intact alongside the derived (cleaned) version.

Every data transformation — filtering, interpolation, outlier removal, unit
conversion, or any other modification — MUST be logged with a **reason**, such that
any downstream output can be traced back, step by step, to the raw source record(s)
that produced it. Provenance MUST be reconstructable from the logs alone.

**Rationale:** Trustworthy analysis requires an unbroken chain from raw measurement
to conclusion. Mutable or untraceable data destroys the ability to audit, reproduce,
or refute a decision after the fact.

### III. Modularity

Every agent — data collection, analysis, risk reasoning, reporting, alerting, and
any future agent — MUST be built as a **standalone, independently testable module**
with an explicit input/output contract.

No agent may directly call another agent's internals. Inter-agent communication MUST
flow only through defined interfaces (e.g., documented function signatures, message
schemas, or API contracts). Reaching into another module's private state, internal
functions, or implementation details is prohibited.

**Rationale:** Independently testable, contract-bound modules can be verified,
replaced, and reasoned about in isolation. Hidden coupling makes failures
unpredictable and undermines every other principle, including testability and
auditability.

### IV. Reliability Over Cleverness

Rule-based, deterministic logic MUST be used wherever a deterministic check is
possible — range checks, liveness/heartbeat checks, threshold comparisons, schema
validation, and similar. LLM/AI reasoning is **reserved exclusively** for genuinely
ambiguous judgment calls (e.g., interpreting compound risk, writing human-facing
narrative reports). Using an LLM where a deterministic rule suffices is a violation
and MUST be rejected in review.

Every agent MUST handle malformed or missing input without crashing. An agent MUST
**always return a status** describing the outcome (success, degraded, error, etc.)
and MUST NOT propagate an unhandled exception. Failure is an expected input
condition, not an exceptional one.

**Rationale:** Deterministic checks are predictable, cheap, fast, and auditable;
LLM calls are none of those by default. In a safety-critical system, a component
that crashes on bad input is itself a hazard. Predictability beats cleverness.

### V. Testability

Every agent MUST have unit tests covering, at minimum, all four of the following
scenarios:

1. **Normal input** — well-formed, in-range data.
2. **Missing sensor data** — required fields or readings absent.
3. **Corrupt / out-of-range data** — malformed, impossible, or out-of-bounds values.
4. **Sensor offline** — the sensor is unreachable or has stopped reporting.

No agent is considered "done" until it passes tests for all four scenarios. A merge
or release that includes an agent lacking any of these four tests violates this
constitution.

**Rationale:** The four scenarios are the failure modes that occur in the field.
An agent unverified against them is unverified against reality, regardless of how
well it handles the happy path.

### VI. Auditability

Every decision an agent makes — flag, score, alert, recommendation, or transformation
— MUST be logged with a **timestamp** and the **input that caused it**. The log MUST
be sufficient to answer, after the fact: *what did the system decide, when, and on
the basis of what data?*

This logging is required for government and regulatory accountability and is not
optional, not sampled, and not disabled in production.

**Rationale:** A safety-critical public-infrastructure system must be answerable to
regulators, investigators, and the public. A decision that cannot be reconstructed
and explained cannot be defended or corrected.

### VII. Tech Stack Constraints

The following stack is mandatory unless and until this constitution is amended. It is
reconciled with `CLAUDE.md`, the project's operative constitution (Digital FTE / AI
Agent Factory framework):

- **Agent reasoning:** Python with the **OpenAI Agents SDK**. Prefer the SDK's built-in
  primitives (sessions, guardrails, tracing, handoffs) over custom-rolled equivalents.
- **Backend:** Python service(s) built on the OpenAI Agents SDK, with **n8n** as the
  workflow glue between MQTT ingestion and agent triggers.
- **Tool connections:** **MCP** (Model Context Protocol) for connecting tools to agents.
- **Database:** **Neon / PostgreSQL** (serverless Postgres) as the system of record.
  **Standard Postgres indexes only** — TimescaleDB is NOT used. A composite index on
  `(sensor_id, sensor_time)` covers the sensor time-series query patterns (per-sensor
  time-range scans, latest-per-sensor, gap detection); do not add a time-series extension
  without a constitutional amendment justifying it.
- **Agent-framework packaging:** the OpenAI Agents SDK's top-level import name `agents`
  **collides** with this repo's own `agents` package (resolved first via `pythonpath=["src"]`).
  The SDK MUST be **alias-imported through a single adapter module** (e.g.
  `import agents as openai_agents` inside `src/agents/**/sdk_adapter.py`); the repo's `agents`
  package is **not** renamed. No other module imports the SDK directly — the adapter is the one
  seam, keeping the collision contained and the deterministic code SDK-free (Principle IV).
- **Sensor ingestion:** MQTT protocol (unchanged).
- **Dashboard:** **TypeScript / Next.js** with Tailwind CSS.
- **AI reasoning calls:** used sparingly and only where justified by Principle IV
  (Reliability Over Cleverness) — deterministic logic is preferred wherever possible.

Introducing an alternative language, datastore, ingestion protocol, agent framework,
or AI provider for in-scope functionality requires a constitutional amendment, not
merely a design decision.

**Trace from day one.** Tracing MUST be enabled for every model-calling agent run from
its first run — including development — with no exceptions. Purely deterministic steps
(which call no model) satisfy auditability via the decision log (Principle VI) rather
than SDK tracing; an agent that calls a model MUST be traced.

**Gate real-world actions.** Every tool that can cause a real-world action (closure
recommendation, alert dispatch, report publication) MUST be gated behind the Agents
SDK `needs_approval` (human-in-the-loop) pattern until a human engineer has explicitly
reviewed and downgraded it (see Principle I).

**Rationale:** A fixed, well-understood stack reduces operational risk and concentrates
expertise. Standardising on the Agents SDK gives sessions, guardrails, tracing, and
human-approval primitives out of the box, so the safety and auditability guarantees
above are enforced by the framework rather than re-implemented per feature.

## Operational Constraints

- **Human-in-the-loop boundary:** The codebase MUST expose no path by which an AI
  agent's output is wired directly to a physical actuator or closure mechanism.
  Physical actions are gated behind a recorded human approval step (Principle I).
- **Append-only data store:** The persistence layer for raw sensor data MUST be
  configured to forbid in-place update and delete of raw records (Principle II).
- **Provenance retention:** Transformation logs and decision logs MUST be retained
  for at least the period required by applicable regulatory authority; where no
  period is specified, they are retained indefinitely (Principles II, VI).
- **LLM budget discipline:** Claude API usage MUST be justified per call site against
  Principle IV. Deterministic alternatives, where they exist, take precedence.

## Development Workflow & Quality Gates

1. **Constitution Check precedes design.** Every feature plan MUST verify compliance
   with Principles I–VII before implementation begins. A plan that cannot satisfy a
   principle MUST be revised or escalated to amendment — it MUST NOT proceed on a
   silent exception.
2. **Test-first for the four scenarios.** For each agent, the four mandatory test
   scenarios (Principle V) are written and agreed before the agent is considered
   complete. "Done" is defined by passing tests, not by code existing.
3. **Contracts before integration.** An agent's input/output contract (Principle III)
   MUST be defined and documented before another agent depends on it.
4. **Explainability is a gate, not a feature.** A risk score or alert without its WHY
   explanation (Principle I) fails review.
5. **Auditability is a gate, not a feature.** A decision path that does not log
   timestamp + causing input (Principle VI) fails review.
6. **Reviews enforce this constitution.** Code review MUST explicitly check the
   relevant principles. Reviewers reject changes that violate them.

## Governance

This constitution supersedes all other development practices, conventions, and
preferences where they conflict. In a conflict, the constitution wins.

**Amendments.** Any change to this document MUST be proposed explicitly, recorded
with its rationale, and version-bumped per the policy below. Amendments take effect
only once merged into this file.

**Versioning policy (semantic):**
- **MAJOR** — removal or backward-incompatible redefinition of a principle, or any
  change that weakens a safety, integrity, or auditability guarantee.
- **MINOR** — addition of a new principle or section, or a materially expanded
  obligation that is backward compatible.
- **PATCH** — clarifications, wording, and non-semantic refinements that do not change
  any obligation.

**Compliance review.** Every plan, spec, and pull request is reviewed for compliance.
Violations MUST be remediated before merge; an accepted violation requires a recorded,
justified amendment, never an undocumented exception. Where runtime complexity is
added, it MUST be justified against these principles or removed.

**Version:** 2.1.0 | **Ratified:** 2026-06-20 | **Last Amended:** 2026-07-04
