# Configuring the Report Generation Agent — presentation & safety numbers are **config, not code**

Everything a human needs to set to make a real report — the layout, the headline wording, the
raw-data depth, and how strict the anti-drift check is — lives in **configuration objects**, never
in the assembly, gate, render, or service logic. You change a report by editing config; you do
**not** touch `assembler.py`, `fidelity.py`, `service.py`, `marks.py`, or the render modules.

This is deliberate: presentation and safety values for a government artifact must be reviewable and
changeable without a code change, and must be **visibly unset** until a human supplies them. Unset
values are `TODO`/`NaN`/`None` sentinels — **do not guess** a value for a safety-critical system.

## The two config objects

### `ReportConfig` (`config/report_config.py`)

| Field | What it controls | Default / status |
|-------|------------------|------------------|
| `report_template_version` | Audit stamp — WHICH template a report used (for reproducibility) | required, concrete |
| `fidelity_tolerance` | How far a printed number may differ from its source (the anti-drift knob) | `0.0` = exact match (the fail-safe) |
| `appendix_max_rows` | The raw-data appendix depth bound (caps memory) | **TODO** (`NaN`) — do not guess |
| `letterhead_ref` | The government letterhead asset | **TODO** (`None`) |
| `template_ref` | The report layout template | **TODO** (`None`) |

`is_fully_configured` is `False` until `template_ref`, `letterhead_ref`, and `appendix_max_rows` are
supplied — and it fails if `fidelity_tolerance` is blanked from its safe default. You cannot
accidentally disable the anti-drift check.

### `HeadlineTable` (`config/headline_table.py`)

The **only** non-copied text in the whole report: a fixed severity→**headline** phrase, a pure
lookup (no model). Set one phrase per band plus the withheld-report phrase:

| Knob | What it controls |
|------|------------------|
| `phrases` (SAFE / WATCH / WARNING / CRITICAL) | the exec-summary headline for each band |
| `withheld_phrase` | the headline when the assessment withheld its score |

Any unset band returns a loud `TODO-UNSET-HEADLINE` sentinel — never a guessed phrase.

## How to change common things (config only, no code change)

- **Change the report layout / letterhead** → set `template_ref` / `letterhead_ref` and bump
  `report_template_version`. No render code changes.
- **Reword a severity headline** → edit the `HeadlineTable.phrases` entry for that band. The wording
  changes with the config, never with the data.
- **Change the appendix depth** → set `appendix_max_rows`. The reader honours the bound and flags
  truncation ("showing N of M").
- **Adjust anti-drift strictness** → set `fidelity_tolerance`. Keep it `0.0` (exact) unless a
  reviewer has a specific rounding rule; a looser value can only admit more numbers, so never guess
  one for a safety control.

## What you must NOT touch

The deterministic logic is fixed and must stay untouched when tuning:

- `assembler.py` — copies finalized values into the report model (assemble, never re-decide).
- `fidelity.py` — the exact-match, fail-closed anti-drift gate.
- `service.py` — the orchestrator (`run_report`): resolve → assemble → gate → render → persist.
- `marks.py`, `render/…` — mark determination and the ReportLab/matplotlib rendering.

If a change seems to need editing one of these, it is a **spec change**, not tuning — take it back
to `specs/report-generation-agent/`.

## Discipline

- Safety/presentation numbers stay **`TODO`** until a human supplies them — **do not guess**.
- `fidelity_tolerance` defaults to the strictest safe value (`0.0`); loosening it is a reviewed
  decision, not a convenience.
