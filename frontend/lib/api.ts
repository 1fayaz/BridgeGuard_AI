import type { Bridge, Alert } from "./data";

const BASE = process.env.NEXT_PUBLIC_API_URL || "";
const TOKEN = process.env.NEXT_PUBLIC_DEMO_TOKEN || "demo-token-hackathon";

const AUTH_HEADERS = {
  Authorization: `Bearer ${TOKEN}`,
  "Content-Type": "application/json",
} as const;

export async function fetchBridges(): Promise<Bridge[] | null> {
  try {
    const res = await fetch(`${BASE}/v1/bridges`, { headers: AUTH_HEADERS });
    if (!res.ok) return null;
    return (await res.json()) as Bridge[];
  } catch {
    return null;
  }
}

export async function fetchBridgeRisk(
  bridgeId: string,
): Promise<{
  bridge_id: string;
  risk_score: number;
  severity: string;
  explanation: string;
  review_status: string;
  assessed_at: string;
  avg_rms: number | null;
  sample_count: number;
} | null> {
  try {
    const res = await fetch(`${BASE}/v1/bridges/${bridgeId}/risk`, {
      headers: AUTH_HEADERS,
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function fetchReadings(
  bridgeId: string,
  sensorId: string,
  limit = 50,
): Promise<{ sensor_time: string; value: number }[] | null> {
  try {
    const res = await fetch(
      `${BASE}/v1/bridges/${bridgeId}/sensors/${sensorId}/readings?limit=${limit}`,
      { headers: AUTH_HEADERS },
    );
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

export async function fetchAlerts(
  bridgeId: string,
): Promise<Alert[] | null> {
  try {
    const res = await fetch(`${BASE}/v1/bridges/${bridgeId}/alerts`, {
      headers: AUTH_HEADERS,
    });
    if (!res.ok) return null;
    return (await res.json()) as Alert[];
  } catch {
    return null;
  }
}

export async function ingestReading(
  payload: { readings: Record<string, unknown>[] },
  apiKey: string,
): Promise<{
  accepted_count: number;
  rejected_count: number;
  results: { index: number; accepted: boolean; reason?: string }[];
} | null> {
  try {
    const res = await fetch(`${BASE}/v1/ingest`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-API-Key": apiKey,
      },
      body: JSON.stringify(payload),
    });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}
