"use client";
import Link from "next/link";
import { useState, useEffect, useRef } from "react";
import {
  LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { BRIDGES, SEVERITY_CONFIG, type Bridge } from "@/lib/data";

function generateReading(severity: string, index: number) {
  const now = new Date();
  const time = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}:${String(now.getSeconds()).padStart(2, "0")}`;
  let rms: number;
  if (severity === "CRITICAL") {
    rms = index > 35
      ? parseFloat((2.3 + Math.random() * 1.2).toFixed(3))
      : parseFloat((0.28 + Math.random() * 0.12).toFixed(3));
  } else if (severity === "WARNING") {
    rms = index > 30
      ? parseFloat((0.7 + Math.random() * 0.4).toFixed(3))
      : parseFloat((0.32 + Math.random() * 0.1).toFixed(3));
  } else if (severity === "WATCH") {
    rms = parseFloat((0.42 + Math.random() * 0.15).toFixed(3));
  } else {
    rms = parseFloat((0.22 + Math.random() * 0.08).toFixed(3));
  }
  return { time, rms };
}

function generateInitialReadings(severity: string) {
  return Array.from({ length: 40 }, (_, i) => {
    const base = new Date(Date.now() - (40 - i) * 3000);
    const time = `${String(base.getHours()).padStart(2, "0")}:${String(base.getMinutes()).padStart(2, "0")}:${String(base.getSeconds()).padStart(2, "0")}`;
    let rms: number;
    if (severity === "CRITICAL") {
      rms = i > 32
        ? parseFloat((2.3 + Math.random() * 1.0).toFixed(3))
        : parseFloat((0.28 + Math.random() * 0.1).toFixed(3));
    } else if (severity === "WARNING") {
      rms = i > 28
        ? parseFloat((0.7 + Math.random() * 0.3).toFixed(3))
        : parseFloat((0.31 + Math.random() * 0.1).toFixed(3));
    } else if (severity === "WATCH") {
      rms = parseFloat((0.4 + Math.random() * 0.15).toFixed(3));
    } else {
      rms = parseFloat((0.22 + Math.random() * 0.06).toFixed(3));
    }
    return { time, rms };
  });
}

export default function BridgeDetailClient({ bridge }: { bridge: Bridge }) {
  const [readings, setReadings] = useState<{ time: string; rms: number }[]>([]);
  const [liveCount, setLiveCount] = useState(0);
  const indexRef = useRef(40);

  useEffect(() => {
    setReadings(generateInitialReadings(bridge.severity));
  }, [bridge.id]);

  useEffect(() => {
    const interval = setInterval(() => {
      const newReading = generateReading(
        bridge.severity, indexRef.current);
      indexRef.current += 1;
      setReadings(prev => {
        const updated = [...prev, newReading];
        return updated.slice(-50);
      });
      setLiveCount(prev => prev + 1);
    }, 3000);
    return () => clearInterval(interval);
  }, [bridge.id]);

  const cfg = SEVERITY_CONFIG[bridge.severity];
  const currentRms = readings.length > 0
    ? readings[readings.length - 1].rms
    : bridge.current_rms;

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="flex items-start justify-between mb-6">
        <div>
          <Link href="/"
            className="text-sm text-gray-400 hover:text-gray-600 no-underline">
            ← All bridges
          </Link>
          <h1 className="text-xl font-semibold text-gray-900 mt-1">
            {bridge.name}
          </h1>
          <p className="text-sm text-gray-500">
            📍 {bridge.location}
          </p>
        </div>
        <div className="flex gap-2 items-center flex-shrink-0">
          <span className="text-xs font-semibold px-3 py-1.5 rounded-full"
            style={{ background: cfg.bgHex, color: cfg.textHex }}>
            {cfg.label}
          </span>
          <Link href={`/bridges/${bridge.id}/alerts`}
            className="px-3 py-1.5 rounded-lg text-sm border border-gray-200 text-gray-600 hover:bg-gray-50 no-underline">
            View alerts {bridge.alerts.length > 0 && `(${bridge.alerts.length})`}
          </Link>
        </div>
      </div>

      <div className="bg-white border border-gray-100 rounded-xl p-5 mb-4 shadow-sm">
        <div className="flex items-center gap-6 mb-5">
          <div className="text-center">
            <div className="text-5xl font-bold"
              style={{ color: cfg.bar }}>
              {bridge.risk_score}
            </div>
            <div className="text-xs text-gray-400 mt-1">Risk score</div>
            <div className="text-xs text-gray-400">out of 100</div>
          </div>
          <div className="flex-1">
            <div className="flex justify-between text-xs text-gray-400 mb-1">
              <span>0 — Safe</span>
              <span>100 — Critical</span>
            </div>
            <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
              <div className="h-full rounded-full"
                style={{ width: `${bridge.risk_score}%`, background: cfg.bar }} />
            </div>
            <div className="flex gap-2 mt-3 flex-wrap">
              {bridge.chips.map((c) => (
                <span key={c.label}
                  className="text-xs px-2 py-0.5 rounded-md font-medium"
                  style={c.warn
                    ? { background: "#faeeda", color: "#854F0B" }
                    : { background: "#f0f0ea", color: "#666" }}>
                  {c.label}
                </span>
              ))}
            </div>
          </div>
        </div>

        <div className="p-4 rounded-xl mb-3"
          style={{ background: "#e6f1fb", border: "0.5px solid #b5d4f4" }}>
          <div className="text-xs font-semibold mb-2"
            style={{ color: "#185fa5" }}>
            🤖 AI Risk Assessment — plain language
          </div>
          <p className="text-sm text-gray-800 leading-relaxed">
            {bridge.explanation}
          </p>
        </div>

        {bridge.review_status === "PENDING_HUMAN_REVIEW" && (
          <div className="p-3 rounded-lg text-xs"
            style={{ background: "#fff7ed",
                     border: "0.5px solid #f97316",
                     color: "#c2410c" }}>
            ⏳ <strong>Awaiting engineer sign-off</strong> — AI recommends.
            Human decides. This alert cannot be cleared without
            a qualified engineer&apos;s approval.
          </div>
        )}
      </div>

      <div className="bg-white border border-gray-100 rounded-xl p-5 mb-4 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold text-gray-700">
            Live vibration readings — accelerometer
          </h2>
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1.5 text-xs font-medium"
              style={{ color: "#3B6D11" }}>
              <span className="w-2 h-2 rounded-full bg-green-500 animate-pulse inline-block" />
              LIVE · {liveCount} updates
            </span>
            <span className="text-xs text-gray-400">
              New reading every 3s
            </span>
          </div>
        </div>

        <ResponsiveContainer width="100%" height={220}>
          <LineChart data={readings}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0ea" />
            <XAxis dataKey="time" tick={{ fontSize: 9 }}
              interval={Math.floor(readings.length / 5)} />
            <YAxis tick={{ fontSize: 10 }}
              unit=" m/s²" width={72} />
            <Tooltip
              formatter={(v) => [`${v} m/s²`, "Vibration RMS"]} />
            <ReferenceLine y={0.5} stroke="#f97316"
              strokeDasharray="4 4"
              label={{ value: "Design limit",
                       fontSize: 10, fill: "#f97316",
                       position: "insideTopRight" }} />
            <Line type="monotone" dataKey="rms"
              stroke={cfg.bar} strokeWidth={2.5}
              dot={false} isAnimationActive={true}
              animationDuration={300} />
          </LineChart>
        </ResponsiveContainer>

        <div className="flex gap-6 mt-2 text-xs text-gray-400">
          <span>● Normal range: 0.2–0.5 m/s²</span>
          <span style={{ color: "#f97316" }}>
            — Orange: design limit
          </span>
          <span style={{ color: cfg.bar }}>
            — Current: {currentRms} m/s²
          </span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        {[
          { label: "Current vibration",
            value: `${currentRms} m/s²`,
            color: cfg.bar },
          { label: "Readings received",
            value: `${40 + liveCount}`,
            color: "#1a1a18" },
          { label: "Sensor status",
            value: "● Active",
            color: "#3B6D11" },
        ].map((s) => (
          <div key={s.label}
            className="bg-white border border-gray-100 rounded-xl p-4 shadow-sm">
            <div className="text-xs text-gray-400 mb-1">{s.label}</div>
            <div className="text-lg font-semibold"
              style={{ color: s.color }}>
              {s.value}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
