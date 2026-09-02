import { AGENT_PIPELINE } from "@/lib/data";

const ICONS = ["📡", "🧹", "🧠", "🚨", "📄"];

export default function AgentsPage() {
  return (
    <div className="space-y-12">
      <section className="rounded-3xl bg-gradient-to-br from-indigo-900 via-slate-800 to-slate-900 px-6 py-12 text-white shadow-2xl shadow-slate-900/20 md:px-10 md:py-16">
        <h1 className="text-4xl font-extrabold tracking-tight md:text-5xl">
          AI Agent Pipeline
        </h1>
        <p className="mt-4 max-w-2xl text-lg text-slate-300">
          Five autonomous agents work in sequence to turn raw sensor data into
          trusted, human-reviewable engineering decisions for Sindh&apos;s bridges.
        </p>
      </section>

      <section className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
        {AGENT_PIPELINE.map((agent, index) => (
          <div
            key={agent.name}
            className="group relative overflow-hidden rounded-3xl border border-slate-200 bg-white p-6 shadow-sm card-hover"
          >
            <div className="absolute -right-6 -top-6 h-24 w-24 rounded-full bg-gradient-to-br from-sky-400/20 to-indigo-500/20 blur-2xl transition group-hover:scale-150" />
            <div className="relative">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-sky-500 to-indigo-600 text-xl text-white shadow-lg shadow-sky-500/25">
                {ICONS[index]}
              </div>
              <div className="mt-4 flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-100 text-xs font-bold text-slate-500">
                  {index + 1}
                </span>
                <h2 className="text-lg font-bold text-slate-900">{agent.name}</h2>
              </div>
              <p className="mt-3 leading-relaxed text-slate-600">{agent.role}</p>
            </div>
          </div>
        ))}
      </section>

      <section className="rounded-3xl border border-slate-200 bg-white p-8 shadow-sm">
        <div className="flex flex-col gap-6 md:flex-row md:items-center">
          <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-rose-100 text-3xl text-rose-600">
            🛡️
          </div>
          <div>
            <h2 className="text-2xl font-bold text-slate-900">Safety-first design</h2>
            <p className="mt-2 max-w-3xl text-slate-600">
              No agent can recommend bridge closure, dispatch emergency services,
              or publish a report without explicit human approval. Risk scores and
              alerts are always recommendations — never autonomous actions.
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
