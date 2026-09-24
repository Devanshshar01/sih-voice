import type { RiskStatus } from "../types";

interface TrustGaugeProps {
  score: number;
  status: RiskStatus;
}

const STATUS_CONFIG: Record<
  RiskStatus,
  {
    label: string;
    description: string;
    color: string;
    textColor: string;
    badgeBg: string;
    badgeBorder: string;
  }
> = {
  ALLOW: {
    label: "AUTHENTIC VOICE",
    description: "Acoustic, speaker, and intent features within nominal policy tolerance.",
    color: "#D4D4D4",
    textColor: "text-safe",
    badgeBg: "bg-safe-bg",
    badgeBorder: "border-safe/30",
  },
  WARN: {
    label: "SUSPICIOUS DYNAMICS",
    description: "Acoustic irregularities or conversational urgency detected.",
    color: "#8E8E8E",
    textColor: "text-warn",
    badgeBg: "bg-warn-bg",
    badgeBorder: "border-warn/30",
  },
  LOCK_VERIFY: {
    label: "CRITICAL THREAT: CLONE DETECTED",
    description: "High-confidence synthetic audio signature or coercive transfer pressure.",
    color: "#FFFFFF",
    textColor: "text-danger",
    badgeBg: "bg-danger-bg",
    badgeBorder: "border-danger/40",
  },
};

export default function TrustGauge({ score, status }: TrustGaugeProps) {
  const roundedScore = Math.round(Math.max(0, Math.min(100, score)));
  const config = STATUS_CONFIG[status];

  return (
    <div className="flex flex-col items-center justify-center text-center p-2">
      {/* Risk Level Badge */}
      <div
        className={`inline-flex items-center gap-2 rounded-full border px-3.5 py-1 text-xs font-semibold uppercase tracking-wider ${config.badgeBg} ${config.badgeBorder} ${config.textColor}`}
      >
        <span
          className="h-2 w-2 rounded-full animate-pulse"
          style={{ backgroundColor: config.color }}
        />
        <span>{config.label}</span>
      </div>

      {/* Hero Numerical Risk Readout */}
      <div className="mt-3 flex items-baseline justify-center gap-2">
        <span
          className="font-sans text-6xl sm:text-7xl font-extrabold tracking-tight tabular"
          style={{ color: config.color }}
        >
          {roundedScore}
        </span>
        <span className="text-sm sm:text-base font-semibold text-paper-muted uppercase tracking-widest">
          / 100 FUSED RISK
        </span>
      </div>

      {/* Contextual Rationale Description */}
      <p className="mt-2 max-w-sm text-xs sm:text-sm text-paper-dim leading-relaxed">
        {config.description}
      </p>

      {/* Horizontal Threat Spectrum Bar */}
      <div className="mt-5 w-full max-w-md">
        {/* Spectrum Bar Segments */}
        <div className="relative h-2.5 w-full overflow-hidden rounded-full bg-ink-800 flex">
          {/* Safe Zone (0-40) */}
          <div className="h-full w-[40%] bg-gradient-to-r from-paper-dim/20 to-paper-dim/40" />
          {/* Warn Zone (40-70) */}
          <div className="h-full w-[30%] bg-gradient-to-r from-paper-dim/50 to-paper-dim/75" />
          {/* Lock Zone (70-100) */}
          <div className="h-full w-[30%] bg-gradient-to-r from-paper/80 to-paper-bright" />

          {/* Current Score Marker Line */}
          <div
            className="absolute top-0 bottom-0 w-1 bg-white shadow-[0_0_8px_white] transition-all duration-500 ease-out"
            style={{ left: `calc(${roundedScore}% - 2px)` }}
          />
        </div>

        {/* Spectrum Scale Labels */}
        <div className="mt-1.5 flex justify-between text-[10px] font-mono text-paper-muted">
          <span>0 (Safe)</span>
          <span className="text-warn">40 (Warning)</span>
          <span className="text-danger">70 (Lockdown)</span>
          <span>100</span>
        </div>
      </div>
    </div>
  );
}
