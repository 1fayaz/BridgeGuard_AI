import type { Severity } from "./data";
import type { ResearchConditionKey } from "./research-data";

/** The "in the style of the old Vercel version" demo assignment: familiar bridge names/locations
 * as display labels for cards that are explicitly, repeatedly disclosed as replaying real
 * research recordings - never claimed as live readings from these bridges. Overview, Reports,
 * and Alerts all import this one mapping so every page agrees. */
export interface NamedBridge {
  id: string;
  name: string;
  location: string;
  sensorId: string;
  conditionKey: ResearchConditionKey;
}

export const NAMED_BRIDGES: NamedBridge[] = [
  { id: "bridge-kotri-01", name: "Kotri Barrage Bridge", location: "Kotri, Sindh", sensorId: "acc-kotri-01", conditionKey: "danger" },
  { id: "bridge-indus-hwy-01", name: "Indus Highway (Hyd-Khi) Bridge", location: "Near Hyderabad, Sindh", sensorId: "acc-indus-hwy-01", conditionKey: "moderate" },
  { id: "bridge-guddu-01", name: "Guddu Barrage Bridge", location: "Guddu, Sindh", sensorId: "acc-guddu-01", conditionKey: "little_moderate" },
  { id: "bridge-sukkur-01", name: "Sukkur Barrage Bridge", location: "Sukkur, Sindh", sensorId: "acc-sukkur-01", conditionKey: "safe" },
];

/** Computed by scripts/demo/compute_overview_scores.py via the real deterministic scorer
 * (agents.risk_reasoning.scorer/.band) from each card's real ratio_vs_reference - never
 * hand-typed. See frontend/public/replay/research/overview-scores.json. */
export interface OverviewScoreEntry {
  ratio_vs_reference: number;
  risk_score: number;
  severity: Severity;
  computed_with: string;
}

export async function loadOverviewScores(
  fetchImpl: typeof fetch = fetch,
): Promise<Partial<Record<ResearchConditionKey, OverviewScoreEntry>>> {
  try {
    const res = await fetchImpl("/replay/research/overview-scores.json");
    if (!res.ok) return {};
    return (await res.json()) as Partial<Record<ResearchConditionKey, OverviewScoreEntry>>;
  } catch {
    return {};
  }
}
