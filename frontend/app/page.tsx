"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { SEVERITY_CONFIG } from "@/lib/data";
import { NAMED_BRIDGES, loadOverviewScores, type OverviewScoreEntry } from "@/lib/named-bridges";
import {
  CONDITION_CARD_TITLE,
  loadAllResearchConditions,
  type ResearchConditionFile,
  type ResearchConditionKey,
} from "@/lib/research-data";
import WatchDemo from "@/components/WatchDemo";
import { useAlertStore } from "@/lib/alert-store";

export default function HomePage() {
  const router = useRouter();
  const { openCountFor } = useAlertStore();
  const [showWatchDemo, setShowWatchDemo] = useState(false);
  const [conditions, setConditions] = useState<Partial<Record<ResearchConditionKey, ResearchConditionFile>>>({});
  const [scores, setScores] = useState<Partial<Record<ResearchConditionKey, OverviewScoreEntry>>>({});
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadAllResearchConditions(), loadOverviewScores()]).then(([c, s]) => {
      if (cancelled) return;
      setConditions(c);
      setScores(s);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const cards = NAMED_BRIDGES.map((b) => ({
    bridge: b,
    data: conditions[b.conditionKey],
    score: scores[b.conditionKey],
  })).filter((c) => c.data && c.score);

  return (
    <div className="flex flex-col gap-6">
      {/* Headline */}
      <div className="flex flex-wrap items-end justify-between gap-5">
        <div className="max-w-[760px]">
          <h1 className="mt-2.5 font-display text-[32px] font-extrabold leading-[1.12] tracking-tight text-navy sm:text-[42px]">
            Sindh bridge infrastructure health.
          </h1>
          <p className="mt-3.5 text-base leading-relaxed text-navy-text sm:text-[19px]">
            Each card below replays a real accelerometer recording from a published research
            bridge - not a live reading from this bridge. BridgeGuard AI checks every bridge on
            the Indus corridor, day and night, and tells you in plain words what to do.
          </p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <button onClick={() => setShowWatchDemo(true)} className="rounded-xl bg-blue px-6 py-3.5 text-[15px] font-bold text-white">
            Watch the demo
          </button>
          <Link href="/reports" className="rounded-xl bg-navy px-6 py-3.5 text-[15px] font-bold text-white">
            Create a report
          </Link>
          <Link href="/agents" className="rounded-xl border-[1.5px] border-navy bg-white px-6 py-3.5 text-[15px] font-bold text-navy">
            How it works
          </Link>
        </div>
      </div>

      {showWatchDemo && (
        <WatchDemo
          onClose={() => setShowWatchDemo(false)}
          onGoToApproval={() => {
            setShowWatchDemo(false);
            router.push("/demo#approval-panel");
          }}
        />
      )}

      {/* Bridge cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {!loaded && <div className="col-span-full rounded-[20px] bg-white p-8 text-center text-navy-muted shadow-sm">Loading…</div>}
        {loaded && cards.length === 0 && (
          <div className="col-span-full rounded-[20px] bg-white p-8 text-center text-navy-muted shadow-sm">
            No recorded condition files are available in this build.
          </div>
        )}
        {cards.map(({ bridge, data, score }) => {
          const d = data!;
          const s = score!;
          const cfg = SEVERITY_CONFIG[s.severity];
          const conditionTitle = CONDITION_CARD_TITLE[bridge.conditionKey];
          return (
            <Link
              key={bridge.id}
              href={`/conditions/${bridge.conditionKey}`}
              className="block rounded-[20px] bg-white p-5 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)] transition hover:-translate-y-0.5 hover:shadow-lg"
              style={{ borderTop: `6px solid ${cfg.bar}` }}
            >
              <div className="flex items-start justify-between gap-2">
                <div
                  className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full font-display text-lg font-extrabold"
                  style={{ background: cfg.bar, color: cfg.shieldTextDark ? "#2B1D00" : "#FFFFFF" }}
                >
                  {s.risk_score}
                </div>
                <span className="rounded-full px-3 py-1.5 text-[13px] font-bold" style={{ background: cfg.bgHex, color: cfg.textHex }}>
                  {cfg.label}
                </span>
              </div>
              <div className="mt-3.5 font-display text-lg font-bold text-navy">{bridge.name}</div>
              <div className="mt-0.5 text-[13px] text-navy-muted">{bridge.location}</div>

              <div className="mt-2.5 flex flex-wrap gap-1.5 text-[12px] font-semibold">
                <span className="rounded-full bg-page-bg px-2.5 py-1 text-navy-text">RMS {d.rms.toFixed(4)} {d.sensor.unit}</span>
                {(() => {
                  const n = openCountFor(bridge.name);
                  return (
                    <span className={`rounded-full px-2.5 py-1 ${n > 0 ? "bg-urgent-bg text-urgent-text" : "bg-page-bg text-navy-text"}`}>
                      {n > 0 ? `${n} alert${n === 1 ? "" : "s"}` : "No alerts"}
                    </span>
                  );
                })()}
              </div>

              <div className="mt-3 h-2 overflow-hidden rounded-full bg-page-bg">
                <div className="h-full rounded-full" style={{ width: `${s.risk_score}%`, background: cfg.bar }} />
              </div>

              <p className="mt-3 text-[13px] leading-relaxed text-navy-text">
                Demo data: replays research recording {conditionTitle}.
              </p>
              <div className="mt-1.5 inline-block rounded-full bg-unknown-bg px-2.5 py-1 text-[11px] font-bold text-unknown-text">
                Recorded research data, not measured on this bridge
              </div>

              <div className="mt-3 text-[14px] font-bold text-blue">Open →</div>
            </Link>
          );
        })}
      </div>

      {/* Simulated scenario - clearly distinct from the real recordings above. */}
      <Link
        href="/demo"
        className="block rounded-[20px] border-2 border-dashed border-blue bg-[#E8F3FB] p-5 transition hover:-translate-y-0.5"
      >
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="font-display text-lg font-bold text-navy">Simulated scenario</div>
            <div className="mt-0.5 text-[13px] text-navy-muted">Demonstration Bridge</div>
          </div>
          <span className="shrink-0 rounded-full bg-blue px-3 py-1.5 text-[13px] font-bold text-white">Not real data</span>
        </div>
        <p className="mt-3 text-[15px] leading-relaxed text-navy-text">
          A heavy truck crosses a fictional bridge. See the full five-agent pipeline and the
          replay approval step.
        </p>
        <div className="mt-3 text-[14px] font-bold text-blue">Watch the demo →</div>
      </Link>

      {/* Data sources */}
      {cards.length > 0 && (
        <section className="rounded-[20px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
          <h2 className="font-display text-xl font-extrabold text-navy">Data sources</h2>
          <div className="mt-3 rounded-xl bg-page-bg p-4 text-[13px] leading-relaxed text-navy-text">
            {cards[0].data!.dataset.citation}
          </div>
          <p className="mt-3 text-[13px] text-navy-muted">
            Licensed{" "}
            <a href={cards[0].data!.dataset.license_url} className="text-blue underline">
              {cards[0].data!.dataset.license}
            </a>
            . One 10-minute recording per condition.
          </p>
        </section>
      )}
    </div>
  );
}
