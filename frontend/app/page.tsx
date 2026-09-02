"use client";

import Link from "next/link";
import { BRIDGES, SEVERITY_CONFIG } from "@/lib/data";

export default function HomePage() {
  const sorted = [...BRIDGES].sort((a, b) => b.risk_score - a.risk_score);

  return (
    <div className="space-y-10">
      <section>
        <h1 className="text-3xl font-bold text-slate-900">Bridge Overview</h1>
        <p className="mt-2 text-slate-600">
          Real-time structural health for monitored bridges in Sindh.
        </p>
      </section>

      <section className="grid gap-6 md:grid-cols-2">
        {sorted.map((bridge) => {
          const cfg = SEVERITY_CONFIG[bridge.severity];
          return (
            <Link
              key={bridge.id}
              href={`/bridges/${bridge.id}`}
              className="block rounded-xl border border-slate-200 bg-white p-6 shadow-sm hover:shadow-md transition"
            >
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900">
                    {bridge.name}
                  </h2>
                  <p className="text-sm text-slate-500">{bridge.location}</p>
                </div>
                <span
                  className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-wide ${cfg.bg} ${cfg.text}`}
                >
                  {cfg.label}
                </span>
              </div>

              <div className="mt-5 flex items-end justify-between">
                <div>
                  <p className="text-sm text-slate-500">Risk Score</p>
                  <p className="text-3xl font-bold text-slate-900">
                    {bridge.risk_score}
                  </p>
                </div>
                <div className="flex gap-2">
                  {bridge.chips.map((chip, idx) => (
                    <span
                      key={idx}
                      className={`rounded-md px-2 py-1 text-xs font-medium ${
                        chip.warn
                          ? "bg-amber-100 text-amber-800"
                          : "bg-slate-100 text-slate-700"
                      }`}
                    >
                      {chip.label}
                    </span>
                  ))}
                </div>
              </div>

              <div className="mt-4 h-2 w-full overflow-hidden rounded-full bg-slate-100">
                <div
                  className={`h-full ${cfg.color}`}
                  style={{ width: `${bridge.risk_score}%` }}
                />
              </div>
            </Link>
          );
        })}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-6">
        <h2 className="text-xl font-semibold text-slate-900">
          5-Agent AI Pipeline
        </h2>
        <p className="mt-2 text-slate-600">
          BridgeGuard runs five specialized agents in sequence to turn raw sensor
          data into actionable engineering insight.
        </p>
        <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {[
            "Ingest",
            "Clean",
            "Score",
            "Alert",
            "Report",
          ].map((step, i) => (
            <div
              key={step}
              className="rounded-lg bg-slate-50 px-4 py-3 text-center text-sm font-semibold text-slate-700"
            >
              <span className="block text-xs text-slate-400">Step {i + 1}</span>
              {step}
            </div>
          ))}
        </div>
        <div className="mt-4 text-right">
          <Link
            href="/agents"
            className="text-sm font-medium text-sky-600 hover:text-sky-700"
          >
            Learn more about the agents &rarr;
          </Link>
        </div>
      </section>
    </div>
  );
}
