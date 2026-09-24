import { Mic, MicOff, Pause, PhoneOff, Play } from "lucide-react";

interface CallControlsProps {
  muted: boolean;
  onHold: boolean;
  onToggleMute: () => void;
  onToggleHold: () => void;
  onEndCall: () => void;
}

export default function CallControls({
  muted,
  onHold,
  onToggleMute,
  onToggleHold,
  onEndCall,
}: CallControlsProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      {/* Voice Stream Controls */}
      <div className="flex items-center gap-2.5">
        <button
          onClick={onToggleMute}
          aria-pressed={muted}
          title={muted ? "Unmute local microphone" : "Mute local microphone"}
          className={`flex items-center gap-2 rounded-xl border px-4 py-2.5 text-xs font-semibold transition-all ${
            muted
              ? "border-warn/50 bg-warn-bg text-warn ring-1 ring-warn/30"
              : "border-ink-700/60 bg-ink-850 text-paper-dim hover:border-ink-600 hover:text-paper-bright"
          }`}
        >
          {muted ? <MicOff size={15} className="text-warn" /> : <Mic size={15} />}
          <span>{muted ? "Microphone Muted" : "Mute Mic"}</span>
        </button>

        <button
          onClick={onToggleHold}
          aria-pressed={onHold}
          title={onHold ? "Resume stream monitoring" : "Place stream on hold"}
          className={`flex items-center gap-2 rounded-xl border px-4 py-2.5 text-xs font-semibold transition-all ${
            onHold
              ? "border-signal/50 bg-signal-bg text-signal ring-1 ring-signal/30"
              : "border-ink-700/60 bg-ink-850 text-paper-dim hover:border-ink-600 hover:text-paper-bright"
          }`}
        >
          {onHold ? <Play size={15} className="text-signal" /> : <Pause size={15} />}
          <span>{onHold ? "Resume Monitoring" : "Hold Stream"}</span>
        </button>
      </div>

      {/* Emergency / Session Closeout Action */}
      <button
        onClick={onEndCall}
        aria-label="Terminate and closeout voice session"
        className="flex items-center gap-2 rounded-xl border border-danger/40 bg-danger-bg px-4 py-2.5 text-xs font-bold text-danger transition-all hover:bg-danger hover:text-white active:scale-95"
      >
        <PhoneOff size={15} />
        <span>Terminate &amp; Proceed to Forensics</span>
      </button>
    </div>
  );
}
