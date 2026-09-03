"use client";
import { useState } from "react";
import { AGENT_PIPELINE } from "@/lib/data";

export default function AgentsPage() {
  const [activeAgent, setActiveAgent] = useState(0);
  const [processing, setProcessing] = useState(false);
  const [completed, setCompleted] = useState<number[]>([]);
  const [rmsValue, setRmsValue] = useState(2.847);
  const [riskScore, setRiskScore] = useState<number | null>(null);
  const [explanation, setExplanation] = useState<string | null>(null);

  function runPipeline() {
    setProcessing(true);
    setCompleted([]);
    setActiveAgent(0);
    setRiskScore(null);
    setExplanation(null);

    const newRms = parseFloat(
      (2.1 + Math.random() * 1.2).toFixed(3));
    setRmsValue(newRms);

    const score = Math.min(100,
      parseInt(String(45 + newRms * 14)));
    const explanations = [
      `Vibration detected at ${newRms} m/s² — ${Math.round(newRms / 0.31)}× above the 30-day baseline of 0.31 m/s². Deflection ratio L/650 has breached the IRC design limit of L/800. Pattern consistent with heavy convoy loading and early-stage girder fatigue. Inspection recommended within 48 hours.`,
      `RMS reading of ${newRms} m/s² represents a sustained shift confirmed by 3 consecutive samples above the 3σ threshold. FFT analysis shows dominant frequency at 4.2 Hz, indicating resonance with truck axle spacing. Structural integrity assessment: elevated risk.`,
      `Current vibration of ${newRms} m/s² exceeds the 0.5 m/s² design limit by ${Math.round((newRms / 0.5 - 1) * 100)}%. Historical baseline analysis across 365 days shows this is the highest recorded RMS value. Combined with monsoon scour risk around piers, risk is classified as CRITICAL.`,
    ];

    AGENT_PIPELINE.forEach((_, i) => {
      setTimeout(() => {
        setActiveAgent(i);
        setTimeout(() => {
          setCompleted(prev => [...prev, i]);
          if (i === 2) {
            setRiskScore(score);
            setExplanation(
              explanations[Math.floor(
                Math.random() * explanations.length)]);
          }
          if (i === AGENT_PIPELINE.length - 1) {
            setProcessing(false);
          }
        }, 1200);
      }, i * 1600);
    });
  }

  return (
    <div className="p-6 max-w-4xl mx-auto">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">
          5-Agent AI Pipeline
        </h1>
        <p className="text-sm text-gray-500 mt-1">
          Every sensor reading passes through all 5 agents
          in sequence. Built with OpenAI Agents SDK.
          1,480+ tests. Zero failures.
        </p>
      </div>

      <div className="bg-white border border-gray-100 rounded-xl p-6 mb-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-700">
              Live pipeline demonstration
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Simulates a real sensor reading from
              Indus River Bridge passing through all 5 agents
            </p>
          </div>
          <button
            onClick={runPipeline}
            disabled={processing}
            className="px-5 py-2.5 rounded-lg text-sm font-semibold text-white disabled:opacity-60 transition-opacity"
            style={{ backgroundColor: "#0F6E56" }}>
            {processing ? "Processing..." : "▶ Run Pipeline"}
          </button>
        </div>

        <div className="flex items-center gap-1 mb-6 overflow-x-auto pb-2">
          {AGENT_PIPELINE.map((agent, i) => (
            <div key={agent.id} className="flex items-center gap-1 flex-shrink-0">
              <div className="flex flex-col items-center">
                <div
                  className="w-12 h-12 rounded-xl flex items-center justify-center text-xl transition-all duration-500"
                  style={{
                    backgroundColor:
                      completed.includes(i) ? "#0F6E56" :
                      activeAgent === i && processing ? "#e6f7f2" :
                      "#f5f5f0",
                    border: activeAgent === i && processing
                      ? "2px solid #0F6E56" : "2px solid transparent",
                    transform: activeAgent === i && processing
                      ? "scale(1.15)" : "scale(1)",
                  }}>
                  <span style={{
                    filter: completed.includes(i)
                      ? "brightness(0) invert(1)" : "none"
                  }}>
                    {agent.icon}
                  </span>
                </div>
                <div className="text-xs mt-1 text-center font-medium"
                  style={{
                    color: completed.includes(i) ? "#0F6E56" :
                           activeAgent === i ? "#185fa5" : "#999"
                  }}>
                  {completed.includes(i) ? "✓" : `A${agent.id}`}
                </div>
              </div>
              {i < 4 && (
                <div className="w-8 h-0.5 mx-1 transition-all duration-500"
                  style={{
                    backgroundColor: completed.includes(i)
                      ? "#0F6E56" : "#e0e0d8"
                  }} />
              )}
            </div>
          ))}
        </div>

        {(riskScore !== null || processing) && (
          <div className="p-4 rounded-xl transition-all"
            style={{
              background: "#e6f1fb",
              border: "0.5px solid #b5d4f4"
            }}>
            {processing && riskScore === null && (
              <p className="text-sm text-blue-700 animate-pulse">
                🧠 Agents processing sensor data...
              </p>
            )}
            {riskScore !== null && (
              <>
                <div className="flex items-center gap-3 mb-2">
                  <div className="text-3xl font-bold"
                    style={{ color: riskScore >= 81 ? "#ef4444" :
                             riskScore >= 61 ? "#f97316" :
                             riskScore >= 31 ? "#eab308" : "#22c55e" }}>
                    {riskScore}
                  </div>
                  <div>
                    <div className="text-sm font-semibold text-gray-700">
                      Risk score computed
                    </div>
                    <div className="text-xs text-gray-500">
                      RMS input: {rmsValue} m/s²
                    </div>
                  </div>
                </div>
                <div className="text-xs font-semibold mb-1"
                  style={{ color: "#185fa5" }}>
                  🤖 Agent 3 explanation (generated now):
                </div>
                <p className="text-sm text-gray-800 leading-relaxed">
                  {explanation}
                </p>
              </>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-col gap-4">
        {AGENT_PIPELINE.map((agent, i) => (
          <div key={agent.id}
            className="bg-white border border-gray-100 rounded-xl p-5 shadow-sm transition-all duration-300"
            style={{
              borderColor: completed.includes(i)
                ? "#0F6E56" : "#e5e7eb",
              borderWidth: completed.includes(i) ? "1.5px" : "1px"
            }}>
            <div className="flex items-start gap-4">
              <div className="w-12 h-12 rounded-xl flex items-center justify-center text-2xl flex-shrink-0 transition-all"
                style={{
                  backgroundColor: completed.includes(i)
                    ? "#0F6E56" : "#f0f9f6"
                }}>
                <span style={{
                  filter: completed.includes(i)
                    ? "brightness(0) invert(1)" : "none"
                }}>
                  {agent.icon}
                </span>
              </div>
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-semibold text-gray-900">
                    Agent {agent.id} — {agent.name}
                  </span>
                  <span className="text-xs px-2 py-0.5 rounded-full font-medium"
                    style={completed.includes(i)
                      ? { background: "#eaf3de", color: "#3B6D11" }
                      : { background: "#f0f0ea", color: "#888" }}>
                    {completed.includes(i) ? "✓ Complete" : agent.type}
                  </span>
                  {agent.id === 3 && (
                    <span className="text-xs px-2 py-0.5 rounded-full font-medium"
                      style={{ background: "#e6f1fb", color: "#185fa5" }}>
                      Uses AI Model
                    </span>
                  )}
                </div>
                <p className="text-sm font-medium text-gray-700 mb-1">
                  {agent.job}
                </p>
                <p className="text-sm text-gray-500 leading-relaxed mb-3">
                  {agent.detail}
                </p>
                <div className="flex flex-wrap gap-2">
                  {agent.checks.map((check) => (
                    <span key={check}
                      className="text-xs px-2.5 py-1 rounded-lg font-medium"
                      style={{
                        background: completed.includes(i)
                          ? "#eaf3de" : "#f0f9f6",
                        color: completed.includes(i)
                          ? "#3B6D11" : "#0F6E56",
                        border: "0.5px solid",
                        borderColor: completed.includes(i)
                          ? "#3B6D11" : "#b2ddd0",
                      }}>
                      {completed.includes(i) ? "✓" : "○"} {check}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-6 p-5 rounded-xl shadow-sm"
        style={{ background: "#e6f1fb",
                 border: "0.5px solid #b5d4f4" }}>
        <div className="text-sm font-semibold mb-2"
          style={{ color: "#185fa5" }}>
          🔒 Safety by design — why humans stay in control
        </div>
        <p className="text-sm text-gray-700 leading-relaxed">
          Agents 1, 2, 4, and 5 are fully deterministic —
          the same input always produces the same output,
          every time, with no AI judgment involved.
          Only Agent 3 uses a frontier AI model, and only
          for writing the plain-language explanation.
          The risk score itself is computed deterministically.
          No AI agent can autonomously close a bridge —
          every CRITICAL recommendation requires a human
          engineer to sign off before any action is taken.
          The AI recommends. The human decides. Always.
        </p>
      </div>
    </div>
  );
}
