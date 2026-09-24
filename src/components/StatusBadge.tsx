import { AlertTriangle, CheckCircle2, Shield, ShieldAlert, Wifi } from "lucide-react";

export type BadgeVariant =
  | "safe"
  | "warn"
  | "danger"
  | "signal"
  | "neutral"
  | "degraded";

interface StatusBadgeProps {
  label: string;
  variant?: BadgeVariant;
  pulse?: boolean;
  icon?: boolean;
  size?: "sm" | "md";
  className?: string;
}

export default function StatusBadge({
  label,
  variant = "neutral",
  pulse = false,
  icon = true,
  size = "md",
  className = "",
}: StatusBadgeProps) {
  const variantStyles: Record<BadgeVariant, { container: string; dot: string; iconColor: string }> = {
    safe: {
      container: "border-safe/25 bg-safe-bg text-safe",
      dot: "bg-safe",
      iconColor: "text-safe",
    },
    warn: {
      container: "border-warn/25 bg-warn-bg text-warn",
      dot: "bg-warn",
      iconColor: "text-warn",
    },
    danger: {
      container: "border-danger/30 bg-danger-bg text-danger font-semibold",
      dot: "bg-danger animate-pulse",
      iconColor: "text-danger",
    },
    signal: {
      container: "border-signal/25 bg-signal-bg text-signal",
      dot: "bg-signal",
      iconColor: "text-signal",
    },
    neutral: {
      container: "border-ink-700/60 bg-ink-850 text-paper-muted",
      dot: "bg-ink-500",
      iconColor: "text-paper-muted",
    },
    degraded: {
      container: "border-warn/30 bg-warn-bg/40 text-warn-dim",
      dot: "bg-warn-dim",
      iconColor: "text-warn-dim",
    },
  };

  const current = variantStyles[variant];
  const sizeClasses = size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-[11px]";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-sans font-medium tracking-wide ${sizeClasses} ${current.container} ${className}`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${current.dot} ${
          pulse ? "animate-pulse" : ""
        }`}
      />
      {icon && (
        <span className="shrink-0">
          {variant === "safe" && <CheckCircle2 size={12} className={current.iconColor} />}
          {variant === "warn" && <AlertTriangle size={12} className={current.iconColor} />}
          {variant === "danger" && <ShieldAlert size={12} className={current.iconColor} />}
          {variant === "signal" && <Wifi size={12} className={current.iconColor} />}
          {(variant === "neutral" || variant === "degraded") && <Shield size={12} className={current.iconColor} />}
        </span>
      )}
      <span>{label}</span>
    </span>
  );
}
