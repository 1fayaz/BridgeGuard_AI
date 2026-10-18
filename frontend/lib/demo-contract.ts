// Types + data access for the demo feature, matching the frozen API Contract in
// specs/005-demo-mode-and-approval/spec.md. Do not change these shapes without updating the
// spec first — the backend session owns the contract.

export type ExplanationKind = "live_ai" | "pregenerated_ai" | "template_fallback";

export interface StageStatus {
  helper_name: string;
  plain_text: string;
  done: boolean;
  completed_at: string | null;
  awaiting_engineer?: boolean;
}

export interface PipelineStatusResponse {
  bridge_id: string;
  cycle_id: string;
  is_demo: boolean;
  stages: {
    ingestion: StageStatus;
    signal: StageStatus;
    risk: StageStatus;
    alert: StageStatus;
    report: StageStatus;
  };
}

export interface ScoreTraceResponse {
  bridge_id: string;
  is_demo: boolean;
  assessment_id: number;
  risk_score: number;
  severity: "SAFE" | "WATCH" | "WARNING" | "CRITICAL";
  review_status: string;
  bridge_status: string;
  sensor_offline_note: boolean;
  reading: { sensor_id: string; value: number; unit: string; sensor_time: string };
  limit: { value: number | null; ratio: number | null; basis_label: string; is_configured: boolean };
  explanation: { text: string; kind: ExplanationKind; source_label: string };
}

export interface ApproveResponse {
  alert_dispatch_id: string;
  approval_state: "APPROVED" | "REJECTED";
  approved_by: string;
  approved_at: string;
  note: string | null;
  delivery_state: string | null;
  notification_status: string | null;
}

export interface SimulateResponse {
  cycle_id: string;
  status: string;
  is_demo: boolean;
}

export interface ErrorResponse {
  error: string;
  code: string;
  detail: string;
  correlation_id: string;
}

export interface ReplayTimelineEntry {
  at_ms: number;
  endpoint: string;
  response: SimulateResponse | PipelineStatusResponse | ScoreTraceResponse | ApproveResponse;
}

export interface ReplayFile {
  recorded: boolean;
  generated_at: string;
  bridge_id: string;
  cycle_id: string;
  is_demo: boolean;
  timeline: ReplayTimelineEntry[];
}

export const EXPLANATION_LABELS: Record<ExplanationKind, string> = {
  live_ai: "Written by AI. Not edited.",
  pregenerated_ai: "AI-written explanation, generated in advance for this scenario.",
  template_fallback: "Template explanation: AI unavailable.",
};

export const DEMO_STATE_NOT_FOUND_MESSAGE = "Press Simulate again.";

// --- REPLAY mode: the ONLY network call replay mode is allowed to make. No backend, no login. ---
export async function loadReplayTimeline(
  fetchImpl: typeof fetch = fetch,
): Promise<ReplayFile> {
  const res = await fetchImpl("/replay/demo-run.json");
  if (!res.ok) throw new Error(`could not load replay data: HTTP ${res.status}`);
  return (await res.json()) as ReplayFile;
}

// --- LIVE mode: real backend calls. Never invoked unless NEXT_PUBLIC_DEMO_MODE_ENABLED === "true". ---
const liveBase = () => process.env.NEXT_PUBLIC_API_URL || "";
const liveToken = () => process.env.NEXT_PUBLIC_DEMO_TOKEN || "";

async function liveFetch<T>(path: string, init?: RequestInit): Promise<T | { __error: ErrorResponse }> {
  const res = await fetch(`${liveBase()}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${liveToken()}`,
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
  });
  const body = await res.json();
  if (!res.ok) return { __error: body as ErrorResponse };
  return body as T;
}

export function isDemoStateNotFound(result: unknown): result is { __error: ErrorResponse } {
  return (
    typeof result === "object" &&
    result !== null &&
    "__error" in result &&
    (result as { __error: ErrorResponse }).__error.detail === DEMO_STATE_NOT_FOUND_MESSAGE
  );
}

export const liveApi = {
  simulate: () => liveFetch<SimulateResponse>("/v1/demo/simulate-heavy-truck", { method: "POST" }),
  reset: () => liveFetch<SimulateResponse>("/v1/demo/reset", { method: "POST" }),
  pipelineStatus: (bridgeId: string, cycleId: string) =>
    liveFetch<PipelineStatusResponse>(`/v1/bridges/${bridgeId}/pipeline-status?cycle_id=${cycleId}`),
  scoreTrace: (bridgeId: string) =>
    liveFetch<ScoreTraceResponse>(`/v1/bridges/${bridgeId}/score-trace`),
  approve: (alertId: string, note?: string) =>
    liveFetch<ApproveResponse>(`/v1/alerts/${alertId}/approve`, {
      method: "POST",
      body: JSON.stringify({ note: note ?? null }),
    }),
  reject: (alertId: string, note?: string) =>
    liveFetch<ApproveResponse>(`/v1/alerts/${alertId}/reject`, {
      method: "POST",
      body: JSON.stringify({ note: note ?? null }),
    }),
};

export function isLiveModeEnabled(): boolean {
  return process.env.NEXT_PUBLIC_DEMO_MODE_ENABLED === "true";
}

export const DEMO_BRIDGE_NAME = "Demonstration Bridge";
export const REPLAY_BANNER = "Replay of a recorded demonstration run. Demonstration data.";
export const REPLAY_APPROVAL_DISCLAIMER = "Replay: no real approval is recorded.";
