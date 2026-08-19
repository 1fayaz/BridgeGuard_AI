# Database Layer — Research Findings (Spec 002)

**Status:** Research only. No schema, no migrations, no code proposed here. This documents what the
five agent contracts + backend API + dashboard *already require* of the DB, cross-checked against the
migrations that already exist in `db/migrations/`.

**Read for this:** `CLAUDE.md`; `skills/bridgeguard-skills-README.md`; all 7 `specs/*/spec.md`; and
every existing migration (`0001`–`0011`).

**Two framing facts to hold throughout:**

1. **`analysis_results` (SA output) has NO migration and NO store module.** It is referenced as
   `analysis_results` (migration 0005) by `0006`/`0008` header comments and by the Risk/Report
   input contracts, but **no `0005_analysis_results.sql` exists** and `Glob db/migrations/*.sql`
   skips from `0004` to `0006`. The SA table is the **single biggest gap** the DB layer must close.
2. **The user's point-2/point-3 name "dispatch_history" — the real table is `alert_dispatches`**
   (migration `0010`). There is no `dispatch_history`. All findings below use `alert_dispatches`.

---

## [1] Every table each agent writes to / reads from — with exact fields + spec line

Fields are quoted from each spec's **input/output contract table**, not guessed. `[NO MIGRATION]`
marks a contract with no table built yet.

### Agent 001 — Data Collection (DCA)
- **WRITES `raw_readings`** (mig 0001): `sensor_time`, `ingest_time`, `sensor_id`, `sensor_type`,
  `value`, `unit`, `raw_payload`. Mandate: DCA spec FR-7 (§111–113) "original raw reading preserved
  unchanged."
- **WRITES `validated_readings`** (mig 0002): `sensor_time`, `sensor_id`, `sensor_type`, `value`,
  `unit`, `status` (the six reading-statuses `OK|INTERPOLATED|SPIKE|CORRUPT|NO_DATA|PENDING`, DCA
  §34), `is_interpolated`, `clock_drift`+`clock_drift_s`, `source_raw_ids`, `reason`, `superseded_by`,
  `computed_at`. Two-axis model: DCA §31–34.
- **WRITES `decision_log`** (mig 0004): `decided_at`, `sensor_id`, `decision` (kind), `old_status`,
  `new_status`, `raw_value`, `raw_payload`, `source_raw_ids`, `reason`. DCA FR-7.
- **WRITES `sensor_status`** (mig 0003): current LIVE/OFFLINE device state (DCA FR-1, §70–73).
- **READS**: its own `raw_readings`/`validated_readings` recent window (baseline, gap, late-arrival).

### Agent 002 — Structural Analysis (SA)
- **READS `validated_readings`** (DCA output). Input contract §90–98: `sensor_id`, `sensor_type`,
  `sensor_status`, `reading_status`, `value`, `sensor_time`, `clock_drift`; plus block `sample rate`
  + `sample count` (§100–101) and recent validated history + re-baseline marker + reference-zero.
- **WRITES `analysis_results`** `[NO MIGRATION — 0005 missing]`. Output contract FR-13 (§383–391):
  per (sensor, calculation, block) exactly one row with `outcome` (`RAN|SKIPPED|ERROR`), skip
  `reason_code`, result `value(s)` (RMS / FFT top-N peaks+amplitudes / deflection ratios +
  pass/fail-vs-limit), the **`source_validated_ids`** that formed the input, the **input version**
  (FR-16 §407), `interpolated_input` flag, `clock_drift` flag (FR-14 §428), `rate_mismatch` flag
  (FR-2), and the **config version + constant values used** (FR-17 §417–422). Append+supersede on
  correction: FR-8 (§149, §212, §327).

### Agent 003 — Risk Reasoning
- **READS `analysis_results`** (SA output). Input contract §110–112: current RAN results — RMS/FFT
  peaks/ratios+pass-fail, each with `outcome`, `reason_code`, flags
  (`interpolated_input`,`clock_drift`,`rate_mismatch`,`abnormal_quiet`), `source_validated_ids`.
  Also reads historical baseline (§113) and pinned engineering standard (§114).
