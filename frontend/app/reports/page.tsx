"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { RESEARCH_STATUS_CONFIG, SEVERITY_CONFIG, type ResearchStatus, type Severity } from "@/lib/data";
import {
  CONDITION_CARD_TITLE,
  RESEARCH_CONDITION_KEYS,
  loadAllResearchConditions,
  normalizeStatus,
  type ResearchConditionFile,
  type ResearchConditionKey,
} from "@/lib/research-data";
import { NAMED_BRIDGES } from "@/lib/named-bridges";
import { EXPLANATION_LABELS, loadReplayTimeline, type ScoreTraceResponse } from "@/lib/demo-contract";
import DataSourceBadge from "@/components/DataSourceBadge";

type ReportKey = ResearchConditionKey | "simulated";

interface ReportEntry {
  key: ReportKey;
  isSimulated: boolean;
  title: string;
  location: string;
  explanationText: string;
  explanationLabel: string;
  recommendation: string;
  readings: { label: string; value: string }[];
  statusLabel: string;
  statusBar: string;
  statusBgHex: string;
  statusTextHex: string;
  bigNumber: string;
  bigNumberSuffix: string;
  citation?: string;
  licence?: string;
  licenceUrl?: string;
}

function recommendationFor(status: ResearchStatus | Severity): string {
  if (status === "DANGER" || status === "CRITICAL") {
    return "IMMEDIATE ACTION: Engineering inspection within 48 hours. Do not delay. Reduce load limits until cleared by engineer.";
  }
  if (status === "MODERATE" || status === "WARNING") {
    return "ACTION REQUIRED: Engineering inspection within 14 days. Monitor continuously. Document any new anomalies.";
  }
  if (status === "LITTLE_MODERATE" || status === "WATCH") {
    return "MONITOR: Continue standard monitoring. Review readings weekly. No immediate action required.";
  }
  return "NO ACTION: All systems within normal range. Next scheduled review in 30 days.";
}

function researchToEntry(key: ResearchConditionKey, data: ResearchConditionFile): ReportEntry {
  const status = normalizeStatus(data.status);
  const cfg = RESEARCH_STATUS_CONFIG[status];
  const n = data.time_series.value.length;
  const sampleIdx = Array.from({ length: 10 }, (_, i) => Math.floor((i / 9) * (n - 1)));
  // Same four names and mapping as Overview and Alerts (lib/named-bridges.ts) - every page agrees.
  const bridge = NAMED_BRIDGES.find((b) => b.conditionKey === key);
  return {
    key,
    isSimulated: false,
    title: bridge ? bridge.name : CONDITION_CARD_TITLE[key],
    location: bridge
      ? `${bridge.location} — showing research recording: ${CONDITION_CARD_TITLE[key]}. Not measured on this bridge.`
      : "Bautzen, Germany — OpenBridgeLAB research bridge (not Sindh)",
    explanationText: data.status_rule,
    explanationLabel: "Rule-based status (not AI-written)",
    recommendation: recommendationFor(status),
    readings: sampleIdx.map((i) => ({
      label: `t+${data.time_series.time_s[i].toFixed(0)}s`,
      value: `${data.time_series.value[i].toFixed(5)} ${data.sensor.unit}`,
    })),
    statusLabel: cfg.label,
    statusBar: cfg.bar,
    statusBgHex: cfg.bgHex,
    statusTextHex: cfg.textHex,
    bigNumber: data.ratio_vs_reference.toFixed(2),
    bigNumberSuffix: "× baseline",
    citation: data.dataset.citation,
    licence: data.dataset.license,
    licenceUrl: data.dataset.license_url,
  };
}

function simulatedToEntry(trace: ScoreTraceResponse | null): ReportEntry {
  const severity = (trace?.severity ?? "CRITICAL") as Severity;
  const cfg = SEVERITY_CONFIG[severity];
  const label = trace?.explanation.source_label ?? (trace ? EXPLANATION_LABELS[trace.explanation.kind] : EXPLANATION_LABELS.template_fallback);
  return {
    key: "simulated",
    isSimulated: true,
    title: "Simulated scenario — Demonstration Bridge",
    location: "Fictional bridge, for demonstration only",
    explanationText: trace?.explanation.text ?? "Template explanation: AI unavailable.",
    explanationLabel: label,
    recommendation: recommendationFor(severity),
    readings: [
      { label: "Reading", value: trace ? `${trace.reading.value} ${trace.reading.unit}` : "—" },
      { label: "Limit", value: trace ? `${trace.limit.value} (${trace.limit.basis_label})` : "—" },
      { label: "Ratio vs limit", value: trace?.limit.ratio ? `${trace.limit.ratio.toFixed(1)}×` : "—" },
    ],
    statusLabel: cfg.label,
    statusBar: cfg.bar,
    statusBgHex: cfg.bgHex,
    statusTextHex: cfg.textHex,
    bigNumber: trace ? String(trace.risk_score) : "—",
    bigNumberSuffix: "/100",
  };
}

