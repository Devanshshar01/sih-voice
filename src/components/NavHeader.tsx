interface NavHeaderProps {
  connected: boolean;
  callerId?: string;
  recipientId?: string;
  durationSeconds?: number;
}

function formatDuration(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60).toString().padStart(2, "0");
  const seconds = Math.floor(totalSeconds % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export default function NavHeader({ connected, callerId, recipientId, durationSeconds }: NavHeaderProps) {
  return (
    <header className="hairline-bottom flex items-center justify-between bg-ink-900 px-5 py-3">
      <div className="flex items-center gap-4">
        <span className="text-sm font-medium tracking-tight text-paper">VoiceTrust</span>
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
        <span className="flex items-center gap-1.5 text-mute">
          <span
            className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-safe animate-pulseRing" : "bg-ink-500"}`}
          />
          {connected ? "Live" : "Offline"}
        </span>
      </div>
    </header>
  );
}
