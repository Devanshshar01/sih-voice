import { Activity, Clock, PhoneForwarded, Shield } from "lucide-react";
import StatusBadge from "./StatusBadge";

interface NavHeaderProps {
  connected: boolean;
  ended?: boolean;
  callerId?: string;
  recipientId?: string;
  durationSeconds?: number;
}

function formatDuration(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60)
    .toString()
    .padStart(2, "0");
  const seconds = Math.floor(totalSeconds % 60)
    .toString()
    .padStart(2, "0");
  if (hours > 0) {
    return `${hours}:${minutes}:${seconds}`;
  }
  return `${minutes}:${seconds}`;
}

export default function NavHeader({
  connected,
  ended = false,
  callerId,
  recipientId,
  durationSeconds,
}: NavHeaderProps) {
  return (
    <header className="relative z-30 flex flex-wrap items-center justify-between gap-4 border-b border-ink-700/40 bg-ink-950/90 px-5 py-3 backdrop-blur-md sm:px-8">
      {/* Brand Identity */}
      <div className="flex items-center gap-3.5">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-signal/30 bg-signal-bg text-signal">
          <Shield size={18} />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <span className="text-base font-bold tracking-tight text-paper-bright">SatyaVoice</span>
            <span className="rounded-md bg-ink-800 px-2 py-0.5 font-mono text-[10px] font-semibold text-paper-muted uppercase tracking-wider">
              Voice Intelligence
            </span>
          </div>
          {callerId && (
            <div className="flex items-center gap-2 text-xs text-paper-muted">
              <span className="font-mono text-paper-dim">{callerId}</span>
              {recipientId && (
                <span className="flex items-center gap-1 font-mono text-[11px]">
                  <PhoneForwarded size={10} className="text-signal" />
                  <span>{recipientId}</span>
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Right Stream Telemetry */}
      <div className="flex items-center gap-3 sm:gap-4">
        {typeof durationSeconds === "number" && (
          <div className="flex items-center gap-2 rounded-full border border-ink-700/60 bg-ink-900 px-3 py-1 text-xs">
            <Clock size={13} className="text-signal animate-pulse" />
            <span className="tabular font-mono text-xs font-semibold text-paper-bright">
              {formatDuration(durationSeconds)}
            </span>
          </div>
        )}

        <div className="flex items-center gap-2.5">
          {connected ? (
            <StatusBadge label="Live Protection Active" variant="safe" pulse icon />
          ) : ended ? (
            <StatusBadge label="Session Concluded" variant="neutral" icon />
          ) : (
            <StatusBadge label="Connecting Telemetry" variant="warn" pulse icon />
          )}

          <div className="hidden lg:flex items-center gap-1.5 rounded-full border border-ink-700/40 bg-ink-900/60 px-2.5 py-1 text-[11px] text-paper-muted font-mono">
            <Activity size={12} className="text-signal" />
            <span>16 kHz Rolling PCM</span>
          </div>
        </div>
      </div>
    </header>
  );
}
