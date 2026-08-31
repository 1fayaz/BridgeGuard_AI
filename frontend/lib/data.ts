export type Severity = "SAFE" | "WATCH" | "WARNING" | "CRITICAL";
export type ReviewStatus = "FINAL" | "PENDING_HUMAN_REVIEW";

export interface Alert {
  severity: Severity;
  message: string;
  timestamp?: string;
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
}

export const BRIDGES: Bridge[] = [
  {
    id: "bridge-indus-khi-hyd",
    name: "Indus River Bridge — KHI-HYD",
    location: "Karachi-Hyderabad Highway, Sindh",
    risk_score: 82,
    severity: "CRITICAL",
    explanation:
      "The Indus River Bridge on the KHI-HYD Highway is showing vibration levels 9 times above its normal baseline, triggered by heavy truck convoys crossing simultaneously. The steel girders are absorbing repeated stress above their design tolerance. Recent monsoon flooding has raised concerns about scour erosion around the pier foundations. Immediate engineering inspection recommended within 48 hours.",
    review_status: "PENDING_HUMAN_REVIEW",
    chips: [
      { label: "Vibration ↑↑", warn: true },
      { label: "Scour risk", warn: true },
    ],
    alerts: [
      {
        severity: "CRITICAL",
        message:
          "Vibration 9x above normal. Heavy truck convoy detected. Engineer sign-off required.",
        timestamp: "Today, 09:42",
      },
      {
        severity: "WARNING",
        message: "Deflection approaching design limit L/650 vs limit L/800.",
        timestamp: "Today, 08:15",
      },
    ],
  },
  {
    id: "bridge-kotri-01",
    name: "Kotri Bridge",
    location: "Hyderabad, Sindh",
    risk_score: 64,
    severity: "WARNING",
    explanation:
      "Crack growth detected on the main girder. Rate above acceptable threshold of 0.1mm per month. Current crack width 2.3mm. Inspection within 14 days recommended.",
    review_status: "FINAL",
    chips: [
      { label: "Crack +0.3mm", warn: true },
      { label: "Vibration OK", warn: false },
    ],
    alerts: [
      {
        severity: "WARNING",
        message:
          "Crack growth rate above acceptable threshold. Inspection within 14 days.",
        timestamp: "Yesterday, 16:20",
      },
    ],
  },
  {
    id: "bridge-sukkur-01",
    name: "Sukkur Barrage Bridge",
    location: "Sukkur, Sindh",
    risk_score: 41,
    severity: "WATCH",
    explanation:
      "Gradual vibration increase over 30-day trend. Still within design limits. Monitor closely.",
    review_status: "FINAL",
    chips: [
      { label: "Traffic ↑", warn: false },
      { label: "Sensors OK", warn: false },
    ],
    alerts: [],
  },
  {
    id: "bridge-guddu-01",
    name: "Guddu Barrage Bridge",
    location: "Kashmore, Sindh",
    risk_score: 18,
    severity: "SAFE",
    explanation:
      "All readings within normal range. No structural concerns detected. Next review in 30 days.",
    review_status: "FINAL",
    chips: [{ label: "All sensors OK", warn: false }],
    alerts: [],
  },
];

export const getBridge = (id: string) => BRIDGES.find((b) => b.id === id);

export interface Reading {
  time: string;
  rms: number;
}

// Deterministic pseudo-random readings so server and client render identically.
export function generateReadings(severity: Severity, seedKey: string): Reading[] {
  let seed = seedKey.split("").reduce((acc, c) => acc + c.charCodeAt(0), 0) || 1;
  const rand = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  return Array.from({ length: 50 }, (_, i) => ({
    time: `${String(Math.floor(i / 6)).padStart(2, "0")}:${String((i % 6) * 10).padStart(2, "0")}`,
    rms:
      i > 30 && severity === "CRITICAL"
        ? parseFloat((2.5 + rand() * 0.8).toFixed(3))
        : parseFloat((0.3 + rand() * 0.15).toFixed(3)),
  }));
}
