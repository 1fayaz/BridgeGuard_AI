"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { getBridge, type Alert } from "@/lib/data";

const badge: Record<string, { bg: string; text: string; label: string }> = {
  CRITICAL: { bg: "#fcebeb", text: "#A32D2D", label: "🔴 Critical" },
  WARNING:  { bg: "#FAECE7", text: "#993C1D", label: "🟠 Warning" },
  WATCH:    { bg: "#faeeda", text: "#854F0B", label: "🟡 Watch" },
  SAFE:     { bg: "#eaf3de", text: "#3B6D11", label: "🟢 Safe" },
};

const SEVERITY_ORDER: Record<string, number> = { CRITICAL: 0, WARNING: 1, WATCH: 2, SAFE: 3 };

const ICONS: Record<string, string> = {
  CRITICAL: "🚨",
  WARNING: "⚠️",
  WATCH: "👁️",
  SAFE: "✅",
};

function sortAlerts(alerts: Alert[]): Alert[] {
  return [...alerts].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9)
  );
}

export default function AlertsPage() {
  const { id } = useParams<{ id: string }>();
  const bridge = typeof id === "string" ? getBridge(id) : undefined;

  if (!bridge) {
    return (
      <main className="p-6 text-center">
        <p className="text-gray-500">Bridge not found.</p>
        <Link href="/" className="text-sm text-blue-600 mt-2 inline-block">
          ← Back to overview
        </Link>
      </main>
    );
  }

  const alerts = sortAlerts(bridge.alerts);
  const criticalCount = alerts.filter((a) => a.severity === "CRITICAL").length;

  return (
    <main className="p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <Link
            href={`/bridges/${bridge.id}`}
            className="text-sm text-gray-400 hover:text-gray-600 no-underline"
          >
            ← {bridge.name}
          </Link>
          <h1 className="text-xl font-medium text-gray-900 mt-1">Alerts</h1>
          <p className="text-sm text-gray-500">📍 {bridge.location}</p>
        </div>
        <Link
          href="/reports"
          className="px-4 py-2 rounded-lg text-sm font-medium text-white no-underline"
          style={{ backgroundColor: "#0F6E56" }}
        >
          Generate Report
        </Link>
      </div>

      <div className="flex gap-3 mb-5">
        <div className="bg-white border border-gray-100 rounded-xl px-4 py-3 flex-1">
          <div className="text-xs text-gray-400 mb-1">Total alerts</div>
          <div className="text-2xl font-medium text-gray-900">{alerts.length}</div>
        </div>
        <div className="bg-white border border-gray-100 rounded-xl px-4 py-3 flex-1">
          <div className="text-xs text-gray-400 mb-1">Critical</div>
          <div
            className="text-2xl font-medium"
            style={{ color: criticalCount > 0 ? "#ef4444" : "#9ca3af" }}
          >
            {criticalCount}
          </div>
        </div>
        <div className="bg-white border border-gray-100 rounded-xl px-4 py-3 flex-1">
          <div className="text-xs text-gray-400 mb-1">Status</div>
          <div className="text-sm font-medium" style={{ color: "#3B6D11" }}>
            ● Monitoring active
          </div>
        </div>
      </div>

      {alerts.length === 0 ? (
        <div className="bg-white border border-gray-100 rounded-xl p-10 text-center">
          <div className="text-4xl mb-3">✅</div>
          <div className="text-sm font-medium text-gray-800 mb-1">No active alerts</div>
          <p className="text-xs text-gray-500 max-w-sm mx-auto">
            {bridge.name} is not showing any structural concerns. All sensors are reporting
            normal readings — this page will update automatically if that changes.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {alerts.map((a, i) => {
            const bd = badge[a.severity];
            const isCritical = a.severity === "CRITICAL";
            return (
              <div
                key={i}
                className="bg-white rounded-xl p-4"
                style={{
                  border: `1px solid ${isCritical ? "#ef4444" : "#f0f0ea"}`,
                  borderWidth: isCritical ? "1.5px" : "1px",
                }}
              >
                <div className="flex items-start gap-3">
                  <div className="text-lg leading-none mt-0.5">{ICONS[a.severity]}</div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-3 mb-1.5">
                      <span
                        className="text-xs font-medium px-2.5 py-1 rounded-full"
                        style={{ background: bd.bg, color: bd.text }}
                      >
                        {bd.label}
                      </span>
                      {a.timestamp && (
                        <span className="text-xs text-gray-400">{a.timestamp}</span>
                      )}
                    </div>
                    <p className="text-sm text-gray-800 leading-relaxed">{a.message}</p>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <p className="text-xs text-gray-400 mt-5">
        Alerts are raised automatically by the Risk Reasoning agent when sensor readings cross
        safe thresholds. Critical alerts always appear first and require engineer sign-off.
      </p>
    </main>
  );
}
