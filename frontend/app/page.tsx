import Link from "next/link";

const BRIDGES = [
  {
    id: "bridge-indus-khi-hyd",
    name: "Indus River Bridge — KHI-HYD",
    location: "Karachi-Hyderabad Highway, Sindh",
    risk_score: 82,
    severity: "CRITICAL",
    explanation: "Vibration 9× above normal baseline. Heavy truck convoys detected. Scour erosion risk around pier foundations after recent monsoon flooding. Immediate inspection required.",
    chips: [{ label: "Vibration ↑↑", warn: true }, { label: "Scour risk", warn: true }],
  },
  {
    id: "bridge-kotri-01",
    name: "Kotri Bridge",
    location: "Hyderabad, Sindh",
    risk_score: 64,
    severity: "WARNING",
    explanation: "Crack growth detected on main girder. Rate above acceptable threshold. Inspection within 14 days recommended.",
    chips: [{ label: "Crack +0.3mm", warn: true }, { label: "Vibration OK", warn: false }],
  },
  {
    id: "bridge-sukkur-01",
    name: "Sukkur Barrage Bridge",
    location: "Sukkur, Sindh",
    risk_score: 41,
    severity: "WATCH",
    explanation: "Gradual vibration increase over 30-day trend. Still within design limits. Monitor closely.",
    chips: [{ label: "Traffic ↑", warn: false }, { label: "Sensors OK", warn: false }],
  },
  {
    id: "bridge-guddu-01",
    name: "Guddu Barrage Bridge",
    location: "Kashmore, Sindh",
    risk_score: 18,
    severity: "SAFE",
    explanation: "All readings within normal range. No structural concerns. Next review in 30 days.",
    chips: [{ label: "All sensors OK", warn: false }],
  },
];

const badge: Record<string, { bg: string; text: string; label: string }> = {
  CRITICAL: { bg: "#fcebeb", text: "#A32D2D", label: "🔴 Critical" },
  WARNING:  { bg: "#FAECE7", text: "#993C1D", label: "🟠 Warning" },
  WATCH:    { bg: "#faeeda", text: "#854F0B", label: "🟡 Watch" },
  SAFE:     { bg: "#eaf3de", text: "#3B6D11", label: "🟢 Safe" },
};

const barColor: Record<string, string> = {
  CRITICAL: "#ef4444",
  WARNING:  "#f97316",
  WATCH:    "#eab308",
  SAFE:     "#22c55e",
};

const counts = {
  CRITICAL: BRIDGES.filter(b => b.severity === "CRITICAL").length,
  WARNING:  BRIDGES.filter(b => b.severity === "WARNING").length,
  SAFE:     BRIDGES.filter(b => b.severity === "SAFE").length,
};

export default function Page() {
  return (
    <main className="p-6 max-w-4xl mx-auto">
      <div className="mb-5">
        <h1 className="text-xl font-medium text-gray-900">Bridge overview</h1>
        <p className="text-sm text-gray-500 mt-1">
          Sindh Province · {BRIDGES.length} bridges monitored in real time · Last updated just now
        </p>
      </div>

      <div className="grid grid-cols-4 gap-3 mb-5">
        {[
          { label: "Total bridges", value: BRIDGES.length, sub: "Under monitoring", color: "#1a1a18" },
          { label: "Critical", value: counts.CRITICAL, sub: "Immediate action", color: "#ef4444" },
          { label: "Warning", value: counts.WARNING, sub: "Inspection needed", color: "#f97316" },
          { label: "Safe", value: counts.SAFE, sub: "No action needed", color: "#3B6D11" },
        ].map(s => (
          <div key={s.label} className="bg-white border border-gray-100 rounded-xl p-4">
            <div className="text-xs text-gray-500 mb-1">{s.label}</div>
            <div className="text-2xl font-medium" style={{ color: s.color }}>{s.value}</div>
            <div className="text-xs text-gray-400 mt-1">{s.sub}</div>
          </div>
        ))}
      </div>

      {counts.CRITICAL > 0 && (
        <div className="mb-5 p-4 rounded-xl border" style={{ background: "#fcebeb", borderColor: "#ef4444" }}>
          <div className="text-sm font-medium text-red-700">
            ⚠️ {counts.CRITICAL} bridge requires immediate attention
          </div>
          <div className="text-xs text-red-600 mt-1">
            An engineer must review and sign off before the alert can be cleared.
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        {BRIDGES.map(b => {
          const bd = badge[b.severity];
          const bc = barColor[b.severity];
          return (
            <Link
              key={b.id}
              href={`/bridges/${b.id}`}
              className="no-underline block bg-white border border-gray-100 rounded-xl p-5 hover:border-gray-300 transition-colors"
              style={b.severity === "CRITICAL" ? { borderColor: "#ef4444", borderWidth: "1.5px" } : {}}
            >
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="text-sm font-medium text-gray-900">{b.name}</div>
                  <div className="text-xs text-gray-500 mt-1">📍 {b.location}</div>
                </div>
                <span className="text-xs font-medium px-2.5 py-1 rounded-full"
                  style={{ background: bd.bg, color: bd.text }}>
                  {bd.label}
                </span>
              </div>

              <div className="flex items-center gap-3 mb-3">
                <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                  <div className="h-full rounded-full" style={{ width: `${b.risk_score}%`, background: bc }} />
                </div>
                <span className="text-sm font-medium" style={{ color: bc }}>{b.risk_score}/100</span>
              </div>

              <p className="text-xs text-gray-500 leading-relaxed line-clamp-2">{b.explanation}</p>

              <div className="flex gap-2 mt-3">
                {b.chips.map(c => (
                  <span key={c.label} className="text-xs px-2 py-0.5 rounded"
                    style={c.warn
                      ? { background: "#faeeda", color: "#854F0B" }
                      : { background: "#f0f0ea", color: "#666" }}>
                    {c.label}
                  </span>
                ))}
              </div>
            </Link>
          );
        })}
      </div>
    </main>
  );
}