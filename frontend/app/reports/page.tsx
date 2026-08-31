"use client";

import { useMemo, useState } from "react";
import { BRIDGES, generateReadings } from "@/lib/data";
import { generateReportPdf } from "@/lib/report";

interface RecentReport {
  id: string;
  bridge: string;
  kind: string;
  date: string;
  url?: string;
}

const MOCK_RECENT: RecentReport[] = [
  { id: "r-3", bridge: "Kotri Bridge", kind: "Monthly structural review", date: "28 Aug 2026" },
  { id: "r-2", bridge: "Sukkur Barrage Bridge", kind: "Routine monitoring summary", date: "20 Aug 2026" },
  { id: "r-1", bridge: "Guddu Barrage Bridge", kind: "Routine monitoring summary", date: "12 Aug 2026" },
];

const INCLUDES = [
  "Current risk score and severity rating",
  "AI risk assessment written in plain language",
  "Full alert history with timestamps",
  "Vibration readings summary",
  "Recommended actions with deadlines",
];

export default function ReportsPage() {
  const [bridgeId, setBridgeId] = useState(BRIDGES[0].id);
  const [status, setStatus] = useState<"idle" | "generating" | "done">("idle");
  const [lastReport, setLastReport] = useState<{ url: string; filename: string; kb: number } | null>(null);
  const [recent, setRecent] = useState<RecentReport[]>(MOCK_RECENT);

  const bridge = useMemo(() => BRIDGES.find((b) => b.id === bridgeId) ?? BRIDGES[0], [bridgeId]);

  function onSelect(id: string) {
    setBridgeId(id);
    setStatus("idle");
    setLastReport(null);
  }

  async function generate() {
    if (status === "generating") return;
    setStatus("generating");
    setLastReport(null);
    await new Promise((r) => setTimeout(r, 1500));

    const readings = generateReadings(bridge.severity, bridge.id);
    const currentRms = readings[readings.length - 1].rms;
    const { bytes, filename } = generateReportPdf(bridge, currentRms);
    const blob = new Blob([bytes], { type: "application/pdf" });
    const url = URL.createObjectURL(blob);

    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();

    setLastReport({ url, filename, kb: Math.round((bytes.length / 1024) * 10) / 10 });
    setRecent((prev) => [
      { id: `r-${Date.now()}`, bridge: bridge.name, kind: "Full structural report", date: "Just now", url },
      ...prev,
    ]);
    setStatus("done");
  }

  return (
    <main className="p-6 max-w-4xl mx-auto">
      <div className="mb-5">
        <h1 className="text-xl font-medium text-gray-900">Reports</h1>
        <p className="text-sm text-gray-500 mt-1">
          Generate a professional PDF report for any bridge — compiled by 5 AI agents in seconds.
        </p>
      </div>

      <div className="bg-white border border-gray-100 rounded-xl p-5 mb-4">
        <h2 className="text-sm font-medium text-gray-700 mb-4">Generate a report</h2>
        <div className="flex gap-3 items-end">
          <label className="flex-1">
            <span className="block text-xs text-gray-400 mb-1.5">Bridge</span>
            <select
              value={bridgeId}
              onChange={(e) => onSelect(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-800 bg-white"
            >
              {BRIDGES.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} — {b.severity}
                </option>
              ))}
            </select>
          </label>
          <button
            onClick={generate}
            disabled={status === "generating"}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white disabled:opacity-60"
            style={{ backgroundColor: "#0F6E56" }}
          >
            {status === "generating" ? "Generating…" : "Generate PDF Report"}
          </button>
        </div>

        {status === "generating" && (
          <div className="mt-4 flex items-center gap-3 text-sm text-gray-500">
            <span
              className="w-4 h-4 rounded-full border-2 border-gray-200 animate-spin shrink-0"
              style={{ borderTopColor: "#0F6E56" }}
            />
            Compiling report — collecting readings, risk assessment, alerts and recommendations…
          </div>
        )}

        {status === "done" && lastReport && (
          <div className="mt-4 p-4 rounded-xl" style={{ background: "#eaf3de", border: "1px solid #3B6D11" }}>
            <div className="text-sm font-medium" style={{ color: "#3B6D11" }}>
              Report generated — {lastReport.filename} ({lastReport.kb} KB)
            </div>
            <div className="text-xs mt-1" style={{ color: "#3B6D11" }}>
              The report has been downloaded to your device.{" "}
              <a href={lastReport.url} download={lastReport.filename} className="underline">
                Download again
              </a>
            </div>
          </div>
        )}

        <p className="text-xs text-gray-400 mt-3">
          Reports are generated in your browser and work offline — no data leaves this device.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="bg-white border border-gray-100 rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-700 mb-3">What the report includes</h2>
          <ul className="space-y-2.5">
            {INCLUDES.map((t) => (
              <li key={t} className="text-xs text-gray-600 flex gap-2">
                <span style={{ color: "#0F6E56" }}>✓</span>
                {t}
              </li>
            ))}
          </ul>
        </div>

        <div className="bg-white border border-gray-100 rounded-xl p-5">
          <h2 className="text-sm font-medium text-gray-700 mb-3">Recent reports</h2>
          <div className="divide-y divide-gray-50">
            {recent.map((r) => (
              <div key={r.id} className="py-2.5 flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-xs font-medium text-gray-800 truncate">{r.bridge}</div>
                  <div className="text-xs text-gray-400">{r.kind}</div>
                </div>
                {r.url ? (
                  <a href={r.url} download className="text-xs no-underline shrink-0" style={{ color: "#0F6E56" }}>
                    Download
                  </a>
                ) : (
                  <span className="text-xs text-gray-400 shrink-0">{r.date}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
