import Link from "next/link";
import { notFound } from "next/navigation";
import { BRIDGES, SEVERITY_CONFIG } from "@/lib/data";

const severityRank = { CRITICAL: 0, WARNING: 1, WATCH: 2, SAFE: 3 };

export function generateStaticParams() {
  return BRIDGES.map((bridge) => ({ id: bridge.id }));
}

export const dynamicParams = false;

export default function AlertsPage({ params }: { params: { id: string } }) {
  const bridge = BRIDGES.find((b) => b.id === params.id);

  if (!bridge) {
    notFound();
  }

  const alerts = [...bridge.alerts].sort(
    (a, b) => severityRank[a.severity] - severityRank[b.severity]
  );

  const cfg = SEVERITY_CONFIG[bridge.severity];

  return (
    <div className="space-y-8">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            {bridge.location}
          </p>
          <h1 className="mt-1 text-3xl font-extrabold text-slate-900">
            Alerts: {bridge.name}
          </h1>
          <p className="mt-2 text-slate-600">
            {alerts.length} active alert{alerts.length !== 1 && "s"} · sorted by
            severity
          </p>
        </div>
        <Link
          href={`/bridges/${bridge.id}`}
          className="inline-flex items-center gap-1 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
        >
          &larr; Bridge detail
        </Link>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm">
          <p className="text-sm font-semibold uppercase tracking-wider text-slate-400">
            Bridge Risk Score
          </p>
          <p className="mt-2 text-5xl font-extrabold text-slate-900">
            {bridge.risk_score}
          </p>
          <span
            className={`mt-4 inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold uppercase ${cfg.bg} ${cfg.text} ${cfg.border} ring-1 ${cfg.ring}`}
          >
            <span>{cfg.icon}</span>
            {cfg.label}
          </span>
        </div>

        <div className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm lg:col-span-2">
          <h2 className="text-lg font-bold text-slate-900">Engineering Actions</h2>
          <p className="mt-2 text-slate-600">
            Generate a timestamped structural-health report for this bridge to
            share with the operations team and regulators.
          </p>
          <Link
            href="/reports"
            className="mt-5 inline-flex rounded-xl bg-sky-600 px-6 py-3 text-sm font-bold text-white shadow-lg shadow-sky-600/20 transition hover:bg-sky-700"
          >
            Generate Report
          </Link>
        </div>
      </div>

      <div className="space-y-4">
        {alerts.length === 0 ? (
          <div className="rounded-3xl border border-slate-200 bg-white p-12 text-center shadow-sm">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-100 text-3xl">
              ✅
            </div>
            <h3 className="mt-4 text-xl font-bold text-slate-900">
              No active alerts
            </h3>
            <p className="mt-2 text-slate-600">
              This bridge has no active alerts at this time.
            </p>
          </div>
        ) : (
          alerts.map((alert) => {
            const acfg = SEVERITY_CONFIG[alert.severity];
            return (
              <div
                key={alert.id}
                className="flex items-start gap-4 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm transition hover:shadow-md"
              >
                <div
                  className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-xl ${acfg.bg} ${acfg.text} ring-1 ${acfg.ring}`}
                >
                  {acfg.icon}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-3">
                    <span
                      className={`rounded-full border px-2.5 py-0.5 text-xs font-bold uppercase ${acfg.bg} ${acfg.text} ${acfg.border}`}
                    >
                      {acfg.label}
                    </span>
                    <span className="text-xs font-medium text-slate-400">
                      {alert.time}
                    </span>
                  </div>
                  <p className="mt-2 text-lg font-semibold text-slate-900">
                    {alert.message}
                  </p>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
