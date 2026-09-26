import { useState } from "react";
import { Activity } from "lucide-react";
import type { RiskTelemetry } from "../types";

interface RiskTimelineProps {
  points: RiskTelemetry[];
}

function statusLabel(status: RiskTelemetry["status"]) {
  if (status === "LOCK_VERIFY") return "LOCKED";
  if (status === "WARN") return "SUSPICIOUS";
  return "SAFE";
}

export default function RiskTimeline({ points }: RiskTimelineProps) {
  const visible = points.slice(-32);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const max = Math.max(100, ...visible.map((p) => p.risk_score));
  const peakScore = visible.reduce((m, p) => Math.max(m, p.risk_score), 0);

  const hoveredPoint = hoveredIndex !== null ? visible[hoveredIndex] : null;

  return (
    <section className="rounded-3xl border border-forensic-border bg-forensic-panel/70 p-6 shadow-panel backdrop-blur" aria-labelledby="risk-timeline-heading">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-forensic-border pb-3.5">
        <div>
          <p className="eyebrow text-forensic-accent">Chronological Evolution</p>
          <h2 id="risk-timeline-heading" className="mt-0.5 text-sm font-bold text-forensic-text">
            Decision &amp; Risk Trajectory
          </h2>
        </div>
        <div className="flex items-center gap-3 font-mono text-[11px] text-forensic-muted">
          <span>
            Frames: <span className="text-forensic-text font-bold">{visible.length}</span>
          </span>
          <span className="text-forensic-muted/50">·</span>
          <span>
            Peak:{" "}
            <span
              className={
                peakScore >= 70
                  ? "text-danger font-bold"
                  : peakScore >= 40
                    ? "text-warn font-bold"
                    : "text-safe font-bold"
              }
            >
              {Math.round(peakScore)}%
            </span>
          </span>
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="flex h-28 flex-col items-center justify-center text-center">
          <Activity size={20} className="text-forensic-muted animate-pulse" />
          <p className="mt-2 font-mono text-xs text-forensic-muted">Awaiting first 4-second audio window...</p>
        </div>
      ) : (
        <div className="relative mt-4">
          {/* Threshold reference lines */}
          <div className="pointer-events-none absolute inset-x-0 top-[30%] h-px border-t border-dashed border-danger/40 z-10">
            <span className="absolute right-0 -top-3 font-mono text-[9px] text-danger font-bold">
              Lock Policy (70%)
            </span>
          </div>
          <div className="pointer-events-none absolute inset-x-0 top-[60%] h-px border-t border-dashed border-warn/40 z-10">
            <span className="absolute right-0 -top-3 font-mono text-[9px] text-warn font-bold">
              Warning Policy (40%)
            </span>
          </div>

          {/* Timeline Bar Chart */}
          <div
            className="flex h-28 items-end gap-1.5 border-b border-forensic-border pb-1 pt-2"
            aria-label="Risk score over time"
          >
            {visible.map((point, index) => {
              const height = Math.max(6, Math.min(100, Math.round((point.risk_score / max) * 100)));
              const color =
                point.status === "LOCK_VERIFY"
                  ? "bg-danger"
                  : point.status === "WARN"
                    ? "bg-warn"
                    : "bg-safe";

              const isHovered = hoveredIndex === index;

              return (
                <div
                  key={`${point.timestamp}-${index}`}
                  onMouseEnter={() => setHoveredIndex(index)}
                  onMouseLeave={() => setHoveredIndex(null)}
                  className="group relative flex h-full flex-1 items-end cursor-pointer"
                >
                  <div
                    className={`w-full rounded-t-sm ${color} transition-all duration-300 ${
                      isHovered ? "opacity-100 ring-2 ring-white scale-y-105" : "opacity-85"
                    }`}
                    style={{ height: `${height}%` }}
                  />
                </div>
              );
            })}
          </div>

          {/* Hover Details readout */}
          {hoveredPoint ? (
            <div className="mt-2.5 flex items-center justify-between rounded-xl border border-forensic-border bg-forensic-surface px-3.5 py-2 text-xs font-mono">
              <span className="text-forensic-muted">
                Score:{" "}
                <span className="font-bold text-forensic-text">
                  {Math.round(hoveredPoint.risk_score)}%
                </span>{" "}
                ({statusLabel(hoveredPoint.status)})
              </span>
              <span className="text-forensic-muted">
                Acoustic: {Math.round(hoveredPoint.acoustic_score * 100)}% · Intent:{" "}
                {Math.round(hoveredPoint.intent_score * 100)}%
              </span>
            </div>
          ) : (
            <div className="mt-2.5 flex items-center justify-between text-[11px] text-forensic-muted">
              <div className="flex items-center gap-3.5 font-sans">
                <span className="flex items-center gap-1.5 font-bold">
                  <span className="h-2 w-2 rounded-full bg-safe" /> Safe (&lt;40%)
                </span>
                <span className="flex items-center gap-1.5 font-bold">
                  <span className="h-2 w-2 rounded-full bg-warn" /> Suspicious (40-70%)
                </span>
                <span className="flex items-center gap-1.5 font-bold">
                  <span className="h-2 w-2 rounded-full bg-danger" /> Critical Lock (&gt;70%)
                </span>
              </div>
              <span className="font-mono text-[10px] text-forensic-muted hidden sm:inline">Hover bar for details</span>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export { statusLabel };

