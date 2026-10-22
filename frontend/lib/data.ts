export type Severity = "SAFE" | "WATCH" | "WARNING" | "CRITICAL" | "UNKNOWN";

/** Status vocabulary for the real research-recording cards (RMS ratio vs. this structure's own
 * healthy baseline) - a different axis from the 0-100 score Severity above, which stays
 * unchanged for the simulated-truck demo scenario. Colours are reused 1:1 from SEVERITY_CONFIG
 * (SAFE/WATCH/WARNING/CRITICAL) rather than invented, per the instruction to reuse SEVERITY_CONFIG
 * colours; "LITTLE_MODERATE" gets WATCH's amber. */
export type ResearchStatus = "SAFE" | "LITTLE_MODERATE" | "MODERATE" | "DANGER";
export type ReviewStatus = "FINAL" | "PENDING_HUMAN_REVIEW";

/** Where a page's displayed numbers actually came from. Shown via <DataSourceBadge>; never
 * implied silently — a reader must always be able to tell sample data from a live backend. */
export type DataSource = "sample" | "live" | "live-unavailable";

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
  last_seen: string;
  maintenance_log: {
    date: string;
    inspector: string;
    finding: string;
    action: string;
  }[];
}

export const SEVERITY_CONFIG: Record<
  Severity,
  {
    /** Plain-language label shown everywhere (design wording, not the raw severity name). */
    label: string;
    /** Technical name, shown only where the underlying band matters (e.g. API debug views). */
    technicalLabel: string;
    oneLiner: string;
    scoreRange: string;
    color: string;
    bg: string;
    text: string;
    border: string;
    ring: string;
    icon: string;
    bar: string;
    bgHex: string;
    textHex: string;
    /** Whether score text drawn on the shield badge needs dark or white ink (contrast). */
    shieldTextDark: boolean;
  }
> = {
  SAFE: {
    label: "Safe",
    technicalLabel: "SAFE",
    oneLiner: "Nothing to do",
    scoreRange: "0–30",
    color: "bg-safe",
    bg: "bg-safe-bg",
    text: "text-safe-text",
    border: "border-safe",
    ring: "ring-safe/20",
    icon: "🟢",
    bar: "#097F37",
    bgHex: "#E4F4EA",
    textHex: "#0B5F2B",
    shieldTextDark: false,
  },
  WATCH: {
    label: "Keep an eye on",
    technicalLabel: "WATCH",
    oneLiner: "Watch for changes",
    scoreRange: "31–60",
    color: "bg-watch",
    bg: "bg-watch-bg",
    text: "text-watch-text",
    border: "border-watch",
    ring: "ring-watch/20",
    icon: "🟡",
    bar: "#E0A100",
    bgHex: "#FFF3D2",
    textHex: "#7A5200",
    shieldTextDark: true,
  },
  WARNING: {
    label: "Inspect soon",
    technicalLabel: "WARNING",
    oneLiner: "Plan a visit this week",
    scoreRange: "61–80",
    color: "bg-warn",
    bg: "bg-warn-bg",
    text: "text-warn-text",
    border: "border-warn",
    ring: "ring-warn/20",
    icon: "🟠",
    bar: "#D45A00",
    bgHex: "#FFE7D3",
    textHex: "#9A4300",
    shieldTextDark: false,
  },
  CRITICAL: {
    label: "Urgent",
    technicalLabel: "CRITICAL",
    oneLiner: "Act as soon as possible",
    scoreRange: "81–100",
    color: "bg-urgent",
    bg: "bg-urgent-bg",
    text: "text-urgent-text",
    border: "border-urgent",
    ring: "ring-urgent/20",
    icon: "🔴",
    bar: "#C62828",
    bgHex: "#FDE6E6",
    textHex: "#A31F1F",
    shieldTextDark: false,
  },
  // Never styled as safe (green) or omitted — an offline sensor or a missing verdict is its own,
  // visibly-distinct grey state. See specs/005-demo-mode-and-approval/spec.md §4 FR-4.2.
  UNKNOWN: {
    label: "Unknown",
    technicalLabel: "UNKNOWN",
    oneLiner: "Sensor offline — status cannot be confirmed",
    scoreRange: "—",
    color: "bg-unknown",
    bg: "bg-unknown-bg",
    text: "text-unknown-text",
    border: "border-unknown",
    ring: "ring-unknown/20",
    icon: "⚪",
    bar: "#6B7B8C",
    bgHex: "#EBEEF2",
    textHex: "#3D4A59",
    shieldTextDark: false,
  },
};

export const RESEARCH_STATUS_CONFIG: Record<
  ResearchStatus,
  { label: string; bar: string; bgHex: string; textHex: string; shieldTextDark: boolean }
> = {
  SAFE: { label: "Safe", bar: SEVERITY_CONFIG.SAFE.bar, bgHex: SEVERITY_CONFIG.SAFE.bgHex, textHex: SEVERITY_CONFIG.SAFE.textHex, shieldTextDark: false },
  LITTLE_MODERATE: { label: "Little moderate", bar: SEVERITY_CONFIG.WATCH.bar, bgHex: SEVERITY_CONFIG.WATCH.bgHex, textHex: SEVERITY_CONFIG.WATCH.textHex, shieldTextDark: true },
  MODERATE: { label: "Moderate", bar: SEVERITY_CONFIG.WARNING.bar, bgHex: SEVERITY_CONFIG.WARNING.bgHex, textHex: SEVERITY_CONFIG.WARNING.textHex, shieldTextDark: false },
  DANGER: { label: "Danger", bar: SEVERITY_CONFIG.CRITICAL.bar, bgHex: SEVERITY_CONFIG.CRITICAL.bgHex, textHex: SEVERITY_CONFIG.CRITICAL.textHex, shieldTextDark: false },
};

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
    sensor_id: "acc-sukkur-01",
    last_seen: "1 minute ago",
    maintenance_log: [],
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
    sensor_id: "acc-guddu-01",
    last_seen: "3 minutes ago",
    maintenance_log: [],
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
    sensor_id: "acc-indus-hwy-01",
    last_seen: "2 minutes ago",
    maintenance_log: [
      {
        date: "12 Aug 2026",
        inspector: "Eng. Saleem",
        finding: "Surface cracks on east span",
        action: "Marked for monitoring",
      },
      {
        date: "15 Mar 2026",
        inspector: "Eng. Raza",
        finding: "Minor corrosion on pier 2",
        action: "Anti-rust coating applied",
      },
    ],
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
    sensor_id: "acc-kotri-01",
    last_seen: "4 minutes ago",
    maintenance_log: [
      {
        date: "20 Jul 2026",
        inspector: "Eng. Ahmed",
        finding: "No visible defects",
        action: "Routine inspection complete",
      },
    ],
  },
];

// Exact plain-language card copy from the design files, keyed by bridge id. A bridge not listed
// here (e.g. a future fixture) falls back to its severity band's generic one-liner — never blank.
const PLAIN_ONE_LINER: Record<string, string> = {
  "bridge-kotri-01": "Shaking is almost 10 times the safe limit. Send an engineer as soon as possible.",
  "bridge-indus-hwy-01": "Shaking is about 5 times the safe limit. Plan an inspection this week.",
  "bridge-guddu-01": "Slightly above the safe limit. Nothing to do yet. We are watching it closely.",
  "bridge-sukkur-01": "Within the safe limit. No action needed.",
};

export function plainOneLiner(bridge: Bridge): string {
  return PLAIN_ONE_LINER[bridge.id] ?? SEVERITY_CONFIG[bridge.severity].oneLiner;
}

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
