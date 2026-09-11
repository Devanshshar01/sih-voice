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
  const visible = points.slice(-24);
  const max = Math.max(1, ...visible.map((point) => point.risk_score));

  return (
    <section className="panel p-4 sm:p-5" aria-labelledby="risk-timeline-heading">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="eyebrow">Decision history</p>
          <h2 id="risk-timeline-heading" className="mt-1 text-sm font-medium text-paper">Risk timeline</h2>
        </div>
        <span className="font-mono text-[10px] text-mute">{visible.length} frames</span>
      </div>
      {visible.length === 0 ? (
        <p className="mt-6 text-sm text-mute">Waiting for the first risk frame.</p>
      ) : (
        <div className="mt-5 flex h-28 items-end gap-1 border-b border-ink-600 pb-0" aria-label="Risk score over time">
          {visible.map((point, index) => {
            const height = Math.max(8, Math.round((point.risk_score / max) * 100));
            const color = point.status === "LOCK_VERIFY" ? "bg-danger" : point.status === "WARN" ? "bg-warn" : "bg-safe";
            return (
              <div key={`${point.timestamp}-${index}`} className="group relative flex h-full flex-1 items-end" title={`${statusLabel(point.status)} · ${Math.round(point.risk_score * 100)}%`}>
                <div className={`w-full ${color} opacity-85 transition-all duration-500 group-hover:opacity-100`} style={{ height: `${height}%` }} />
              </div>
            );
          })}
        </div>
      )}
      <div className="mt-3 flex items-center gap-4 text-[10px] uppercase tracking-[0.12em] text-mute">
        <span><i className="mr-1 inline-block h-1.5 w-1.5 bg-safe" />Safe</span>
        <span><i className="mr-1 inline-block h-1.5 w-1.5 bg-warn" />Suspicious</span>
        <span><i className="mr-1 inline-block h-1.5 w-1.5 bg-danger" />Locked</span>
      </div>
    </section>
  );
}

export { statusLabel };

