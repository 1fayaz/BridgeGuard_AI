"use client";
import { useParams } from "next/navigation";
import Link from "next/link";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine, ResponsiveContainer } from "recharts";
import { getBridge, generateReadings } from "@/lib/data";

const scoreColor: Record<string, string> = {
  CRITICAL: "#ef4444", WARNING: "#f97316",
  WATCH: "#eab308", SAFE: "#22c55e",
};

const badge: Record<string, { bg: string; text: string; label: string }> = {
  CRITICAL: { bg: "#fcebeb", text: "#A32D2D", label: "🔴 Critical" },
  WARNING:  { bg: "#FAECE7", text: "#993C1D", label: "🟠 Warning" },
  WATCH:    { bg: "#faeeda", text: "#854F0B", label: "🟡 Watch" },
  SAFE:     { bg: "#eaf3de", text: "#3B6D11", label: "🟢 Safe" },
};

export default function BridgeDetailPage() {
  const { id } = useParams<{ id: string }>();
  const bridge = typeof id === "string" ? getBridge(id) : undefined;

  if (!bridge) return (
    <main className="p-6 text-center">
      <p className="text-gray-500">Bridge not found.</p>
      <Link href="/" className="text-sm text-blue-600 mt-2 inline-block">← Back to overview</Link>
    </main>
  );

  const readings = generateReadings(bridge.severity, bridge.id);
  const color = scoreColor[bridge.severity];
  const bd = badge[bridge.severity];
  const currentRms = readings[readings.length - 1].rms;
  const alertCount = bridge.alerts.length;

  return (
    <main className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <Link href="/" className="text-sm text-gray-400 hover:text-gray-600 no-underline">← All bridges</Link>
          <h1 className="text-xl font-medium text-gray-900 mt-1">{bridge.name}</h1>
          <p className="text-sm text-gray-500">📍 {bridge.location} · Live monitoring</p>
        </div>
        <div className="flex gap-2 items-center">
          <span className="text-xs font-medium px-3 py-1.5 rounded-full"
            style={{ background: bd.bg, color: bd.text }}>{bd.label}</span>
          <Link href={`/bridges/${bridge.id}/alerts`}
            className="px-3 py-1.5 rounded-lg text-sm border border-gray-200 text-gray-600 hover:bg-gray-50 no-underline">
            View Alerts {alertCount > 0 ? `(${alertCount}) ` : ""}→
          </Link>
        </div>
      </div>

      <div className="bg-white border border-gray-100 rounded-xl p-5 mb-4">
        <div className="flex items-center gap-6 mb-4">
          <div>
            <div className="text-5xl font-medium" style={{ color }}>{bridge.risk_score}</div>
            <div className="text-xs text-gray-400 mt-1">Risk score (0–100)</div>
          </div>
          <div className="flex-1">
            <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full rounded-full"
                style={{ width: `${bridge.risk_score}%`, background: color }} />
            </div>
            <div className="flex justify-between text-xs text-gray-400 mt-1">
              <span>Safe</span><span>Critical</span>
            </div>
          </div>
        </div>

        <div className="p-4 rounded-xl mb-3"
          style={{ background: "#e6f1fb", border: "0.5px solid #b5d4f4" }}>
          <div className="text-xs font-medium mb-2" style={{ color: "#185fa5" }}>
            🤖 AI Risk Assessment — plain language explanation
          </div>
          <p className="text-sm text-gray-800 leading-relaxed">{bridge.explanation}</p>
        </div>

        {bridge.review_status === "PENDING_HUMAN_REVIEW" && (
          <div className="p-3 rounded-lg text-xs"
            style={{ background: "#fff7ed", border: "0.5px solid #f97316", color: "#c2410c" }}>
            ⏳ Awaiting engineer sign-off — this assessment is not final until reviewed by a qualified engineer.
          </div>
        )}
      </div>

      <div className="bg-white border border-gray-100 rounded-xl p-5 mb-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-medium text-gray-700">Live vibration readings — accelerometer</h2>
          <span className="text-xs text-gray-400">Updates every 10 seconds</span>
        </div>
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={readings}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0ea" />
            <XAxis dataKey="time" tick={{ fontSize: 10 }} interval={9} />
            <YAxis tick={{ fontSize: 10 }} unit=" m/s²" width={65} />
            <Tooltip formatter={(v) => [`${v} m/s²`, "Vibration"]} />
            <ReferenceLine y={0.5} stroke="#f97316" strokeDasharray="4 4"
              label={{ value: "Normal limit", fontSize: 10, fill: "#f97316" }} />
            <Line type="monotone" dataKey="rms" stroke="#0F6E56"
              strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
        <div className="flex gap-4 mt-2 text-xs text-gray-400">
          <span>● Normal range: 0.2–0.5 m/s²</span>
          <span style={{ color: "#f97316" }}>— Orange line: design limit</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <div className="bg-white border border-gray-100 rounded-xl p-4">
          <div className="text-xs text-gray-400 mb-1">Current vibration</div>
          <div className="text-xl font-medium" style={{ color }}>{currentRms} m/s²</div>
        </div>
        <div className="bg-white border border-gray-100 rounded-xl p-4">
          <div className="text-xs text-gray-400 mb-1">Readings collected</div>
          <div className="text-xl font-medium text-gray-900">50</div>
        </div>
        <div className="bg-white border border-gray-100 rounded-xl p-4">
          <div className="text-xs text-gray-400 mb-1">Monitoring status</div>
          <div className="text-sm font-medium" style={{ color: "#3B6D11" }}>● Active</div>
        </div>
      </div>
    </main>
  );
}
