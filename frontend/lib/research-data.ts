import type { ResearchStatus } from "./data";

/** Mirrors the JSON shape written by scripts/demo/prepare_research_data.py and
 * scripts/demo/search_moderate_band.py - do not change field names here without updating
 * those scripts, or the two will drift. */
export interface ResearchConditionFile {
  dataset: {
    name: string;
    authors: string;
    year: number;
    link: string;
    doi: string;
    license: string;
    license_url: string;
    citation: string;
  };
  condition: string;
  damage_note: string;
  sensor: {
    channel: number;
    channel_location: string;
    sensor_model: string;
    sampling_rate_hz: number;
    unit: string;
  };
  window: {
    measurement_date: string;
    duration_s: number;
    excitation: string;
    project: string;
  };
  time_series: { time_s: number[]; value: number[]; note: string };
  rms: number;
  ratio_vs_reference: number;
  status_rule: string;
  status: string; // "SAFE" | "LITTLE MODERATE" | "MODERATE" | "DANGER" (space-separated, as written)
  night_reference_note: string;
  selection_note: string;
}

export const RESEARCH_CONDITION_KEYS = ["safe", "little_moderate", "moderate", "danger"] as const;
export type ResearchConditionKey = (typeof RESEARCH_CONDITION_KEYS)[number];

export const CONDITION_CARD_TITLE: Record<ResearchConditionKey, string> = {
  safe: "Reference state (healthy)",
  little_moderate: "Damage State 1",
  moderate: "Damage State 1",
  danger: "Damage State 2",
};

/** JSON status strings use spaces ("LITTLE MODERATE"); our color config keys use underscores. */
export function normalizeStatus(raw: string): ResearchStatus {
  return raw.trim().replace(/\s+/g, "_") as ResearchStatus;
}

export async function loadResearchCondition(
  key: ResearchConditionKey,
  fetchImpl: typeof fetch = fetch,
): Promise<ResearchConditionFile | null> {
  try {
    const res = await fetchImpl(`/replay/research/${key}.json`);
    if (!res.ok) return null;
    return (await res.json()) as ResearchConditionFile;
  } catch {
    return null;
  }
}

/** Loads whichever condition files actually exist - three or four - never invents a missing one. */
export async function loadAllResearchConditions(
  fetchImpl: typeof fetch = fetch,
): Promise<Partial<Record<ResearchConditionKey, ResearchConditionFile>>> {
  const entries = await Promise.all(
    RESEARCH_CONDITION_KEYS.map(async (key) => [key, await loadResearchCondition(key, fetchImpl)] as const),
  );
  const out: Partial<Record<ResearchConditionKey, ResearchConditionFile>> = {};
  for (const [key, data] of entries) {
    if (data) out[key] = data;
  }
  return out;
}
