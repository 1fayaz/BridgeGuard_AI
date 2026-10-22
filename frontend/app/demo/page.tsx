"use client";

import { useEffect, useRef, useState } from "react";
import ShieldScore from "@/components/ShieldScore";
import WatchDemo from "@/components/WatchDemo";
import { SEVERITY_CONFIG, type Severity } from "@/lib/data";
import {
  DEMO_BRIDGE_NAME,
  EXPLANATION_LABELS,
  REPLAY_BANNER,
  REPLAY_NOTHING_SAVED,
  loadReplayTimeline,
  type ApproveResponse,
  type PipelineStatusResponse,
  type ReplayFile,
  type ScoreTraceResponse,
} from "@/lib/demo-contract";

// LIVE mode is architecturally present in lib/demo-contract.ts (liveApi, isLiveModeEnabled) but
// this build never calls it and exposes no UI path to reach it - the live API/approval backend
// (slices 2-5, JWT auth) does not exist yet. Tonight's demo is REPLAY only.

const EMPTY_STAGES: PipelineStatusResponse["stages"] = {
  ingestion: { helper_name: "The Listener", plain_text: "Sensor heard it", done: false, completed_at: null },
  signal: { helper_name: "The Analyst", plain_text: "Vibration checked", done: false, completed_at: null },
  risk: { helper_name: "The Explainer", plain_text: "Risk scored", done: false, completed_at: null },
  alert: { helper_name: "The Messenger", plain_text: "Alert prepared", done: false, completed_at: null, awaiting_engineer: false },
  report: { helper_name: "The Writer", plain_text: "Report written", done: false, completed_at: null },
};

