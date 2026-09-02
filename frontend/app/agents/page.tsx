import { AGENT_PIPELINE } from "@/lib/data";

export default function AgentsPage() {
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">AI Agent Pipeline</h1>
        <p className="mt-2 text-slate-600">
          BridgeGuard uses five autonomous agents, each responsible for one stage
          of the sensor-to-decision pipeline.
        </p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {AGENT_PIPELINE.map((agent, index) => (
          <div
            key={agent.name}
            className="rounded-xl border border-slate-200 bg-white p-6"
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-sky-100 text-sky-700 font-bold">
              {index + 1}
            </div>
            <h2 className="mt-4 text-lg font-semibold text-slate-900">
              {agent.name}
            </h2>
            <p className="mt-2 text-slate-600">{agent.role}</p>
          </div>
        ))}
      </div>

      <div className="rounded-xl border border-slate-200 bg-slate-900 p-6 text-white">
        <h2 className="text-xl font-semibold">Safety-first design</h2>
        <p className="mt-2 text-slate-300">
          No agent can close a bridge or dispatch emergency services without
          explicit human approval. Risk scores and alerts are recommendations,
          not autonomous actions.
        </p>
      </div>
    </div>
  );
}
