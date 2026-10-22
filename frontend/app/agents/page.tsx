import fs from "node:fs";
import path from "node:path";
import { RESEARCH_STATUS_CONFIG } from "@/lib/data";
import { normalizeStatus, type ResearchConditionFile } from "@/lib/research-data";
import DataSourceBadge from "@/components/DataSourceBadge";

/** The worked example below uses the real Damage State 2 recording (same RMS/ratio/status shown
 * on Overview and its condition detail page) - never an invented number. Read server-side
 * straight off disk (same JSON the frontend fetches at /replay/research/danger.json) rather than
 * duplicating the numbers by hand, so this page can never drift from that file. */
const EXAMPLE: ResearchConditionFile = JSON.parse(
  fs.readFileSync(path.join(process.cwd(), "public", "replay", "research", "danger.json"), "utf-8"),
);

const STEPS = ["Collect", "Analyse", "Explain", "Alert", "Report"];

// One naming set used here and in the "Watch the demo" animation (WatchDemo.tsx): plain name,
// then the real backend package in parentheses (ingestion/signal/risk/alert/report - see
// src/agents/{data_collection,structural_analysis,risk_reasoning,alert_escalation,
// report_generation}). These match the "helper_name" strings ("The Listener", "The Analyst", ...)
// the backend itself writes into public/replay/demo-run.json's pipeline-status entries.
const HELPERS = [
  {
    name: "Listener (Ingestion agent)",
    tag: "Fixed rules",
    tagStyle: { background: "#E4F4EA", color: "#0B5F2B" },
    summary:
      "Collects the sensor readings and removes bad ones, such as a sensor that went quiet or a number that is physically impossible.",
    technical:
      "Receives 100 samples per second via the LoRaWAN gateway, checks sensor liveness and range limits, flags statistical spikes and computes RMS.",
    circle: "#00325D",
  },
  {
    name: "Analyst (Signal agent)",
    tag: "Fixed rules",
    tagStyle: { background: "#E4F4EA", color: "#0B5F2B" },
    summary: "Compares today's shaking with how this bridge normally behaves and with the allowed limits.",
    technical:
      "Runs FFT frequency analysis, compares RMS against the rolling baseline and checks deflection ratios against IRC/AASHTO design limits.",
    circle: "#00325D",
  },
  {
    name: "Explainer (Risk agent)",
    tag: "Uses AI, to explain only",
    tagStyle: { background: "#E8F3FB", color: "#0A63B8" },
    summary:
      "Gives the bridge a score from 0 to 100 and writes a plain-language explanation. The score comes from a fixed formula. The AI never decides the number.",
    technical:
      "Deterministic scoring plus an AI-written explanation citing IRC and AASHTO standards. A guardrail checks that every number in the text traces back to a real input.",
    circle: "#0081D3",
    highlighted: true,
  },
  {
    name: "Messenger (Alert agent)",
    tag: "Fixed rules",
    tagStyle: { background: "#E4F4EA", color: "#0B5F2B" },
    summary: "Decides who needs to hear about a problem and how urgently, then notifies the right engineering team.",
    technical:
      "Evaluates the severity band and routes notifications. Critical alerts never send on their own; they wait for human approval.",
    circle: "#00325D",
  },
  {
    name: "Writer (Report agent)",
    tag: "Fixed rules",
    tagStyle: { background: "#E4F4EA", color: "#0B5F2B" },
    summary: "Puts everything into a clean PDF or text report that can go to a government office or an engineering review.",
    technical:
      "Assembles sensor tables, risk score, the AI explanation word for word, and maintenance recommendations.",
    circle: "#00325D",
  },
];

