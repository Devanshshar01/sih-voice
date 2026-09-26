import { Activity, Clock, PhoneForwarded, Shield, Cpu, LockKeyhole, Layers } from "lucide-react";
import StatusBadge from "./StatusBadge";

interface NavHeaderProps {
  connected: boolean;
  ended?: boolean;
  callerId?: string;
  recipientId?: string;
  durationSeconds?: number;
  currentTab?: "overview" | "live" | "forensics" | "verification";
  onTabChange?: (tab: "overview" | "live" | "forensics" | "verification") => void;
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
  currentTab = connected ? "live" : ended ? "forensics" : "overview",
  onTabChange,
}: NavHeaderProps) {
  return (
    <header className="sticky top-0 z-40 flex flex-wrap items-center justify-between gap-4 border-b border-forensic-border bg-forensic-bg/95 px-5 py-3 backdrop-blur-xl sm:px-8">
      {/* Brand Identity & Section Navigation */}
      <div className="flex flex-wrap items-center gap-6">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-forensic-accent/40 bg-forensic-panel/60 text-forensic-accent shadow-signal">
            <Shield size={19} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-base font-extrabold tracking-tight text-forensic-text">SatyaVoice</span>
              <span className="rounded-md border border-forensic-accent/30 bg-forensic-panel/80 px-2 py-0.5 font-mono text-[10px] font-bold text-forensic-accent uppercase tracking-wider">
                Forensic Intelligence
              </span>
            </div>
            {callerId && (
              <div className="flex items-center gap-2 text-xs text-forensic-muted">
                <span className="font-mono font-medium text-forensic-text">{callerId}</span>
                {recipientId && (
                  <span className="flex items-center gap-1 font-mono text-[11px] text-forensic-muted">
                    <PhoneForwarded size={11} className="text-forensic-accent" />
                    <span>{recipientId}</span>
                  </span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Navigation IA */}
        <nav aria-label="Main Navigation" className="hidden md:flex items-center gap-1 rounded-xl border border-forensic-border bg-forensic-surface p-1 text-xs shadow-sm">
          <button
            type="button"
            onClick={() => onTabChange?.("overview")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-medium transition-all ${
              currentTab === "overview"
                ? "bg-forensic-accent text-white font-semibold shadow-sm"
                : "text-forensic-muted hover:text-forensic-text hover:bg-forensic-panel"
            }`}
          >
            <Layers size={13} />
            <span>Overview</span>
          </button>

          <button
            type="button"
            onClick={() => onTabChange?.("live")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-medium transition-all ${
              currentTab === "live"
                ? "bg-forensic-accent text-white font-semibold shadow-sm"
                : "text-forensic-muted hover:text-forensic-text hover:bg-forensic-panel"
            }`}
          >
            <Activity size={13} className={connected ? (currentTab === "live" ? "text-white animate-pulse" : "text-safe animate-pulse") : ""} />
            <span>Live Protection</span>
          </button>

          <button
            type="button"
            onClick={() => onTabChange?.("forensics")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-medium transition-all ${
              currentTab === "forensics"
                ? "bg-forensic-accent text-white font-semibold shadow-sm"
                : "text-forensic-muted hover:text-forensic-text hover:bg-forensic-panel"
            }`}
          >
            <Cpu size={13} />
            <span>Investigations</span>
          </button>

          <button
            type="button"
            onClick={() => onTabChange?.("verification")}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 font-medium transition-all ${
              currentTab === "verification"
                ? "bg-forensic-accent text-white font-semibold shadow-sm"
                : "text-forensic-muted hover:text-forensic-text hover:bg-forensic-panel"
            }`}
          >
            <LockKeyhole size={13} />
            <span>Verification</span>
          </button>
        </nav>
      </div>

      {/* Right Stream Telemetry */}
      <div className="flex items-center gap-3 sm:gap-4">
        {typeof durationSeconds === "number" && (
          <div className="flex items-center gap-2 rounded-full border border-forensic-border bg-forensic-surface px-3 py-1 text-xs">
            <Clock size={13} className="text-forensic-accent animate-pulse" />
            <span className="tabular font-mono text-xs font-semibold text-forensic-text">
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

          <div className="hidden lg:flex items-center gap-1.5 rounded-full border border-forensic-border bg-forensic-surface/80 px-3 py-1 text-[11px] text-forensic-muted font-mono">
            <Activity size={12} className="text-forensic-accent" />
            <span>16 kHz PCM</span>
          </div>
        </div>
      </div>
    </header>
  );
}

