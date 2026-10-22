import Link from "next/link";
import { notFound } from "next/navigation";
import { BRIDGES, SEVERITY_CONFIG, type Severity } from "@/lib/data";
import AlertCard from "@/components/AlertCard";
import DataSourceBadge from "@/components/DataSourceBadge";

const severityRank: Record<Severity, number> = { CRITICAL: 0, WARNING: 1, WATCH: 2, SAFE: 3, UNKNOWN: 4 };

export function generateStaticParams() {
  return BRIDGES.map((bridge) => ({ id: bridge.id }));
}

export const dynamicParams = false;

export default function AlertsPage({ params }: { params: { id: string } }) {
  const bridge = BRIDGES.find((b) => b.id === params.id);
  if (!bridge) notFound();

  const alerts = [...bridge.alerts].sort((a, b) => severityRank[a.severity] - severityRank[b.severity]);
  const urgentCount = alerts.filter((a) => a.severity === "CRITICAL").length;
  // Pills are built from whatever severities are actually present - never a fabricated
  // "Resolved" bucket the fixture data doesn't model.
  const present = Array.from(new Set(alerts.map((a) => a.severity)));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="text-[13px] font-bold tracking-wider text-blue">{bridge.name.toUpperCase()}</div>
        <h1 className="mt-2 font-display text-[28px] font-extrabold tracking-tight text-navy sm:text-[38px]">
          {urgentCount > 0
            ? `${urgentCount} urgent alert${urgentCount === 1 ? "" : "s"} need${urgentCount === 1 ? "s" : ""} you.`
            : "No urgent alerts right now."}
        </h1>
        <p className="mt-3 max-w-[720px] text-[16px] leading-relaxed text-navy-text sm:text-[18px]">
          Alerts tell you what changed and what to do. Urgent ones stay at the top until someone
          presses &ldquo;I have seen this&rdquo;.
        </p>
        <div className="mt-3">
          <DataSourceBadge source="sample" />
        </div>
      </div>

      <div className="flex flex-wrap gap-2.5 text-sm font-bold">
        <span className="rounded-full bg-navy px-4 py-2.5 text-white">All · {alerts.length}</span>
        {present.map((sev) => {
          const cfg = SEVERITY_CONFIG[sev];
          const count = alerts.filter((a) => a.severity === sev).length;
          return (
            <span key={sev} className="rounded-full border-[1.5px] px-4 py-2.5" style={{ borderColor: "#C5D2E0", color: cfg.textHex }}>
              {cfg.label} · {count}
            </span>
          );
        })}
      </div>

      <div className="flex flex-wrap items-start gap-6">
        <section className="flex min-w-0 flex-[2_1_520px] flex-col gap-3.5">
          {alerts.length === 0 ? (
            <div className="rounded-3xl bg-white p-12 text-center shadow-sm">
              <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-safe-bg text-3xl">✅</div>
              <h3 className="mt-4 text-xl font-bold text-navy">No active alerts</h3>
              <p className="mt-2 text-navy-text">This bridge has no active alerts at this time.</p>
            </div>
          ) : (
            alerts.map((alert) => (
              <AlertCard
                key={alert.id}
                severity={alert.severity}
                title={alert.message}
                detail={`Reported at ${alert.time} today.`}
                time={`Today, ${alert.time}`}
              />
            ))
          )}
        </section>

        <aside className="min-w-0 flex-[1_1_340px] rounded-[20px] bg-white p-6.5 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]" style={{ maxWidth: 460 }}>
          <h2 className="font-display text-xl font-extrabold text-navy">Share a report</h2>
          <p className="mt-2 text-[15px] leading-relaxed text-navy-text">
            One click creates a PDF you can hand to a senior officer or authority.
          </p>
          <div className="my-4.5 flex flex-col gap-2.5 text-[15px]">
            {["Bridge name, location and date", "Risk score and status", "Plain-language explanation", "Open alerts and what to do next"].map((f) => (
              <div key={f} className="flex items-center gap-2.5">
                <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="#097F37" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M5 12l5 5L20 7" />
                </svg>
                {f}
              </div>
            ))}
          </div>
          <Link href="/reports" className="block rounded-xl bg-navy px-5 py-4 text-center text-[16px] font-bold text-white">
            Create PDF report
          </Link>
        </aside>
      </div>
    </div>
  );
}
