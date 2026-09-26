import { AlertCircle, CheckCircle2, Cpu, MessageSquareWarning, UserCheck, UserX, ArrowDown } from "lucide-react";
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
      ? { text: "text-red-600", bg: "bg-red-500", border: "border-red-200" }
      : pct >= 40
        ? { text: "text-amber-600", bg: "bg-amber-500", border: "border-amber-200" }
        : { text: "text-emerald-600", bg: "bg-emerald-500", border: "border-emerald-200" };

  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50/70 p-3.5 transition-all hover:border-[#7C3AED]/40 hover:bg-slate-50">
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <div className="rounded-xl border border-slate-200 bg-white p-2 text-[#7C3AED] shadow-sm">{icon}</div>
          <div>
            <p className="text-xs font-bold text-slate-900">{label}</p>
            <p className="text-[11px] text-slate-500">{sublabel}</p>
          </div>
        </div>
        <div className="text-right">
          <span className={`tabular font-mono text-sm font-extrabold ${tone.text}`}>
            {formatPercent ? `${pct}%` : pct}
          </span>
          {weightLabel && (
            <span className="block font-mono text-[10px] text-slate-400">{weightLabel}</span>
          )}
        </div>
      </div>

      {/* Progress Bar */}
      <div className="mt-3 h-2 w-full rounded-full bg-slate-200 overflow-hidden">
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
    <section className="rounded-3xl border border-slate-200 bg-white p-6 shadow-sm flex h-full flex-col justify-between">
      <div>
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-slate-200 pb-3.5">
          <div>
            <p className="eyebrow text-[#7C3AED]">Three-Signal Intelligence</p>
            <h2 className="mt-0.5 text-sm font-bold text-slate-900">
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
        <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-3 flex flex-col items-center justify-center text-center font-mono text-[11px] text-slate-600">
          <div className="flex items-center gap-1.5 font-bold text-slate-800">
            <span>ANTI-SPOOF</span>
            <span>+</span>
            <span>IDENTITY</span>
            <span>+</span>
            <span>CONTEXT</span>
          </div>
          <ArrowDown size={14} className="text-[#7C3AED] my-1 animate-pulse" />
          <div className="flex items-center gap-2">
            <span className="text-[#7C3AED] font-bold">FUSED RISK INDEX</span>
            <span>→</span>
            <span className={`font-extrabold ${status === "LOCK_VERIFY" ? "text-red-600" : status === "WARN" ? "text-amber-600" : "text-emerald-600"}`}>
              POLICY DECISION ({status})
            </span>
          </div>
        </div>
      </div>

      {/* Decision Rationale */}
      <div className="mt-5 border-t border-slate-200 pt-4">
        <div className="flex items-center justify-between text-xs text-slate-500">
          <span className="font-bold uppercase tracking-wider text-[10px] text-slate-500">
            Audit Findings &amp; Rationale
          </span>
          <span className="font-mono text-[10px] text-slate-500">{rationale.length} detected</span>
        </div>

        {rationale.length === 0 ? (
          <p className="mt-2 text-xs text-slate-500 leading-relaxed font-sans">
            Nominal acoustics. Zero threat keywords or spoof characteristics detected in the active rolling window.
          </p>
        ) : (
          <div className="mt-2.5 space-y-1.5 max-h-48 overflow-y-auto pr-1">
            {rationale.map((r, i) => {
              const isThreat =
                status === "LOCK_VERIFY" ||
                /synthetic|spoof|mismatch|extortion|fraud|pressure|anomaly|critical/i.test(r);
              const isWarning = status === "WARN" && !isThreat;

              const styleClass = isThreat
                ? "border-red-200 bg-red-50 text-red-900"
                : isWarning
                  ? "border-amber-200 bg-amber-50 text-amber-900"
                  : "border-emerald-200 bg-emerald-50/80 text-emerald-900";

              return (
                <div
                  key={`${r}-${i}`}
                  className={`flex items-start gap-2.5 rounded-xl border px-3 py-2 text-xs leading-relaxed ${styleClass}`}
                >
                  {isThreat ? (
                    <AlertCircle size={14} className="shrink-0 text-red-600 mt-0.5" />
                  ) : isWarning ? (
                    <AlertCircle size={14} className="shrink-0 text-amber-600 mt-0.5" />
                  ) : (
                    <CheckCircle2 size={14} className="shrink-0 text-emerald-600 mt-0.5" />
                  )}
                  <span>{r}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </section>
  );
}

