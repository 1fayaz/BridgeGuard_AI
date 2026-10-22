"use client";

import { useState } from "react";
import { SEVERITY_CONFIG, type Severity } from "@/lib/data";

/** One alert card matching Alerts.dc.html. "I have seen this" is a local, honest
 * acknowledge-only action for fixture/sample alerts - there is no real backend to approve
 * against here. Real Approve/Reject with an audit trail exists ONLY on /demo, against the
 * actual demo pipeline - this component never pretends to be that. */
export default function AlertCard({
  severity,
  title,
  detail,
  time,
  bridgeName,
}: {
  severity: Severity;
  title: string;
  detail: string;
  time: string;
  bridgeName?: string;
}) {
  const [seen, setSeen] = useState(false);
  const cfg = SEVERITY_CONFIG[severity];
  const urgent = severity === "CRITICAL";

  return (
    <div
      className="flex items-start gap-4.5 rounded-[20px] bg-white p-6 shadow-[0_1px_2px_rgba(0,50,93,0.06),0_10px_28px_rgba(0,50,93,0.07)]"
      style={{ borderLeft: `8px solid ${cfg.bar}`, opacity: seen && !urgent ? 0.85 : 1 }}
    >
      <svg width={44} height={50} viewBox="0 0 64 72" className="shrink-0">
        <path d="M32 3 L59 13 V35 C59 52 47 63 32 69 C17 63 5 52 5 35 V13 Z" fill={cfg.bar} />
        {severity === "CRITICAL" || severity === "WARNING" ? (
          <>
            <path d="M32 22 V40" stroke="#FFFFFF" strokeWidth={5} strokeLinecap="round" />
            <circle cx={32} cy={50} r={3.2} fill="#FFFFFF" />
          </>
        ) : severity === "WATCH" ? (
          <circle cx={32} cy={37} r={11} fill="none" stroke={cfg.shieldTextDark ? "#2B1D00" : "#FFFFFF"} strokeWidth={5} />
        ) : (
          <path d="M20 37 L29 46 L45 27" fill="none" stroke="#FFFFFF" strokeWidth={5.5} strokeLinecap="round" strokeLinejoin="round" />
        )}
      </svg>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="rounded-full px-3 py-1 text-[13px] font-bold" style={{ background: cfg.bgHex, color: cfg.textHex }}>
            {cfg.label}
          </span>
          {bridgeName && <span className="text-[13px] font-semibold text-blue">{bridgeName}</span>}
          <span className="text-[13px] text-navy-muted">{time}</span>
        </div>
        <div className="mt-2 font-display text-lg font-bold leading-snug text-navy">{title}</div>
        <div className="mt-1.5 text-[15px] leading-relaxed text-navy-text">{detail}</div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            onClick={() => setSeen(true)}
            disabled={seen}
            className="rounded-[10px] px-5.5 py-3 text-sm font-bold disabled:opacity-60"
            style={seen
              ? { background: "#E3EAF2", color: "#00325D" }
              : urgent
              ? { background: cfg.bar, color: "#FFFFFF" }
              : { border: "1.5px solid #00325D", color: "#00325D" }}
          >
            {seen ? "Seen" : "I have seen this"}
          </button>
          {urgent && !seen && (
            <span className="text-[13px] text-navy-muted">Stays at the top until someone confirms it.</span>
          )}
        </div>
      </div>
    </div>
  );
}
