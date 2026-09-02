"use client";

import Link from "next/link";
import { BRIDGES, SEVERITY_CONFIG } from "@/lib/data";

export default function HomePage() {
  const sorted = [...BRIDGES].sort((a, b) => b.risk_score - a.risk_score);
  const criticalCount = BRIDGES.filter((b) => b.severity === "CRITICAL").length;
  const warningCount = BRIDGES.filter((b) => b.severity === "WARNING").length;

  return (
    <div className="space-y-12">
      <section className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-slate-900 via-slate-800 to-indigo-900 px-6 py-12 text-white shadow-2xl shadow-slate-900/20 md:px-10 md:py-16">
        <div className="relative z-10 max-w-2xl">
          <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-1 text-xs font-medium backdrop-blur-sm">
            <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
            Live monitoring active
          </div>
          <h1 className="text-4xl font-extrabold tracking-tight md:text-5xl">
            Sindh Bridge Infrastructure Health
          </h1>
          <p className="mt-4 text-lg text-slate-300">
            AI-powered real-time structural monitoring for bridges across the
            Indus corridor.
          </p>
        </div>
        <div className="relative z-10 mt-8 grid gap-4 sm:grid-cols-3">
          <StatCard value={BRIDGES.length} label="Monitored bridges" />
          <StatCard value={criticalCount} label="Critical" warn />
          <StatCard value={warningCount} label="Warning" warn />
        </div>
      </section>

      <section>
        <div className="mb-6 flex items-end justify-between">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Bridge Overview</h2>
            <p className="mt-1 text-slate-600">
              Sorted by risk score — highest priority first.
            </p>
          </div>
          <Link
            href="/reports"
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white shadow-md transition hover:bg-slate-800"
          >
            Generate Report
          </Link>
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          {sorted.map((bridge) => {
            const cfg = SEVERITY_CONFIG[bridge.severity];
            return (
              <Link
                key={bridge.id}
                href={`/bridges/${bridge.id}`}
                className="group relative overflow-hidden rounded-2xl border border-slate-200 bg-white p-6 shadow-sm card-hover"
              >
                <div
                  className={`absolute left-0 top-0 h-full w-1 ${cfg.color}`}
                />
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-lg font-bold text-slate-900 transition group-hover:text-sky-700">
                      {bridge.name}
                    </h3>
                    <p className="text-sm text-slate-500">{bridge.location}</p>
                  </div>
                  <span
                    className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-bold uppercase tracking-wide ${cfg.bg} ${cfg.text} ${cfg.border} ring-1 ${cfg.ring}`}
                  >
                    <span>{cfg.icon}</span>
                    {cfg.label}
                  </span>
                </div>

                <div className="mt-6 flex items-end justify-between">
                  <div>
                    <p className="text-xs font-medium uppercase tracking-wider text-slate-400">
                      Risk Score
                    </p>
                    <p className="text-4xl font-extrabold text-slate-900">
                      {bridge.risk_score}
                      <span className="ml-1 text-base font-medium text-slate-400">
                        /100
                      </span>
                    </p>
                  </div>
                  <div className="flex flex-wrap justify-end gap-2">
                    {bridge.chips.map((chip, idx) => (
                      <span
                        key={idx}
                        className={`rounded-md px-2.5 py-1 text-xs font-semibold ${
                          chip.warn
                            ? "bg-amber-100 text-amber-800 ring-1 ring-amber-200"
                            : "bg-slate-100 text-slate-700 ring-1 ring-slate-200"
                        }`}
                      >
                        {chip.label}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="mt-5">
                  <div className="flex justify-between text-xs font-medium text-slate-400">
                    <span>0</span>
                    <span>100</span>
                  </div>
                  <div className="mt-1 h-2.5 w-full overflow-hidden rounded-full bg-slate-100 ring-1 ring-slate-200">
                    <div
                      className={`h-full rounded-full ${cfg.color} shadow-[0_0_12px_rgba(0,0,0,0.15)]`}
                      style={{ width: `${bridge.risk_score}%` }}
                    />
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-2xl font-bold text-slate-900">
              5-Agent AI Pipeline
            </h2>
            <p className="mt-2 max-w-xl text-slate-600">
              BridgeGuard orchestrates five specialized agents that turn raw
              sensor data into actionable engineering insight.
            </p>
          </div>
          <Link
            href="/agents"
            className="rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-center text-sm font-semibold text-slate-700 shadow-sm transition hover:bg-slate-50"
          >
            Explore the pipeline &rarr;
          </Link>
        </div>
        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {["Ingest", "Clean", "Score", "Alert", "Report"].map((step, i) => (
            <div
              key={step}
              className="rounded-xl bg-gradient-to-br from-slate-50 to-slate-100 px-4 py-4 text-center shadow-sm ring-1 ring-slate-200"
            >
              <span className="block text-xs font-semibold text-slate-400">
                Step {i + 1}
              </span>
              <span className="mt-1 block text-sm font-bold text-slate-800">
                {step}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

function StatCard({
  value,
  label,
  warn,
}: {
  value: number;
  label: string;
  warn?: boolean;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/10 p-4 backdrop-blur-sm">
      <p className="text-3xl font-extrabold">{value}</p>
      <p className={`text-sm font-medium ${warn ? "text-amber-300" : "text-slate-300"}`}>
        {label}
      </p>
    </div>
  );
}
