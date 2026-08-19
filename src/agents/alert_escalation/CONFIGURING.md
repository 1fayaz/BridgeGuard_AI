# Configuring the Alert & Escalation Agent — policy is config, not code

Everything a stakeholder tunes about *who* gets alerted, *how*, *how hard the system tries*, and
*what the alert says* is **configuration**, held in two frozen dataclasses. You change behaviour by
editing config values — **never** by touching the decision logic. The tiering, consistency gate,
approval gate, escalation ladder, and orchestrator are fixed and shared across every deployment.

> **This is a config-only change: no code change.** If you find yourself editing `tiering.py`,
> `consistency.py`, `approval.py`, `escalation.py`, or `service.py` to change a roster, a channel, a
> retry count, or a message, stop — that value belongs in config.

## The two config objects

- **`AlertPolicy`** (`config/alert_policy.py`) — the operational policy: retry/escalation timing, the
  contact roster + escalation order, the per-band channel, and the authority-recipient set.
- **`MessageTemplateTable`** (`config/message_template_table.py`) — the fixed per-band message
  wording the alert body is built from.

## Safety numbers are `TODO` until a human supplies them — do not guess

`AlertPolicy` follows the same discipline as the Report `ReportConfig` and the Risk `ScoreConfig`: a
value a human must still supply is a **loudly-flagged `TODO` sentinel** (`NaN` for numbers, `None`
for references), never silently defaulted to a plausible value. We do **not** guess an on-call
roster, a retry count, an escalation timeout, or which recipients are authority-facing for a
safety-critical system. `is_fully_configured` is `False` until every field is supplied.

There is **no safe default** here (unlike the report's `fidelity_tolerance`, whose `0.0` is a genuine
safe value): every operational field is a real policy choice, so all of them gate
`is_fully_configured`. The one always-present field is `policy_version` — a non-physical audit stamp
recording *which* policy an alert was dispatched under.

## What you can change (and the field that holds it)

| To change… | Edit this `AlertPolicy` field | Notes |
|------------|-------------------------------|-------|
| the audit stamp for this policy revision | `policy_version` | always concrete (not a safety number) |
| how many times a channel is retried | `retry_max` | `TODO` (`NaN`) until supplied |
| the delay between retries | `backoff_seconds` | `TODO` until supplied |
| how long before an unacked/undelivered alert escalates | `escalation_timeout_seconds` | `TODO` until supplied |
| **who** is notified per band | `contact_roster` | `(band, recipient)` pairs; `None` until supplied |
| the on-call **escalation order** | `escalation_order` | the failover chain, primary first; `None` until supplied |
| **which channel** per band | `channel_per_band` | `(band, channel)` pairs; `None` until supplied |
| which recipients are **authority-facing** | `authority_recipients` | drives the blast-radius override; `None` = undecided, `()` = reviewed-empty |

To change the **alert wording**, edit `MessageTemplateTable.templates` — the `(severity, template)`
pairs. Each template is a format string referencing verdict fields (`{bridge_id}`, `{risk_score}`,
`{severity}`, `{recommendation}`, `{explanation}`); the assembler fills it by **copying** those
values verbatim. An unset band returns the `TODO-UNSET-TEMPLATE` sentinel — never guessed wording.

## The logic files you must NOT touch to make a config change

These implement fixed, shared behaviour. Changing a roster/channel/retry/template must require
**zero** edits here:

- `tiering.py` — the settled severity→approval mapping + the overrides.
- `consistency.py` — the fail-closed contradiction gate.
- `approval.py` — the `needs_approval` chokepoint.
- `escalation.py` — the retry→failover→escalate ladder and the severity-dependent close.
- `service.py` — the `run_alert` orchestrator.

## Worked example — a config-only change

To onboard a new bridge authority as a WARNING-band contact reachable by SMS, retried twice:

1. add `("WARNING", "authority@city.gov")` to `contact_roster`;
2. add `("WARNING", "sms")` to `channel_per_band` (or leave the existing WARNING channel);
3. append `"authority@city.gov"` to `escalation_order` at the right rung;
4. add `"authority@city.gov"` to `authority_recipients` so the blast-radius override fires
   (`NEEDS_APPROVAL` regardless of band);
5. set `retry_max=2`, and supply `backoff_seconds` / `escalation_timeout_seconds`;
6. bump `policy_version`.

No decision-logic module changes. The tiering, gate, and escalation behaviour is identical — only
the policy values differ.
