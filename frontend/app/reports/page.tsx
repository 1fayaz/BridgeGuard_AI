"use client";

import { useState } from "react";
import { BRIDGES } from "@/lib/data";

export default function ReportsPage() {
  const [selectedId, setSelectedId] = useState<string>(BRIDGES[0].id);
  const [format, setFormat] = useState<"txt" | "pdf">("txt");

  const bridge = BRIDGES.find((b) => b.id === selectedId)!;

  function downloadReport() {
    const timestamp = new Date().toISOString();
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
      ...bridge.alerts.map(
        (a) => `- [${a.severity}] ${a.message} (${a.time})`
      ),
      ``,
      `End of report`,
    ];

    if (format === "txt") {
      const blob = new Blob([lines.join("\n")], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${bridge.id}-report-${Date.now()}.txt`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } else {
      const html = `
        <html>
          <head><title>BridgeGuard Report</title></head>
          <body style="font-family:sans-serif; padding:40px;">
            <h1>BridgeGuard AI Report</h1>
            <pre style="white-space:pre-wrap; font-size:14px;">${lines
              .join("\n")
              .replace(/</g, "&lt;")}</pre>
          </body>
        </html>
      `;
      const blob = new Blob([html], { type: "text/html" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${bridge.id}-report-${Date.now()}.html`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  }

  return (
    <div className="max-w-2xl space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Generate Report</h1>
        <p className="mt-2 text-slate-600">
          Download an offline structural-health report for any monitored bridge.
        </p>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-6 space-y-5">
        <div>
          <label className="block text-sm font-medium text-slate-700">
            Bridge
          </label>
          <select
            value={selectedId}
            onChange={(e) => setSelectedId(e.target.value)}
            className="mt-2 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-slate-900 focus:border-sky-500 focus:outline-none"
          >
            {BRIDGES.map((b) => (
              <option key={b.id} value={b.id}>
                {b.name} — {b.location}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="block text-sm font-medium text-slate-700">
            Format
          </label>
          <div className="mt-2 flex gap-3">
            <button
              onClick={() => setFormat("txt")}
              className={`rounded-lg px-4 py-2 text-sm font-semibold border ${
                format === "txt"
                  ? "bg-sky-600 text-white border-sky-600"
                  : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
              }`}
            >
              TXT
            </button>
            <button
              onClick={() => setFormat("pdf")}
              className={`rounded-lg px-4 py-2 text-sm font-semibold border ${
                format === "pdf"
                  ? "bg-sky-600 text-white border-sky-600"
                  : "bg-white text-slate-700 border-slate-300 hover:bg-slate-50"
              }`}
            >
              PDF (HTML)
            </button>
          </div>
        </div>

        <button
          onClick={downloadReport}
          className="w-full rounded-lg bg-slate-900 px-5 py-3 text-sm font-bold text-white hover:bg-slate-800 transition"
        >
          Download Report
        </button>
      </div>

      <div className="rounded-xl border border-slate-200 bg-slate-50 p-5 text-sm text-slate-600">
        Reports are generated client-side from mock data for this demo. In
        production, the Report Agent produces PDFs with embedded charts and a
        digital signature.
      </div>
    </div>
  );
}
