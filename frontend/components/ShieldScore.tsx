import { SEVERITY_CONFIG, type Severity } from "@/lib/data";

/** The shield-shaped risk-score badge used across Overview, Bridge detail, and the map
 * (design: Main.dc.html's shield-tile SVG). Severity drives colour and ink contrast — never
 * hardcode a colour here, always go through SEVERITY_CONFIG so UNKNOWN can never render green. */
export default function ShieldScore({
  severity,
  score,
  size = 64,
}: {
  severity: Severity;
  score: number | null;
  size?: number;
}) {
  const cfg = SEVERITY_CONFIG[severity];
  const height = Math.round(size * 1.125);
  const ink = cfg.shieldTextDark ? "#2B1D00" : "#FFFFFF";
  return (
    <svg
      width={size}
      height={height}
      viewBox="0 0 64 72"
      role="img"
      aria-label={score === null ? `Risk score unknown, ${cfg.label}` : `Risk score ${score}, ${cfg.label}`}
    >
      <path
        d="M32 3 L59 13 V35 C59 52 47 63 32 69 C17 63 5 52 5 35 V13 Z"
        fill={cfg.bar}
      />
      <path
        d="M32 9 L53 17 V35 C53 48 44 57 32 62 C20 57 11 48 11 35 V17 Z"
        fill="none"
        stroke={ink}
        strokeOpacity={0.5}
        strokeWidth={1.6}
      />
      {score !== null && (
        <text
          x="32"
          y="43"
          textAnchor="middle"
          fontFamily="Montserrat, sans-serif"
          fontWeight={800}
          fontSize={22}
          fill={ink}
        >
          {score}
        </text>
      )}
    </svg>
  );
}
