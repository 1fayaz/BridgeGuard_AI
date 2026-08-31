// Dependency-free PDF writer for bridge reports. Emits a valid PDF 1.4 file
// with Helvetica text, word wrapping, colors, rules and automatic pagination.

import type { Bridge, Severity } from "./data";

const PAGE_W = 595.28;
const PAGE_H = 841.89;
const MARGIN = 50;
const CONTENT_W = PAGE_W - MARGIN * 2;

type RGB = [number, number, number];

const BRAND: RGB = [0.06, 0.43, 0.34];
const INK: RGB = [0.16, 0.16, 0.14];
const GRAY: RGB = [0.45, 0.45, 0.42];

const SEVERITY_RGB: Record<Severity, RGB> = {
  CRITICAL: [0.94, 0.27, 0.27],
  WARNING: [0.98, 0.45, 0.09],
  WATCH: [0.92, 0.7, 0.03],
  SAFE: [0.13, 0.77, 0.37],
};

const RECOMMENDATIONS: Record<Severity, string> = {
  CRITICAL:
    "Immediate engineering inspection within 48 hours. Restrict heavy vehicle convoys until the inspection is complete. A qualified engineer must review and sign off on this assessment before the alert can be cleared.",
  WARNING:
    "Schedule an engineering inspection within 14 days. Continue daily monitoring of sensor readings.",
  WATCH:
    "No immediate action required. Continue monitoring and review the 30-day trend within 7 days.",
  SAFE: "No action required. Next routine review in 30 days.",
};

interface TextItem {
  kind: "text";
  text: string;
  size: number;
  bold?: boolean;
  color?: RGB;
  indent?: number;
  leading?: number;
}
interface GapItem {
  kind: "gap";
  size: number;
}
interface RuleItem {
  kind: "rule";
  leading?: number;
}
type Item = TextItem | GapItem | RuleItem;

// Map display text into Latin-1, the range WinAnsiEncoding can render.
function toLatin1(s: string): string {
  return s
    .replace(/[\u2014\u2013]/g, "-")
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/[\u201C\u201D]/g, '"')
    .replace(/\u2191/g, "^")
    .replace(/\u2192/g, "->")
    .replace(/\u00D7/g, "x")
    .replace(/\u2026/g, "...")
    .replace(/[^\u0000-\u00FF]/g, "?");
}

function esc(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)");
}

// Approximate Helvetica advance widths (fraction of font size).
function charWidth(ch: string, bold: boolean): number {
  if (ch === " ") return 0.28;
  if ("iljtfrI.,;:'!|()[]{}/\\-".includes(ch)) return 0.33;
  if ("mwMW@".includes(ch)) return 0.9;
  if ("ABCDEFGHKNOPQRSUVXYZ".includes(ch)) return 0.7;
  if (ch >= "0" && ch <= "9") return 0.56;
  return bold ? 0.58 : 0.53;
}

function textWidth(text: string, size: number, bold: boolean): number {
  let w = 0;
  for (const ch of text) w += charWidth(ch, bold);
  return w * size;
}

function wrap(text: string, size: number, bold: boolean, maxWidth: number): string[] {
  const words = text.split(/\s+/).filter(Boolean);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    const candidate = line ? `${line} ${word}` : word;
    if (textWidth(candidate, size, bold) <= maxWidth) {
      line = candidate;
    } else {
      if (line) lines.push(line);
      line = word;
    }
  }
  if (line) lines.push(line);
  return lines.length ? lines : [""];
}

function layout(items: Item[]): string[] {
  const pages: string[] = [];
  let ops: string[] = [];
  let y = PAGE_H - MARGIN;

  const startPage = () => {
    if (ops.length) pages.push(ops.join("\n"));
    ops = [];
    y = PAGE_H - MARGIN;
  };

  for (const item of items) {
    if (item.kind === "gap") {
      y -= item.size;
      continue;
    }
    if (item.kind === "rule") {
      y -= item.leading ?? 8;
      if (y < MARGIN + 20) startPage();
      ops.push(
        `0.85 0.85 0.83 RG 0.8 w ${MARGIN} ${y.toFixed(1)} m ${(PAGE_W - MARGIN).toFixed(1)} ${y.toFixed(1)} l S`
      );
      y -= 12;
      continue;
    }
    const { text, size, bold = false, color = INK, indent = 0, leading = 0 } = item;
    y -= leading;
    for (const ln of wrap(toLatin1(text), size, bold, CONTENT_W - indent)) {
      if (y - size < MARGIN) startPage();
      y -= size * 1.42;
      const font = bold ? "/F2" : "/F1";
      ops.push(
        `${color[0].toFixed(2)} ${color[1].toFixed(2)} ${color[2].toFixed(2)} rg ` +
          `BT ${font} ${size} Tf ${(MARGIN + indent).toFixed(1)} ${y.toFixed(1)} Td (${esc(ln)}) Tj ET`
      );
    }
  }
  if (ops.length) pages.push(ops.join("\n"));
  return pages;
}

