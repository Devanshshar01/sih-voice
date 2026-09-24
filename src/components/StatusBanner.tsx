import { AlertTriangle, CheckCircle2, Lock, ShieldCheck } from "lucide-react";
import type { RiskStatus } from "../types";

interface StatusBannerProps {
  status: RiskStatus;
  rationale: string[];
  verified?: boolean;
}

export default function StatusBanner({ status, rationale, verified = false }: StatusBannerProps) {
  if (verified) {
    return (
      <div
        role="status"
        className="flex items-start gap-3.5 rounded-2xl border border-safe/40 bg-safe-bg/80 p-4 shadow-glow-safe backdrop-blur transition-all"
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-safe/50 bg-safe/10 text-safe">
          <CheckCircle2 size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs font-semibold uppercase tracking-wider text-safe">
              IDENTITY OVERRIDE ACTIVE
            </span>
            <span className="h-1.5 w-1.5 rounded-full bg-safe animate-pulse" />
          </div>
          <p className="mt-0.5 text-xs text-paper-bright leading-relaxed">
            Out-of-band biometric challenge completed successfully. Gated controls unlocked for this
            monitored session.
          </p>
        </div>
      </div>
    );
  }

  if (status === "LOCK_VERIFY") {
    return (
      <div
        role="alert"
        className="flex items-start gap-3.5 rounded-2xl border border-danger/60 bg-danger-bg/90 p-4 shadow-glow-danger backdrop-blur transition-all"
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-danger/60 bg-danger/20 text-danger animate-pulse">
          <Lock size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-bold uppercase tracking-wider text-danger">
              CRITICAL INCIDENT: CONTROLS GATED
            </span>
            <span className="hud-badge hud-badge-danger">VERIFICATION REQUIRED</span>
          </div>
          <p className="mt-1 text-xs text-paper-bright font-medium leading-relaxed">
            High-confidence voice clone or impersonation indicators detected. All sensitive financial
            and credential actions have been locked.
          </p>
          {rationale.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {rationale.map((r) => (
                <span
                  key={r}
                  className="rounded-md border border-danger/30 bg-ink-950/70 px-2 py-0.5 font-mono text-[11px] text-danger"
                >
                  {r}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  if (status === "WARN") {
    return (
      <div
        role="status"
        className="flex items-start gap-3.5 rounded-2xl border border-warn/40 bg-warn-bg/80 p-4 shadow-glow-warn backdrop-blur transition-all"
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-warn/50 bg-warn/10 text-warn">
          <AlertTriangle size={16} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs font-semibold uppercase tracking-wider text-warn">
              ACOUSTIC / CONTEXTUAL ANOMALY
            </span>
            <span className="hud-badge hud-badge-warn">ELEVATED SCRUTINY</span>
          </div>
          <p className="mt-1 text-xs text-paper-bright leading-relaxed">
            Acoustic dissonance or conversational urgency detected in the active window. Continuous
            monitoring active; controls remain open under advisory.
          </p>
          {rationale.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {rationale.map((r) => (
                <span
                  key={r}
                  className="rounded-md border border-warn/30 bg-ink-950/70 px-2 py-0.5 font-mono text-[11px] text-warn"
                >
                  {r}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // ALLOW / NOMINAL
  return (
    <div
      role="status"
      className="flex items-start gap-3.5 rounded-2xl border border-safe/30 bg-safe-bg/40 p-3.5 backdrop-blur transition-all"
    >
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border border-safe/40 bg-safe/10 text-safe">
        <ShieldCheck size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold uppercase tracking-wider text-safe">
            NOMINAL OPERATIONAL POSTURE
          </span>
          <span className="h-1.5 w-1.5 rounded-full bg-safe shadow-[0_0_6px_theme(colors.safe.DEFAULT)]" />
        </div>
        <p className="mt-0.5 text-xs text-paper-dim leading-relaxed">
          Biometric acoustics, speaker similarity, and conversational intent remain within verified
          safe policy parameters.
        </p>
      </div>
    </div>
  );
}
