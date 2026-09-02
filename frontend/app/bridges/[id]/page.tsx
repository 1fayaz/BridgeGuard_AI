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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{bridge.name}</h1>
          <p className="text-slate-500">{bridge.location}</p>
        </div>
        <Link
          href="/"
          className="text-sm font-medium text-slate-600 hover:text-slate-900"
        >
          &larr; Back
        </Link>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-6">
          <p className="text-sm text-slate-500">Current Risk Score</p>
          <p className="mt-2 text-5xl font-bold text-slate-900">
            {bridge.risk_score}
          </p>
          <span
            className={`mt-3 inline-block rounded-full px-3 py-1 text-xs font-bold uppercase ${cfg.bg} ${cfg.text}`}
          >
            {cfg.label}
          </span>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-6 lg:col-span-2">
          <p className="text-sm text-slate-500">AI Assessment</p>
          <p className="mt-2 text-slate-800 leading-relaxed">
            {bridge.explanation}
          </p>
          {bridge.review_status === "PENDING_HUMAN_REVIEW" && (
            <div className="mt-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800">
              This score is pending human engineering review.
            </div>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">
            Vibration Time Series
          </h2>
          <span className="text-sm text-slate-500">
            Sensor {bridge.sensor_id}
          </span>
        </div>
        <BridgeChart severity={bridge.severity} />
      </div>

      <div className="flex gap-4">
        <Link
          href={`/bridges/${bridge.id}/alerts`}
          className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 transition"
        >
          View Alerts ({bridge.alerts.length})
        </Link>
        <Link
          href="/reports"
          className="rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition"
        >
          Generate Report
        </Link>
      </div>
    </div>
  );
}
