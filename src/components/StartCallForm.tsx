import { useState } from "react";
import { Mic, PlayCircle, ShieldAlert } from "lucide-react";
import type { AudioMode } from "../types";

interface StartCallFormProps {
  onStart: (callerId: string, recipientId: string, audioMode: AudioMode) => void;
  error: string | null;
  connecting: boolean;
}

const AUDIO_OPTIONS: { mode: AudioMode; label: string; description: string; icon: typeof Mic }[] = [
  {
    mode: "live",
    label: "Live microphone",
    description: "Capture and analyze this device's mic in real time.",
    icon: Mic,
  },
  {
    mode: "demo-genuine",
    label: "Scripted demo — genuine call",
    description: "Trust index stays low throughout, no injected artifacts.",
    icon: PlayCircle,
  },
  {
    mode: "demo-cloned",
    label: "Scripted demo — cloned-voice attack",
    description: "Escalates from baseline to a locked, verified attack.",
    icon: ShieldAlert,
  },
];

export default function StartCallForm({ onStart, error, connecting }: StartCallFormProps) {
  const [callerId, setCallerId] = useState("+91 98450 12233");
  const [recipientId, setRecipientId] = useState("finance-desk-01");
  const [audioMode, setAudioMode] = useState<AudioMode>("demo-cloned");

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-6">
      <div className="mb-8">
        <p className="text-xs text-mute">Voice integrity console</p>
        <h1 className="mt-1 text-2xl font-medium text-paper">Connect a call to monitor</h1>
        <p className="mt-2 text-sm leading-relaxed text-paper-dim">
          VoiceTrust analyzes the audio stream in real time and locks sensitive actions the
          moment a cloned voice and an urgent request coincide.
        </p>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          onStart(callerId, recipientId, audioMode);
        }}
        className="space-y-5"
      >
        <div>
          <label className="block text-xs text-mute" htmlFor="caller-id">
            Caller ID
          </label>
          <input
            id="caller-id"
            value={callerId}
            onChange={(e) => setCallerId(e.target.value)}
            className="mt-1 w-full border border-ink-600 bg-ink-800 px-3 py-2 font-mono text-sm text-paper outline-none focus:border-signal"
            required
          />
        </div>

        <div>
          <label className="block text-xs text-mute" htmlFor="recipient-id">
            Receiving desk
          </label>
          <input
            id="recipient-id"
            value={recipientId}
            onChange={(e) => setRecipientId(e.target.value)}
            className="mt-1 w-full border border-ink-600 bg-ink-800 px-3 py-2 font-mono text-sm text-paper outline-none focus:border-signal"
            required
          />
        </div>

        <div>
          <p className="text-xs text-mute">Audio source</p>
          <div className="mt-2 space-y-2">
            {AUDIO_OPTIONS.map(({ mode, label, description, icon: Icon }) => (
              <button
                type="button"
                key={mode}
                onClick={() => setAudioMode(mode)}
                className={`flex w-full items-start gap-3 border px-3 py-2.5 text-left transition-colors ${
                  audioMode === mode
                    ? "border-signal/60 bg-signal-bg"
                    : "border-ink-600 bg-ink-800 hover:border-ink-500"
                }`}
              >
                <Icon size={16} className={`mt-0.5 shrink-0 ${audioMode === mode ? "text-signal" : "text-mute"}`} />
                <span>
                  <span className={`block text-sm ${audioMode === mode ? "text-paper" : "text-paper-dim"}`}>
                    {label}
                  </span>
                  <span className="block text-xs text-mute">{description}</span>
                </span>
              </button>
            ))}
          </div>
        </div>

        {error && (
          <p className="border border-danger/40 bg-danger-bg px-3 py-2 text-xs text-danger">{error}</p>
        )}

        <button
          type="submit"
          disabled={connecting}
          className="w-full border border-signal/50 bg-signal-bg px-4 py-2.5 text-sm font-medium text-signal transition-colors hover:bg-signal/15 disabled:opacity-60"
        >
          {connecting ? "Connecting…" : "Start call"}
        </button>
      </form>
    </div>
  );
}
