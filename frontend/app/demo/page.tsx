"use client";

import { useEffect, useRef, useState } from "react";
import ShieldScore from "@/components/ShieldScore";
import { SEVERITY_CONFIG, type Severity } from "@/lib/data";
import {
  DEMO_BRIDGE_NAME,
  EXPLANATION_LABELS,
  REPLAY_APPROVAL_DISCLAIMER,
  REPLAY_BANNER,
  isDemoStateNotFound,
  isLiveModeEnabled,
  liveApi,
  loadReplayTimeline,
  type ApproveResponse,
  type PipelineStatusResponse,
  type ReplayFile,
  type ScoreTraceResponse,
} from "@/lib/demo-contract";

type Mode = "live" | "replay";

const EMPTY_STAGES: PipelineStatusResponse["stages"] = {
  ingestion: { helper_name: "The Listener", plain_text: "Sensor heard it", done: false, completed_at: null },
  signal: { helper_name: "The Analyst", plain_text: "Vibration checked", done: false, completed_at: null },
  risk: { helper_name: "The Explainer", plain_text: "Risk scored", done: false, completed_at: null },
  alert: { helper_name: "The Messenger", plain_text: "Alert prepared", done: false, completed_at: null, awaiting_engineer: false },
  report: { helper_name: "The Writer", plain_text: "Report written", done: false, completed_at: null },
};

