"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
import { EXPLANATION_LABELS, REPLAY_BANNER, loadReplayTimeline, type ScoreTraceResponse } from "@/lib/demo-contract";
import { SEVERITY_CONFIG, type Severity } from "@/lib/data";

/** Ported from animation/watch-demo-preview.html (approved reference, kept as reference-only -
 * nothing is imported from that folder). Numbers are read from public/replay/demo-run.json's
 * score-trace entry at mount; any field missing from that file falls back to the reference's own
 * worked example (3.4 m/s² / limit 1.0 / score 85 / CRITICAL), never a newly-invented number. */

const T_END = 37;

interface RunData {
  peak: number;
  limit: number;
  ratio: number;
  score: number;
  severity: Severity;
  label: string;
  calm: number;
  calmScore: number;
  explanationText: string;
  explanationLabel: string;
}

const FALLBACK_RUN: RunData = {
  peak: 3.4,
  limit: 1.0,
  ratio: 3.4,
  score: 85,
  severity: "CRITICAL",
  label: "Urgent",
  calm: 0.1,
  calmScore: 2,
  explanationText:
    "The sensor recorded shaking about 3.4 times the demonstration limit while a heavy vehicle crossed. This is far above normal, so the system rated the situation urgent and asked an engineer to review it.",
  explanationLabel: EXPLANATION_LABELS.pregenerated_ai,
};

// One naming set used here and on /agents: plain name first, the real backend package name
// (ingestion/signal/risk/alert/report - see src/agents/{data_collection,structural_analysis,
// risk_reasoning,alert_escalation,report_generation}) in parentheses. These also match the
// "helper_name" strings ("The Listener", "The Analyst", ...) the backend itself writes into
// public/replay/demo-run.json's pipeline-status entries.
const AGENTS = [
  { name: "Listener", technical: "Ingestion agent", job: "Receives the reading and checks it is valid." },
  { name: "Analyst", technical: "Signal agent", job: "Removes noise and finds the peak shaking." },
  { name: "Explainer", technical: "Risk agent", job: "Compares with the limit and gives a score." },
  { name: "Messenger", technical: "Alert agent", job: "Decides how urgent it is and who to tell." },
  { name: "Writer", technical: "Report agent", job: "Writes the explanation and the PDF report." },
] as const;

function buildSteps(run: RunData) {
  return [
    {
      s: 0,
      e: 10,
      tag: "Truck",
      h: "A heavy truck crosses the bridge.",
      p: `A small sensor under the deck feels the bridge shake. Normal traffic barely moves it. This truck shakes it ${run.ratio.toFixed(1)} times more than the limit set for this demo.`,
      en: `Accelerometer on the deck. Peak ${run.peak.toFixed(1)} m/s² against a demonstration limit of ${run.limit.toFixed(1)} m/s² (ratio ${run.ratio.toFixed(1)}×). The truck scenario is simulated input.`,
    },
    {
      s: 10,
      e: 18,
      tag: "Journey",
      h: "The reading travels to the cloud.",
      p: "The sensor sends its reading by long-range radio to a small computer on the river bank. That computer passes it on to the cloud, where the AI agents work.",
      en: "LoRaWAN uplink to a Raspberry Pi 5 gateway, then MQTT to the cloud ingestion API.",
    },
    {
      s: 18,
      e: 37,
      tag: "AI agents",
      h: "Five AI agents check it, one after another.",
      p: "Each agent has one simple job. Together they turn a raw number into a clear risk score that anyone can read. Then a human takes over.",
      en: `Listener (Ingestion), Analyst (Signal), Explainer (Risk), Messenger (Alert), Writer (Report). Risk score ${run.score}/100 comes from the real scoring code run on the simulated reading.`,
    },
  ];
}

const NODES = [
  ["Sensor on the bridge", "MPU-6050 accelerometer", "sent"],
  ["Long-range radio", "LoRaWAN", "On its way"],
  ["Computer on the river bank", "Raspberry Pi 5 · MQTT", "Received"],
  ["The cloud", "FastAPI · Postgres", "Stored safely"],
] as const;
const NT = [10.8, 12.7, 14.6, 16.5];

function clamp(x: number, a: number, b: number) {
  return Math.max(a, Math.min(b, x));
}
function seg(t: number, a: number, b: number) {
  return clamp((t - a) / (b - a), 0, 1);
}
function fmt(s: number) {
  s = Math.floor(s);
  return Math.floor(s / 60) + ":" + ("0" + (s % 60)).slice(-2);
}
function mix(a: number[], b: number[], k: number) {
  return (
    "rgb(" +
    Math.round(a[0] + (b[0] - a[0]) * k) +
    "," +
    Math.round(a[1] + (b[1] - a[1]) * k) +
    "," +
    Math.round(a[2] + (b[2] - a[2]) * k) +
    ")"
  );
}
const NS = "http://www.w3.org/2000/svg";
function el<K extends keyof SVGElementTagNameMap>(
  tag: K,
  at: Record<string, string | number>,
  par?: Element,
): SVGElementTagNameMap[K] {
  const e = document.createElementNS(NS, tag) as SVGElementTagNameMap[K];
  for (const k in at) e.setAttribute(k, String(at[k]));
  if (par) par.appendChild(e);
  return e;
}

