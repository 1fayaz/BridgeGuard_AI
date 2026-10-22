"use client";

/** Renders the real downsampled acceleration time-series as a continuously-scrolling strip
 * chart (seismograph style) - genuine recorded values, not a placeholder animation. The path
 * is drawn twice back-to-back and scrolled with a seamless CSS loop; no chart library, no
 * resize-observer bugs. */
export default function ResearchWaveform({
  values,
  color,
  height = 64,
}: {
  values: number[];
  color: string;
  height?: number;
}) {
  if (values.length < 2) return null;

  const width = 600;
  const max = Math.max(...values.map((v) => Math.abs(v)), 1e-6);
  const toY = (v: number) => height / 2 - (v / max) * (height / 2 - 4);
  const step = width / (values.length - 1);

  const path = values.map((v, i) => `${i === 0 ? "M" : "L"}${(i * step).toFixed(2)} ${toY(v).toFixed(2)}`).join(" ");

  return (
    <div className="overflow-hidden rounded-lg" style={{ height, background: "#F1F5F9" }}>
      <svg
        viewBox={`0 0 ${width * 2} ${height}`}
        preserveAspectRatio="none"
        className="research-waveform-scroll"
        style={{ display: "block", width: "200%", height: "100%" }}
      >
        <path d={path} fill="none" stroke={color} strokeWidth={1.4} />
        <path d={path} fill="none" stroke={color} strokeWidth={1.4} transform={`translate(${width},0)`} />
      </svg>
      <style jsx>{`
        .research-waveform-scroll {
          animation: research-waveform-scroll 14s linear infinite;
        }
        @keyframes research-waveform-scroll {
          from {
            transform: translateX(0);
          }
          to {
            transform: translateX(-50%);
          }
        }
      `}</style>
    </div>
  );
}