export default function AgentsPage() {
  const status = normalizeStatus(EXAMPLE.status);
  const cfg = RESEARCH_STATUS_CONFIG[status];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="text-[13px] font-bold tracking-wider text-blue">HOW IT WORKS</div>
        <h1 className="mt-2 font-display text-[28px] font-extrabold tracking-tight text-navy sm:text-[38px]">
          Five helpers check every bridge, around the clock.
        </h1>
        <p className="mt-3 max-w-[760px] text-[16px] leading-relaxed text-navy-text sm:text-[18px]">
          Each sensor reading passes through five helpers, one after another. Each has one clear job.
          Only one uses AI, and only to explain the result in plain words.
        </p>
      </div>

      <section className="rounded-[22px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-display text-xl font-extrabold text-navy">Example from sample data</h2>
            <div className="mt-1 text-sm text-navy-text">
              One reading, start to finish, using {EXAMPLE.condition}&rsquo;s real recorded numbers, the same ones shown on Overview.
            </div>
          </div>
          <DataSourceBadge source="sample" />
        </div>

        <div className="my-6 flex flex-wrap items-center">
          {STEPS.map((label, i) => (
            <div key={label} className="flex flex-1 items-center" style={{ minWidth: 70 }}>
              <div className="flex flex-col items-center gap-2" style={{ width: 90 }}>
                <div
                  className="flex h-[54px] w-[54px] items-center justify-center rounded-full font-display text-xl font-extrabold text-white"
                  style={{ background: i === 2 ? "#0081D3" : "#00325D" }}
                >
                  {i + 1}
                </div>
                <span className="text-[13px] font-bold text-navy">{label}</span>
              </div>
              {i < STEPS.length - 1 && <div className="mb-6.5 h-[3px] flex-1 bg-navy" style={{ minWidth: 20 }} />}
            </div>
          ))}
        </div>

        <div className="rounded-2xl border border-[#A9D3F0] bg-[#E8F3FB] p-5.5">
          <div className="flex flex-wrap items-center gap-6">
            <div className="flex min-w-[190px] items-center gap-3.5">
              <span
                className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full font-display text-lg font-extrabold"
                style={{ background: cfg.bar, color: cfg.shieldTextDark ? "#2B1D00" : "#FFFFFF" }}
              >
                {EXAMPLE.ratio_vs_reference.toFixed(1)}×
              </span>
              <div>
                <div className="text-[13px] font-bold text-blue">Status</div>
                <div className="font-display text-[17px] font-extrabold" style={{ color: cfg.textHex }}>
                  {cfg.label}
                </div>
                <div className="text-[13px] text-[#3F6A8F]">RMS {EXAMPLE.rms.toFixed(4)} {EXAMPLE.sensor.unit}</div>
              </div>
            </div>
            <div className="min-w-0 flex-[1_1_360px]">
              <div className="text-xs font-bold tracking-wider text-blue">WHY THIS STATUS, DECIDED BY AGENT 3</div>
              <p className="mt-2 text-[16px] leading-relaxed text-navy">{EXAMPLE.status_rule}</p>
              <div className="mt-2 text-[13px] text-[#3F6A8F]">
                A fixed rule, not an AI-written sentence - this recording has no live AI explanation. Sample data, not a live run.
              </div>
            </div>
          </div>
        </div>
      </section>

      <h2 className="font-display text-2xl font-extrabold text-navy">Meet the five helpers</h2>

      <div className="flex flex-col gap-4">
        {HELPERS.map((helper, i) => (
          <div key={helper.name} className="flex items-stretch gap-4.5">
            <div className="flex shrink-0 flex-col items-center">
              <div
                className="flex h-11 w-11 items-center justify-center rounded-full font-display font-extrabold text-white"
                style={{ background: helper.circle }}
              >
                {i + 1}
              </div>
              {i < HELPERS.length - 1 && <div className="mt-1 w-[3px] flex-1 bg-[#C5D2E0]" />}
            </div>
            <div
              className="min-w-0 flex-1 rounded-[18px] bg-white p-6 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]"
              style={helper.highlighted ? { border: "2px solid #0081D3" } : undefined}
            >
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="font-display text-xl font-extrabold text-navy">{helper.name}</span>
                <span className="rounded-full px-2.5 py-1 text-xs font-bold" style={helper.tagStyle}>
                  {helper.tag}
                </span>
              </div>
              <p className="mt-2 text-[16px] leading-relaxed text-navy-text">{helper.summary}</p>
              <p className="mt-2.5 text-[13px] leading-relaxed text-[#4B5D73]">{helper.technical}</p>
            </div>
          </div>
        ))}
      </div>

      <section className="rounded-[22px] bg-navy p-8 text-white">
        <div className="font-display text-xl font-extrabold sm:text-2xl">People stay in control</div>
        <div className="mt-5 grid gap-5 sm:grid-cols-3">
          {[
            {
              title: "Same input, same result",
              body: "Four of the five helpers follow fixed rules, so results are repeatable.",
            },
            {
              title: "AI only explains",
              body: "Only the Explainer uses AI, and it cannot change the score.",
            },
            {
              title: "Engineers approve urgent alerts",
              body: "Urgent alerts are never sent automatically.",
            },
          ].map((item) => (
            <div key={item.title} className="rounded-2xl bg-white/10 p-4.5">
              <div className="text-[16px] font-bold">{item.title}</div>
              <div className="mt-1.5 text-[15px] leading-relaxed text-white/85">{item.body}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
