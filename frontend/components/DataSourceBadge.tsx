import type { DataSource } from "@/lib/data";

const COPY: Record<DataSource, { text: string; bg: string; fg: string; dot: string }> = {
  sample: { text: "Sample data", bg: "#EBEEF2", fg: "#3D4A59", dot: "#6B7B8C" },
  live: { text: "Live data", bg: "#E4F4EA", fg: "#0B5F2B", dot: "#097F37" },
  "live-unavailable": {
    text: "Live data unavailable, showing sample",
    bg: "#FFF3D2",
    fg: "#7A5200",
    dot: "#E0A100",
  },
};

/** Required on every page that renders bridge/alert/score numbers (fixtures or live-overlaid).
 * The backend overlay in lib/api.ts fails silently by design — this badge is what makes that
 * silence visible to a reader instead of letting sample numbers pass as real. */
export default function DataSourceBadge({ source }: { source: DataSource }) {
  const c = COPY[source];
  return (
    <span
      className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold"
      style={{ background: c.bg, color: c.fg }}
    >
      <span className="h-2 w-2 rounded-full" style={{ background: c.dot }} />
      {c.text}
    </span>
  );
}
