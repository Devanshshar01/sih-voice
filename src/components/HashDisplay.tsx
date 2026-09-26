import { useState } from "react";
import { Check, Copy, ChevronDown, ChevronUp } from "lucide-react";

interface HashDisplayProps {
  label?: string;
  value?: string | null;
  pendingLabel?: string;
  status?: "ok" | "bad" | "warn" | null;
  className?: string;
  truncateLength?: { lead: number; tail: number };
}

export default function HashDisplay({
  label,
  value,
  pendingLabel = "NOT AVAILABLE",
  status = null,
  className = "",
  truncateLength = { lead: 10, tail: 8 },
}: HashDisplayProps) {
  const [expanded, setExpanded] = useState(false);
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  const tone =
    status === "bad"
      ? "text-danger"
      : status === "ok"
        ? "text-safe"
        : status === "warn"
          ? "text-warn"
          : "text-forensic-text";

  const displayString = !value
    ? pendingLabel
    : expanded || value.length <= truncateLength.lead + truncateLength.tail + 3
      ? value
      : `${value.slice(0, truncateLength.lead)}…${value.slice(-truncateLength.tail)}`;

  return (
    <div className={`py-2 ${className}`}>
      {label && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-forensic-muted font-sans">{label}</span>
          {value && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={copy}
                title="Copy full cryptographic digest"
                aria-label={`Copy ${label || "hash"}`}
                className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-forensic-muted hover:text-forensic-accent transition-colors"
              >
                {copied ? <Check size={11} className="text-safe" /> : <Copy size={11} />}
                <span className={copied ? "text-safe font-bold" : ""}>{copied ? "Copied" : "Copy"}</span>
              </button>
              {value.length > truncateLength.lead + truncateLength.tail + 3 && (
                <button
                  type="button"
                  onClick={() => setExpanded((v) => !v)}
                  title={expanded ? "Show shortened hash" : "Show complete digest"}
                  aria-label={expanded ? "Collapse full hash" : "Expand full hash"}
                  className="flex items-center gap-0.5 font-mono text-[10px] uppercase tracking-wider text-forensic-muted hover:text-forensic-accent transition-colors"
                >
                  {expanded ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
                  <span>{expanded ? "Fold" : "Expand"}</span>
                </button>
              )}
            </div>
          )}
        </div>
      )}
      <div className="mt-1 flex items-center justify-between gap-2">
        <p
          className={`font-mono text-xs break-all ${tone} select-all ${
            expanded ? "bg-forensic-bg/90 p-2 rounded-xl border border-forensic-border leading-relaxed text-[11px]" : ""
          }`}
          title={value ?? pendingLabel}
        >
          {displayString}
        </p>
        {!label && value && (
          <button
            type="button"
            onClick={copy}
            title="Copy full cryptographic digest"
            aria-label="Copy hash"
            className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-wider text-forensic-muted hover:text-forensic-accent transition-colors shrink-0"
          >
            {copied ? <Check size={12} className="text-safe" /> : <Copy size={12} />}
          </button>
        )}
      </div>
    </div>
  );
}

