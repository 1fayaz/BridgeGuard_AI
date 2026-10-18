"use client";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceArea,
} from "recharts";
import { BRIDGES, SEVERITY_CONFIG, plainOneLiner, generateReadings, type Bridge, type Severity, type DataSource } from "@/lib/data";
import { fetchBridgeRisk, fetchReadings } from "@/lib/api";
import ShieldScore from "@/components/ShieldScore";
import DataSourceBadge from "@/components/DataSourceBadge";

// A handful of plain-language "what happened today" steps, derived from this bridge's own
// fixture alerts rather than invented timestamps unrelated to its data.
function buildTimeline(bridge: Bridge) {
  const steps = [
    { color: "#097F37", title: "Everything normal", detail: "Shaking was inside the safe zone." },
  ];
  const order: Severity[] = ["WATCH", "WARNING", "CRITICAL"];
  for (const sev of order) {
    const alert = bridge.alerts.find((a) => a.severity === sev);
    if (!alert) continue;
    const cfg = SEVERITY_CONFIG[sev];
    steps.push({ color: cfg.bar, title: `${cfg.label} alert raised`, detail: alert.message });
  }
  return steps.map((s, i) => ({ ...s, time: bridge.alerts[i - 1]?.time ?? "—" }));
}

export default function BridgeDetailClient({ bridge }: { bridge: Bridge }) {
  const [readings, setReadings] = useState<{ time: string; rms: number }[]>([]);
  const [readingsSource, setReadingsSource] = useState<DataSource>("sample");
  const [liveBridge, setLiveBridge] = useState(bridge);
  const [riskSource, setRiskSource] = useState<DataSource>("sample");

  // One static, honestly-labelled simulated series — generated once, never silently re-randomized
  // on an interval pretending to be live (that was the old fake-chart behaviour).
  const simulatedReadings = useMemo(
    () => generateReadings(bridge.severity).map((p) => ({ time: p.time, rms: p.value })),
    [bridge.severity],
  );

  useEffect(() => {
    let cancelled = false;
    setReadings(simulatedReadings);
    setReadingsSource("sample");

    async function tryLive() {
      if (!process.env.NEXT_PUBLIC_API_URL || !bridge.sensor_id) return;
      const real = await fetchReadings(bridge.id, bridge.sensor_id, 50);
      if (cancelled) return;
      if (!real || real.length === 0) {
        setReadingsSource("live-unavailable");
        return;
      }
      setReadings(real.map((r) => ({ time: new Date(r.sensor_time).toLocaleTimeString("en-GB"), rms: r.value })));
      setReadingsSource("live");
    }
    tryLive();
    return () => {
      cancelled = true;
    };
  }, [bridge.id, bridge.sensor_id, simulatedReadings]);

  useEffect(() => {
    let cancelled = false;
    async function pollRisk() {
      if (!process.env.NEXT_PUBLIC_API_URL) return;
      const risk = await fetchBridgeRisk(bridge.id);
      if (cancelled) return;
      if (!risk) {
        setRiskSource("live-unavailable");
        return;
      }
      setLiveBridge((prev) => ({
        ...prev,
        risk_score: risk.risk_score,
        severity: risk.severity as Severity,
        explanation: risk.explanation,
        review_status: risk.review_status as Bridge["review_status"],
      }));
      setRiskSource("live");
    }
    pollRisk();
    const interval = process.env.NEXT_PUBLIC_API_URL ? setInterval(pollRisk, 10_000) : undefined;
    return () => {
      cancelled = true;
      if (interval) clearInterval(interval);
    };
  }, [bridge.id]);

  const cfg = SEVERITY_CONFIG[liveBridge.severity];
  const currentRms = readings.length > 0 ? readings[readings.length - 1].rms : liveBridge.current_rms;
  const timeline = useMemo(() => buildTimeline(liveBridge), [liveBridge]);
  const overallSource: DataSource = riskSource === "live" || readingsSource === "live" ? "live" : riskSource;

  // Measured directly rather than via recharts' <ResponsiveContainer> — its internal
  // ResizeObserver-driven width got stuck at 0 in narrow-viewport/headless rendering even though
  // its own DOM node measured correctly (262px container, 0px svg). A plain ref + ResizeObserver
  // sidesteps whatever's wrong inside that component.
  const chartBoxRef = useRef<HTMLDivElement>(null);
  const [chartWidth, setChartWidth] = useState(320);
  useEffect(() => {
    const el = chartBoxRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) setChartWidth(w);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="flex flex-col gap-5">
      <Link href="/" className="inline-block text-[15px] font-bold text-blue">
        ← All bridges
      </Link>

      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <svg width={56} height={63} viewBox="0 0 64 72" className="shrink-0">
            <path d="M32 3 L59 13 V35 C59 52 47 63 32 69 C17 63 5 52 5 35 V13 Z" fill={cfg.bar} />
            <path d="M32 9 L53 17 V35 C53 48 44 57 32 62 C20 57 11 48 11 35 V17 Z" fill="none" stroke="#FFFFFF" strokeOpacity={0.5} strokeWidth={1.6} />
            <path d="M32 22 V40" stroke="#FFFFFF" strokeWidth={5} strokeLinecap="round" />
            <circle cx={32} cy={50} r={3.2} fill="#FFFFFF" />
          </svg>
          <div>
            <h1 className="font-display text-[28px] font-extrabold tracking-tight text-navy sm:text-[34px]">
              {liveBridge.name}
            </h1>
            <div className="mt-1 flex flex-wrap items-center gap-3.5 text-[15px] text-navy-text">
              <span>{liveBridge.location}</span>
              <DataSourceBadge source={overallSource} />
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <Link href={`/bridges/${liveBridge.id}/alerts`} className="rounded-xl border-[1.5px] border-navy bg-white px-6 py-3.5 text-[15px] font-bold text-navy">
            View alerts {liveBridge.alerts.length > 0 && `(${liveBridge.alerts.length})`}
          </Link>
          <Link href="/reports" className="rounded-xl bg-navy px-6 py-3.5 text-[15px] font-bold text-white">
            Create report
          </Link>
        </div>
      </div>

      <div className="flex flex-wrap gap-5">
        <section className="flex-1 basis-[300px] rounded-[22px] bg-white p-7 text-center shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]" style={{ maxWidth: 380 }}>
          <div className="text-sm font-bold tracking-wide text-navy-muted">RISK SCORE RIGHT NOW</div>
          <div className="mx-auto mt-3.5 w-[170px]">
            <ShieldScore severity={liveBridge.severity} score={liveBridge.risk_score} size={170} />
          </div>
          <div className="mt-2 inline-block rounded-full px-4.5 py-2 text-[15px] font-bold" style={{ background: cfg.bgHex, color: cfg.textHex }}>
            {cfg.label}
          </div>
          {liveBridge.review_status === "PENDING_HUMAN_REVIEW" && (
            <div className="mt-5 rounded-xl border border-[#F0B35A] bg-[#FFF4E0] p-3.5 text-left text-sm leading-relaxed text-[#6B3E05]">
              <strong>Awaiting engineer review.</strong> This result is not final until a person confirms it.
            </div>
          )}
        </section>

        <div className="flex min-w-0 flex-[2_1_460px] flex-col gap-5">
          <section className="rounded-[22px] border border-[#A9D3F0] bg-[#E8F3FB] p-7">
            <div className="text-[13px] font-bold tracking-wider text-blue">WHAT THIS MEANS, IN PLAIN WORDS</div>
            <p className="mt-3 font-display text-xl font-semibold leading-relaxed text-navy">
              {liveBridge.explanation}
            </p>
            <div className="mt-3.5 text-[13px] text-[#3F6A8F]">Written by the AI assistant from sensor readings.</div>
          </section>

          <section className="rounded-[22px] bg-white p-6 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
            <h2 className="font-display text-lg font-extrabold text-navy">What should we do?</h2>
            <div className="mt-3.5 flex flex-col gap-3.5">
              {[
                liveBridge.severity === "SAFE" ? "No action needed right now." : plainOneLiner(liveBridge),
                "Keep watching the live readings below.",
                "Create a report to share with the authority.",
              ].map((step, i) => (
                <div key={i} className="flex items-start gap-3.5">
                  <div
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-extrabold"
                    style={i === 0 ? { background: cfg.bar, color: cfg.shieldTextDark ? "#2B1D00" : "#fff" } : { background: "#E3EAF2", color: "#00325D" }}
                  >
                    {i + 1}
                  </div>
                  <div className="pt-1 text-base leading-relaxed">{i === 0 ? <strong>{step}</strong> : step}</div>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      {/* Timeline */}
      <section className="rounded-[22px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
        <h2 className="font-display text-xl font-extrabold text-navy">What happened today</h2>
        <p className="mt-1.5 mb-5 text-[15px] text-navy-text">The story so far, in order.</p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {timeline.map((step, i) => (
            <div key={i} className="pt-3.5" style={{ borderTop: `5px solid ${step.color}` }}>
              <div className="font-display text-lg font-extrabold">{step.time}</div>
              <div className="mt-1 text-base font-bold">{step.title}</div>
              <div className="mt-1 text-sm leading-relaxed text-navy-text">{step.detail}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Chart */}
      <section className="rounded-[22px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <div>
            <h2 className="font-display text-xl font-extrabold text-navy">How much is the bridge shaking?</h2>
            <div className="mt-1 text-sm text-navy-muted">The green zone is a comfortable range.</div>
          </div>
          <DataSourceBadge source={readingsSource} />
        </div>

        <div ref={chartBoxRef} className="mt-4 w-full overflow-x-auto">
          <LineChart
            data={readings}
            width={chartWidth}
            height={220}
            margin={{ left: 0, right: 8, top: 4, bottom: 0 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#E3EAF2" />
            <XAxis dataKey="time" tick={{ fontSize: 9 }} interval={Math.floor(readings.length / 5)} />
            <YAxis tick={{ fontSize: 10 }} tickFormatter={(v: number) => v.toFixed(2)} unit=" m/s²" width={75} domain={[0, "auto"]} />
            <Tooltip formatter={(value) => [`${Number(value).toFixed(3)} m/s²`, "Vibration RMS"]} labelFormatter={(l) => `Time: ${l}`} />
            <ReferenceArea y1={0} y2={0.5} fill={SEVERITY_CONFIG.SAFE.bar} fillOpacity={0.08} />
            <Line type="monotone" dataKey="rms" stroke={cfg.bar} strokeWidth={2.5} dot={false} isAnimationActive={false} />
          </LineChart>
        </div>

        <div className="mt-2 flex flex-wrap gap-6 text-xs text-navy-muted">
          <span>● Comfortable range shown in green</span>
          <span style={{ color: cfg.bar }}>— Current: {currentRms} m/s²</span>
          <span className="italic">{readingsSource === "live" ? "Live readings" : "Simulated readings"}</span>
        </div>
      </section>

      {/* Facts */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {[
          { label: "Current vibration", value: `${currentRms} m/s²`, color: cfg.bar },
          { label: "Open alerts", value: `${liveBridge.alerts.length}`, color: "#00325D" },
          { label: "Sensor status", value: "Online", color: "#097F37" },
          { label: "Final decision by", value: "An engineer", color: "#00325D" },
        ].map((f) => (
          <div key={f.label} className="rounded-2xl bg-white p-5 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
            <div className="text-sm font-semibold text-navy-muted">{f.label}</div>
            <div className="mt-1.5 font-display text-2xl font-extrabold" style={{ color: f.color }}>
              {f.value}
            </div>
          </div>
        ))}
      </div>

      {liveBridge.maintenance_log.length > 0 && (
        <section className="rounded-[22px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
          <h2 className="font-display text-xl font-extrabold text-navy">Maintenance history</h2>
          <div className="mt-3.5 flex flex-col gap-3.5">
            {liveBridge.maintenance_log.map((log, i) => (
              <div key={i} className="flex gap-3.5 border-b border-border-light pb-3.5 last:border-0 last:pb-0">
                <div className="min-w-24 pt-0.5 text-xs text-navy-muted">{log.date}</div>
                <div>
                  <div className="text-xs font-semibold text-navy-text">{log.inspector}</div>
                  <div className="mt-0.5 text-xs text-navy-text">{log.finding}</div>
                  <div className="mt-1 text-xs" style={{ color: "#0F6E56" }}>→ {log.action}</div>
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
