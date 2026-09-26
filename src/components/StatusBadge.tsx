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
      container: "border-safe/30 bg-safe-bg text-safe font-bold",
      dot: "bg-safe",
      iconColor: "text-safe",
    },
    warn: {
      container: "border-warn/30 bg-warn-bg text-warn font-bold",
      dot: "bg-warn",
      iconColor: "text-warn",
    },
    danger: {
      container: "border-danger/40 bg-danger-bg text-danger font-extrabold",
      dot: "bg-danger animate-pulse",
      iconColor: "text-danger",
    },
    signal: {
      container: "border-forensic-accent/30 bg-forensic-accentMuted text-forensic-accent font-bold",
      dot: "bg-forensic-accent",
      iconColor: "text-forensic-accent",
    },
    neutral: {
      container: "border-forensic-border bg-forensic-surface text-forensic-muted font-bold",
      dot: "bg-forensic-muted",
      iconColor: "text-forensic-muted",
    },
    degraded: {
      container: "border-degraded/30 bg-degraded-bg text-degraded font-bold",
      dot: "bg-degraded",
      iconColor: "text-degraded",
    },
  };

  const current = variantStyles[variant];
  const sizeClasses = size === "sm" ? "px-2 py-0.5 text-[10px]" : "px-2.5 py-1 text-[11px]";

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border font-sans tracking-wide ${sizeClasses} ${current.container} ${className}`}
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

