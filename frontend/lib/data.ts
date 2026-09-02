export type Severity = "SAFE" | "WATCH" | "WARNING" | "CRITICAL";
export type ReviewStatus = "FINAL" | "PENDING_HUMAN_REVIEW";

export interface Alert {
  id: string;
  severity: Severity;
  message: string;
  time: string;
}

export interface Bridge {
  id: string;
  name: string;
  location: string;
  risk_score: number;
  severity: Severity;
  explanation: string;
  review_status: ReviewStatus;
  chips: { label: string; warn: boolean }[];
  alerts: Alert[];
  current_rms: number;
  sensor_id: string;
}

export const SEVERITY_CONFIG: Record<
  Severity,
  {
    label: string;
    color: string;
    bg: string;
    text: string;
    border: string;
    ring: string;
    icon: string;
  }
> = {
  SAFE: {
    label: "Safe",
    color: "bg-emerald-500",
    bg: "bg-emerald-50/80",
    text: "text-emerald-800",
    border: "border-emerald-200",
    ring: "ring-emerald-500/20",
    icon: "🟢",
  },
  WATCH: {
    label: "Watch",
    color: "bg-amber-400",
    bg: "bg-amber-50/80",
    text: "text-amber-800",
    border: "border-amber-200",
    ring: "ring-amber-500/20",
    icon: "🟡",
  },
  WARNING: {
    label: "Warning",
    color: "bg-orange-500",
    bg: "bg-orange-50/80",
    text: "text-orange-800",
    border: "border-orange-200",
    ring: "ring-orange-500/20",
    icon: "🟠",
  },
  CRITICAL: {
    label: "Critical",
    color: "bg-rose-600",
    bg: "bg-rose-50/80",
    text: "text-rose-800",
    border: "border-rose-200",
    ring: "ring-rose-500/20",
    icon: "🔴",
  },
};

export const AGENT_PIPELINE = [
  {
    name: "Ingestion Agent",
    role: "Collects raw accelerometer & strain data from IoT edge nodes along the Indus corridor.",
  },
  {
    name: "Signal Agent",
    role: "Cleans gaps, filters noise, and flags interpolated points for full traceability.",
  },
  {
    name: "Risk Agent",
    role: "Computes the 0-100 risk score and writes a human-readable engineering explanation.",
  },
  {
    name: "Alert Agent",
    role: "Raises WATCH, WARNING, or CRITICAL alerts when thresholds are crossed.",
  },
  {
    name: "Report Agent",
    role: "Generates downloadable PDF/TXT audit reports for maintenance teams and regulators.",
  },
];

export const BRIDGES: Bridge[] = [
  {
    id: "bridge-sukkur-01",
    name: "Sukkur Barrage Bridge",
    location: "Sukkur, Sindh",
    risk_score: 14,
    severity: "SAFE",
    explanation:
      "Vibration RMS is stable and within safe limits. No structural anomalies detected in the last 24 hours across the barrage approach spans.",
    review_status: "FINAL",
    chips: [
      { label: "RMS 0.45", warn: false },
      { label: "No alerts", warn: false },
    ],
    alerts: [],
    current_rms: 0.45,
    sensor_id: "sensor-sukkur-01",
  },
  {
    id: "bridge-guddu-01",
    name: "Guddu Barrage Bridge",
    location: "Guddu, Sindh",
    risk_score: 36,
    severity: "WATCH",
    explanation:
      "Minor vibration increase during peak river-flow hours. Pattern matches hydrological load, not structural degradation.",
    review_status: "FINAL",
    chips: [
      { label: "RMS 1.08", warn: true },
      { label: "1 watch", warn: true },
    ],
    alerts: [
      {
        id: "alert-guddu-01",
        severity: "WATCH",
        message: "Flow-induced RMS elevated above weekly baseline.",
        time: "14:20",
      },
    ],
    current_rms: 1.08,
    sensor_id: "sensor-guddu-01",
  },
  {
    id: "bridge-indus-hwy-01",
    name: "Indus Highway (Hyd-Khi) Bridge",
    location: "Near Hyderabad, Sindh",
    risk_score: 69,
    severity: "WARNING",
    explanation:
      "Repeated peak accelerations exceed the warning threshold on the heavy-traffic carriageway. Recommend manual inspection within 48 hours.",
    review_status: "PENDING_HUMAN_REVIEW",
    chips: [
      { label: "RMS 2.52", warn: true },
      { label: "3 alerts", warn: true },
    ],
    alerts: [
      {
        id: "alert-indus-01",
        severity: "WARNING",
        message: "Peak acceleration 2.9x baseline detected on lane 2.",
        time: "10:05",
      },
      {
        id: "alert-indus-02",
        severity: "WARNING",
        message: "Strain gauge delta increased 19% overnight.",
        time: "06:15",
      },
      {
        id: "alert-indus-03",
        severity: "WATCH",
        message: "Traffic-induced resonance detected briefly.",
        time: "16:40",
      },
    ],
    current_rms: 2.52,
    sensor_id: "sensor-indus-hwy-01",
  },
  {
    id: "bridge-kotri-01",
    name: "Kotri Barrage Bridge",
    location: "Kotri, Sindh",
    risk_score: 93,
    severity: "CRITICAL",
    explanation:
      "Sustained high-amplitude vibrations and rapid strain growth on the downstream cantilever. Immediate engineering review and potential load restriction advised.",
    review_status: "PENDING_HUMAN_REVIEW",
    chips: [
      { label: "RMS 4.85", warn: true },
      { label: "2 critical", warn: true },
    ],
    alerts: [
      {
        id: "alert-kotri-01",
        severity: "CRITICAL",
        message: "Critical RMS sustained above 4.8 for 12 minutes.",
        time: "08:35",
      },
      {
        id: "alert-kotri-02",
        severity: "CRITICAL",
        message: "Maximum strain increased 36% in last 4 hours.",
        time: "08:10",
      },
    ],
    current_rms: 4.85,
    sensor_id: "sensor-kotri-01",
  },
];

export function generateReadings(severity: Severity) {
  const count = 50;
  const base =
    severity === "SAFE"
      ? 0.4
      : severity === "WATCH"
      ? 1.1
      : severity === "WARNING"
      ? 2.5
      : 4.7;
  const points = [];
  for (let i = 0; i < count; i++) {
    points.push({
      time: `${i * 5}s`,
      value: Number(
        (base + (Math.random() - 0.5) * base * 0.6 + Math.sin(i / 4) * 0.2).toFixed(2)
      ),
    });
  }
  return points;
}
