"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { BRIDGES, SEVERITY_CONFIG, generateReadings } from "@/lib/data";

export default function BridgeDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const bridge = BRIDGES.find((b) => b.id === id);

  if (!bridge) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-8 text-center">
        <h1 className="text-xl font-semibold text-red-800">Bridge not found</h1>
        <p className="mt-2 text-red-700">
          No bridge matches <code>{id}</code>.
        </p>
        <Link
          href="/"
          className="mt-4 inline-block text-sm font-medium text-red-800 underline"
        >
          Back to overview
        </Link>
      </div>
    );
  }

  const cfg = SEVERITY_CONFIG[bridge.severity];
  const readings = generateReadings(bridge.severity);

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">{bridge.name}</h1>
          <p className="text-slate-500">{bridge.location}</p>
        </div>
        <Link
          href="/"
          className="text-sm font-medium text-slate-600 hover:text-slate-900"
        >
          &larr; Back
        </Link>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-6">
          <p className="text-sm text-slate-500">Current Risk Score</p>
          <p className="mt-2 text-5xl font-bold text-slate-900">
            {bridge.risk_score}
          </p>
          <span
            className={`mt-3 inline-block rounded-full px-3 py-1 text-xs font-bold uppercase ${cfg.bg} ${cfg.text}`}
          >
            {cfg.label}
          </span>
        </div>

        <div className="rounded-xl border border-slate-200 bg-white p-6 lg:col-span-2">
          <p className="text-sm text-slate-500">AI Assessment</p>
          <p className="mt-2 text-slate-800 leading-relaxed">
            {bridge.explanation}
          </p>
          {bridge.review_status === "PENDING_HUMAN_REVIEW" && (
            <div className="mt-4 rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-800">
              This score is pending human engineering review.
            </div>
          )}
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white p-6">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-900">
            Vibration Time Series
          </h2>
          <span className="text-sm text-slate-500">
            Sensor {bridge.sensor_id}
          </span>
        </div>
        <div className="mt-4 h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={readings}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
              <XAxis dataKey="time" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip
                formatter={(value) => [`${value} mm/s²`, "RMS"]}
                labelStyle={{ color: "#334155" }}
              />
              <Line
                type="monotone"
                dataKey="value"
                stroke={bridge.severity === "CRITICAL" ? "#dc2626" : "#0ea5e9"}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="flex gap-4">
        <Link
          href={`/bridges/${bridge.id}/alerts`}
          className="rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white hover:bg-slate-800 transition"
        >
          View Alerts ({bridge.alerts.length})
        </Link>
        <Link
          href="/reports"
          className="rounded-lg border border-slate-300 bg-white px-5 py-2.5 text-sm font-semibold text-slate-700 hover:bg-slate-50 transition"
        >
          Generate Report
        </Link>
      </div>
    </div>
  );
}
