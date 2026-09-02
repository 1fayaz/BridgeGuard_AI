"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { generateReadings, type Severity } from "@/lib/data";

export default function BridgeChart({ severity }: { severity: Severity }) {
  const readings = generateReadings(severity);

  return (
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
            stroke={severity === "CRITICAL" ? "#dc2626" : "#0ea5e9"}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
