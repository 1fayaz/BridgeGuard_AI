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
  { label: string; color: string; bg: string; text: string }
> = {
  SAFE: {
    label: "Safe",
    color: "bg-emerald-500",
    bg: "bg-emerald-50",
    text: "text-emerald-700",
  },
  WATCH: {
    label: "Watch",
    color: "bg-yellow-400",
    bg: "bg-yellow-50",
    text: "text-yellow-700",
  },
  WARNING: {
    label: "Warning",
    color: "bg-orange-500",
    bg: "bg-orange-50",
    text: "text-orange-700",
  },
  CRITICAL: {
    label: "Critical",
    color: "bg-red-600",
    bg: "bg-red-50",
    text: "text-red-700",
  },
};

export const AGENT_PIPELINE = [
  {
    name: "Ingestion Agent",
    role: "Collects raw accelerometer & strain data from IoT edge nodes.",
  },
  {
    name: "Signal Agent",
    role: "Cleans gaps, filters noise, flags interpolated points.",
  },
  {
    name: "Risk Agent",
    role: "Computes 0-100 risk score and writes a human explanation.",
  },
  {
    name: "Alert Agent",
    role: "Raises WARNING/CRITICAL when thresholds are crossed.",
  },
  {
    name: "Report Agent",
    role: "Generates downloadable PDF/TXT audit reports on demand.",
  },
];

export const BRIDGES: Bridge[] = [
  {
    id: "bridge-ravi-01",
    name: "Ravi River Bridge",
    location: "Lahore, Punjab",
    risk_score: 12,
    severity: "SAFE",
    explanation:
      "Vibration RMS is stable and within safe limits. No structural anomalies detected in the last 24h.",
    review_status: "FINAL",
    chips: [
      { label: "RMS 0.42", warn: false },
      { label: "No alerts", warn: false },
    ],
    alerts: [],
    current_rms: 0.42,
    sensor_id: "sensor-ravi-01",
  },
  {
    id: "bridge-data-01",
    name: "Data Darbar Underpass",
    location: "Lahore, Punjab",
    risk_score: 38,
    severity: "WATCH",
    explanation:
      "Minor vibration increase during rush hour. Pattern matches traffic load, not structural degradation.",
    review_status: "FINAL",
    chips: [
      { label: "RMS 1.12", warn: true },
      { label: "1 watch", warn: true },
    ],
    alerts: [
      {
        id: "alert-data-01",
        severity: "WATCH",
        message: "Rush-hour RMS elevated above weekly baseline.",
        time: "17:30",
      },
    ],
    current_rms: 1.12,
    sensor_id: "sensor-data-01",
  },
  {
    id: "bridge-mall-01",
    name: "Mall Road Overpass",
    location: "Lahore, Punjab",
    risk_score: 67,
    severity: "WARNING",
    explanation:
      "Repeated peak accelerations exceed the warning threshold. Recommend manual inspection within 48 hours.",
    review_status: "PENDING_HUMAN_REVIEW",
    chips: [
      { label: "RMS 2.45", warn: true },
      { label: "3 alerts", warn: true },
    ],
    alerts: [
      {
        id: "alert-mall-01",
        severity: "WARNING",
        message: "Peak acceleration 2.8x baseline detected.",
        time: "09:15",
      },
      {
        id: "alert-mall-02",
        severity: "WARNING",
        message: "Strain gauge delta increased 18% overnight.",
        time: "06:40",
      },
      {
        id: "alert-mall-03",
        severity: "WATCH",
        message: "Traffic-induced resonance detected briefly.",
        time: "14:22",
      },
    ],
    current_rms: 2.45,
    sensor_id: "sensor-mall-01",
  },
  {
    id: "bridge-thokar-01",
    name: "Thokar Niaz Baig Bridge",
    location: "Lahore, Punjab",
    risk_score: 91,
    severity: "CRITICAL",
    explanation:
      "Sustained high-amplitude vibrations and rapid strain growth. Immediate engineering review and potential traffic restriction advised.",
    review_status: "PENDING_HUMAN_REVIEW",
    chips: [
      { label: "RMS 4.71", warn: true },
      { label: "2 critical", warn: true },
    ],
    alerts: [
      {
        id: "alert-thokar-01",
        severity: "CRITICAL",
        message: "Critical RMS sustained above 4.5 for 10 minutes.",
        time: "08:05",
      },
      {
        id: "alert-thokar-02",
        severity: "CRITICAL",
        message: "Maximum strain increased 34% in last 4 hours.",
        time: "07:50",
      },
    ],
    current_rms: 4.71,
    sensor_id: "sensor-thokar-01",
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
