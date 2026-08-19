# Risk Reasoning Agent

The Risk Reasoning Agent is BridgeGuard's **judgment layer**. It consumes the Structural
Analysis Agent's (SA) calculation results and produces **two inseparable outputs**: a
deterministic **0–100 risk score with a severity band**, and a plain-language **explanation**
of *why* — the contributing factors and reasoning a government engineer reads and acts on.

> It is the **one agent in BridgeGuard that genuinely calls a model** (Constitution IV reserves
> the LLM for exactly this compound, ambiguous, human-facing judgment — every upstream agent is
> deterministic). But **the model never invents the number**: the score is pure code; the model
> only *explains* it.

It produces a **recommendation only**. It never takes — and never gates — a real-world action
(Constitution I); that human-approval gate lives downstream on the Alert Agent. This agent's
Principle-I contribution is the `PENDING_HUMAN_REVIEW` **flag** on grave verdicts, not a gate.

---

## The core split: deterministic score, model-written explanation

```
SA results ──► score_bridge()  ──►  risk_score (0–100)  ──► severity_for() ──► band
              (pure code, FR-2)          │                    (config table, FR-4)
                                         ▼
                          the model EXPLAINS this fixed number
                          (never re-estimates or changes it, mandate #1/#2)
```

- **`scorer.py`** normalises each SA result's **value/limit ratio** to 0–100, weights each by
  config, and combines them into one whole-bridge score. Pure, deterministic, order-independent,
  reproducible — **no model, no `openai`/`anthropic`/SDK import in its graph** (asserted in
  `test_r1103`). Principle IV: keep the arithmetic out of the LLM.
- **`agent.py`** frames that already-computed score as a *fixed input to explain* and forbids
  citing any number not in the retrieved inputs. (Inert `AgentDefinition` today — the live SDK
  `Agent(...)` is deferred; see **Deferred** below.)

---

## Inputs — three read-only fetches (FR-3), `tools/`

The agent obtains its inputs through three **distinct read-only retrievals** and reasons only
over what it actually retrieved. It never mutates an upstream record and never fabricates a
missing input.

| Tool (`tools/`) | Provides | On missing data |
|---|---|---|
| `get_calculation_results` | current (non-superseded) SA `analysis_results` for the bridge+cycle: each calc, `outcome` (`RAN`/`SKIPPED`/`ERROR`), `reason_code`, `result` payload, the four data-quality flags, `source_validated_ids` | structured-empty, never a raise |
| `get_historical_baseline` | rolling baseline / prior assessments for trend context | "no baseline" signal (cold-start) |
| `get_engineering_standard` | the applicable standard's limits **with code + version**, pinned at decision time (FR-10) | "standard unavailable" — never a guessed limit |

Each tool reads through a small **source Protocol**, so it runs against the in-memory fake now
and a Supabase-backed source later with no logic change.

## Outputs — one `RiskAssessment` per run (`assessment.py`)

Score and explanation are **one deliverable, emitted together or not at all** (FR-1); a bare
number is a defect the dataclass invariant makes unconstructable.

| Field | Meaning |
|---|---|
| `risk_score` | integer 0–100; **`None` when withheld** (below coverage floor, or guardrail fail) |
| `severity` | one closed-set band `SAFE \| WATCH \| WARNING \| CRITICAL` (`statuses.py`); `None` when withheld |
| `recommendation` | plain-language posture aligned to the band — a recommendation, never an action |
| `explanation` | the written WHY, logged **verbatim** — a first-class safety output |
| `contributing_factors` | the structured factor list the score was built from (value, limit, ratio, weight, contribution, direction, `source_analysis_id`) — machine-checkable backing for the narrative |
| `confidence` / `data_completeness` | deterministic annotation of how much expected input was present — **does not move the score** (FR-6a) |
| `review_status` | closed set `FINAL \| PENDING_HUMAN_REVIEW`, **always explicitly set** |
| provenance | `source_analysis_ids`, `baseline_ref`, `standard_code`+`standard_version`, `score_weights_version`, `model_id`+`model_version`, `trace_id` |

Severity bands are the fixed `math-analysis` table held as **config** (`ScoreConfig`
cut-points), not invented per run. The spec's illustrative ranges are
`SAFE 0–30 / WATCH 31–60 / WARNING 61–80 / CRITICAL 81–100`; the **actual** cut-points are
`TODO`/`NaN` config until a structural engineer supplies them (see `R1202` /
`TUNING.md`) — the code refuses to guess a band when they are unset.

---

## Per-assessment flow (`orchestrator.py :: assess_bridge`)

```
1. three read-only fetches        (calc results, baseline, standard)
2. coverage gate  (coverage.py)   below floor OR standard missing -> WITHHOLD, stop (FR-6)
3. deterministic score + band     score_bridge() + severity_for()   (pure code, FR-2/FR-4)
4. model drafts the explanation   the ONLY [LLM-DEP] step
5. numeric-provenance guardrail   regenerate once, then fail closed  (guardrail.py, FR-7)
6. review_status                  CRITICAL or withheld -> PENDING_HUMAN_REVIEW (review.py, FR-11)
7. build one RiskAssessment       scored or withheld — ALWAYS structured, NEVER raises (FR-8)
```

Any tool/model failure is isolated into a **withheld `PENDING_HUMAN_REVIEW`** assessment — the
agent always returns a structured status, never a crash (Constitution IV/V).

### The numeric-provenance guardrail (FR-7, mandate #2) — the highest-value control

An invented number in a government report is the system's worst failure mode. Before an
explanation is emitted, **every number in it** must match a value actually returned this run:

```
build_legitimate_set()   = every RAN result's numbers + the deterministic score
                           + each factor's value/limit/ratio/weight/contribution
                           + the pinned standard's limits
        │
extract_numbers(draft)   pull every numeric literal (ints, decimals, %, thousands, mm…)
        │
any number not in the legitimate set (within config tolerance)  ->  TRIPWIRE
        │
regenerate ONCE ─ still tripwires? ─►  FAIL CLOSED: score withheld,
                                       review_status = PENDING_HUMAN_REVIEW,
                                       RISK_GUARDRAIL_FAIL audited.
                                       The untraceable number is NEVER emitted.
```

The retry is hard-bounded (`MAX_REGENERATIONS = 1`) — never an unbounded loop. Default match
tolerance is `0.0` (exact-match, fail-safe: it can only reject more, never accept a fabrication);
a rounding tolerance is config `TODO`, never guessed.

### The coverage gate (FR-6) — score vs. withhold

A scored (possibly degraded) assessment is emitted **only** when RAN coverage is at/above the
configured floor **and** the standard is present. Below the floor, or standard missing, the
agent **withholds the score and routes to human review** — it never invents a missing input,
never emits a falsely-confident score on a near-blind bridge, never crashes on partial input.
`confidence`/`data_completeness` annotates but **does not alter** the score (FR-6a).

---

## Trigger contract (downstream of SA, per bridge per cycle)

Runs **once per bridge, on SA-cycle-complete** — one assessment = the **whole bridge** at that
moment, fusing all that bridge's sensors' current calc results (FR-3a). Not per-sensor, not on a
wall-clock schedule.

```
SA cycle complete ─► n8n (risk_reasoning.workflow.json, GLUE ONLY)
                       └─ POST {bridge_id, cycle_id, bridge_type} ─► service.py :: run_assessment
```

`service.py :: run_assessment` is the single callable n8n hits. It validates the payload, runs
one assessment, persists it, and returns a structured `AssessmentSummary` — **never raises**
(malformed payload → structured error). It is **idempotent by scope** (FR-3a): a redelivered
trigger for the same `(bridge_id, cycle_id)` **supersedes**, never duplicates. n8n contains **no**
scoring/judgment logic (Constitution III).

## Persistence + dual audit (`store.py`, `persistence.py`, `db/migrations/`)

| Table | Migration | Guarantee |
|---|---|---|
| `risk_assessments` | `0006` | scored **or** withheld rows; CRITICAL requires `PENDING_HUMAN_REVIEW`; correct-by-append (only `superseded_by` mutable); DELETE blocked; one current row per `(bridge, cycle)` |
| `decision_log` (risk kinds) | `0007` | `RISK_ASSESSMENT` / `RISK_WITHHELD` / `RISK_GUARDRAIL_FAIL`, appended to the shared cross-agent audit |

**Dual audit (FR-9):** the structured row (score, severity, recommendation, consulted IDs,
model+version, `trace_id`, factors, **verbatim** explanation) **and** the always-on SDK trace.
The structured record alone answers *what was decided, when, on the basis of what data*.
Reproducible from pinned inputs even after a standard is revised or an SA result superseded
(FR-10); a re-assessment supersedes, never overwrites (AC-10). `FakeRiskStore` mirrors these
guarantees in memory for tests.

---

## Out of scope

This agent only **judges and explains** — it turns trustworthy numbers into an accountable,
human-readable verdict, and stops at the recommendation. It does **not**:

- **take or gate any real-world action** — dispatch alerts, change signage, execute a closure,
  or apply the `needs_approval` gate: the **Alert Agent** owns that chokepoint (Constitution I);
- **run or re-run engineering calculations** (FFT/RMS/deflection/fatigue) — the **SA's** job; it
  consumes calc *results*, never computes;
- **validate or clean sensor data** — the **Data Collection Agent's** job;
- **author the PDF/government report or charts** — `pdf-report` / `visual-output`, downstream;
- **maintain the engineering-standards corpus** — it *looks up* standards, it does not curate;
- **invent the weighted-score formula or band thresholds** — those are `math-analysis` config;
- **run the human-review-clearing workflow** — it only *emits* `PENDING_HUMAN_REVIEW`; **who**
  clears it and the cleared→`FINAL` transition are a separate downstream concern.

## Configuration (safety numbers are config, not code)

All score weights, the ratio→0–100 normalisation bounds, the band cut-points, the coverage
floor, the completeness formula, and the guardrail match tolerance are **`TODO`/`NaN` config**
in `config/score_config.py` + `config/coverage_config.py` — loudly flagged unset
(`is_fully_configured` is `False`), **never** silently defaulted to a plausible number in a
safety-critical system. See **`TUNING.md`** (R1202) to change any of them **with config edits
only**, touching no scorer or agent code.

## Tested contract

Tests in `tests/risk_reasoning/` cover every unit plus the end-to-end acceptance criteria
AC-1…AC-12 (`test_r1102`) and the Constitution check (`test_r1103`). **[DB-DEP]/[LLM-DEP]:** the
suite runs against an in-memory fake store + a deterministic fake model; live Supabase and
frontier-model verification are deferred (none available locally) — flagged honestly, not faked.

### Deferred (needs a human decision / live infra)

- **Live SDK wiring:** the OpenAI Agents SDK is not installed, and its top-level import name
  `agents` **collides** with this repo's own `agents` package. `agent.py` is an inert
  `AgentDefinition` until that packaging decision is made (alias-import the SDK, or rename the
  repo package) — an R701 adapter.
- **Config TODOs:** every safety number above, supplied by a structural engineer.
- **Standards source + pinning**, **historical-baseline contract shape**, **frozen model id/tier**,
  **Alert-Agent chokepoint confirmation**, **trace retention/PII** — see `tasks.md` Open Items.