export default function WatchDemo({ onClose, onGoToApproval }: { onClose: () => void; onGoToApproval: () => void }) {
  const [run, setRun] = useState<RunData>(FALLBACK_RUN);
  const [engineerDetail, setEngineerDetail] = useState(true);
  const [stepIdx, setStepIdx] = useState(0);
  const [timeLabel, setTimeLabel] = useState("0:00 / 0:37");
  const [playing, setPlaying] = useState(false);
  const [finished, setFinished] = useState(false);

  const closeBtnRef = useRef<HTMLButtonElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const bsvgRef = useRef<SVGSVGElement>(null);
  const netRef = useRef<HTMLDivElement>(null);
  const agRef = useRef<HTMLDivElement>(null);
  const trkRef = useRef<HTMLDivElement>(null);
  const handoffRef = useRef<HTMLDivElement>(null);
  const sbRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const trackFillRefs = useRef<(HTMLSpanElement | null)[]>([]);

  const layerRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // ----- load real numbers (static file only - no backend, no login) -----
  useEffect(() => {
    let cancelled = false;
    loadReplayTimeline()
      .then((data) => {
        if (cancelled) return;
        const traceEntry = data.timeline.find((e) => e.endpoint.includes("score-trace"));
        const trace = traceEntry?.response as ScoreTraceResponse | undefined;
        const severity = (trace?.severity as Severity | undefined) ?? FALLBACK_RUN.severity;
        const label = SEVERITY_CONFIG[severity]?.label ?? FALLBACK_RUN.label;
        const kind = trace?.explanation?.kind;
        setRun({
          peak: trace?.reading?.value ?? FALLBACK_RUN.peak,
          limit: trace?.limit?.value ?? FALLBACK_RUN.limit,
          ratio: trace?.limit?.ratio ?? FALLBACK_RUN.ratio,
          score: trace?.risk_score ?? FALLBACK_RUN.score,
          severity,
          label,
          calm: FALLBACK_RUN.calm,
          calmScore: FALLBACK_RUN.calmScore,
          explanationText: trace?.explanation?.text ?? FALLBACK_RUN.explanationText,
          explanationLabel:
            trace?.explanation?.source_label ?? (kind ? EXPLANATION_LABELS[kind] : undefined) ?? FALLBACK_RUN.explanationLabel,
        });
      })
      .catch(() => {
        /* static fixture missing - keep the reference fallback values, never block the animation */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // ----- focus return + initial focus -----
  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null;
    closeBtnRef.current?.focus();
    return () => {
      previouslyFocused?.focus?.();
    };
  }, []);

  // ----- build the bridge SVG scene once -----
  const bridgeApi = useRef<{
    render: (t: number) => void;
    fit: () => void;
  } | null>(null);

  useEffect(() => {
    const svgMaybeNull = bsvgRef.current;
    if (!svgMaybeNull) return;
    const svg: SVGSVGElement = svgMaybeNull;
    while (svg.firstChild) svg.removeChild(svg.firstChild);

    const defs = el("defs", {}, svg);
    const grad = el("linearGradient", { id: "wg", x1: 0, y1: 0, x2: 0, y2: 1 }, defs);
    el("stop", { offset: 0, "stop-color": "#1B5A8F" }, grad);
    el("stop", { offset: 1, "stop-color": "#0A2744" }, grad);
    el("rect", { x: 0, y: 296, width: 960, height: 60, fill: "url(#wg)" }, svg);
    const wv = [
      el("path", { fill: "none", stroke: "rgba(255,255,255,.16)", "stroke-width": 2 }, svg),
      el("path", { fill: "none", stroke: "rgba(255,255,255,.10)", "stroke-width": 2 }, svg),
    ];
    el("path", { d: "M0 244H160L190 296 160 356H0Z", fill: "#27412E" }, svg);
    el("path", { d: "M960 244H800L770 296 800 356H960Z", fill: "#27412E" }, svg);
    const deck = el("path", { fill: "none", stroke: "#C9D8E8", "stroke-width": 8, "stroke-linecap": "round" }, svg);

    const BX: number[] = [];
    const TX: number[] = [];
    for (let i = 0; i <= 8; i++) BX.push(160 + i * 80);
    for (let i = 0; i < 8; i++) TX.push(200 + i * 80);
    type Node = ["b" | "t", number];
    const mem: { a: Node; b: Node; p: SVGPathElement }[] = [];
    function addM(a: Node, b: Node) {
      mem.push({
        a,
        b,
        p: el(
          "path",
          {
            fill: "none",
            "stroke-width": 3.2,
            "stroke-linecap": "round",
            pathLength: 1,
            "stroke-dasharray": 1,
            "stroke-dashoffset": 1,
          },
          svg,
        ),
      });
    }
    for (let i = 0; i < 8; i++) addM(["b", i], ["b", i + 1]);
    for (let i = 0; i < 7; i++) addM(["t", i], ["t", i + 1]);
    for (let i = 0; i < 8; i++) {
      addM(["b", i], ["t", i]);
      addM(["t", i], ["b", i + 1]);
    }

    const truck = el("g", {}, svg);
    el("rect", { x: -62, y: -44, width: 84, height: 38, rx: 3, fill: "#F2B233" }, truck);
    const truckLabel = document.createElementNS(NS, "text");
    truckLabel.setAttribute("x", "-20");
    truckLabel.setAttribute("y", "-20");
    truckLabel.setAttribute("text-anchor", "middle");
    truckLabel.setAttribute("font-size", "13");
    truckLabel.setAttribute("font-weight", "800");
    truckLabel.setAttribute("fill", "#3a2a00");
    truckLabel.setAttribute("font-family", "system-ui,sans-serif");
    truckLabel.textContent = "HEAVY";
    truck.appendChild(truckLabel);
    el("path", { d: "M26 -6V-30H44L58 -18V-6Z", fill: "#F4F7FB" }, truck);
    el("path", { d: "M31 -26H42L52 -18H31Z", fill: "#7CB7E8" }, truck);
    [-46, -24, 2, 40].forEach((x) =>
      el("circle", { cx: x, cy: -2, r: 8, fill: "#10233A", stroke: "#9DB3CC", "stroke-width": 2 }, truck),
    );

    const rings = [0, 1, 2].map(() => el("circle", { cx: 480, cy: 258, r: 14, fill: "none", "stroke-width": 2.5 }, svg));
    const sens = el("rect", { x: 471, y: 250, width: 18, height: 14, rx: 3, stroke: "#fff", "stroke-width": 2 }, svg);
    const sl = document.createElementNS(NS, "text");
    sl.setAttribute("x", "480");
    sl.setAttribute("y", "292");
    sl.setAttribute("text-anchor", "middle");
    sl.setAttribute("font-size", "17");
    sl.setAttribute("font-weight", "600");
    sl.setAttribute("fill", "#EAF2FB");
    sl.setAttribute("font-family", "system-ui,sans-serif");
    sl.textContent = "Sensor under the deck";
    svg.appendChild(sl);
    const caption = document.createElementNS(NS, "text");
    caption.setAttribute("x", "480");
    caption.setAttribute("y", "327");
    caption.setAttribute("text-anchor", "middle");
    caption.setAttribute("font-size", "13");
    caption.setAttribute("fill", "rgba(255,255,255,.55)");
    caption.setAttribute("font-family", "system-ui,sans-serif");
    caption.textContent = "Bridge movement is exaggerated so you can see it.";
    svg.appendChild(caption);

    function sag(x: number, tx: number) {
      if (x < 160 || x > 800) return 0;
      return 9 * Math.sin((Math.PI * (x - 160)) / 640) * Math.exp(-Math.pow((x - tx) / 150, 2));
    }
    function truckX(t: number) {
      return -150 + 1130 * clamp((t - 0.4) / 9.2, 0, 1);
    }
    // Visual shake amplitude follows the real peak reading (minus the resting 0.1 m/s² idle
    // value), so the cartoon never shows a shake bigger or smaller than the number under it.
    const amplitude = Math.max(0.1, run.peak - 0.1);
    function shake(t: number) {
      const d = truckX(t) - 480;
      return 0.1 + amplitude * Math.exp(-Math.pow(d / 170, 2));
    }
    const TP = 0.4 + (9.2 * 630) / 1130;
    const displayScale = Math.max(4, Math.ceil(run.peak * 1.2));

    function pos(n: Node): [number, number] {
      const x = n[0] === "b" ? BX[n[1]] : TX[n[1]];
      let y = n[0] === "b" ? 246 : 170;
      const txNow = truckX(lastT);
      y += n[0] === "b" ? sag(x, txNow) : sag(x, txNow) * 0.8;
      return [x, y];
    }
    let lastT = 0;

    function render(t: number) {
      lastT = t;
      const tx = truckX(t);
      const v = shake(t);
      const over = v > run.limit;
      let d = "";
      for (let x = 0; x <= 960; x += 24) d += (x ? "L" : "M") + x + " " + (240 + sag(x, tx)).toFixed(1);
      deck.setAttribute("d", d);
      truck.setAttribute("transform", "translate(" + tx.toFixed(1) + "," + (240 + sag(tx, tx)).toFixed(1) + ")");
      const load = clamp((v - 0.1) / amplitude, 0, 1);
      mem.forEach((m, k) => {
        const A = pos(m.a);
        const B = pos(m.b);
        m.p.setAttribute("d", "M" + A[0] + " " + A[1].toFixed(1) + "L" + B[0] + " " + B[1].toFixed(1));
        const mx = (A[0] + B[0]) / 2;
        const pr = Math.exp(-Math.pow((mx - tx) / 120, 2)) * load;
        m.p.setAttribute("stroke", mix([111, 168, 220], [255, 90, 77], clamp(pr * 1.15, 0, 1)));
        m.p.setAttribute("stroke-dashoffset", (1 - seg(t, 0.1 + k * 0.045, 0.1 + k * 0.045 + 0.7)).toFixed(3));
      });
      const col = over ? "#FF5A4D" : "#3AA3F0";
      sens.setAttribute("fill", col);
      sens.setAttribute("transform", "translate(0," + sag(480, tx).toFixed(1) + ")");
      rings.forEach((r, k) => {
        const ph = (t * 1.1 + k / 3) % 1;
        r.setAttribute("r", (14 + ph * 40).toFixed(1));
        r.setAttribute("stroke", col);
        r.setAttribute("opacity", (Math.max(0, 1 - ph) * clamp(load * 1.4 + 0.12, 0, 1) * 0.85 * seg(t, 2.5, 3.2)).toFixed(2));
        r.setAttribute("transform", "translate(0," + sag(480, tx).toFixed(1) + ")");
      });
      wv.forEach((w, k) => {
        let dd = "M0 " + (312 + k * 14);
        for (let x = 0; x <= 960; x += 30)
          dd += "L" + x + " " + (312 + k * 14 + Math.sin(x / 70 + t * (1 + k * 0.4) + k) * 3).toFixed(1);
        w.setAttribute("d", dd);
      });
      setReadout({
        value: v,
        over,
        barPct: clamp(v / displayScale, 0, 1) * 100,
        peakShown: seg(t, TP, TP + 0.6) > 0.5,
      });
    }
    function fit() {
      const w = stageRef.current?.clientWidth ?? 960;
      svg.setAttribute("viewBox", w < 600 ? "170 130 620 220" : "0 130 960 220");
    }
    bridgeApi.current = { render, fit };
    fit();
    render(0);
  }, [run]);

  // small readout state for the non-SVG value card (vibration number/bar/peak callout)
  const [readout, setReadout] = useState({ value: 0.1, over: false, barPct: 2.5, peakShown: false });

  // ----- network scene -----
  const ndRefs = useRef<(HTMLDivElement | null)[]>([]);
  const cnFillRefs = useRef<(HTMLSpanElement | null)[]>([]);
  function renderNet(t: number) {
    // Matches the sm: (640px) breakpoint used on the connector/card layout below.
    const vertical = typeof window !== "undefined" && window.innerWidth < 640;
    NT.forEach((start, k) => {
      const d = ndRefs.current[k];
      if (!d) return;
      const a = seg(t, start - 0.3, start + 0.3);
      d.style.opacity = (0.35 + 0.65 * a).toFixed(2);
      d.style.borderColor = a > 0 ? `rgba(58,163,240,${(0.3 + 0.7 * a).toFixed(2)})` : "";
    });
    cnFillRefs.current.forEach((b, k) => {
      if (!b) return;
      const p = seg(t, NT[k] + 0.2, NT[k + 1] - 0.2);
      const pct = (p * 100).toFixed(1) + "%";
      if (vertical) {
        b.style.top = pct;
        b.style.left = "";
      } else {
        b.style.left = pct;
        b.style.top = "";
      }
      b.style.opacity = p > 0 && p < 1 ? "1" : "0";
    });
  }

  // ----- agents scene -----
  const A0 = 18.8;
  const AD = 3.0;
  const acRefs = useRef<(HTMLDivElement | null)[]>([]);
  const acBadgeRefs = useRef<(HTMLSpanElement | null)[]>([]);
  const acOutRefs = useRef<(HTMLDivElement | null)[]>([]);
  const riskFillRef = useRef<HTMLSpanElement>(null);
  function renderAgents(t: number) {
    if (trkRef.current) trkRef.current.style.width = (seg(t, A0, A0 + AD * 5) * 100).toFixed(1) + "%";
    const outcomes = ["1 reading accepted", `Peak ${run.peak.toFixed(1)} m/s²`, `Score ${run.score} / 100`, "Urgent alert raised", "Report ready"];
    AGENTS.forEach((_, k) => {
      const s = A0 + k * AD;
      const on = t >= s && t < s + AD * 0.55;
      const dn = t >= s + AD * 0.55;
      const c = acRefs.current[k];
      if (c) {
        c.style.opacity = t >= s ? "1" : "0.4";
        c.style.borderColor = on ? "#3AA3F0" : dn ? "rgba(55,179,107,.5)" : "";
        c.style.boxShadow = on ? "0 0 0 1px #3AA3F0, 0 0 24px rgba(58,163,240,.35)" : "";
      }
      const badge = acBadgeRefs.current[k];
      if (badge) {
        badge.textContent = dn ? "✓" : String(k + 1);
        badge.style.background = dn ? "#37B36B" : "";
        badge.style.color = dn ? "#04210f" : "";
      }
      const out = acOutRefs.current[k];
      if (out) {
        out.style.opacity = seg(t, s + AD * 0.5, s + AD * 0.8).toFixed(2);
        if (k === 2) {
          const rb = riskFillRef.current;
          const scorePct = seg(t, s + AD * 0.2, s + AD * 0.95) * run.score;
          if (rb) rb.style.width = scorePct + "%";
          out.textContent = t < s + AD * 0.8 ? `Score ${Math.round(scorePct)} / 100` : `Score ${run.score} / 100`;
        } else {
          out.textContent = outcomes[k];
        }
      }
    });
  }

  // ----- hand-off card (replaces the old approval/result scenes - the real decision now
  // happens only on /demo, never simulated in this video) -----
  function renderHandoff(t: number) {
    const node = handoffRef.current;
    if (!node) return;
    const a = seg(t, 34.4, 35.2);
    node.style.opacity = String(a);
    node.style.transform = `translateY(${((1 - a) * 10).toFixed(1)}px)`;
  }

  // ----- layer visibility + caption + master render -----
  const L = [
    { k: "L1", a: -1, b: 10.6 },
    { k: "L2", a: 9.6, b: 18.4 },
    { k: "L3", a: 17.6, b: 999 },
  ];
  const curStepRef = useRef(-1);
  function stepOf(t: number, steps: ReturnType<typeof buildSteps>) {
    for (let i = steps.length - 1; i >= 0; i--) if (t >= steps[i].s) return i;
    return 0;
  }
  function render(t: number) {
    t = clamp(t, 0, T_END);
    L.forEach((l) => {
      const node = layerRefs.current[l.k];
      if (!node) return;
      let o = seg(t, l.a, l.a + 0.7) * (1 - seg(t, l.b - 0.7, l.b));
      if (l.a < 0) o = 1 - seg(t, l.b - 0.7, l.b);
      node.style.opacity = o.toFixed(3);
      node.style.visibility = o > 0.01 ? "visible" : "hidden";
    });
    bridgeApi.current?.render(t);
    renderNet(t);
    renderAgents(t);
    renderHandoff(t);
    const steps = buildSteps(run);
    const si = stepOf(t, steps);
    if (si !== curStepRef.current) {
      curStepRef.current = si;
      setStepIdx(si);
    }
    steps.forEach((s, k) => {
      const fill = trackFillRefs.current[k];
      if (fill) fill.style.width = seg(t, s.s, s.e) * 100 + "%";
    });
    setTimeLabel(fmt(t) + " / " + fmt(T_END));
  }

  // ----- play/pause loop -----
  const tRef = useRef(0);
  const rafRef = useRef(0);
  const lastTsRef = useRef(0);
  const playingRef = useRef(false);

  function tick(ts: number) {
    if (!playingRef.current) return;
    const dt = Math.min(0.1, (ts - lastTsRef.current) / 1000);
    lastTsRef.current = ts;
    tRef.current += dt;
    if (tRef.current >= T_END) {
      tRef.current = T_END;
      playingRef.current = false;
      setPlaying(false);
      setFinished(true);
    }
    render(tRef.current);
    if (playingRef.current) rafRef.current = requestAnimationFrame(tick);
  }
  function play() {
    if (tRef.current >= T_END) tRef.current = 0;
    playingRef.current = true;
    setPlaying(true);
    setFinished(false);
    lastTsRef.current = performance.now();
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(tick);
  }
  function pause() {
    playingRef.current = false;
    setPlaying(false);
    cancelAnimationFrame(rafRef.current);
  }
  function seekTo(t: number) {
    tRef.current = clamp(t, 0, T_END);
    render(tRef.current);
    if (tRef.current < T_END) setFinished(false);
  }

  // ----- mount: fit, first paint, autoplay unless reduced-motion, resize observer -----
  useEffect(() => {
    bridgeApi.current?.fit();
    render(0);
    const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (!reduce) play();

    let ro: ResizeObserver | undefined;
    if (typeof ResizeObserver !== "undefined" && stageRef.current) {
      ro = new ResizeObserver(() => {
        bridgeApi.current?.fit();
        render(tRef.current);
      });
      ro.observe(stageRef.current);
    }

    function onKeydown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight") seekTo(tRef.current + 5);
      else if (e.key === "ArrowLeft") seekTo(tRef.current - 5);
      else if (e.key === " " && (document.activeElement as HTMLElement)?.tagName !== "BUTTON") {
        e.preventDefault();
        playingRef.current ? pause() : play();
      }
    }
    document.addEventListener("keydown", onKeydown);

    return () => {
      cancelAnimationFrame(rafRef.current);
      document.removeEventListener("keydown", onKeydown);
      ro?.disconnect();
    };
    // run once on mount; `run` updates re-render the SVG scene in its own effect above, the
    // playback loop itself does not need to restart when the loaded numbers change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const steps = buildSteps(run);
  const cur = steps[stepIdx];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="BridgeGuard AI demo animation"
      className="fixed inset-0 z-50 grid place-items-center overflow-auto p-3"
      style={{ background: "rgba(3,10,20,.8)" }}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="w-full overflow-hidden rounded-2xl border"
        style={{
          maxWidth: 1040,
          background: "#07182B",
          color: "#EAF2FB",
          borderColor: "rgba(255,255,255,.13)",
          boxShadow: "0 30px 80px rgba(0,0,0,.5)",
        }}
      >
        <div
          className="flex items-center justify-between gap-2.5 border-b px-4 py-2.5"
          style={{ borderColor: "rgba(255,255,255,.13)" }}
        >
          <span className="inline-flex items-center rounded-[10px] border bg-white px-3 py-1.5" style={{ borderColor: "rgba(255,255,255,.13)" }}>
            <Image src="/logo-icon.png" alt="BridgeGuard AI" width={26} height={26} className="h-[26px] w-auto" />
          </span>
          <button
            ref={closeBtnRef}
            onClick={onClose}
            className="rounded-lg border px-3 py-1.5 text-sm"
            style={{ borderColor: "rgba(255,255,255,.13)", color: "#EAF2FB" }}
          >
            Close ✕
          </button>
        </div>

        <div
          className="flex items-center gap-2 border-b px-4 py-1.5 text-[13px]"
          style={{ background: "rgba(242,178,51,.13)", borderColor: "rgba(242,178,51,.3)", color: "#F7D58A" }}
        >
          <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: "#F2B233" }} />
          {REPLAY_BANNER}
        </div>

        <div
          ref={stageRef}
          className="grid p-4"
          style={{ background: "radial-gradient(120% 90% at 50% 0%, #0F2E52 0%, #07182B 70%)", minHeight: 330 }}
        >
          {/* layer 1: bridge */}
          <div ref={(n) => { layerRefs.current.L1 = n; }} style={{ gridArea: "1/1", minWidth: 0, position: "relative" }}>
            <svg ref={bsvgRef} viewBox="0 130 960 220" role="img" aria-label="A heavy truck crossing a truss bridge with a sensor under the deck" style={{ display: "block", width: "100%", height: "auto" }} />
            <div
              className="mt-1.5 grid items-center gap-2.5 rounded-xl border p-3"
              style={{ gridTemplateColumns: "auto 1fr", background: "#0D2744", borderColor: "rgba(255,255,255,.13)" }}
            >
              <div>
                <div className="mb-1 text-[13px]" style={{ color: "#9DB3CC" }}>Shaking measured by the sensor</div>
                <div className="text-[34px] font-bold leading-none" style={{ fontVariantNumeric: "tabular-nums" }}>
                  {readout.value.toFixed(1)}
                  <small className="ml-1 text-sm font-medium" style={{ color: "#9DB3CC" }}>m/s²</small>
                </div>
              </div>
              <div className="justify-self-end text-right">
                <span
                  className="inline-block whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-bold tracking-wide"
                  style={readout.over ? { background: "rgba(255,90,77,.2)", color: "#FF9A91" } : { background: "rgba(55,179,107,.18)", color: "#7BE0A5" }}
                >
                  {readout.over ? "OVER THE LIMIT" : "NORMAL"}
                </span>
              </div>
              <div className="relative mt-9 h-3 rounded-full" style={{ gridColumn: "1/-1", background: "rgba(255,255,255,.1)" }}>
                <span
                  className="absolute left-0 top-0 block h-full rounded-full"
                  style={{ width: readout.barPct + "%", background: readout.over ? "#FF5A4D" : "#37B36B" }}
                />
                <span className="absolute -top-1.5 -bottom-1.5 w-[2px] bg-white" style={{ left: Math.max(4, Math.min(96, (run.limit / Math.max(4, Math.ceil(run.peak * 1.2))) * 100)) + "%" }}>
                  <span className="absolute -top-[17px] left-1/2 -translate-x-1/2 whitespace-nowrap text-[11px] text-white">
                    Limit {run.limit.toFixed(1)}
                  </span>
                </span>
              </div>
              <div className="mt-2 text-sm" style={{ gridColumn: "1/-1", opacity: readout.peakShown ? 1 : 0 }}>
                Peak <b style={{ color: "#FF9A91" }}>{run.peak.toFixed(1)} m/s²</b> = <b style={{ color: "#FF9A91" }}>{run.ratio.toFixed(1)} times</b> the limit set for this demonstration
              </div>
            </div>
          </div>

          {/* layer 2: network. Stacked vertically below sm (640px) - a horizontal row of 4 cards
              plus 3 fixed-width connectors has no room to shrink into at 390px and was clipping
              the last card; the reference's own stylesheet makes the same switch below 700px. */}
          <div ref={(n) => { layerRefs.current.L2 = n; }} style={{ gridArea: "1/1", minWidth: 0, position: "relative" }}>
            <div className="flex flex-col items-stretch gap-0 py-5.5 sm:flex-row" ref={netRef}>
              {NODES.map((n, k) => (
                <div key={n[0]} className="flex flex-col items-stretch sm:contents">
                  <div
                    ref={(d) => { ndRefs.current[k] = d; }}
                    className="min-w-0 flex-1 rounded-xl border p-3.5 text-center"
                    style={{ background: "#0D2744", borderColor: "rgba(255,255,255,.13)", opacity: 0.35 }}
                  >
                    <h4 className="m-0 text-[15px]">{n[0]}</h4>
                    {engineerDetail && <div className="mt-0.5 text-xs" style={{ color: "#3AA3F0" }}>{n[1]}</div>}
                    <div className="mt-2 min-h-[20px] text-[13px]" style={{ color: "#7BE0A5" }}>✓ {n[2]}</div>
                  </div>
                  {k < NODES.length - 1 && (
                    <div
                      className="relative mx-auto my-1 h-9 w-1 shrink-0 self-center bg-[repeating-linear-gradient(180deg,rgba(255,255,255,.28)_0_6px,transparent_6px_12px)] sm:my-0 sm:h-1 sm:w-[clamp(36px,7vw,90px)] sm:flex-[0_0_clamp(36px,7vw,90px)] sm:bg-[repeating-linear-gradient(90deg,rgba(255,255,255,.28)_0_6px,transparent_6px_12px)]"
                    >
                      <span
                        ref={(b) => { cnFillRefs.current[k] = b; }}
                        className="absolute h-3.5 w-3.5 rounded-full"
                        style={{ top: "0%", left: "50%", marginTop: -7, marginLeft: -7, background: "#7BD0FF", boxShadow: "0 0 14px 4px rgba(58,163,240,.8)", opacity: 0 }}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* layer 3: agents */}
          <div ref={(n) => { layerRefs.current.L3 = n; }} style={{ gridArea: "1/1", minWidth: 0, position: "relative" }}>
            <div className="h-[3px] overflow-hidden rounded-[3px]" style={{ background: "rgba(255,255,255,.1)" }}>
              <div ref={trkRef} className="h-full" style={{ width: 0, background: "linear-gradient(90deg,#3AA3F0,#37B36B)" }} />
            </div>
            <div className="grid grid-cols-2 gap-2.5 pt-4 sm:grid-cols-5" ref={agRef}>
              {AGENTS.map((a, k) => (
                <div
                  key={a.name}
                  ref={(d) => { acRefs.current[k] = d; }}
                  className="relative rounded-xl border p-3"
                  style={{ minWidth: 0, background: "#0D2744", borderColor: "rgba(255,255,255,.13)", opacity: 0.4 }}
                >
                  <div className="flex items-center gap-2 text-[15px] font-bold">
                    <span
                      ref={(s) => { acBadgeRefs.current[k] = s; }}
                      className="grid h-[22px] w-[22px] shrink-0 place-items-center rounded-full text-xs"
                      style={{ background: "rgba(255,255,255,.12)" }}
                    >
                      {k + 1}
                    </span>
                    {a.name}
                  </div>
                  <p className="mt-1.5 text-[13px]" style={{ color: "#9DB3CC" }}>{a.job}</p>
                  {engineerDetail && <div className="mt-1 text-[11px]" style={{ color: "#3AA3F0" }}>{a.technical}</div>}
                  <div ref={(d) => { acOutRefs.current[k] = d; }} className="mt-2.5 text-sm font-semibold" style={{ color: "#7BE0A5", opacity: 0 }}>
                    {k === 2 && (
                      <div className="mb-1.5 h-2 overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,.1)" }}>
                        <span ref={riskFillRef} className="block h-full" style={{ width: 0, background: "linear-gradient(90deg,#F2B233,#FF5A4D)" }} />
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>

            {/* Hand-off card: the pipeline run ends here. No simulated approval in this video -
                the real Approve/Reject lives only on /demo, decided by an actual person. */}
            <div
              ref={handoffRef}
              className="mt-4 flex flex-wrap items-center justify-between gap-3.5 rounded-xl border p-3.5"
              style={{ background: "rgba(55,179,107,.12)", borderColor: "rgba(55,179,107,.45)", opacity: 0 }}
            >
              <div>
                <b className="block text-[17px]">Next, a real engineer decides.</b>
                <span className="text-sm" style={{ color: "#C9D8E8" }}>
                  The system never acts alone. The approval happens on the live page, by a person, not in this video.
                </span>
              </div>
              <button
                onClick={onGoToApproval}
                className="shrink-0 rounded-full px-5 py-2.5 font-bold text-white"
                style={{ background: "#097F37" }}
              >
                Go to the approval page →
              </button>
            </div>
          </div>
        </div>

        <div className="grid min-h-[150px] content-start gap-1.5 border-t px-5 py-4" style={{ borderColor: "rgba(255,255,255,.13)" }}>
          <div className="text-xs font-bold uppercase tracking-wide" style={{ color: "#3AA3F0" }}>Step {stepIdx + 1} of {steps.length}</div>
          <h2 className="m-0 text-xl leading-tight sm:text-2xl">{cur.h}</h2>
          <p className="m-0 max-w-[52em] text-base" style={{ color: "#C9D8E8" }}>{cur.p}</p>
          {engineerDetail && (
            <p className="m-0 mt-1.5 max-w-[56em] border-l-[3px] pl-2.5 text-[13px]" style={{ borderColor: "#3AA3F0", color: "#9DB3CC" }}>
              <b className="mr-1.5 font-bold" style={{ color: "#3AA3F0" }}>For engineers</b>
              {cur.en}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2.5 border-t px-4 py-3.5" style={{ borderColor: "rgba(255,255,255,.13)" }}>
          <button
            onClick={() => (finished ? play() : playing ? pause() : play())}
            aria-label={finished ? "Watch again" : playing ? "Pause" : "Play"}
            className="grid h-10 w-10 shrink-0 place-items-center rounded-full text-white"
            style={{ background: "#0081D3" }}
          >
            {finished ? (
              <svg width={16} height={16} viewBox="0 0 16 16"><path d="M8 2a6 6 0 1 1-5.6 3.8" stroke="#fff" strokeWidth={2} fill="none" strokeLinecap="round" /><path d="M1 1.5v5h5z" fill="#fff" /></svg>
            ) : playing ? (
              <svg width={16} height={16} viewBox="0 0 16 16"><path d="M3 1h4v14H3zM9 1h4v14H9z" fill="#fff" /></svg>
            ) : (
              <svg width={16} height={16} viewBox="0 0 16 16"><path d="M3 1.5l11 6.5-11 6.5z" fill="#fff" /></svg>
            )}
          </button>
          <div className="flex min-w-0 flex-1 gap-1" style={{ flex: "1 1 280px" }}>
            {steps.map((s, k) => (
              <button
                key={s.tag}
                ref={(b) => { sbRefs.current[k] = b; }}
                onClick={() => {
                  seekTo(s.s + 0.01);
                  if (!playingRef.current) play();
                }}
                aria-label={`Go to step ${k + 1}: ${s.tag}`}
                className="min-w-0 border-0 bg-transparent p-0 text-left text-xs"
                style={{ flex: `${s.e - s.s} 1 0`, color: k === stepIdx ? "#fff" : "#9DB3CC" }}
              >
                <span className="mb-1 block h-1.5 overflow-hidden rounded-[3px]" style={{ background: "rgba(255,255,255,.14)" }}>
                  <span ref={(i) => { trackFillRefs.current[k] = i; }} className="block h-full" style={{ width: 0, background: "#3AA3F0" }} />
                </span>
                <span className="block overflow-hidden text-ellipsis whitespace-nowrap">{k + 1} {s.tag}</span>
              </button>
            ))}
          </div>
          <span className="min-w-[74px] text-right text-[13px]" style={{ color: "#9DB3CC", fontVariantNumeric: "tabular-nums" }}>
            {timeLabel}
          </span>
          <button
            onClick={() => setEngineerDetail((v) => !v)}
            aria-pressed={engineerDetail}
            className="flex items-center gap-2 border-0 bg-transparent p-1 text-[13px]"
            style={{ color: "#EAF2FB" }}
          >
            <span className="relative block h-5 w-[34px] rounded-full" style={{ background: engineerDetail ? "#3AA3F0" : "rgba(255,255,255,.2)" }}>
              <span
                className="absolute top-[3px] h-3.5 w-3.5 rounded-full bg-white transition-[left]"
                style={{ left: engineerDetail ? 17 : 3 }}
              />
            </span>
            Engineer detail
          </button>
        </div>
      </div>
    </div>
  );
}
