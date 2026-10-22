"use client";

import { useEffect, useState } from "react";
import { type DataSource } from "@/lib/data";
import { NAMED_BRIDGES } from "@/lib/named-bridges";
import { fetchReadings } from "@/lib/api";
import DataSourceBadge from "@/components/DataSourceBadge";

interface ConnectedSensor {
  bridgeName: string;
  sensorId: string;
  lastSeen: string;
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.round(ms / 1000);
  if (s < 5) return "just now";
  if (s < 90) return `${s} s ago`;
  const m = Math.round(s / 60);
  if (m < 90) return `${m} min ago`;
  return `${Math.round(m / 60)} h ago`;
}

const SETUP_ITEMS = [
  "Cloud server and database",
  "The five AI agents",
  "Alerts and the engineer approval page",
  "PDF reports",
];

const STEPS = [
  {
    title: "Register the bridge and sensor",
    body: "Give the bridge a name and location, and the sensor an ID, in the backend's sensor registry.",
  },
  {
    title: "Power on the gateway",
    body: "Turn on the Raspberry Pi gateway near the bridge and let it join the LoRaWAN network.",
  },
  {
    title: "Point it to the server",
    body: "Set the gateway's upload address to the BridgeGuard server shown below.",
  },
  {
    title: "Wait for the first reading",
    body: "Once a reading arrives, this page updates on its own - nothing else to configure.",
  },
];

export default function ConnectPage() {
  const [source, setSource] = useState<DataSource>("sample");
  const [connected, setConnected] = useState<ConnectedSensor[]>([]);
  const [copied, setCopied] = useState(false);

  const serverUrl = process.env.NEXT_PUBLIC_API_URL || "";

  useEffect(() => {
    let cancelled = false;
    async function checkSensors() {
      if (!serverUrl) return; // no backend configured - stay honestly "sample".
      const results = await Promise.all(
        NAMED_BRIDGES.map(async (b) => {
          const readings = await fetchReadings(b.id, b.sensorId, 1);
          if (!readings || readings.length === 0) return null;
          return { bridgeName: b.name, sensorId: b.sensorId, lastSeen: readings[0].sensor_time };
        }),
      );
      if (cancelled) return;
      setSource("live");
      setConnected(results.filter((r): r is ConnectedSensor => r !== null));
    }
    checkSensors();
    return () => {
      cancelled = true;
    };
  }, [serverUrl]);

  function copyUrl() {
    if (!serverUrl) return;
    navigator.clipboard?.writeText(serverUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="text-[13px] font-bold tracking-wider text-blue">CONNECT SENSORS</div>
        <h1 className="mt-2 font-display text-[28px] font-extrabold tracking-tight text-navy sm:text-[38px]">
          Your system is ready. Sensors are the last step.
        </h1>
        <p className="mt-3 max-w-[720px] text-[16px] leading-relaxed text-navy-text sm:text-[18px]">
          Everything that reads, scores, alerts on, and reports a sensor reading is already built
          and running. The only thing left is attaching hardware to a real bridge.
        </p>
        <div className="mt-3">
          <DataSourceBadge source={source} />
        </div>
      </div>

      {/* Top banner: calm status, never alarming - this is the expected state before hardware exists. */}
      {connected.length === 0 ? (
        <div className="flex items-center gap-3 rounded-2xl border border-border bg-white px-6 py-5">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-blue" />
          <div>
            <div className="font-display text-lg font-bold text-navy">System ready. No sensors connected yet.</div>
            <div className="mt-0.5 text-[14px] text-navy-text">
              That is expected until hardware is attached - see the setup guide below.
            </div>
          </div>
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {connected.map((s) => (
            <div key={s.sensorId} className="flex items-center gap-3 rounded-2xl border border-safe bg-safe-bg px-6 py-5">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-safe" />
              <div>
                <div className="font-display text-lg font-bold text-navy">{s.bridgeName}</div>
                <div className="mt-0.5 text-[14px] text-navy-text">
                  Connected · sensor {s.sensorId} · last reading {timeAgo(s.lastSeen)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* What is already set up */}
      <section className="rounded-[22px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
        <h2 className="font-display text-xl font-extrabold text-navy">What is already set up</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {SETUP_ITEMS.map((item) => (
            <div key={item} className="flex items-center gap-3 rounded-xl bg-page-bg px-4 py-3.5">
              <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="#097F37" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12l5 5L20 7" />
              </svg>
              <span className="text-[15px] font-semibold text-navy">{item}</span>
              <span className="ml-auto rounded-full bg-safe-bg px-3 py-1 text-xs font-bold text-safe-text">Ready</span>
            </div>
          ))}
        </div>
      </section>

      {/* How to connect a sensor */}
      <section className="rounded-[22px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
        <div className="text-[13px] font-bold tracking-wider text-blue">SETUP GUIDE</div>
        <h2 className="mt-1 font-display text-xl font-extrabold text-navy">Hardware connection is the next phase.</h2>
        <div className="mt-5 flex flex-col gap-4">
          {STEPS.map((step, i) => (
            <div key={step.title} className="flex items-start gap-3.5">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-navy text-[15px] font-extrabold text-white">
                {i + 1}
              </div>
              <div className="min-w-0 flex-1 pt-1">
                <div className="text-base font-bold text-navy">{step.title}</div>
                <p className="mt-1 text-[15px] leading-relaxed text-navy-text">{step.body}</p>
                {i === 2 && (
                  <div className="mt-2.5 flex flex-wrap items-center gap-2">
                    <code className="min-w-0 break-all rounded-lg bg-page-bg px-3.5 py-2.5 text-[14px] text-navy">
                      {serverUrl || "Not configured for this deployment - ask your presenter for the server address."}
                    </code>
                    {serverUrl && (
                      <button
                        onClick={copyUrl}
                        className="shrink-0 rounded-lg border-[1.5px] border-navy px-3.5 py-2.5 text-[13px] font-bold text-navy"
                      >
                        {copied ? "Copied!" : "Copy"}
                      </button>
                    )}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* Sample preview - clearly fake, never confused with the real empty/connected states above. */}
      <section className="rounded-[22px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
        <h2 className="font-display text-xl font-extrabold text-navy">What a connected sensor will look like</h2>
        <p className="mt-1.5 mb-4 text-[15px] text-navy-text">
          A preview only - this card does not represent a real bridge or reading.
        </p>
        <div className="flex items-center gap-3 rounded-2xl border border-safe bg-safe-bg px-6 py-5 opacity-80">
          <span className="h-2.5 w-2.5 shrink-0 rounded-full bg-safe" />
          <div className="flex-1">
            <div className="font-display text-lg font-bold text-navy">Example Bridge</div>
            <div className="mt-0.5 text-[14px] text-navy-text">Connected · sensor acc-example-01 · last reading 3 s ago</div>
          </div>
          <span className="rounded-full bg-unknown-bg px-3 py-1 text-xs font-bold text-unknown-text">
            Sample data, not a real connection
          </span>
        </div>
      </section>
    </div>
  );
}
