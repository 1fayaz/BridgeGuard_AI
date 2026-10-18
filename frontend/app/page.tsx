"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { BRIDGES, SEVERITY_CONFIG, plainOneLiner, type Bridge, type Severity, type DataSource } from "@/lib/data";
import { fetchBridges, fetchBridgeRisk } from "@/lib/api";
import BridgeMap from "@/components/BridgeMap";
import ShieldScore from "@/components/ShieldScore";
import DataSourceBadge from "@/components/DataSourceBadge";

export default function HomePage() {
  const [bridges, setBridges] = useState<Bridge[]>(BRIDGES);
  const [source, setSource] = useState<DataSource>("sample");

  useEffect(() => {
    let cancelled = false;

    async function loadLive() {
      const apiUrlConfigured = Boolean(process.env.NEXT_PUBLIC_API_URL);
      if (!apiUrlConfigured) return; // no backend configured — stay honestly "sample".

      const apiBridges = await fetchBridges();
      if (cancelled) return;
      if (!apiBridges) {
        setSource("live-unavailable");
        return;
      }

      const riskMap = new Map<
        string,
        { risk_score: number; severity: string; explanation: string }
      >();
      await Promise.all(
        apiBridges.map(async (b) => {
          const risk = await fetchBridgeRisk(b.id);
          if (risk) {
            riskMap.set(risk.bridge_id, {
              risk_score: risk.risk_score,
              severity: risk.severity,
              explanation: risk.explanation,
            });
          }
        }),
      );
      if (cancelled) return;

      if (riskMap.size === 0) {
        setSource("live-unavailable");
        return;
      }

      setBridges((prev) =>
        prev.map((b) => {
          const live = riskMap.get(b.id);
          if (!live) return b;
          return {
            ...b,
            risk_score: live.risk_score,
            severity: live.severity as Severity,
            explanation: live.explanation,
          };
        }),
      );
      setSource("live");
    }

    loadLive();
    return () => {
      cancelled = true;
    };
  }, []);

  const sorted = [...bridges].sort((a, b) => b.risk_score - a.risk_score);
  const needsAttention = bridges.filter((b) => b.severity === "WARNING" || b.severity === "CRITICAL");
  const todoOrder = [...bridges].sort((a, b) => b.risk_score - a.risk_score);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <DataSourceBadge source={source} />
        <span className="text-xs font-semibold uppercase tracking-wider text-blue">
          Sindh bridge infrastructure health · updated 2 minutes ago
        </span>
      </div>

      {/* Headline */}
      <div className="flex flex-wrap items-end justify-between gap-5">
        <div className="max-w-[760px]">
          <h1 className="mt-2.5 font-display text-[32px] font-extrabold leading-[1.12] tracking-tight text-navy sm:text-[42px]">
            {needsAttention.length === 0
              ? "All bridges are fine for now."
              : `${needsAttention.length} bridge${needsAttention.length === 1 ? "" : "s"} need${needsAttention.length === 1 ? "s" : ""} your attention today.`}
          </h1>
          <p className="mt-3.5 text-base leading-relaxed text-navy-text sm:text-[19px]">
            {needsAttention.length > 0 &&
              `The other ${bridges.length - needsAttention.length} ${bridges.length - needsAttention.length === 1 ? "is" : "are"} fine for now. `}
            BridgeGuard AI checks every bridge on the Indus corridor, day and
            night, and tells you in plain words what to do.
          </p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <Link href="/reports" className="rounded-xl bg-navy px-6 py-3.5 text-[15px] font-bold text-white">
            Create a report
          </Link>
          <Link
            href="/agents"
            className="rounded-xl border-[1.5px] border-navy bg-white px-6 py-3.5 text-[15px] font-bold text-navy"
          >
            How it works
          </Link>
        </div>
      </div>

      {/* Shield tiles */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {sorted.map((bridge) => {
          const cfg = SEVERITY_CONFIG[bridge.severity];
          return (
            <Link
              key={bridge.id}
              href={`/bridges/${bridge.id}`}
              className="block rounded-[20px] bg-white p-5 pb-5 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)] transition hover:-translate-y-0.5 hover:shadow-lg"
              style={{ borderTop: `6px solid ${cfg.bar}` }}
            >
              <div className="flex items-start justify-between gap-2">
                <ShieldScore severity={bridge.severity} score={bridge.risk_score} />
                <span
                  className="rounded-full px-3 py-1.5 text-[13px] font-bold"
                  style={{ background: cfg.bgHex, color: cfg.textHex }}
                >
                  {cfg.label}
                </span>
              </div>
              <div className="mt-3.5 font-display text-lg font-bold text-navy">{bridge.name}</div>
              <div className="mt-0.5 text-[13px] text-navy-muted">{bridge.location}</div>
              <p className="mt-2.5 text-[15px] leading-relaxed">{plainOneLiner(bridge)}</p>
              <div className="mt-4 flex items-center justify-between text-[13px] text-navy-muted">
                <span>Checked {bridge.last_seen}</span>
                <span className="text-[14px] font-bold text-blue">Open →</span>
              </div>
            </Link>
          );
        })}
      </div>

      {/* Map + to-do */}
      <div className="flex flex-wrap items-stretch gap-5">
        <section className="min-w-0 flex-[3_1_560px] rounded-[20px] bg-white p-6 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
          <h2 className="font-display text-xl font-extrabold text-navy">Where your bridges are</h2>
          <p className="mt-1.5 mb-4 text-[15px] text-navy-text">
            Each shield is a bridge. The number is its risk score out of 100.
          </p>
          <div className="overflow-hidden rounded-2xl border border-border">
            <BridgeMap />
          </div>
        </section>

        <section className="min-w-0 flex-[2_1_340px] rounded-[20px] bg-white p-6 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
          <h2 className="font-display text-xl font-extrabold text-navy">Your to-do list today</h2>
          <p className="mt-1.5 mb-3.5 text-[15px] text-navy-text">In order of importance.</p>
          <div className="flex flex-col">
            {todoOrder.map((bridge, i) => {
              const cfg = SEVERITY_CONFIG[bridge.severity];
              const done = bridge.severity === "SAFE";
              return (
                <Link
                  key={bridge.id}
                  href={`/bridges/${bridge.id}`}
                  className="flex items-start gap-3.5 border-t border-border-light py-4 first:border-t-0"
                >
                  <div
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-[15px] font-extrabold text-white"
                    style={{ background: cfg.bar, color: cfg.shieldTextDark ? "#2B1D00" : "#FFFFFF" }}
                  >
                    {done ? "✓" : i + 1}
                  </div>
                  <div>
                    <div className="text-base font-bold">{bridge.name}</div>
                    <div className="mt-0.5 text-[15px] leading-snug text-navy-text">
                      {plainOneLiner(bridge)}
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        </section>
      </div>

      {/* How to read */}
      <section className="rounded-[20px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
        <h2 className="font-display text-xl font-extrabold text-navy">How to read the colours</h2>
        <p className="mt-1.5 mb-5 text-[15px] text-navy-text">
          A higher score means more risk. An engineer always makes the final decision.
        </p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {(["SAFE", "WATCH", "WARNING", "CRITICAL", "UNKNOWN"] as Severity[]).map((sev) => {
            const cfg = SEVERITY_CONFIG[sev];
            return (
              <div key={sev} className="flex items-center gap-3.5 rounded-2xl bg-page-bg p-4">
                <ShieldScore severity={sev} score={null} size={36} />
                <div>
                  <div className="text-[15px] font-bold">
                    {cfg.label} · {cfg.scoreRange}
                  </div>
                  <div className="mt-0.5 text-[13px] text-navy-text">{cfg.oneLiner}</div>
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
