import { AlertTriangle, ShieldCheck, ShieldAlert } from "lucide-react";
import type { RiskStatus } from "../types";

interface StatusBannerProps {
  status: RiskStatus;
  rationale: string[];
}

const CONFIG: Record<RiskStatus, { icon: typeof ShieldCheck; label: string; className: string }> = {
  ALLOW: {
    icon: ShieldCheck,
    label: "All controls unlocked. No anomalies in the current window.",
    className: "border-safe/40 bg-safe-bg text-safe",
  },
  WARN: {
    icon: AlertTriangle,
    label: "Acoustic anomaly detected — reviewing before any action is restricted.",
    className: "border-warn/40 bg-warn-bg text-warn",
  },
  LOCK_VERIFY: {
    icon: ShieldAlert,
    label: "High-confidence impersonation signal. Sensitive controls are locked.",
    className: "border-danger/40 bg-danger-bg text-danger animate-pulseRing",
  },
};

export default function StatusBanner({ status, rationale }: StatusBannerProps) {
  const { icon: Icon, label, className } = CONFIG[status];

  return (
    <div className={`flex items-start gap-3 border px-4 py-3 ${className}`}>
      <Icon size={18} className="mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="text-sm font-medium">{label}</p>
        {rationale.length > 0 && (
          <p className="mt-0.5 truncate text-xs text-mute">{rationale[0]}</p>
        )}
      </div>
    </div>
  );
}