export default function DemoPage() {
  const [phase, setPhase] = useState<"idle" | "running">("idle");
  const [stages, setStages] = useState<PipelineStatusResponse["stages"]>(EMPTY_STAGES);
  const [scoreTrace, setScoreTrace] = useState<ScoreTraceResponse | null>(null);
  const [approveResult, setApproveResult] = useState<ApproveResponse | null>(null);
  const [showWatchDemo, setShowWatchDemo] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const approveEntry = useRef<ApproveResponse | null>(null);

  useEffect(() => {
    return () => {
      timers.current.forEach(clearTimeout);
    };
  }, []);

  function clearLocalState() {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    approveEntry.current = null;
    setPhase("idle");
    setStages(EMPTY_STAGES);
    setScoreTrace(null);
    setApproveResult(null);
  }

  function applyEntry(entry: ReplayFile["timeline"][number]) {
    if (entry.endpoint.includes("pipeline-status")) {
      setStages((entry.response as PipelineStatusResponse).stages);
    } else if (entry.endpoint.includes("score-trace")) {
      setScoreTrace(entry.response as ScoreTraceResponse);
    } else if (entry.endpoint.includes("/approve")) {
      setApproveResult(entry.response as ApproveResponse);
    }
  }

  async function startReplay() {
    clearLocalState();
    setPhase("running");
    const data = await loadReplayTimeline(); // the ONLY network call replay mode ever makes.
    for (const entry of data.timeline) {
      if (entry.endpoint.includes("/approve")) {
        // Held back for a real click (see decide()) instead of auto-applying on a timer - a
        // replay still asks a person to press the button, it just never saves their answer.
        approveEntry.current = entry.response as ApproveResponse;
        continue;
      }
      const t = setTimeout(() => applyEntry(entry), entry.at_ms);
      timers.current.push(t);
    }
  }

  // Replay has no backend state to clear - "Reset demo" only restarts local playback.
  function handleResetClick() {
    clearLocalState();
  }

  // A real person's click on a replay: it reveals the same result the recorded run produced,
  // right when clicked - but presses nothing backward into that recording. Nothing is saved.
  function decide() {
    if (approveEntry.current) setApproveResult(approveEntry.current);
  }

  const severity = (scoreTrace?.severity ?? null) as Severity | null;
  const cfg = severity ? SEVERITY_CONFIG[severity] : null;
  const allDone = Object.values(stages).every((s) => s.done);
  const showAlertCard = stages.alert.done || approveResult !== null;
  const decided = approveResult !== null;

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-xl bg-watch-bg px-4 py-3 text-sm font-semibold text-watch-text">
        {REPLAY_BANNER}
      </div>

      <div>
        <h1 className="font-display text-3xl font-extrabold text-navy">See it work: a heavy truck crosses {DEMO_BRIDGE_NAME}</h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-navy-text">
          This plays back a recorded run of the real pipeline, exactly as it happened.
        </p>
      </div>

      <div id="demo-start" className="flex flex-wrap gap-3 scroll-mt-24">
        <button
          onClick={startReplay}
          disabled={phase === "running" && !allDone}
          className="rounded-xl bg-navy px-6 py-3.5 text-[15px] font-bold text-white disabled:opacity-60"
        >
          Start the replay
        </button>
        {phase !== "idle" && (
          <button onClick={handleResetClick} className="rounded-xl border-[1.5px] border-navy bg-white px-6 py-3.5 text-[15px] font-bold text-navy">
            Reset demo
          </button>
        )}
        <button
          onClick={() => setShowWatchDemo(true)}
          className="rounded-xl border-[1.5px] border-blue bg-white px-6 py-3.5 text-[15px] font-bold text-blue"
        >
          Watch the demo
        </button>
      </div>

      {showWatchDemo && (
        <WatchDemo
          onClose={() => setShowWatchDemo(false)}
          onGoToApproval={() => {
            setShowWatchDemo(false);
            requestAnimationFrame(() => {
              const target = document.getElementById("approval-panel") ?? document.getElementById("demo-start");
              target?.scrollIntoView({ behavior: "smooth", block: "start" });
            });
          }}
        />
      )}

      {/* 5-step progress strip */}
      {phase !== "idle" && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {(Object.keys(stages) as (keyof typeof stages)[]).map((key) => {
            const s = stages[key];
            return (
              <div
                key={key}
                className={`rounded-2xl border p-4 text-center transition ${
                  s.done ? "border-safe bg-safe-bg" : "border-border bg-white"
                }`}
              >
                <div className="text-xs font-bold uppercase tracking-wide text-navy-muted">{s.helper_name}</div>
                <div className="mt-1 text-sm font-semibold text-navy">{s.plain_text}</div>
                {key === "alert" && s.awaiting_engineer && (
                  <div className="mt-1 text-xs font-bold text-watch-text">Waiting for engineer</div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Score climbing + colour change */}
      {scoreTrace && cfg && (
        <div className="flex flex-wrap items-center gap-6 rounded-2xl bg-white p-6 shadow-sm">
          <ShieldScore severity={severity!} score={scoreTrace.risk_score} size={90} />
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-navy-muted">{DEMO_BRIDGE_NAME}</div>
            <div className="font-display text-2xl font-extrabold text-navy">
              {scoreTrace.risk_score}/100 · {cfg.label}
            </div>
          </div>
        </div>
      )}

      {/* Why this score? */}
      {scoreTrace && (
        <section className="rounded-2xl bg-white p-6 shadow-sm">
          <h2 className="font-display text-xl font-extrabold text-navy">Why this score?</h2>
          <p className="mt-2 text-[15px] text-navy-text">
            Vibration was {scoreTrace.limit.ratio?.toFixed(1)}× the configured limit.
          </p>
          <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-navy-muted">Reading</dt>
              <dd className="font-semibold">{scoreTrace.reading.value} {scoreTrace.reading.unit}</dd>
            </div>
            <div>
              <dt className="text-navy-muted">Limit compared against</dt>
              <dd className="font-semibold">
                {scoreTrace.limit.is_configured ? scoreTrace.limit.value : "—"}
                <span className="ml-2 text-xs font-normal text-navy-muted">{scoreTrace.limit.basis_label}</span>
              </dd>
            </div>
          </dl>
          <div
            className={`mt-4 rounded-xl border-l-4 p-4 text-[15px] leading-relaxed ${
              scoreTrace.explanation.kind === "template_fallback" ? "border-unknown bg-unknown-bg" : "border-blue bg-page-bg"
            }`}
          >
            <div className="mb-2 text-xs font-bold uppercase tracking-wide text-navy-muted">
              {scoreTrace.explanation.source_label ?? EXPLANATION_LABELS[scoreTrace.explanation.kind]}
            </div>
            &ldquo;{scoreTrace.explanation.text}&rdquo;
          </div>
        </section>
      )}

      {/* Urgent alert card - a real person's click on a replay. This is the page the "Watch the
          demo" animation's closing hand-off card points to. */}
      {showAlertCard && (
        <section id="approval-panel" className="scroll-mt-24 rounded-2xl border-2 border-urgent bg-urgent-bg p-6">
          <h2 className="font-display text-xl font-extrabold text-urgent-text">Urgent alert — human approval required</h2>
          <p className="mt-2 text-[15px] text-navy-text">
            {decided
              ? "AI suggests. A person decides."
              : "Waiting for an engineer to decide. AI suggests. A person decides."}
          </p>

          {!decided ? (
            <div className="mt-4 flex gap-3">
              <button onClick={decide} className="rounded-xl bg-urgent px-6 py-3 text-sm font-bold text-white">
                Approve (replay)
              </button>
              <button onClick={decide} className="rounded-xl border-2 border-urgent bg-white px-6 py-3 text-sm font-bold text-urgent-text">
                Reject (replay)
              </button>
            </div>
          ) : (
            <div className="mt-4 flex flex-col gap-4 rounded-xl bg-white p-5 text-sm">
              <div>
                <div className="font-bold text-navy-muted">{REPLAY_NOTHING_SAVED}</div>
                <div className="mt-1">
                  <strong className="text-base">{approveResult!.approval_state === "APPROVED" ? "Approved" : "Rejected"}</strong> by{" "}
                  {approveResult!.approved_by} at {new Date(approveResult!.approved_at).toLocaleTimeString()} in this recorded run.
                </div>
                <div className="mt-1 text-navy-muted">In the live system this will be logged.</div>
              </div>

              {scoreTrace && cfg && (
                <>
                  <div className="flex items-center gap-3 border-t border-border pt-4">
                    <ShieldScore severity={severity!} score={scoreTrace.risk_score} size={48} />
                    <div>
                      <div className="text-xs font-bold uppercase tracking-wide text-navy-muted">Final risk level</div>
                      <div className="font-display text-lg font-extrabold text-navy">
                        {scoreTrace.risk_score}/100 · {cfg.label}
                      </div>
                    </div>
                  </div>
                  <div className="rounded-lg border-l-4 border-blue bg-page-bg p-4 leading-relaxed">
                    <div className="mb-1.5 text-xs font-bold uppercase tracking-wide text-navy-muted">
                      {scoreTrace.explanation.source_label ?? EXPLANATION_LABELS[scoreTrace.explanation.kind]}
                    </div>
                    &ldquo;{scoreTrace.explanation.text}&rdquo;
                  </div>
                </>
              )}

              <a href="/replay/demo-report.pdf" className="font-bold text-blue">
                Open the demonstration report (PDF) →
              </a>
            </div>
          )}
        </section>
      )}

      {/* Share a report */}
      {stages.report.done && (
        <section id="report" className="scroll-mt-24 rounded-2xl bg-white p-6 shadow-sm">
          <h2 className="font-display text-lg font-bold text-navy">Share a report</h2>
          <a href="/replay/demo-report.pdf" className="mt-3 inline-block rounded-xl bg-navy px-6 py-3 text-sm font-bold text-white">
            Open the demonstration report (PDF)
          </a>
        </section>
      )}
    </div>
  );
}
