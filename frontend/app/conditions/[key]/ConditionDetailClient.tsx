"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { RESEARCH_STATUS_CONFIG } from "@/lib/data";
import {
  CONDITION_CARD_TITLE,
  loadResearchCondition,
  normalizeStatus,
  type ResearchConditionFile,
  type ResearchConditionKey,
} from "@/lib/research-data";
import { NAMED_BRIDGES } from "@/lib/named-bridges";
import ResearchWaveform from "@/components/ResearchWaveform";

export default function ConditionDetailClient({ conditionKey }: { conditionKey: ResearchConditionKey }) {
  const [data, setData] = useState<ResearchConditionFile | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    loadResearchCondition(conditionKey).then((d) => {
      if (!cancelled) setData(d);
    });
    return () => {
      cancelled = true;
    };
  }, [conditionKey]);

  if (data === undefined) {
    return <div className="py-20 text-center text-navy-muted">Loading recorded condition…</div>;
  }
  if (data === null) {
    return <div className="py-20 text-center text-navy-muted">This recorded condition is not available in this build.</div>;
  }

  const status = normalizeStatus(data.status);
  const cfg = RESEARCH_STATUS_CONFIG[status];
  const title = CONDITION_CARD_TITLE[conditionKey];
  const bridge = NAMED_BRIDGES.find((b) => b.conditionKey === conditionKey);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link href="/" className="text-[13px] font-bold tracking-wider text-blue">
          ← OVERVIEW
        </Link>
        <h1 className="mt-2 font-display text-[28px] font-extrabold tracking-tight text-navy sm:text-[38px]">
          {bridge ? bridge.name : title}
        </h1>
        {bridge && (
          <p className="mt-1 text-[14px] font-semibold text-unknown-text">
            Showing research recording: {title}. Not measured on this bridge.
          </p>
        )}
        <p className="mt-3 max-w-[720px] text-[16px] leading-relaxed text-navy-text sm:text-[18px]">
          A real accelerometer recording from a published research dataset, replayed. Not a
          bridge in Sindh, not a live reading.
        </p>
        <div className="mt-3 flex flex-wrap items-center gap-2.5">
          <span className="rounded-full px-4 py-1.5 text-[14px] font-bold" style={{ background: cfg.bgHex, color: cfg.textHex }}>
            {cfg.label}
          </span>
          <span className="rounded-full bg-page-bg px-4 py-1.5 text-[13px] font-semibold text-navy-muted">
            {data.ratio_vs_reference.toFixed(2)}× the healthy baseline
          </span>
        </div>
      </div>

      <section className="rounded-[22px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
        <h2 className="font-display text-lg font-extrabold text-navy">Recorded vibration</h2>
        <p className="mt-1 mb-4 text-[14px] text-navy-text">
          Channel {data.sensor.channel}, {data.sensor.channel_location}, looped.
        </p>
        <ResearchWaveform values={data.time_series.value} color={cfg.bar} height={120} />
        <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="RMS" value={`${data.rms.toFixed(6)} ${data.sensor.unit}`} />
          <Stat label="Ratio vs. baseline" value={`${data.ratio_vs_reference.toFixed(4)}×`} />
          <Stat label="Sampling rate" value={`${data.sensor.sampling_rate_hz} Hz`} />
          <Stat label="Recorded" value={data.window.measurement_date} />
        </div>
      </section>

      <section className="rounded-[22px] border border-[#A9D3F0] bg-[#E8F3FB] p-7">
        <div className="text-[13px] font-bold tracking-wider text-blue">HOW THE STATUS IS DECIDED</div>
        <p className="mt-2 text-[16px] leading-relaxed text-navy">{data.status_rule}</p>
        <p className="mt-3 text-[13px] text-[#3F6A8F]">{data.night_reference_note}</p>
        <p className="mt-2 text-[13px] text-[#3F6A8F]">{data.selection_note}</p>
      </section>

      <section className="rounded-[22px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
        <h2 className="font-display text-lg font-extrabold text-navy">Data source</h2>
        <dl className="mt-3 grid gap-3 text-[15px] sm:grid-cols-2">
          <div>
            <dt className="text-xs font-bold uppercase tracking-wide text-navy-muted">Dataset</dt>
            <dd className="mt-0.5">{data.dataset.name}</dd>
          </div>
          <div>
            <dt className="text-xs font-bold uppercase tracking-wide text-navy-muted">Authors</dt>
            <dd className="mt-0.5">{data.dataset.authors}</dd>
          </div>
          <div>
            <dt className="text-xs font-bold uppercase tracking-wide text-navy-muted">Licence</dt>
            <dd className="mt-0.5">
              <a href={data.dataset.license_url} className="text-blue underline">{data.dataset.license}</a>
            </dd>
          </div>
          <div>
            <dt className="text-xs font-bold uppercase tracking-wide text-navy-muted">Link</dt>
            <dd className="mt-0.5"><a href={data.dataset.link} className="text-blue underline">{data.dataset.doi}</a></dd>
          </div>
        </dl>
        <div className="mt-4 rounded-xl bg-page-bg p-4 text-[13px] leading-relaxed text-navy-text">
          {data.dataset.citation}
        </div>
        <p className="mt-3 text-[13px] text-navy-muted">One 10-minute recording per condition.</p>
      </section>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-page-bg p-3.5">
      <div className="text-xs font-bold uppercase tracking-wide text-navy-muted">{label}</div>
      <div className="mt-1 text-[15px] font-bold text-navy">{value}</div>
    </div>
  );
}