export default function ReportsPage() {
  const [entries, setEntries] = useState<ReportEntry[] | null>(null);
  const [selectedKey, setSelectedKey] = useState<ReportKey>("safe");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([loadAllResearchConditions(), loadReplayTimeline().catch(() => null)]).then(
      ([conditions, replay]) => {
        if (cancelled) return;
        const traceEntry = replay?.timeline.find((e) => e.endpoint.includes("score-trace"));
        const trace = (traceEntry?.response as ScoreTraceResponse | undefined) ?? null;
        const list: ReportEntry[] = [];
        for (const key of RESEARCH_CONDITION_KEYS) {
          const data = conditions[key];
          if (data) list.push(researchToEntry(key, data));
        }
        list.push(simulatedToEntry(trace));
        setEntries(list);
        if (list.length > 0) setSelectedKey(list[0].key);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const entry = entries?.find((e) => e.key === selectedKey) ?? null;

  function downloadTxt() {
    if (!entry) return;
    setLoading(true);
    setDone(false);
    setTimeout(() => {
      const content = generateTxtContent(entry);
      const blob = new Blob([content], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `BridgeGuard-Report-${entry.key}-${Date.now()}.txt`;
      a.click();
      URL.revokeObjectURL(url);
      setLoading(false);
      setDone(true);
    }, 1200);
  }

  function downloadPdf() {
    if (!entry) return;
    setLoading(true);
    setTimeout(() => {
      renderPdf(entry);
      setLoading(false);
      setDone(true);
    }, 800);
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <div className="text-[13px] font-bold tracking-wider text-blue">REPORTS</div>
        <h1 className="mt-2 font-display text-[28px] font-extrabold tracking-tight text-navy sm:text-[38px]">
          Create an official report in two steps.
        </h1>
        <p className="mt-3 max-w-[720px] text-[16px] leading-relaxed text-navy-text sm:text-[18px]">
          Download a PDF or plain text file for a recorded research condition, or the simulated
          truck scenario.
        </p>
        <div className="mt-3">
          <DataSourceBadge source="sample" />
        </div>
      </div>

      {!entries ? (
        <div className="rounded-[22px] bg-white p-10 text-center text-navy-muted shadow-sm">Loading…</div>
      ) : (
        <div className="flex flex-wrap items-start gap-6">
          <div className="flex min-w-0 flex-[1_1_440px] flex-col gap-5">
            <section className="rounded-[22px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
              <div className="flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-navy font-display font-extrabold text-white">1</div>
                <h2 className="font-display text-lg font-extrabold text-navy">Choose a condition</h2>
              </div>
              <select
                value={selectedKey}
                onChange={(e) => {
                  setSelectedKey(e.target.value as ReportKey);
                  setDone(false);
                }}
                className="mt-4 w-full rounded-xl border-[1.5px] border-[#B7C4D4] p-4 text-base font-semibold text-navy-deep focus:outline-none"
              >
                {entries.map((e) => (
                  <option key={e.key} value={e.key}>
                    {e.title} · {e.statusLabel}
                  </option>
                ))}
              </select>
              {entry && (
                <div className="mt-3 rounded-xl p-3.5 text-sm leading-relaxed" style={{ background: entry.statusBgHex, color: entry.statusTextHex }}>
                  <strong>{entry.isSimulated ? "Simulated scenario" : "Recorded research data, replayed"}:</strong>{" "}
                  {entry.statusLabel} · {entry.bigNumber}{entry.bigNumberSuffix}
                </div>
              )}

              <div className="mt-7 flex items-center gap-3">
                <div className="flex h-8 w-8 items-center justify-center rounded-full bg-navy font-display font-extrabold text-white">2</div>
                <h2 className="font-display text-lg font-extrabold text-navy">Choose a format</h2>
              </div>
              <div className="report-buttons mt-4 grid grid-cols-2 gap-3">
                <button onClick={downloadPdf} disabled={loading} className="rounded-xl bg-navy px-5 py-4 text-[15px] font-bold text-white disabled:opacity-60">
                  {loading ? "Generating…" : "Download PDF"}
                </button>
                <button onClick={downloadTxt} disabled={loading} className="rounded-xl border-[1.5px] border-navy px-5 py-4 text-[15px] font-bold text-navy disabled:opacity-60">
                  {loading ? "Generating…" : "Download TXT"}
                </button>
              </div>
              <p className="mt-3 text-[13px] text-navy-muted">
                Every research report is marked &ldquo;Recorded research data, replayed&rdquo; with the
                OpenBridgeLAB citation. The truck scenario is marked &ldquo;Simulated scenario&rdquo;.
              </p>

              {done && (
                <div className="mt-4 rounded-xl p-4" style={{ background: "#E4F4EA", border: "1px solid #8CCB9E" }}>
                  <p className="mb-1 text-sm font-semibold" style={{ color: "#0B5F2B" }}>✓ Report generated successfully</p>
                  <p className="text-xs text-navy-muted">For PDF: allow pop-ups and use &quot;Save as PDF&quot; in the print dialog.</p>
                </div>
              )}
            </section>

            <section className="rounded-[22px] bg-white p-7 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]">
              <h2 className="font-display text-lg font-extrabold text-navy">What the report includes</h2>
              <div className="mt-4 grid grid-cols-1 gap-2.5 text-[15px] sm:grid-cols-2">
                {[
                  "BridgeGuard AI logo and date",
                  "Condition name and data source",
                  "Status and the deciding rule",
                  "Explanation with its real label",
                  "Sample readings from the recording",
                  "Maintenance recommendation",
                  "Sign-off block",
                ].map((item) => (
                  <div key={item} className="flex items-start gap-2.5">
                    <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="#097F37" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" className="mt-0.5 shrink-0">
                      <path d="M5 12l5 5L20 7" />
                    </svg>
                    {item}
                  </div>
                ))}
              </div>
            </section>
          </div>

          {entry && (
            <div className="min-w-0 flex-[1_1_420px]" style={{ maxWidth: 540 }}>
              <div className="mb-2.5 text-sm font-bold text-navy-muted">Preview of page 1</div>
              <div className="overflow-hidden rounded-md border border-[#C5D2E0] bg-white shadow-[0_14px_36px_rgba(0,50,93,0.16)]">
                <div className="flex items-center justify-between gap-3 border-b-[3px] border-navy px-6 pb-3.5 pt-5">
                  <div className="flex items-center gap-2.5">
                    <Image src="/logo-icon.png" alt="" width={34} height={32} className="h-[34px] w-auto" />
                    <span className="font-display text-sm font-extrabold text-navy">BridgeGuard AI</span>
                  </div>
                  <div className="text-right text-[11px] leading-relaxed text-navy-muted">
                    <strong className="text-xs text-navy">Bridge Health Report</strong>
                    <br />
                    {new Date().toLocaleDateString("en-PK", { year: "numeric", month: "long", day: "numeric" })}
                  </div>
                </div>
                <div className="h-1" style={{ background: "linear-gradient(90deg, #00325D 0%, #0081D3 55%, #097F37 100%)" }} />
                <div className="px-6 py-4">
                  <div className="rounded-md px-2.5 py-1.5 text-center text-[11px] font-bold tracking-wide" style={{ background: "#FDE6E6", color: "#A31F1F" }}>
                    {entry.isSimulated ? "SIMULATED SCENARIO — not a real bridge" : "RECORDED RESEARCH DATA, REPLAYED"}
                  </div>
                  <div className="mt-3 font-display text-xl font-extrabold text-navy">{entry.title}</div>
                  <div className="mt-0.5 text-xs text-navy-muted">{entry.location}</div>
                  <div className="mt-4 flex items-center gap-4 rounded-lg p-3.5" style={{ background: entry.statusBgHex }}>
                    <span className="flex h-[50px] w-[50px] shrink-0 items-center justify-center rounded-full font-display text-sm font-extrabold" style={{ background: entry.statusBar, color: "#fff" }}>
                      {entry.bigNumber}
                    </span>
                    <div>
                      <div className="text-sm font-extrabold" style={{ color: entry.statusTextHex }}>{entry.statusLabel.toUpperCase()}</div>
                      <div className="text-[11px] text-navy-muted">{entry.bigNumberSuffix.replace("×", "× healthy baseline")}</div>
                    </div>
                  </div>
                  <div className="mt-4 text-xs font-extrabold text-navy">{entry.explanationLabel}</div>
                  <div className="mt-1 text-[11.5px] leading-relaxed text-[#2B3E57]">{entry.explanationText}</div>
                  {entry.citation && (
                    <div className="mt-3 text-[10px] leading-relaxed text-navy-muted">{entry.citation}</div>
                  )}
                </div>
                <div className="flex items-center justify-between border-t border-border px-6 py-2.5 text-[10px] text-navy-muted" style={{ background: "#F7F9FC" }}>
                  <span>Sample preview. Final decisions are made by a qualified engineer.</span>
                  <span>BridgeGuard AI · Page 1</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function generateTxtContent(e: ReportEntry): string {
  const now = new Date();
  return [
    "╔══════════════════════════════════════════════════╗",
    "║         BRIDGEGUARD AI — HEALTH REPORT           ║",
    "║              *** DEMONSTRATION DATA ***          ║",
    "╚══════════════════════════════════════════════════╝",
    "",
    e.isSimulated ? "*** SIMULATED SCENARIO — not a real bridge ***" : "*** RECORDED RESEARCH DATA, REPLAYED ***",
    "",
    `Report Date:     ${now.toLocaleDateString("en-PK", { year: "numeric", month: "long", day: "numeric" })}`,
    `Condition:       ${e.title}`,
    `Source:          ${e.location}`,
    "",
    "══════════════════════════════════════════════════",
    "STATUS",
    "══════════════════════════════════════════════════",
    `Status:          ${e.statusLabel}`,
    `Value:           ${e.bigNumber}${e.bigNumberSuffix}`,
    "",
    "══════════════════════════════════════════════════",
    e.explanationLabel.toUpperCase(),
    "══════════════════════════════════════════════════",
    e.explanationText,
    "",
    "══════════════════════════════════════════════════",
    "RECOMMENDATION",
    "══════════════════════════════════════════════════",
    e.recommendation,
    "",
    "══════════════════════════════════════════════════",
    "SAMPLE READINGS",
    "══════════════════════════════════════════════════",
    ...e.readings.map((r) => `${r.label.padEnd(14)} | ${r.value}`),
    "",
    ...(e.citation ? ["══════════════════════════════════════════════════", "DATA SOURCE", "══════════════════════════════════════════════════", e.citation, `Licence: ${e.licence}`, ""] : []),
    "══════════════════════════════════════════════════",
    "SIGN-OFF",
    "══════════════════════════════════════════════════",
    "Prepared by (Engineer): _______________________",
    "Reviewed by (Authority): _______________________",
    "",
    "╔══════════════════════════════════════════════════╗",
    "║            *** DEMONSTRATION DATA ***            ║",
    "╚══════════════════════════════════════════════════╝",
  ].join("\n");
}

function renderPdf(e: ReportEntry): void {
  const now = new Date();
  const dateStr = now.toLocaleDateString("en-PK", { year: "numeric", month: "long", day: "numeric" });
  const h = (s: string) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const readingsRows = e.readings
    .map((r) => `<tr><td style="padding:6px 8px;border:1px solid #ccc">${h(r.label)}</td><td style="padding:6px 8px;border:1px solid #ccc;font-family:monospace">${h(r.value)}</td></tr>`)
    .join("");

  const printWindow = window.open("", "_blank");
  if (!printWindow) return;
  printWindow.document.write(`
    <!DOCTYPE html>
    <html><head><title>BridgeGuard Report — ${h(e.title)}</title>
    <style>
      @page { size: A4; margin: 18mm 16mm 22mm 16mm;
        @bottom-center { content: "Page " counter(page) " of " counter(pages); font-size: 10px; color: #666; }
        @top-right { content: "DEMONSTRATION DATA"; font-size: 9px; font-weight: 700; color: #A31F1F; letter-spacing: 0.06em; }
      }
      html { counter-reset: page; }
      body { font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 11px; line-height: 1.5; color: #111; margin: 0; }
      .logo-block { border: 2px solid #00325D; padding: 14px 18px; margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; }
      .logo-block .brand-group { display: flex; align-items: center; gap: 12px; }
      .logo-block img { height: 40px; width: 40px; object-fit: contain; }
      .logo-block .brand { font-size: 20px; font-weight: 800; color: #00325D; }
      .demo-banner { margin-top: 10px; padding: 6px 12px; text-align: center; background: #FDE6E6; border: 1px solid #F0A5A5; color: #A31F1F; font-weight: 700; font-size: 11px; border-radius: 6px; }
      h1 { text-align: center; font-size: 18px; margin: 18px 0 2px; }
      .subtitle { text-align: center; font-size: 11px; color: #666; margin-bottom: 16px; }
      h2 { font-size: 13px; color: #00325D; border-bottom: 1px solid #00325D; padding-bottom: 3px; margin: 18px 0 8px; text-transform: uppercase; }
      .score-block { display: flex; align-items: center; gap: 24px; border: 1px solid #ddd; padding: 14px; margin: 10px 0; background: #fafafa; }
      .score-block .big { font-size: 40px; font-weight: 800; color: ${e.statusBar}; }
      .badge { display: inline-block; padding: 4px 14px; border-radius: 20px; font-weight: 700; font-size: 12px; background: ${e.statusBgHex}; color: ${e.statusTextHex}; text-transform: uppercase; }
      table.readings { width: 100%; border-collapse: collapse; font-size: 11px; }
      table.readings th { background: #00325D; color: white; padding: 6px 8px; text-align: left; }
      .ai-box { border-left: 4px solid #00325D; background: #f4f8f6; padding: 10px 14px; font-size: 11.5px; }
      .rec-box { border: 1px solid #e5a000; background: #fff8e1; padding: 10px 14px; font-size: 11.5px; }
      .cite-box { border-left: 4px solid #0081D3; background: #eef6fc; padding: 10px 14px; font-size: 10.5px; color: #333; }
      .signature-table td { padding: 14px; border: 1px solid #ccc; width: 50%; vertical-align: top; font-size: 11px; line-height: 2; }
      .footer-note { margin-top: 18px; padding-top: 8px; border-top: 1px solid #ccc; font-size: 9.5px; color: #666; text-align: center; }
    </style></head>
    <body>
      <div class="logo-block">
        <div class="brand-group">
          <img src="${window.location.origin}/logo-icon.png" alt="BridgeGuard AI" />
          <div class="brand">BridgeGuard AI</div>
        </div>
        <div style="text-align:right;font-size:10px;color:#444">Generated: ${h(dateStr)}</div>
      </div>
      <div class="demo-banner">${e.isSimulated ? "SIMULATED SCENARIO — not a real bridge" : "RECORDED RESEARCH DATA, REPLAYED"}</div>
      <h1>BridgeGuard AI — Bridge Health Report</h1>
      <div class="subtitle">${h(e.title)} — ${h(e.location)}</div>

      <h2>1. Status</h2>
      <div class="score-block">
        <div class="big">${h(e.bigNumber)}<small style="font-size:14px;color:#666">${h(e.bigNumberSuffix)}</small></div>
        <div><span class="badge">${h(e.statusLabel)}</span></div>
      </div>

      <h2>2. ${h(e.explanationLabel)}</h2>
      <div class="ai-box">${h(e.explanationText)}</div>

      <h2>3. Recommendation</h2>
      <div class="rec-box"><strong>Engineer Action:</strong> ${h(e.recommendation)}</div>

      <h2>4. Sample Readings</h2>
      <table class="readings"><thead><tr><th>Point</th><th>Value</th></tr></thead><tbody>${readingsRows}</tbody></table>

      ${e.citation ? `<h2>5. Data Source</h2><div class="cite-box">${h(e.citation)}<br/>Licence: ${h(e.licence ?? "")}</div>` : ""}

      <div style="margin-top:28px">
        <h3 style="font-size:12px;color:#00325D;text-transform:uppercase">Official Sign-off</h3>
        <table class="signature-table" style="width:100%;border-collapse:collapse"><tr>
          <td><strong>Prepared by (Engineer):</strong>Name: _______________________<br/>Signature: __________________<br/>Date: _______________________</td>
          <td><strong>Reviewed by (Authority):</strong>Name: _______________________<br/>Designation: ________________</td>
        </tr></table>
      </div>

      <div class="footer-note">
        ${e.isSimulated ? "Simulated scenario for demonstration purposes only." : "Recorded research data, replayed from a published dataset."}
        Final decisions require human engineer sign-off.
      </div>
    </body></html>
  `);
  printWindow.document.close();
  printWindow.focus();
  const doPrint = () => { printWindow.print(); printWindow.close(); };
  const logoImg = printWindow.document.querySelector(".logo-block img") as HTMLImageElement | null;
  if (logoImg && !logoImg.complete) {
    let settled = false;
    const finish = () => { if (settled) return; settled = true; doPrint(); };
    logoImg.addEventListener("load", finish, { once: true });
    logoImg.addEventListener("error", finish, { once: true });
    setTimeout(finish, 3000);
  } else {
    setTimeout(doPrint, 500);
  }
}
