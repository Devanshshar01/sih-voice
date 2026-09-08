import { Mic, MicOff, Pause, Play, PhoneOff } from "lucide-react";

interface CallControlsProps {
  muted: boolean;
  onHold: boolean;
  onToggleMute: () => void;
  onToggleHold: () => void;
  onEndCall: () => void;
}

function ControlButton({
  active,
  onClick,
  icon,
  label,
}: {
  active?: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-2 border px-4 py-2.5 text-sm transition-colors ${
        active
          ? "border-signal/50 bg-signal-bg text-signal"
          : "border-ink-600 bg-ink-800 text-paper-dim hover:border-ink-500 hover:text-paper"
      }`}
    >
      {icon}
      {label}
    </button>
  );
}

export default function CallControls({ muted, onHold, onToggleMute, onToggleHold, onEndCall }: CallControlsProps) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 bg-ink-950 px-0 py-0">
      <div className="flex gap-2">
        <ControlButton
          active={muted}
          onClick={onToggleMute}
          icon={muted ? <MicOff size={16} /> : <Mic size={16} />}
          label={muted ? "Unmute" : "Mute"}
        />
        <ControlButton
          active={onHold}
          onClick={onToggleHold}
          icon={onHold ? <Play size={16} /> : <Pause size={16} />}
          label={onHold ? "Resume" : "Hold"}
        />
      </div>
      <button
        onClick={onEndCall}
        aria-label="End monitored call"
        className="flex items-center gap-2 border border-danger/50 bg-danger-bg px-4 py-2.5 text-sm font-medium text-danger transition-colors hover:bg-danger/15"
      >
        <PhoneOff size={16} />
        End call
      </button>
    </div>
  );
}
