import { AlertCircle, Cpu, MessageSquareWarning, UserCheck, UserX } from "lucide-react";
import type { RiskStatus } from "../types";
import StatusBadge from "./StatusBadge";

interface ThreatBreakdownProps {
  acousticScore: number;
  intentScore: number;
  identityMismatch?: number | null;
  speakerSimilarity?: number | null;
  rationale: string[];
  status: RiskStatus;
}

interface SignalVectorProps {
  label: string;
  sublabel: string;
  value: number; // 0 to 1
  icon: React.ReactNode;
  weightLabel?: string;
  formatPercent?: boolean;
}

function SignalVector({
  label,
  sublabel,
  value,
  icon,
  weightLabel,
  formatPercent = true,
}: SignalVectorProps) {
  const pct = Math.min(100, Math.max(0, Math.round(value * 100)));
  const tone =
    pct >= 70
      ? { text: "text-danger", bg: "bg-danger", border: "border-danger/30" }
      : pct >= 40
        ? { text: "text-warn", bg: "bg-warn", border: "border-warn/30" }
        : { text: "text-safe", bg: "bg-safe", border: "border-safe/30" };

  return (
    <div className="rounded-xl border border-ink-700/40 bg-ink-850/60 p-3.5 transition-colors hover:border-ink-600">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <div className="rounded-lg bg-ink-800 p-1.5 text-paper-dim">{icon}</div>
          <div>
            <p className="text-xs font-semibold text-paper-bright">{label}</p>
            <p className="text-[11px] text-paper-muted">{sublabel}</p>
          </div>
        </div>
        <div className="text-right">
          <span className={`tabular font-mono text-sm font-bold ${tone.text}`}>
            {formatPercent ? `${pct}%` : pct}
          </span>
          {weightLabel && (
            <span className="block font-mono text-[10px] text-paper-muted">{weightLabel}</span>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mt-3 h-2 w-full rounded-full bg-ink-800 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ease-out ${tone.bg}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function ThreatBreakdown({
  acousticScore,
  intentScore,
  identityMismatch,
  speakerSimilarity,
  rationale,
  status,
}: ThreatBreakdownProps) {
  const badgeVariant =
    status === "LOCK_VERIFY" ? "danger" : status === "WARN" ? "warn" : "safe";

  return (
    <section className="rounded-2xl border border-ink-700/40 bg-ink-900/90 p-5 shadow-panel flex h-full flex-col justify-between">
      <div>
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-ink-700/40 pb-3.5">
          <div>
            <p className="eyebrow text-signal">Vector Decomposition</p>
            <h2 className="mt-0.5 text-sm font-bold text-paper-bright">
              Signal Intelligence &amp; Multi-Vector Fusion
            </h2>
          </div>
          <StatusBadge
            label={status.replace("_", " ")}
            variant={badgeVariant}
            pulse={status === "LOCK_VERIFY"}
            size="sm"
          />
        </div>

        {/* Signal Vectors */}
        <div className="mt-4 space-y-2.5">
          <SignalVector
            label="Acoustic Anti-Spoof (MMS-300M)"
            sublabel="Vocoder artifacts & synthetic phase analysis"
            value={acousticScore}
            icon={<Cpu size={16} />}
            weightLabel="Weight: 50%"
          />

          <SignalVector
            label="Conversational Intent &amp; Urgency"
            sublabel="Coercion tokens & unauthorized transfer pressure"
            value={intentScore}
            icon={<MessageSquareWarning size={16} />}
            weightLabel="Weight: 30%"
          />

          {identityMismatch != null ? (
            <SignalVector
              label="Speaker Identity Divergence"
              sublabel={
                speakerSimilarity != null
                  ? `Voiceprint similarity: ${Math.round(speakerSimilarity * 100)}%`
                  : "Enrolled profile baseline"
              }
              value={identityMismatch}
              icon={identityMismatch >= 0.7 ? <UserX size={16} /> : <UserCheck size={16} />}
              weightLabel="Weight: 20%"
            />
          ) : (
            <SignalVector
              label="Speaker Biometric Match"
              sublabel="Neutral (unregistered baseline profile)"
              value={0}
              icon={<UserCheck size={16} />}
              weightLabel="Neutral"
            />
          )}
        </div>
      </div>

      {/* Decision Rationale */}
      <div className="mt-5 border-t border-ink-700/40 pt-3.5">
        <div className="flex items-center justify-between text-xs text-paper-dim">
          <span className="font-semibold uppercase tracking-wider text-[10px]">
            Audit Findings &amp; Rationale
          </span>
          <span className="font-mono text-[10px] text-paper-muted">{rationale.length} detected</span>
        </div>

        {rationale.length === 0 ? (
          <p className="mt-2 text-xs text-paper-muted leading-relaxed">
            Nominal acoustics. Zero threat keywords or spoof characteristics detected in the active rolling window.
          </p>
        ) : (
          <div className="mt-2.5 space-y-1.5">
            {rationale.map((r, i) => (
              <div
                key={`${r}-${i}`}
                className="flex items-start gap-2.5 rounded-lg border border-danger/25 bg-danger-bg px-3 py-2 text-xs leading-relaxed text-paper-bright"
              >
                <AlertCircle size={14} className="shrink-0 text-danger mt-0.5" />
                <span>{r}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
