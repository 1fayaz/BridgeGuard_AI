import { SEVERITY_CONFIG, RESEARCH_STATUS_CONFIG } from "./data";
import { NAMED_BRIDGES } from "./named-bridges";
import { loadAllResearchConditions, normalizeStatus } from "./research-data";
import { EXPLANATION_LABELS, loadReplayTimeline, type ScoreTraceResponse } from "./demo-contract";
import type { AlertRecord } from "./alert-store";

/** Builds the 6 seed alerts from real data only - 4 from the research conditions (one per named
 * bridge, see lib/named-bridges.ts), 1 from the simulated truck scenario's real score-trace, and
 * 1 from the real time-of-day finding recorded alongside the Reference State condition
 * (night_reference_note - a genuine secondary finding in that file, not an invented 6th number).
 *
 * Action type: SAFE / LITTLE_MODERATE conditions are informational (Acknowledge / Dismiss);
 * MODERATE / DANGER and the simulated scenario require a human decision (Approve / Reject),
 * matching the project's human-in-the-loop rule for anything past "watch" severity. */
export async function buildAlertSeed(fetchImpl: typeof fetch = fetch): Promise<AlertRecord[]> {
  const [conditions, replay] = await Promise.all([
    loadAllResearchConditions(fetchImpl),
    loadReplayTimeline(fetchImpl).catch(() => null),
  ]);

  const alerts: AlertRecord[] = [];

  for (const bridge of NAMED_BRIDGES) {
    const data = conditions[bridge.conditionKey];
    if (!data) continue;
    const status = normalizeStatus(data.status);
    const cfg = RESEARCH_STATUS_CONFIG[status];
    const needsApproval = status === "MODERATE" || status === "DANGER";
    alerts.push({
      id: `research-${bridge.conditionKey}`,
      bridgeName: bridge.name,
      severityLabel: cfg.label,
      severityBar: cfg.bar,
      severityBgHex: cfg.bgHex,
      severityTextHex: cfg.textHex,
      source: "research",
      metric: `${data.ratio_vs_reference.toFixed(2)}x baseline`,
      explanationText: data.status_rule,
      explanationLabel: "Rule-based status (not AI-written)",
      time: data.window.measurement_date,
      actionType: needsApproval ? "approve-reject" : "acknowledge-dismiss",
      status: "open",
    });
  }

  // The real secondary finding already present in safe.json - not a fabricated 6th number.
  const safeData = conditions.safe;
  if (safeData) {
    alerts.push({
      id: "research-time-of-day",
      bridgeName: NAMED_BRIDGES.find((b) => b.conditionKey === "safe")?.name ?? "Sukkur Barrage Bridge",
      severityLabel: "Info",
      severityBar: "#6B7B8C",
      severityBgHex: "#EBEEF2",
      severityTextHex: "#3D4A59",
      source: "research",
      metric: "Night recording 10x quieter",
      explanationText: safeData.night_reference_note,
      explanationLabel: "Time-of-day finding (not AI-written)",
      time: safeData.window.measurement_date,
      actionType: "acknowledge-dismiss",
      status: "open",
    });
  }

  const traceEntry = replay?.timeline.find((e) => e.endpoint.includes("score-trace"));
  const trace = traceEntry?.response as ScoreTraceResponse | undefined;
  if (trace) {
    const cfg = SEVERITY_CONFIG[trace.severity];
    alerts.push({
      id: "simulated-truck",
      bridgeName: "Demonstration Bridge",
      severityLabel: cfg.label,
      severityBar: cfg.bar,
      severityBgHex: cfg.bgHex,
      severityTextHex: cfg.textHex,
      source: "simulated",
      metric: `${trace.risk_score}/100`,
      explanationText: trace.explanation.text,
      explanationLabel: trace.explanation.source_label ?? EXPLANATION_LABELS[trace.explanation.kind],
      time: "Simulated scenario",
      actionType: "approve-reject",
      status: "open",
    });
  }

  return alerts;
}