- **WRITES `risk_assessments`** (mig 0006). Output contract §127–147 = built columns: `risk_score`
  (0–100, NULL when withheld), `severity` (`SAFE|WATCH|WARNING|CRITICAL`), `recommendation`,
  `explanation` (verbatim, non-empty), `contributing_factors` (JSONB), `confidence`,
  `data_completeness`, `review_status` (`FINAL|PENDING_HUMAN_REVIEW`), provenance
  (`source_analysis_ids`, `baseline_ref`, `standard_code`+`standard_version`,
  `score_weights_version`, `model_id`+`model_version`, `trace_id`), `superseded_by`.
- **WRITES `decision_log`** (shared; risk kinds added mig 0007).

### Agent 004 — Report Generation
- **READS `risk_assessments`** (input contract §158): all verdict fields + full provenance.
- **READS `analysis_results`** via `source_analysis_ids` (§159) `[NO MIGRATION]`; **READS
  `validated_readings`** via the provenance chain (§160); reads pinned standard (§161).
- **WRITES `report_artifacts`** (mig 0008): `bridge_id`, `cycle_id`, `assessment_id`+
  `assessment_version`, `rendered_at`, `outcome` (`RENDERED|WITHHELD|ERROR`), `marks[]`,
  `withheld_reason`, `artifact_ref`, `source_analysis_ids`, `standard_code`+`standard_version`,
  `template_version`, `superseded_by`.
- **WRITES `decision_log`** (report kinds added mig 0009).

### Agent 005 — Alert & Escalation
- **READS `risk_assessments`** (input contract §120–122): `risk_score`, `severity`,
  `recommendation`, verbatim `explanation`, `review_status`, `confidence`/`data_completeness`,
  provenance (`source_analysis_ids`, `standard_*`, `model_*`, `trace_id`). Current row only.
- **WRITES `alert_dispatches`** (mig 0010): `bridge_id`, `cycle_id`, `assessment_id`+
  `assessment_version`, `dispatch_decision` (`AUTO_FIRE|NEEDS_APPROVAL|DASHBOARD_ONLY`), `channel`,
  `recipient`, `provider_message_id`, `delivery_state` (`QUEUED|SENT|DELIVERED|FAILED|ACKNOWLEDGED`),
  `escalation_state` (`OPEN|ESCALATED|CLOSED`), `close_reason`, `approval_state`
  (`AWAITING_APPROVAL|APPROVED|REJECTED`), `approved_by`, `approved_at`, `trace_id`, `attempted_at`,
  `superseded_by`. Output contract §136–149.
- **WRITES `decision_log`** (alert kinds added mig 0011).

---

## [2] Every append-only constraint already decided

All four "system-of-record" tables + the two audit trails are **already append-only in migration**,
each citing Constitution II (raw immutable) / VI (auditability):

