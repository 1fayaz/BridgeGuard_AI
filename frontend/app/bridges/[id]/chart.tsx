"use client";

import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { generateReadings, type Severity } from "@/lib/data";

const STROKES: Record<Severity, string> = {
  SAFE: "#10b981",
  WATCH: "#f59e0b",
  WARNING: "#f97316",
  CRITICAL: "#e11d48",
};

const FILLS: Record<Severity, string> = {
  SAFE: "#10b981",
  WATCH: "#f59e0b",
  WARNING: "#f97316",
  CRITICAL: "#e11d48",
};

export default function BridgeChart({ severity }: { severity: Severity }) {
  const readings = generateReadings(severity);

  return (
    <div className="mt-6 h-80">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={readings} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id={`grad-${severity}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={FILLS[severity]} stopOpacity={0.25} />
              <stop offset="95%" stopColor={FILLS[severity]} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis
            dataKey="time"
            tick={{ fontSize: 11, fill: "#64748b" }}
            axisLine={{ stroke: "#cbd5e1" }}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: "#64748b" }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            formatter={(value) => [`${value} mm/s²`, "RMS Acceleration"]}
            labelStyle={{ color: "#334155", fontWeight: 600 }}
            contentStyle={{
              borderRadius: "0.75rem",
              border: "1px solid #e2e8f0",
              boxShadow: "0 10px 15px -3px rgb(0 0 0 / 0.1)",
            }}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={STROKES[severity]}
            strokeWidth={2.5}
            fill={`url(#grad-${severity})`}
            dot={false}
            activeDot={{ r: 5, strokeWidth: 0, fill: STROKES[severity] }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
