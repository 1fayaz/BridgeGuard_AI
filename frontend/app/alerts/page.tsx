"use client";

import { useState } from "react";
import Link from "next/link";
import DataSourceBadge from "@/components/DataSourceBadge";
import { useAlertStore, type AlertRecord, type AlertStatus } from "@/lib/alert-store";

const STATUS_LABEL: Record<AlertStatus, string> = {
  open: "Open",
  acknowledged: "Acknowledged",
  approved: "Approved",
  rejected: "Rejected",
  dismissed: "Dismissed",
};

function OpenAlertCard({ alert }: { alert: AlertRecord }) {
  const { acknowledge, approve, reject, dismiss } = useAlertStore();
  const [decided, setDecided] = useState<"approved" | "rejected" | null>(null);
  const [closing, setClosing] = useState(false);
  const busy = decided !== null || closing;

  function animateOut(commit: () => void, delayMs: number) {
    setTimeout(() => {
      setClosing(true);
      setTimeout(commit, 300);
    }, delayMs);
  }

  function onApprove() {
    if (busy) return;
    setDecided("approved");
    animateOut(() => approve(alert.id), 1400);
  }
  function onReject() {
    if (busy) return;
    setDecided("rejected");
    animateOut(() => reject(alert.id), 1400);
  }
  function onAcknowledge() {
    if (busy) return;
    animateOut(() => acknowledge(alert.id), 0);
  }
  function onDismiss() {
    if (busy) return;
    animateOut(() => dismiss(alert.id), 0);
  }

  return (
    <div
      className="overflow-hidden transition-all duration-300"
      style={closing ? { opacity: 0, transform: "scale(0.97)", maxHeight: 0, marginBottom: 0 } : { opacity: 1, maxHeight: 400 }}
    >
      <div
        className="rounded-[20px] bg-white p-6 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]"
        style={{ borderLeft: `6px solid ${alert.severityBar}` }}
      >
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="rounded-full px-3 py-1 text-[13px] font-bold" style={{ background: alert.severityBgHex, color: alert.severityTextHex }}>
            {alert.severityLabel}
          </span>
          <span className="text-[13px] font-semibold text-blue">{alert.bridgeName}</span>
          <span className="text-[13px] text-navy-muted">{alert.source === "simulated" ? "Simulated scenario" : "Recorded research data"}</span>
          <span className="ml-auto text-[13px] font-bold text-navy">{alert.metric}</span>
        </div>
        <div className="mt-2 text-[13px] font-bold uppercase tracking-wide text-navy-muted">{alert.explanationLabel}</div>
        <p className="mt-1 text-[15px] leading-relaxed text-navy-text">{alert.explanationText}</p>
        <div className="mt-2 text-[12px] text-navy-muted">{alert.time}</div>

        {decided ? (
          <div className="mt-4 rounded-xl bg-page-bg p-4 text-sm">
            <strong>{decided === "approved" ? "Approved" : "Rejected"}.</strong> Replay: nothing is saved. In the
            live system this will be logged.
          </div>
        ) : (
          <div className="mt-4 flex flex-wrap gap-3">
            {alert.actionType === "approve-reject" ? (
              <>
                <button onClick={onApprove} disabled={busy} className="rounded-xl bg-safe px-5 py-2.5 text-sm font-bold text-white disabled:opacity-60">
                  Approve
                </button>
                <button onClick={onReject} disabled={busy} className="rounded-xl border-2 border-urgent px-5 py-2.5 text-sm font-bold text-urgent-text disabled:opacity-60">
                  Reject
                </button>
              </>
            ) : (
              <>
                <button onClick={onAcknowledge} disabled={busy} className="rounded-xl bg-navy px-5 py-2.5 text-sm font-bold text-white disabled:opacity-60">
                  Acknowledge
                </button>
                <button onClick={onDismiss} disabled={busy} className="rounded-xl border-[1.5px] border-navy px-5 py-2.5 text-sm font-bold text-navy disabled:opacity-60">
                  Dismiss
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AllAlertsPage() {
  const { alerts, openAlerts, handledAlerts, reset } = useAlertStore();

  const total = alerts.length;
  const severityCounts = openAlerts.reduce<Record<string, number>>((acc, a) => {
    acc[a.severityLabel] = (acc[a.severityLabel] ?? 0) + 1;
    return acc;
  }, {});
  const needsAttention = openAlerts.filter((a) => a.actionType === "approve-reject").length;
  const approvedCount = alerts.filter((a) => a.status === "approved").length;
  const rejectedCount = alerts.filter((a) => a.status === "rejected").length;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="text-[13px] font-bold tracking-wider text-blue">ALERTS</div>
        <h1 className="mt-2 font-display text-[28px] font-extrabold tracking-tight text-navy sm:text-[38px]">
          {openAlerts.length === 0
            ? total === 0
              ? "Loading alerts…"
              : `All clear. ${total} alerts handled.`
            : `${openAlerts.length} open alert${openAlerts.length === 1 ? "" : "s"}${needsAttention > 0 ? `, ${needsAttention} needing approval` : ""}.`}
        </h1>
        <p className="mt-3 max-w-[720px] text-[16px] leading-relaxed text-navy-text sm:text-[18px]">
          Built from the four recorded research conditions and the simulated truck scenario -
          not a live alert feed.
        </p>
        <div className="mt-3">
          <DataSourceBadge source="sample" />
        </div>
      </div>

      {total > 0 && (
        <div className="flex flex-wrap gap-2.5 text-sm font-bold">
          <span className="rounded-full bg-navy px-4 py-2.5 text-white">Open · {openAlerts.length}</span>
          {Object.entries(severityCounts).map(([label, count]) => (
            <span key={label} className="rounded-full border-[1.5px] px-4 py-2.5" style={{ borderColor: "#C5D2E0", color: "#3D5068" }}>
              {label} · {count}
            </span>
          ))}
          <span className="rounded-full border-[1.5px] border-safe px-4 py-2.5 text-safe-text">Approved · {approvedCount}</span>
          <span className="rounded-full border-[1.5px] border-urgent px-4 py-2.5 text-urgent-text">Rejected · {rejectedCount}</span>
        </div>
      )}

      <Link
        href="/demo"
        className="flex items-center justify-between gap-4 rounded-[20px] border-2 border-dashed border-blue bg-[#E8F3FB] px-6 py-5"
      >
        <div>
          <div className="text-[13px] font-bold tracking-wider text-blue">DEMONSTRATION BRIDGE</div>
          <div className="mt-1 font-display text-lg font-bold text-navy">
            See an urgent alert go through Approve / Reject on a replay
          </div>
        </div>
        <span className="shrink-0 rounded-xl bg-blue px-5 py-3 text-sm font-bold text-white">Watch the demo →</span>
      </Link>

      {openAlerts.length > 0 ? (
        <section className="flex flex-col gap-3.5">
          {openAlerts.map((a) => (
            <OpenAlertCard key={a.id} alert={a} />
          ))}
        </section>
      ) : total > 0 ? (
        <section className="flex flex-col gap-5">
          <div className="rounded-3xl bg-white p-10 text-center shadow-sm">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-safe-bg text-3xl">✅</div>
            <h3 className="mt-4 text-xl font-bold text-navy">All clear. {total} alerts handled.</h3>
            <p className="mt-2 text-navy-text">
              {approvedCount} approved, {rejectedCount} rejected, {total - approvedCount - rejectedCount} acknowledged or dismissed.
            </p>
            <button
              onClick={reset}
              className="mt-5 rounded-xl bg-navy px-6 py-3 text-sm font-bold text-white"
            >
              Reset demo
            </button>
          </div>

          <div className="flex flex-col gap-2.5">
            {handledAlerts.map((a) => (
              <div key={a.id} className="flex items-center justify-between gap-3 rounded-2xl bg-white px-5 py-4 shadow-sm">
                <div>
                  <div className="font-bold text-navy">{a.bridgeName}</div>
                  <div className="text-[13px] text-navy-muted">{a.explanationLabel}</div>
                </div>
                <span className="rounded-full bg-page-bg px-3 py-1.5 text-[13px] font-bold text-navy-text">
                  {STATUS_LABEL[a.status]}
                </span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      <p className="text-[13px] text-navy-muted">Reloading this page resets the demo.</p>
    </div>
  );
}
