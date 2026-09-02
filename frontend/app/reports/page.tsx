"use client";

import { useState } from "react";
import { BRIDGES, SEVERITY_CONFIG } from "@/lib/data";

export default function ReportsPage() {
  const [selectedId, setSelectedId] = useState<string>(BRIDGES[0].id);
  const [format, setFormat] = useState<"txt" | "pdf">("txt");

  const bridge = BRIDGES.find((b) => b.id === selectedId)!;
  const cfg = SEVERITY_CONFIG[bridge.severity];

  function downloadReport() {
    const timestamp = new Date().toLocaleString();
    const lines = [
      `BRIDGEGUARD AI - STRUCTURAL HEALTH REPORT`,
      `Generated: ${timestamp}`,
      ``,
      `Bridge:        ${bridge.name}`,
      `Location:      ${bridge.location}`,
      `Sensor ID:     ${bridge.sensor_id}`,
      `Risk Score:    ${bridge.risk_score}/100`,
      `Severity:      ${bridge.severity}`,
      `Review Status: ${bridge.review_status}`,
      `Current RMS:   ${bridge.current_rms} mm/s²`,
      ``,
      `AI Assessment`,
      bridge.explanation,
      ``,
      `Active Alerts (${bridge.alerts.length})`,
      ...(bridge.alerts.length
        ? bridge.alerts.map((a) => `- [${a.severity}] ${a.message} (${a.time})`)
        : ["None"]),
      ``,
      `End of report`,
    ];

    if (format === "txt") {
      const blob = new Blob([lines.join("\n")], { type: "text/plain" });
      download(blob, `${bridge.id}-report-${Date.now()}.txt`);
    } else {
      const html = `
        <html>
          <head>
            <title>BridgeGuard AI Report</title>
            <style>
              body { font-family: system-ui, -apple-system, sans-serif; padding: 48px; color: #1e293b; background: #f8fafc; }
              .container { max-width: 720px; margin: 0 auto; background: white; padding: 48px; border-radius: 16px; box-shadow: 0 10px 40px rgba(0,0,0,0.08); }
              h1 { color: #0f172a; margin-bottom: 8px; }
              .meta { color: #64748b; margin-bottom: 32px; font-size: 14px; }
              pre { white-space: pre-wrap; font-size: 14px; line-height: 1.6; background: #f1f5f9; padding: 24px; border-radius: 12px; }
            </style>
          </head>
          <body>
            <div class="container">
              <h1>BridgeGuard AI — Structural Health Report</h1>
              <p class="meta">Generated ${timestamp}</p>
              <pre>${lines.join("\n").replace(/</g, "&lt;")}</pre>
            </div>
          </body>
        </html>
      `;
      const blob = new Blob([html], { type: "text/html" });
      download(blob, `${bridge.id}-report-${Date.now()}.html`);
    }
  }

  function download(blob: Blob, filename: string) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-3xl font-extrabold text-slate-900 md:text-4xl">
          Generate Report
        </h1>
        <p className="mt-3 text-lg text-slate-600">
          Download an offline, timestamped structural-health report for any
          monitored Sindh bridge.
        </p>
      </div>

      <div className="space-y-6 rounded-3xl border border-slate-200 bg-white p-6 shadow-sm md:p-8">
        <div>
          <label className="block text-sm font-semibold text-slate-700">
            Select Bridge
          </label>
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            className="mt-2 block w-full rounded-xl border border-slate-300 bg-white px-4 py-3 text-slate-900 shadow-sm transition focus:border-sky-500 focus:outline-none focus:ring-2 focus:ring-sky-500/20"
          >
            {BRIDGES.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name} — {b.location}
              </option>
            ))}
          </select>
        </div>

        <div className="rounded-2xl border border-slate-100 bg-slate-50 p-5">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                Selected bridge
              </p>
              <p className="mt-1 text-lg font-bold text-slate-900">
                {bridge.name}
              </p>
              <p className="text-sm text-slate-500">{bridge.location}</p>
            </div>
            <span
              className={`rounded-full border px-3 py-1 text-xs font-bold uppercase ${cfg.bg} ${cfg.text} ${cfg.border} ring-1 ${cfg.ring}`}
            >
              {cfg.icon} {cfg.label} · {bridge.risk_score}/100
            </span>
          </div>
        </div>

        <div>
          <label className="block text-sm font-semibold text-slate-700">
            Report Format
          </label>
          <div className="mt-3 grid grid-cols-2 gap-3">
            <button
              onClick={() => setFormat("txt")}
              className={`rounded-xl border px-4 py-3 text-sm font-bold transition ${
                format === "txt"
                  ? "border-sky-600 bg-sky-600 text-white shadow-lg shadow-sky-600/20"
                  : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              📄 Plain Text (.txt)
            </button>
            <button
              onClick={() => setFormat("pdf")}
              className={`rounded-xl border px-4 py-3 text-sm font-bold transition ${
                format === "pdf"
                  ? "border-sky-600 bg-sky-600 text-white shadow-lg shadow-sky-600/20"
                  : "border-slate-300 bg-white text-slate-700 hover:bg-slate-50"
              }`}
            >
              🌐 Styled HTML (.html)
            </button>
          </div>
        </div>

        <button
          onClick={downloadReport}
          className="w-full rounded-xl bg-slate-900 px-5 py-4 text-base font-bold text-white shadow-lg shadow-slate-900/20 transition hover:bg-slate-800"
        >
          Download Report
        </button>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-slate-50 p-5 text-sm leading-relaxed text-slate-600">
        Reports are generated client-side from live mock data for this demo. In
        production, the Report Agent produces signed PDFs with embedded charts
        and audit trails.
      </div>
    </div>
  );
}
