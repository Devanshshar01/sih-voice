import { Activity, Shield } from "lucide-react";

interface NavHeaderProps {
  connected: boolean;
  ended?: boolean;
  callerId?: string;
  recipientId?: string;
  durationSeconds?: number;
}

function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const seconds = Math.floor(totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export default function NavHeader({ connected, ended = false, callerId, recipientId, durationSeconds }: NavHeaderProps) {
  return (
    <header className="hairline-bottom flex flex-wrap items-center justify-between gap-3 bg-ink-950 px-4 py-3 sm:px-6">
      <div className="flex items-center gap-4">
        <span className="flex items-center gap-2 text-sm font-semibold tracking-tight text-paper">
          <span className="flex h-7 w-7 items-center justify-center border border-signal/40 bg-signal-bg text-signal"><Shield size={14} /></span>
          SatyaVoice
        </span>
        {callerId && (
          <>
            <span className="hidden h-4 w-px bg-ink-600 sm:block" />
            <span className="hidden font-mono text-xs text-mute sm:inline">{callerId}</span>
            {recipientId && <span className="hidden text-xs text-mute sm:inline">→ {recipientId}</span>}
          </>
        )}
      </div>

      <div className="flex items-center gap-4 text-xs">
        {typeof durationSeconds === "number" && (
          <span className="tabular font-mono text-paper-dim">{formatDuration(durationSeconds)}</span>
        )}
        <span className={`flex items-center gap-1.5 ${connected ? "text-safe" : ended ? "text-mute" : "text-warn"}`}>
          <span
            className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-safe animate-pulseRing" : "bg-ink-500"}`}
          />
          <Activity size={13} />
          {connected ? "Stream live" : ended ? "Session complete" : "Reconnecting"}
        </span>
      </div>
    </header>
  );
}
