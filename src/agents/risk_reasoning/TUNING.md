# Tuning the Risk Reasoning Agent — weights, floor, and bands (config only)

Every safety number the agent uses is **configuration, not code**. You change the score weights,
the ratio→0–100 normalisation, the severity band cut-points, the coverage floor, the completeness
formula, and the guardrail match tolerance by editing **`config/score_config.py`** and
**`config/coverage_config.py`** — **touching no scorer, band, coverage, guardrail, or agent code.**

> **Why config, not code (Constitution IV).** In a safety-critical system the numbers that decide
> whether a bridge is `CRITICAL` must be supplied and reviewed by a **structural engineer**, not
> baked into logic where they hide. Every such number ships as a `TODO`/`NaN` sentinel and is
> **loudly flagged unset** — `ScoreConfig.is_fully_configured` / `CoverageConfig.is_fully_configured`
> return `False` until a real value is supplied. **Do not guess a safety number.** An unset value
> makes the agent *withhold and route to human review*, which is safe; a *guessed* value produces a
> confident-looking wrong verdict, which is the failure mode this discipline exists to prevent.

The scorer (`scorer.py`), band mapping (`band.py`), coverage gate (`coverage.py`), completeness
(`completeness.py`), guardrail (`guardrail.py`), and agent (`agent.py`) read these values — they
never hardcode them. `test_r1103` asserts the scorer's import graph pulls in **no** model/SDK and
depends only on the config + typed results, so a config change can never require a code change.

---

## What lives where

| Knob | Field (config file) | Ships as | Consumed by |
|---|---|---|---|
| Per-factor weights | `ScoreConfig.weights` — `((factor_name, weight), …)` | empty `()` | `score_bridge` |
| Ratio → 0–100 normalisation | `ScoreConfig.ratio_at_zero_score`, `ratio_at_full_score` | `NaN` (`TODO`) | `normalise_ratio` |
| Severity band cut-points | `ScoreConfig.watch_min`, `warning_min`, `critical_min` | `NaN` (`TODO`) | `severity_for` |
| Near-boundary margin (annotation) | `ScoreConfig.band_near_margin` | `NaN` (`TODO`) | `severity_for` (flag only) |
| Coverage floor (score vs. withhold) | `CoverageConfig.coverage_floor` | `NaN` (`TODO`) | `coverage_check` / `meets_floor` |
| Completeness formula | `CoverageConfig.completeness_full_fraction` | `NaN` (`TODO`) | `data_completeness` |
| Guardrail match tolerance | `guardrail_tolerance` arg (default `0.0`) | exact-match | `provenance_guardrail` |
| Audit stamp (NOT a safety number) | `ScoreConfig.score_weights_version` | concrete string | pinned onto every row (FR-10) |

---

## 1. Change a score weight (`ScoreConfig.weights`)

Weights are `(factor_name, weight)` pairs; `factor_name` matches the SA calculation, lower-cased
(e.g. `"rms"`, `"deflection"`). A factor with **no** configured weight is recorded as a gap and
excluded from the score — never silently guessed.

```python
ScoreConfig(
    score_weights_version="rev2",           # BUMP this stamp whenever weights change (FR-10)
    weights=(("rms", 0.4), ("deflection", 0.6)),
    ...
)
```

The score is `round(Σ(weightᵢ · normalisedᵢ) / Σ weightᵢ)` — a weighted average over the scorable,
weighted factors. Reordering the pairs never changes the score (order-independent combine).
**Always bump `score_weights_version`** so old assessments remain reproducible against the weights
they actually used.

## 2. Change the ratio → 0–100 normalisation

`normalise_ratio` maps a result's `value/limit` ratio linearly onto 0–100, clamped, between two
bounds: `ratio_at_zero_score` (ratio mapping to 0) and `ratio_at_full_score` (ratio mapping to 100).

```python
ratio_at_zero_score=0.0,   # a value at 0% of its limit contributes 0
ratio_at_full_score=1.0,   # a value AT its limit contributes 100
```

While either bound is `NaN`, `normalise_ratio` returns a **not-scorable** signal (never a guessed
number), which propagates to a withheld assessment.

## 3. Change the severity bands (`watch_min` / `warning_min` / `critical_min`)

Cut-points are the **minimum score** for each band above `SAFE`. A score **on** a cut-point maps to
the **higher** band (`>=`).

```python
watch_min=25.0,     # >=25 -> at least WATCH
warning_min=50.0,   # >=50 -> at least WARNING
critical_min=75.0,  # >=75 -> CRITICAL
band_near_margin=3.0,  # optional: a score within 3 of a cut-point is flagged near_boundary
```

While any cut-point is `NaN`, `severity_for` raises `BandNotConfigured` rather than guess a band.
`band_near_margin` is **annotation only** — it sets `near_boundary` for the explanation but never
moves the band, and it does **not** gate `is_fully_configured`.

## 4. Change the coverage floor (`CoverageConfig.coverage_floor`)

The minimum fraction of the bridge's **expected** calculations that must have `RAN` before a score
is emitted vs. withheld to `PENDING_HUMAN_REVIEW`.

```python
CoverageConfig(coverage_floor=0.6, completeness_full_fraction=1.0)
# -> below 60% RAN coverage (or standard missing) => withhold + route to human review
```

While `coverage_floor` is `NaN`, `meets_floor` is always `False` — the agent **withholds** rather
than score on an unset floor. `require_standard_present` defaults `True` (a non-physical policy,
not a safety number): scoring always requires the applicable standard present.

## 5. Change the completeness formula (`completeness_full_fraction`)

`data_completeness` is the deterministic confidence annotation. **It never moves the score**
(FR-6a) — it only annotates the assessment and feeds the withhold decision. Changing it cannot
change a `risk_score`.

## 6. Change the guardrail match tolerance

Passed to `assess_bridge(..., guardrail_tolerance=…)`; default `0.0` (exact-match). A rounding
tolerance widens what counts as "traces to a real input". Keep it **as tight as possible** — the
default can only *reject* more numbers, never *accept* a fabrication; a loose tolerance risks
letting an invented number pass. This is why it is not defaulted to a guessed non-zero value.

---

## What you must NOT touch

Changing any number above requires **config edits only**. You should **not** edit:

- `scorer.py`, `band.py`, `coverage.py`, `completeness.py` — the deterministic logic reads config;
- `guardrail.py` — the anti-hallucination control;
- `orchestrator.py`, `agent.py`, `service.py` — the wiring.

If a tuning change seems to *need* a code edit, the value was probably hardcoded by mistake — treat
that as a bug in the code, not a reason to edit logic here. **No code change** should be needed to
supply or adjust a safety number.

## Checklist for supplying the real (currently `TODO`) values

1. A structural engineer supplies each `NaN` field from the applicable standard / `math-analysis`
   config. **Do not guess.**
2. Bump `score_weights_version` whenever weights or normalisation change (keeps FR-10 reproducibility).
3. Confirm `ScoreConfig.is_fully_configured` and `CoverageConfig.is_fully_configured` are both
   `True` before the agent is trusted to *score* (until then it safely withholds).
4. Re-run `tests/risk_reasoning/` — the logic is unchanged, so all tests stay green with the new
   values; only the fixture numbers in tests differ from production config.
