# Findings: Risk Reasoning Agent as an OpenAI Agents SDK Agent

**Type:** Research findings — NOT a design. No architecture, no code.
**Date:** 2026-06-29
**Anchors:** `CLAUDE.md`; `.specify/memory/constitution.md` v2.0.0 (Principles I, IV, VI, VII);
`skills/bridgeguard-skills-README.md` (`math-analysis` weighted risk score 0–100;
`structural-research` IRC/AASHTO/Eurocode lookups); `specs/structural-analysis-agent/spec.md`
(the upstream contract — it emits numbers/ratios/pass-fail and **never** a danger verdict, and
names this agent as the consumer: spec §25–27, §517–519); precedent
`specs/data-collection-agent/research-agents-sdk.md`.

> Scope note: this agent fuses three inputs — the Structural Analysis Agent's calculation
> results, historical baseline/comparison data, and engineering-standard lookups — into a
> **0–100 risk score plus a plain-language explanation a government engineer acts on**. This
> doc investigates only how that maps onto an Agents-SDK agent; it does not decide the design.

---

## Framing: this is the first agent that genuinely IS a model-calling Agent

The Data Collection Agent and Structural Analysis Agent both resolved to **deterministic
services** (Option A): their math is pure and their decisions are rule-expressible, so
Principle IV forbids an LLM there. This agent is the opposite — **compound, ambiguous
judgment** (fuse heterogeneous inputs into a score *and* a defensible narrative), which is
exactly what Principle IV **reserves** the LLM for ("interpreting compound risk, writing
human-facing narrative reports"). So the question is not *whether* it is an Agent, but *how*
it is shaped, gated, and audited.

---

## 1. Single Agent with @function_tools, vs. a handoff target

**Read: data sources are TOOLS; the SA→Risk edge is NOT an SDK handoff.** Apply the book's
criterion — **hand off when you transfer control/conversation to a differently-specialized
agent; use a tool when you need a discrete capability and want control to RETURN.**

- **The three data sources are @function_tools.** `get_calculation_results`,
  `get_historical_baseline`, `get_engineering_standard(code)` are read-only fetches after
  which control must return to the reasoner to synthesize — textbook tool shape. Three focused
  tools beat one mega-tool: each is independently traceable and mockable (Principle III).
- **SA should NOT hand off to Risk.** SA is a deterministic service with **no model loop** —
  there is no agent conversation to transfer. A handoff would also couple two modules
  (Principle III forbids one agent calling another's internals). The clean contract is: SA
  writes `analysis_results`; a deterministic trigger (n8n) invokes Risk; Risk *reads* those
  results via tool. **Handoff** becomes appropriate only later, for a peer *model-agent* (e.g.
  Risk → a specialist "closure-package drafting" agent), not for this edge.

**Unknowns:** whether the three tools are MCP-backed (Principle VII) or in-process; whether
`get_engineering_standard` reads a curated local store vs. live retrieval (affects
reproducibility — a standard's value must be pinned at decision time).

---

## 2. Does any output need needs_approval=True?

**No `needs_approval` on THIS agent — but the gate is mandatory and lives downstream on the
Alert Agent.** Principle I is explicit: agents produce "recommendations and risk scores only";
the human-approval gate attaches to the **physical/real-world action**, not the recommendation.

- A "**Critical — recommend closure**" output here is *still just a recommendation* — emitting
  it harms nothing and must not be blocked. So this agent emits Critical freely.
- The `needs_approval=True` gate belongs on the **Alert/closure-dispatch tool** (the thing that
  actually notifies authorities or changes signage), which the **Alert Agent** owns. That is
  the human-in-the-loop chokepoint that "cannot be bypassed in code" (Principle I).
- This matches the DCA research conclusion (HITL sits on the *action*, not the *analysis*) and
  sidesteps the open Python-SDK `needs_approval` maturity risk for this agent.

**Unknown to verify:** confirm the Alert Agent is the system's **single** approval chokepoint,
so no other path can dispatch a real-world action ungated (Principle I "cannot be bypassed").

---

## 3. Model tier — frontier vs. mid-tier

**Frontier reasoning tier — this is the one place in the whole system it is justified.**
Principle IV mandates "LLM budget discipline" (justify model spend per call site). The
justification here is real and rare:

- The output is a **safety-critical, government-facing judgment** fusing heterogeneous inputs
  that must be **defensible to a regulator**. Mid-tier risks subtle misweighting of compound
  risk and weaker standards-reasoning — unacceptable when lives and legal accountability are
  downstream.
- **Cost is bounded:** this agent runs per analysis cycle / on threshold events, **not** per
  sensor reading, so frontier spend is small in aggregate.
- **If cost ever bites,** the only safe split is to keep frontier for the scoring rationale +
  narrative and push mechanical sub-steps to deterministic code — **never** downgrade the
  judgment itself.

**Unknown:** the exact trigger cadence (every SA cycle vs. only on a state change / threshold
crossing) — this sets the real cost envelope and should be pinned in the spec.

---

## 4. Preventing hallucination — output guardrail on numeric provenance

**An output guardrail that rejects any numeric claim not traceable to a real tool result is
the highest-value safety control in this agent.**

- **Every number the narrative cites** — a risk contribution, an RMS value, a deflection ratio,
  a standard's limit — must match a value actually returned by one of the three tools **this
  run**. An invented "deflection was 48 mm" in a government report is the system's worst failure
  mode.
- SDK **output guardrails** are the right primitive: validate before the result leaves the
  agent; **tripwire on a mismatch → regenerate or fail-closed**. This operationalizes Principle
  I ("a score without its WHY is a defect") into "a WHY citing a number that doesn't exist is
  *also* a defect."
- **Two reinforcing controls:** (a) tool results carry **source IDs** so the guardrail verifies
  each cited number against provenance; (b) the **score itself is computed deterministically**
  (the README's weighted formula) with the model *explaining* it — never inventing it. The
  model's job is the WHY, not the arithmetic.

**Unknowns:** how strictly to bind narrative numbers to tool outputs (exact-match vs. rounding
tolerance); whether the guardrail regenerates (one retry) or hard-fails to a safe "needs human
review" state on a tripwire.

---

## 5. How is the agent's reasoning logged for audit

**Both, with different roles. Full SDK trace for reproducibility; a structured decision-log row
as the permanent system-of-record audit entry.** Principles VI (auditability) and VII (trace
every model-calling run from day one) are two distinct obligations:

- **(a) SDK tracing** captures the full prompt, model response, and each tool call/result — the
  forensic-replay layer, on from the first run, no exceptions (VII).
- **(b) A structured `decision_log` row** (mirroring the DCA/SA pattern) is the permanent,
  queryable record: the score, the severity band, the input `analysis_results` IDs + baseline +
  standards consulted, the **model + version**, the **trace ID**, and the emitted explanation
  verbatim. This is "not optional, not sampled, not disabled in production" (VI).
- **Log the explanation verbatim** — it is a safety output, not a convenience; Principle I makes
  the WHY part of the deliverable.

**Unknown:** retention/PII review for full prompt+response traces in a government context, and
where the trace store lives relative to Supabase (the structured row is in Supabase; the trace
may be the OpenAI tracing dashboard or a self-hosted equivalent per CLAUDE.md).

---

## Summary

| | Status |
|---|---|
| **What's settled** | This is genuinely a model-calling Agent (Principle IV reserves the LLM for exactly this); the score is computed deterministically and *explained* by the model; the HITL gate lives on the Alert Agent's dispatch tool, not here. |
| **Main options** | Three read-only `@function_tools` (recommended) vs. one mega-tool; tools in-process vs. MCP-backed; guardrail regenerate-once vs. fail-closed on a numeric-provenance tripwire. |
| **Biggest unknowns** | (1) trigger cadence (cost envelope); (2) Alert Agent confirmed as the single un-bypassable approval chokepoint; (3) standards source pinned/reproducible at decision time; (4) guardrail strictness + failure mode; (5) trace retention/PII in a government context. |

**Sources:** OpenAI Agents SDK docs (tools, handoffs, guardrails, tracing, human-in-the-loop);
`.specify/memory/constitution.md` v2.0.0; `skills/bridgeguard-skills-README.md`;
`specs/structural-analysis-agent/spec.md`; `specs/data-collection-agent/research-agents-sdk.md`.