export default function DemoPage() {
  const [mode] = useState<Mode>(() => (isLiveModeEnabled() ? "live" : "replay"));
  const [phase, setPhase] = useState<"idle" | "running" | "error">("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [cycleId, setCycleId] = useState<string | null>(null);
  const [stages, setStages] = useState<PipelineStatusResponse["stages"]>(EMPTY_STAGES);
  const [scoreTrace, setScoreTrace] = useState<ScoreTraceResponse | null>(null);
  const [approveResult, setApproveResult] = useState<ApproveResponse | null>(null);
  const [replayClickDisclaimer, setReplayClickDisclaimer] = useState(false);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      timers.current.forEach(clearTimeout);
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  function reset() {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    if (pollRef.current) clearInterval(pollRef.current);
    setPhase("idle");
    setErrorMessage(null);
    setCycleId(null);
    setStages(EMPTY_STAGES);
    setScoreTrace(null);
    setApproveResult(null);
    setReplayClickDisclaimer(false);
  }

  function applyEntry(entry: ReplayFile["timeline"][number]) {
    if (entry.endpoint.includes("simulate-heavy-truck")) {
      setCycleId((entry.response as { cycle_id: string }).cycle_id);
    } else if (entry.endpoint.includes("pipeline-status")) {
      setStages((entry.response as PipelineStatusResponse).stages);
    } else if (entry.endpoint.includes("score-trace")) {
      setScoreTrace(entry.response as ScoreTraceResponse);
    } else if (entry.endpoint.includes("/approve")) {
      setApproveResult(entry.response as ApproveResponse);
    }
  }

  async function startReplay() {
    reset();
    setPhase("running");
    const data = await loadReplayTimeline(); // the ONLY network call replay mode ever makes.
    for (const entry of data.timeline) {
      const t = setTimeout(() => applyEntry(entry), entry.at_ms);
      timers.current.push(t);
    }
  }

  async function startLive() {
    reset();
    setPhase("running");
    const sim = await liveApi.simulate();
    if ("__error" in sim) {
      setPhase("error");
      const notFound = isDemoStateNotFound(sim);
      const detail = sim.__error.detail;
      setErrorMessage(notFound ? "Press Simulate again." : detail);
      return;
    }
    setCycleId(sim.cycle_id);

    pollRef.current = setInterval(async () => {
      const status = await liveApi.pipelineStatus(DEMO_BRIDGE_ID, sim.cycle_id);
      if ("__error" in status) return; // transient — keep polling.
      setStages(status.stages);

      if (status.stages.risk.done && !scoreTrace) {
        const trace = await liveApi.scoreTrace(DEMO_BRIDGE_ID);
        if (!("__error" in trace)) setScoreTrace(trace);
      }
      if (status.stages.report.done && pollRef.current) {
        clearInterval(pollRef.current);
      }
    }, 1200);
  }

  async function decide(action: "approve" | "reject") {
    if (mode === "replay") {
      setReplayClickDisclaimer(true);
      return; // click-through only — the recorded timeline, not the click, drives replay state.
    }
    const alertId = "demo-alert-1"; // the demo's one fixed dispatch id.
    const result = action === "approve" ? await liveApi.approve(alertId) : await liveApi.reject(alertId);
    if (isDemoStateNotFound(result)) {
      setErrorMessage("Press Simulate again.");
      return;
    }
    if (!("__error" in result)) setApproveResult(result);
  }

  const severity = (scoreTrace?.severity ?? null) as Severity | null;
  const cfg = severity ? SEVERITY_CONFIG[severity] : null;
  const allDone = Object.values(stages).every((s) => s.done);
  // Show the alert card once Alert has prepared something — waiting for a decision, or already
  // decided (permanent audit line). Only hide it before the Alert stage has run at all.
  const showAlertCard = stages.alert.done || approveResult !== null;
  const decided = approveResult !== null;

  return (
    <div className="flex flex-col gap-6">
      {mode === "replay" && (
        <div className="rounded-xl bg-watch-bg px-4 py-3 text-sm font-semibold text-watch-text">
          {REPLAY_BANNER}
        </div>
      )}

      <div>
        <h1 className="font-display text-3xl font-extrabold text-navy">See it work: a heavy truck crosses {DEMO_BRIDGE_NAME}</h1>
        <p className="mt-2 max-w-2xl text-[16px] leading-relaxed text-navy-text">
          {mode === "live"
            ? "This runs the real pipeline on this laptop, right now."
            : "This plays back a recorded run of the real pipeline, exactly as it happened."}
        </p>
      </div>

      {phase === "error" && errorMessage && (
        <div className="rounded-xl bg-urgent-bg px-4 py-3 text-sm font-semibold text-urgent-text">
          {errorMessage}
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        <button
          onClick={mode === "live" ? startLive : startReplay}
          disabled={phase === "running" && !allDone}
          className="rounded-xl bg-navy px-6 py-3.5 text-[15px] font-bold text-white disabled:opacity-60"
        >
          {mode === "live" ? "Simulate a heavy truck" : "Watch the demo"}
        </button>
        {phase !== "idle" && (
          <button onClick={reset} className="rounded-xl border-[1.5px] border-navy bg-white px-6 py-3.5 text-[15px] font-bold text-navy">
            Reset demo
          </button>
        )}
      </div>

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

      {/* Urgent alert card */}
      {showAlertCard && (
        <section className="rounded-2xl border-2 border-urgent bg-urgent-bg p-6">
          <h2 className="font-display text-xl font-extrabold text-urgent-text">Urgent alert — human approval required</h2>
          <p className="mt-2 text-[15px] text-navy-text">
            {decided
              ? "AI suggests. A person decides."
              : "Waiting for an engineer to decide. Nothing has been sent. AI suggests. A person decides."}
          </p>

          {!decided ? (
            <div className="mt-4 flex gap-3">
              <button onClick={() => decide("approve")} className="rounded-xl bg-urgent px-6 py-3 text-sm font-bold text-white">
                Approve and send
              </button>
              <button onClick={() => decide("reject")} className="rounded-xl border-2 border-urgent bg-white px-6 py-3 text-sm font-bold text-urgent-text">
                Reject / needs review
              </button>
            </div>
          ) : (
            <div className="mt-4 rounded-xl bg-white p-4 text-sm">
              <strong>{approveResult!.approval_state === "APPROVED" ? "Approved" : "Rejected"}</strong> by{" "}
              {approveResult!.approved_by} at {new Date(approveResult!.approved_at).toLocaleTimeString()}.
              {approveResult!.notification_status && (
                <span className="ml-1 text-navy-muted">Notification: {approveResult!.notification_status}.</span>
              )}
            </div>
          )}

          {mode === "replay" && replayClickDisclaimer && !decided && (
            <p className="mt-3 text-sm font-semibold text-navy-muted">{REPLAY_APPROVAL_DISCLAIMER}</p>
          )}
        </section>
      )}

      {/* Share a report */}
      {stages.report.done && (
        <section className="rounded-2xl bg-white p-6 shadow-sm">
          <h2 className="font-display text-lg font-bold text-navy">Share a report</h2>
          {mode === "replay" ? (
            <a href="/replay/demo-report.pdf" className="mt-3 inline-block rounded-xl bg-navy px-6 py-3 text-sm font-bold text-white">
              Open the demonstration report (PDF)
            </a>
          ) : (
            <p className="mt-2 text-sm text-navy-text">Report ready — generated by the real renderer, marked DEMONSTRATION DATA.</p>
          )}
        </section>
      )}
    </div>
  );
}

const DEMO_BRIDGE_ID = "bridge-demo-01";
