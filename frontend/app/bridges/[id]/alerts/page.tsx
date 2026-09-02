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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">
            Alerts: {bridge.name}
          </h1>
          <p className="text-slate-500">{alerts.length} active alert(s)</p>
        </div>
        <Link
          href={`/bridges/${bridge.id}`}
          className="text-sm font-medium text-slate-600 hover:text-slate-900"
        >
          &larr; Bridge detail
        </Link>
      </div>

      <div className="space-y-4">
        {alerts.length === 0 ? (
          <div className="rounded-xl border border-slate-200 bg-white p-8 text-center text-slate-600">
            No active alerts for this bridge.
          </div>
        ) : (
          alerts.map((alert) => {
            const cfg = SEVERITY_CONFIG[alert.severity];
            return (
              <div
                key={alert.id}
                className="rounded-xl border border-slate-200 bg-white p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <span
                      className={`rounded-full px-2.5 py-0.5 text-xs font-bold uppercase ${cfg.bg} ${cfg.text}`}
                    >
                      {cfg.label}
                    </span>
                    <p className="mt-2 font-medium text-slate-900">
                      {alert.message}
                    </p>
                    <p className="mt-1 text-sm text-slate-500">
                      Triggered at {alert.time}
                    </p>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-5">
        <h2 className="font-semibold text-slate-900">Engineering Actions</h2>
        <p className="mt-1 text-sm text-slate-600">
          Generate a timestamped report for this bridge to share with the
          operations team.
        </p>
        <Link
          href="/reports"
          className="mt-4 inline-block rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-semibold text-white hover:bg-sky-700 transition"
        >
          Generate Report
        </Link>
      </div>
    </div>
  );
}
