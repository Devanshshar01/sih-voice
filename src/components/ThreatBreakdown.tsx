import { AlertCircle, Cpu, MessageSquareWarning, UserCheck, UserX, ArrowDown } from "lucide-react";
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
    <div className="rounded-2xl border border-forensic-border bg-forensic-surface/60 p-3.5 transition-all hover:border-forensic-accent/40">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <div className="rounded-xl border border-forensic-border bg-forensic-panel p-2 text-forensic-accent">{icon}</div>
          <div>
            <p className="text-xs font-bold text-forensic-text">{label}</p>
            <p className="text-[11px] text-forensic-muted">{sublabel}</p>
          </div>
        </div>
        <div className="text-right">
          <span className={`tabular font-mono text-sm font-extrabold ${tone.text}`}>
            {formatPercent ? `${pct}%` : pct}
          </span>
          {weightLabel && (
            <span className="block font-mono text-[10px] text-forensic-muted">{weightLabel}</span>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mt-3 h-2 w-full rounded-full bg-forensic-panel overflow-hidden border border-forensic-border/40">
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
    <section className="rounded-3xl border border-forensic-border bg-forensic-panel/70 p-6 shadow-panel backdrop-blur flex h-full flex-col justify-between">
      <div>
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-forensic-border pb-3.5">
          <div>
            <p className="eyebrow text-forensic-accent">Three-Signal Intelligence</p>
            <h2 className="mt-0.5 text-sm font-bold text-forensic-text">
              Multi-Vector Threat Fusion Model
            </h2>
          </div>
          <StatusBadge
            label={status.replace("_", " ")}
            variant={badgeVariant}
            pulse={status === "LOCK_VERIFY"}
            size="sm"
          />
        </div>

        {/* 3-Signal Intelligence Pipeline Flow */}
        <div className="mt-4 space-y-2.5">
          {/* Signal 1: Anti-Spoof */}
          <SignalVector
            label="1. Anti-Spoof (MMS-300M)"
            sublabel="Vocoder artifacts & synthetic phase analysis"
            value={acousticScore}
            icon={<Cpu size={16} />}
            weightLabel="Weight: 50%"
          />

          {/* Signal 2: Speaker Identity */}
          {identityMismatch != null ? (
            <SignalVector
              label="2. Speaker Identity (ECAPA)"
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
              label="2. Speaker Identity (ECAPA)"
              sublabel="Neutral baseline (unregistered caller)"
              value={0}
              icon={<UserCheck size={16} />}
              weightLabel="Neutral"
            />
          )}

          {/* Signal 3: Context / Intent */}
          <SignalVector
            label="3. Context &amp; Intent (Multilingual ASR)"
            sublabel="Extortion tokens & unauthorized transfer pressure"
            value={intentScore}
            icon={<MessageSquareWarning size={16} />}
            weightLabel="Weight: 30%"
          />
        </div>

        {/* Fusion Arrow & Equation visualizer */}
        <div className="mt-4 rounded-2xl border border-forensic-border bg-forensic-surface/40 p-3 flex flex-col items-center justify-center text-center font-mono text-[11px] text-forensic-muted">
          <div className="flex items-center gap-1.5 font-bold text-forensic-text">
            <span>ANTI-SPOOF</span>
            <span>+</span>
            <span>IDENTITY</span>
            <span>+</span>
            <span>CONTEXT</span>
          </div>
          <ArrowDown size={14} className="text-forensic-accent my-1 animate-pulse" />
          <div className="flex items-center gap-2">
            <span className="text-forensic-accent font-bold">FUSED RISK INDEX</span>
            <span>→</span>
            <span className={`font-extrabold ${status === "LOCK_VERIFY" ? "text-danger" : status === "WARN" ? "text-warn" : "text-safe"}`}>
              POLICY DECISION ({status})
            </span>
          </div>
        </div>
      </div>

      {/* Decision Rationale */}
      <div className="mt-5 border-t border-forensic-border pt-4">
        <div className="flex items-center justify-between text-xs text-forensic-muted">
          <span className="font-bold uppercase tracking-wider text-[10px] text-forensic-muted">
            Audit Findings &amp; Rationale
          </span>
          <span className="font-mono text-[10px] text-forensic-muted">{rationale.length} detected</span>
        </div>

        {rationale.length === 0 ? (
          <p className="mt-2 text-xs text-forensic-muted leading-relaxed font-sans">
            Nominal acoustics. Zero threat keywords or spoof characteristics detected in the active rolling window.
          </p>
        ) : (
          <div className="mt-2.5 space-y-1.5">
            {rationale.map((r, i) => (
              <div
                key={`${r}-${i}`}
                className="flex items-start gap-2.5 rounded-xl border border-danger/30 bg-danger-bg px-3 py-2 text-xs leading-relaxed text-forensic-text"
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