function buildPdf(pages: string[]): Uint8Array<ArrayBuffer> {
  const objects: string[] = [];
  const pageIds: number[] = [];
  const contentIds: number[] = [];
  let nextId = 5;
  for (let i = 0; i < pages.length; i++) {
    pageIds.push(nextId++);
    contentIds.push(nextId++);
  }

  objects[1] = "<< /Type /Catalog /Pages 2 0 R >>";
  objects[2] = `<< /Type /Pages /Kids [${pageIds.map((id) => `${id} 0 R`).join(" ")}] /Count ${pages.length} >>`;
  objects[3] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>";
  objects[4] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>";

  pages.forEach((content, i) => {
    objects[pageIds[i]] =
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PAGE_W} ${PAGE_H}] ` +
      `/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents ${contentIds[i]} 0 R >>`;
    objects[contentIds[i]] = `<< /Length ${content.length} >>\nstream\n${content}\nendstream`;
  });

  // Every string here is Latin-1, so string length equals byte length.
  let out = "%PDF-1.4\n";
  const offsets: number[] = [];
  for (let id = 1; id < nextId; id++) {
    offsets[id] = out.length;
    out += `${id} 0 obj\n${objects[id]}\nendobj\n`;
  }
  const xrefPos = out.length;
  out += `xref\n0 ${nextId}\n0000000000 65535 f \n`;
  for (let id = 1; id < nextId; id++) {
    out += `${String(offsets[id]).padStart(10, "0")} 00000 n \n`;
  }
  out += `trailer\n<< /Size ${nextId} /Root 1 0 R >>\nstartxref\n${xrefPos}\n%%EOF`;

  const bytes = new Uint8Array(out.length);
  for (let i = 0; i < out.length; i++) bytes[i] = out.charCodeAt(i) & 0xff;
  return bytes;
}

export interface GeneratedReport {
  bytes: Uint8Array<ArrayBuffer>;
  filename: string;
}

export function generateReportPdf(bridge: Bridge, currentRms: number): GeneratedReport {
  const sev = bridge.severity;
  const alertItems: Item[] = bridge.alerts.length
    ? bridge.alerts.map((a) => ({
        kind: "text" as const,
        text: `[${a.severity}] ${a.message}${a.timestamp ? ` (${a.timestamp})` : ""}`,
        size: 11,
        indent: 12,
        leading: 3,
      }))
    : [{ kind: "text" as const, text: "No active alerts for this bridge.", size: 11, leading: 2 }];

  const items: Item[] = [
    { kind: "text", text: "BridgeGuard AI", size: 20, bold: true, color: BRAND },
    { kind: "text", text: "Structural Health Monitoring Report", size: 13, bold: true, color: GRAY, leading: 2 },
    { kind: "rule", leading: 12 },
    { kind: "text", text: `Bridge: ${bridge.name}`, size: 12, bold: true, leading: 4 },
    { kind: "text", text: `Location: ${bridge.location}`, size: 11 },
    { kind: "text", text: `Report generated: ${formatDate()}`, size: 11 },
    { kind: "rule", leading: 12 },
    { kind: "text", text: "1. Risk Assessment Summary", size: 13, bold: true, leading: 6 },
    { kind: "text", text: `Risk score: ${bridge.risk_score} / 100  (${sev})`, size: 14, bold: true, color: SEVERITY_RGB[sev], leading: 8 },
    {
      kind: "text",
      text:
        bridge.review_status === "PENDING_HUMAN_REVIEW"
          ? "Review status: PENDING HUMAN REVIEW - a qualified engineer must sign off before this assessment is final."
          : "Review status: Final",
      size: 11,
      leading: 2,
    },
    { kind: "gap", size: 12 },
    { kind: "text", text: "2. AI Risk Assessment", size: 13, bold: true },
    { kind: "text", text: bridge.explanation, size: 11, leading: 4 },
    { kind: "gap", size: 12 },
    { kind: "text", text: `3. Active Alerts (${bridge.alerts.length})`, size: 13, bold: true },
    ...alertItems,
    { kind: "gap", size: 12 },
    { kind: "text", text: "4. Sensor Readings Summary", size: 13, bold: true },
    { kind: "text", text: "Readings analysed: 50 (accelerometer)", size: 11, leading: 4 },
    { kind: "text", text: "Normal vibration range: 0.2 - 0.5 m/s\u00B2", size: 11 },
    {
      kind: "text",
      text: `Latest vibration reading: ${currentRms} m/s\u00B2`,
      size: 11,
      color: currentRms > 0.5 ? SEVERITY_RGB.WARNING : SEVERITY_RGB.SAFE,
    },
    { kind: "gap", size: 12 },
    { kind: "text", text: "5. Recommended Actions", size: 13, bold: true },
    { kind: "text", text: RECOMMENDATIONS[sev], size: 11, leading: 4 },
    { kind: "gap", size: 16 },
    { kind: "rule", leading: 4 },
    {
      kind: "text",
      text: "This report was generated automatically by BridgeGuard AI. It supports, but does not replace, a qualified structural engineer's judgement.",
      size: 9,
      color: GRAY,
      leading: 4,
    },
  ];

  const pages = layout(items);
  pages.forEach((content, i) => {
    pages[i] =
      content +
      `\n0.45 0.45 0.42 rg BT /F1 8 Tf ${MARGIN} 30 Td (${esc(
        `BridgeGuard AI - automated structural health monitoring - Page ${i + 1} of ${pages.length}`
      )}) Tj ET`;
  });

  const d = new Date();
  const stamp = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  return { bytes: buildPdf(pages), filename: `bridgeguard-report-${bridge.id}-${stamp}.pdf` };
}

function formatDate(): string {
  return new Date().toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" });
}
