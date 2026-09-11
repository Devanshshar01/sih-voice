import type { RiskStatus } from "../types";

interface ThreatBreakdownProps {
  acousticScore: number;
  intentScore: number;
  identityMismatch?: number | null;
  speakerSimilarity?: number | null;
  rationale: string[];
  status: RiskStatus;
}

function VectorBar({ label, value, color }: { label: string; value: number; color: string }) {
  const pct = Math.round(value * 100);
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-mute">{label}</span>
        <span className="tabular font-mono text-paper">{pct}%</span>
      </div>
      <div className="h-1.5 w-full bg-ink-700">
        <div
          className="h-full transition-all duration-500 ease-out"
          style={{ width: `${pct}%`, backgroundColor: color }}
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
  const barColor = status === "LOCK_VERIFY" ? "#f0554a" : status === "WARN" ? "#f5a524" : "#4fc3f7";

  return (
    <div className="panel flex h-full flex-col p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="eyebrow">Signal fusion</p>
          <h2 className="mt-1 text-sm font-medium text-paper">Threat breakdown</h2>
        </div>
        <span className={`font-mono text-[10px] ${status === "LOCK_VERIFY" ? "text-danger" : status === "WARN" ? "text-warn" : "text-safe"}`}>{status.replace("_", " ")}</span>
      </div>
      <div className="mt-4 space-y-4 border-t border-ink-700 pt-4">
        <VectorBar label="Acoustic synthesis vector" value={acousticScore} color={barColor} />
        <VectorBar label="Urgency / intent vector" value={intentScore} color={barColor} />
        {identityMismatch != null ? (
          <VectorBar
            label={
              speakerSimilarity == null
                ? "Identity mismatch (no reference — neutral)"
                : `Identity mismatch (similarity ${Math.round(speakerSimilarity * 100)}%)`
            }
            value={identityMismatch}
            color={barColor}
          />
        ) : (
          <VectorBar label="Identity mismatch (no reference — neutral)" value={0} color={barColor} />
        )}
      </div>

      <div className="mt-5 flex-1 hairline-top pt-3">
        <p className="text-xs text-mute">Rationale</p>
        {rationale.length === 0 ? (
          <p className="mt-2 text-sm text-mute">No signals to report yet.</p>
        ) : (
          <ul className="mt-2 space-y-1.5">
            {rationale.map((line) => (
              <li key={line} className="text-sm leading-snug text-paper-dim">
                {line}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