| Table | Mig | Mechanism | Reference |
|---|---|---|---|
| `raw_readings` | 0001 | `REVOKE UPDATE/DELETE/TRUNCATE` + BEFORE UPDATE/DELETE trigger blocks *all* mutation | DCA FR-7; Const II |
| `decision_log` | 0004 | same total-block trigger (audit trail can't be rewritten) | Const VI |
| `validated_readings` | 0002 | correct-**by-append**: guard trigger blocks changing value/status/sensor_time/source; only `superseded_by` may be stamped; DELETE blocked | DCA FR-5; Const VI |
| `risk_assessments` | 0006 | guard trigger blocks mutating verdict/provenance; supersede-only; DELETE blocked | Risk FR-9/FR-10; Const VI |
| `report_artifacts` | 0008 | guard trigger blocks mutating outcome/artifact/provenance; supersede-only; DELETE blocked | Report FR-9; Const VI |
| `alert_dispatches` | 0010 | guard trigger blocks mutating verdict-identity/decision/trace; **delivery/escalation/approval state may still advance**; supersede-only; DELETE blocked | Alert FR-13; Const VI |

**Note the one nuance the DB must preserve:** `alert_dispatches` is *not* fully frozen — its state
machine (`SENT→DELIVERED→ACKNOWLEDGED`, `OPEN→ESCALATED→CLOSED`) legitimately advances on the current
row (mig 0010 §169–174); only the pinned identity is immutable. This differs from `validated_readings`
/`risk_assessments`, whose verdict fields are frozen.

**Gap:** `analysis_results` (SA) is mandated append+supersede by SA FR-8/FR-13/FR-16 but **has no
migration to enforce it.**

---

## [3] Every foreign-key relationship implied by the agent contracts

The provenance chain the specs describe (Report §156–161 traces it end-to-end):

```
raw_readings.id
   ▲  validated_readings.source_raw_ids  (BIGINT[])
validated_readings.id
   ▲  analysis_results.source_validated_ids  (BIGINT[])   [NO MIGRATION]
analysis_results.id
   ▲  risk_assessments.source_analysis_ids  (BIGINT[])
   ▲  report_artifacts.source_analysis_ids  (BIGINT[])
risk_assessments.id
   ▲  report_artifacts.assessment_id (+ assessment_version)
   ▲  alert_dispatches.assessment_id (+ assessment_version)
```

**Every existing cross-agent link is a deliberate SOFT reference (`BIGINT[]` array or plain
`BIGINT`+version), NOT a hard SQL FK** — stated explicitly in `0006` §23–26 and `0008` §30–33:
"a deliberate, documented decoupling (Principle III)." Rationale: agents publish contracts, they
don't hard-couple schemas. **The DB layer must decide whether to keep these soft** (consistent with
what's built) **or harden any to real FKs.** Self-referential `superseded_by` FKs *are* real FKs and
already exist on `validated_readings`, `risk_assessments`, `report_artifacts`, `alert_dispatches`.

Version pinning (not an FK, but a referential contract): `report_artifacts` and `alert_dispatches`
both carry `assessment_id` **+ `assessment_version`** so they pin an exact verdict revision even
after supersession (Report FR-11; Alert FR-11).

---

## [4] Fields the DB must store whose value is TODO/sentinel (schema present, constraint loose)

These are config/provenance values the agents keep as **loud TODO sentinels** (`NaN`/`None`) until a
human supplies them. The DB must have a **column/version-stamp** for them, but the constraint stays
loose (nullable / no CHECK) until an engineer fills the policy:

- **DCA (per-type config):** physical-bound limits, liveness cadence, σ-floor — resolved from the
  shared sensor registry; not a fixed value (DCA §77–83, Open Items §176).
- **SA (config version + constants):** design limits, RMS margins/ceilings, reference zeros, sample
  rate/block length, baseline window, k, σ-floor, min-block counts (SA §106–108). The result must
  store the **`config_version` + constant values used** (FR-17 §417–422) even though the values are
  TODO. FFT peak-count N, S-N fatigue curve deferred (SA §367, Open Items §643).
- **Risk:** `score_weights_version` (which `ScoreConfig` weights), coverage floor, band thresholds,
  guardrail tolerance — stored as versions on `risk_assessments` (mig 0006 col `score_weights_version`
  is `NOT NULL` but the *values* are config).
- **Report:** `template_version`, fidelity tolerance, headline table / appendix depth — stored as
  `template_version` on `report_artifacts` (loose until config supplied).
- **Alert (`AlertPolicy` — all TODO per `CONFIGURING.md`):** `retry_max`, `backoff_seconds`,
  `escalation_timeout_seconds`, `contact_roster`, `escalation_order`, `channel_per_band`,
  `authority_recipients`, message templates. **None are DB columns** — they live in agent config, not
  `alert_dispatches`. What the *row* stores is the **outcome** of applying that policy (`channel`,
  `recipient`, `approval_state`, etc.), all already nullable. Only `policy_version` is a candidate
  audit stamp the row/`decision_log` may want but does not yet have.

**Takeaway for the schema:** the version-stamp columns (`*_version`) already exist; the DB does **not**
need columns for the raw policy values (those stay in agent config). The one thing to watch:
`alert_dispatches` records *no* `policy_version` today.

---

## [5] Which tables need the `(sensor_id, sensor_time)` composite index (no TimescaleDB)

CLAUDE.md: Neon/Postgres, **standard B-tree only**, "a composite index on `(sensor_id, sensor_time)`
covers the time-series query patterns." Findings on where that pattern actually applies:

- **`raw_readings`** — YES, already built: `idx_raw_readings_sensor_time (sensor_id, sensor_time DESC)`
  (mig 0001 §41). Driven by DCA per-sensor baseline/gap/late-arrival window reads.
- **`validated_readings`** — YES, already built: `idx_validated_sensor_time (sensor_id, sensor_time
  DESC)` (mig 0002 §96). Driven by SA per-sensor chronological window (SA §102–104) **and** the
  backend timeseries endpoint `GET /v1/sensors/{id}/timeseries?from=&to=` (backend FR-6; dashboard
  FR-6 30/90/365-day selector).
- **`analysis_results`** `[NO MIGRATION]` — the SA-output reads are **keyed by (sensor, calculation,
  block, input-version)**, not `sensor_time`; but Risk/dashboard trend reads *are* time-ordered per
  scope. When 0005 is written it will need its **own** index (likely `(sensor_id, block/computed
  time)` and a `(bridge_id/cycle)` lookup), decided then.
- **`risk_assessments` / `report_artifacts` / `alert_dispatches`** — do **NOT** use
  `(sensor_id, sensor_time)`. They are **bridge/cycle/assessment-keyed**, and already carry the
  correct indexes: `(bridge_id, *_at DESC)` for trend + a **partial unique index over current rows**
  for idempotency (`uq_risk_current_bridge_cycle`, `uq_report_current_assessment_version`,
  `uq_alert_current_assessment_version`) + a partial index on the pending/open queue. No sensor-time
  index applies — these have no `sensor_id`.

**So:** the `(sensor_id, sensor_time)` composite is a **DCA/SA/backend-timeseries** concern
(`raw_readings`, `validated_readings`, future `analysis_results`), already correct on the two built
tables. The judgment tables correctly use bridge/assessment keys instead.

**Backend AC-2 (<500ms overview) implication:** the overview must **not** scan raw history; it needs
a current-status read model keyed on `(bridge_id)` reading the current `risk_assessments` row — the
`idx_risk_bridge_time` + partial-current-unique index already support "latest current per bridge."

---

## [6] Multi-tenant isolation — where `bridge_id` / `municipality_id` must appear

**Critical finding: the tenancy columns do NOT exist yet where the API needs them.**

- **`municipality_id` appears in NO table and NO agent spec.** It is introduced only by the backend
  API (spec 003 §32, §58–59, AC-3 §72–74: "principal for municipality A receives **zero** rows of
  municipality B") and consumed by the dashboard (FR-17 §156). There is **no `municipalities` table,
  no `municipality_id` column anywhere.** The DB layer must introduce it.
- **`bridge_id` exists on the judgment tables** (`risk_assessments`, `report_artifacts`,
  `alert_dispatches` — all `TEXT NOT NULL`) but is **absent from the sensor tables**: `raw_readings`
  and `validated_readings` carry only `sensor_id TEXT` (mig 0001 §27, mig 0002 §44). There is **no
  `bridges` table** and no `sensor → bridge` mapping in the schema. So today you cannot answer "which
  bridge does this reading belong to?" or "which municipality owns this bridge?" in SQL.

**What isolation requires the DB to add (the enforcement points):**
1. A **`municipalities`** table and a **`bridges`** table with `bridges.municipality_id → municipalities`.
2. A **`sensors`** table (or a column) mapping `sensor_id → bridge_id`, so `raw_readings` /
   `validated_readings` / `analysis_results` become tenant-attributable (they only have `sensor_id`).
3. `bridge_id` on the sensor/analysis tables **or** a reliable `sensor_id → bridge_id → municipality_id`
   join path, so every read endpoint (backend FR-9, all municipality-scoped) can filter.
4. **Row-level isolation** (backend AC-3): either Postgres RLS policies keyed on the principal's
   `municipality_id`, or a mandatory `WHERE municipality_id = :principal` on every read model. Backend
   spec 003 §19 lists "RLS" as belonging to **Spec 002 (this DB layer)** — which is now
  **written and built** (migrations 0015/0016).

**FK chain isolation must enforce:** `municipalities.id ← bridges.municipality_id ← sensors.bridge_id
← (raw_readings|validated_readings|analysis_results).sensor_id`, and
`bridges.id ← (risk_assessments|report_artifacts|alert_dispatches).bridge_id`. Auth/token design is
explicitly **out of scope** (backend §22, §157) — this layer only provides the scoping columns + RLS
the auth spec plugs a principal into.

---

## Summary of gaps the DB-layer spec must close

### The three blocking gaps (resolution decided; SQL deferred to post-spec approval)

1. **REQUIRED NEW MIGRATION `0005_analysis_results.sql`** — a **blocker**, not an afterthought. The
   Structural Analysis agent (002) has **no output table at all**: `Glob db/migrations/*.sql` jumps
   `0004 → 0006`, and `0006`/`0008` header comments reference `analysis_results (migration 0005)` as
   if it exists. Risk (003) and Report (004) both read it (`source_analysis_ids`), so the whole
   downstream chain is contract-dangling. The new `0005` must carry: the SA output contract fields
   (SA FR-13 §383–391 — `outcome`, `reason_code`, result values, `source_validated_ids`,
   `input_version`, `interpolated_input`/`clock_drift`/`rate_mismatch` flags, `config_version` +
   constants), **append+supersede + DELETE-block** discipline (SA FR-8/FR-16), its own idempotency
   index keyed `(sensor, calculation, block, input_version)`, and the tenancy link (§below).
   *Migration deferred until the DB spec is approved.*

2. **REQUIRED TENANCY FOUNDATION — three new tables everything else references.** `municipality_id`
   exists in **no** table today, and `raw_readings`/`validated_readings` carry only `sensor_id` (no
   `bridge_id`). Without these FKs, RLS cannot be enforced — and CLAUDE.md **Principle III
   (municipality-scoped isolation)** + backend AC-3 require it. The foundation (behaviour fixed here,
   SQL deferred):
   - **`municipalities`** — `id`, `name`, `created_at`.
   - **`bridges`** — `id`, `municipality_id → municipalities`, `name`, `location`, `created_at`.
   - **`sensors`** — `id`, `bridge_id → bridges`, `sensor_type`, `config`, `created_at`.
   These are the root of the ownership chain **`municipalities → bridges → sensors → readings`**.
   Every downstream table becomes tenant-attributable through it: sensor-keyed tables
   (`raw_readings`, `validated_readings`, `analysis_results`) resolve tenancy via
   `sensor_id → sensors.bridge_id → bridges.municipality_id`; bridge-keyed judgment tables
   (`risk_assessments`, `report_artifacts`, `alert_dispatches`) via `bridge_id → bridges.municipality_id`.
   RLS policies key on the principal's `municipality_id`. *Tables/SQL deferred until spec approval.*

3. **STACK-CONFLICT HEADERS — FIXED (comment-only, this change).** `db/migrations/0001_raw_readings.sql`
   and `0004_decision_log.sql` headers previously said "Supabase / PostgreSQL" and "TimescaleDB
   extension MAY be enabled" (v2.0.0 era). Both now read **Neon / PostgreSQL, standard B-tree indexes
   only — NO TimescaleDB**, matching `0006`/`0008`/`0010` (v2.1.0) and CLAUDE.md. No logic touched
   (grants, triggers, indexes, columns unchanged). The remaining CLAUDE.md Reconciliation stack
   question (Agents-SDK vs. deterministic, etc.) is still a human decision, but the migration headers
   no longer diverge on the datastore.

### Remaining (non-blocking) design questions for the DB spec

4. **Decide soft-ref vs hard-FK** for the provenance *arrays* (`source_raw_ids`,
   `source_validated_ids`, `source_analysis_ids`) — currently all deliberately soft (Principle III
   decoupling). The new tenancy FKs (§2) and `superseded_by` self-refs **are** hard FKs; the
   provenance arrays are the open call.
5. Consider a `policy_version` audit stamp for `alert_dispatches` (currently absent).
