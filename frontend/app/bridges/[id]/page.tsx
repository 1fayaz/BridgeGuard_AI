import Link from "next/link";
import { notFound } from "next/navigation";
import { BRIDGES, SEVERITY_CONFIG } from "@/lib/data";
import BridgeChart from "./chart";

export function generateStaticParams() {
  return BRIDGES.map((bridge) => ({ id: bridge.id }));
}

export const dynamicParams = false;

export default function BridgeDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const bridge = BRIDGES.find((b) => b.id === params.id);

  if (!bridge) {
    notFound();
  }

  const cfg = SEVERITY_CONFIG[bridge.severity];

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            {bridge.location}
          </p>
          <h1 className="mt-1 text-3xl font-extrabold text-slate-900">
            {bridge.name}
          </h1>
        </div>
        <Link
          href="/"
          className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
        >
          &larr; Back to overview
        </Link>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="relative overflow-hidden rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <div className={`absolute right-0 top-0 h-24 w-24 -translate-y-8 translate-x-8 rounded-full ${cfg.color} opacity-10 blur-2xl`} />
          <p className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            Current Risk Score
          </p>
          <p className="mt-2 text-6xl font-extrabold text-slate-900">
            {bridge.risk_score}
          </p>
          <p className="text-sm text-slate-400">out of 100</p>
          <span
            className={`mt-4 inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold uppercase ${cfg.bg} ${cfg.text} ${cfg.border} ring-1 ${cfg.ring}`}
          >
            <span>{cfg.icon}</span>
            {cfg.label}
          </span>
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm lg:col-span-2">
          <p className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            AI Assessment
          </p>
          <p className="mt-3 text-lg leading-relaxed text-slate-800">
            {bridge.explanation}
          </p>
          {bridge.review_status === "PENDING_HUMAN_REVIEW" && (
            <div className="mt-5 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50/80 px-4 py-3 text-sm text-amber-800">
              <span className="text-base">⚠️</span>
              <span>
                This score is pending human engineering review. Please verify
                before acting on recommendations.
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm md:p-8">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-xl font-bold text-slate-900">
              Vibration Time Series
            </h2>
            <p className="text-sm text-slate-500">
              Real-time RMS acceleration from sensor {bridge.sensor_id}
            </p>
          </div>
          <span className="inline-flex items-center gap-2 self-start rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">
            <span className="h-2 w-2 rounded-full bg-emerald-500" />
            Live feed
          </span>
        </div>
        <BridgeChart severity={bridge.severity} />
      </div>

      <div className="flex flex-wrap gap-4">
        <Link
          href={`/bridges/${bridge.id}/alerts`}
          className="rounded-xl bg-slate-900 px-6 py-3 text-sm font-bold text-white shadow-lg shadow-slate-900/20 transition hover:bg-slate-800"
        >
          View Alerts ({bridge.alerts.length})
        </Link>
        <Link
          href="/reports"
          className="rounded-xl border border-slate-300 bg-white px-6 py-3 text-sm font-bold text-slate-700 shadow-sm transition hover:bg-slate-50"
        >
          Generate Report
        </Link>
      </div>
    </div>
  );
}
