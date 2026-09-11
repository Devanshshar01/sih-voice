import { useState } from "react";
import { Activity, ArrowRight, Check, Mic, PlayCircle, ShieldAlert, ShieldCheck } from "lucide-react";
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
    mode: "browser-onnx",
    label: "Browser-only ONNX inference (Phase 9 proof-of-concept)",
    description: "Runs the real anti-spoof model in-browser with ONNX Runtime Web, demonstrated in airplane-mode style offline execution.",
    icon: ShieldCheck,
  },
  {
    mode: "demo-genuine",
    label: "Scripted demo — genuine call",
    description: "Risk stays low throughout with no injected artifacts.",
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
    <main className="min-h-[100dvh] bg-ink-950">
      <div className="console-grid mx-auto grid min-h-[100dvh] max-w-[1480px] lg:grid-cols-[0.9fr_1.1fr]">
        <section className="relative flex flex-col justify-between border-b border-ink-700 px-6 py-8 sm:px-10 lg:border-b-0 lg:border-r lg:px-14 lg:py-12">
          <div className="relative">
            <div className="flex items-center gap-3 text-xs uppercase tracking-[0.18em] text-signal">
              <span className="flex h-8 w-8 items-center justify-center border border-signal/40 bg-signal-bg">
                <ShieldCheck size={16} />
              </span>
              SatyaVoice security console
            </div>
            <div className="mt-14 max-w-xl lg:mt-20">
              <p className="text-xs font-medium uppercase tracking-[0.14em] text-safe">REAL-TIME VOICE INTEGRITY</p>
              <h1 className="mt-4 text-3xl font-semibold leading-tight tracking-tight text-paper sm:text-4xl">
                Stop an impersonation attempt before money moves.
              </h1>
              <p className="mt-5 max-w-lg text-sm leading-6 text-paper-dim sm:text-base">
                SatyaVoice scores acoustic and conversational signals while a call is live, then
                pauses sensitive actions when the evidence crosses a risk threshold.
              </p>
            </div>
            <div className="mt-10 grid max-w-xl gap-5 sm:grid-cols-3">
              {[
                ["01", "Listen", "Capture a live audio stream"],
                ["02", "Score", "Fuse voice and intent signals"],
                ["03", "Protect", "Verify before money moves"],
              ].map(([number, title, description]) => (
                <div key={number} className="border-t border-ink-600 pt-3">
                  <p className="font-mono text-xs text-signal">{number}</p>
                  <p className="mt-2 text-sm font-medium text-paper">{title}</p>
                  <p className="mt-1 text-xs leading-5 text-mute">{description}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="relative mt-16 flex items-center gap-2 text-xs text-mute">
            <Activity size={14} className="text-safe" />
            Demo environment · metadata only · audio is never stored
          </div>
        </section>

        <section className="flex items-start px-6 py-10 sm:px-10 lg:items-center lg:px-14 lg:py-12">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onStart(callerId.trim(), recipientId.trim(), audioMode);
            }}
            className="w-full max-w-lg animate-rise"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
              <p className="eyebrow">Secure intake / new session</p>
              <h2 className="mt-2 text-xl font-semibold tracking-tight text-paper">Choose a monitoring mode</h2>
              </div>
            </div>
            <p className="mt-3 text-sm leading-6 text-paper-dim">
              The attack scenario is preselected so the complete protection workflow is one click away.
            </p>

            <div className="mt-8 space-y-3">
              {AUDIO_OPTIONS.map(({ mode, label, description, icon: Icon }) => (
                <button
                  type="button"
                  key={mode}
                  onClick={() => setAudioMode(mode)}
                  className={`group flex w-full items-start gap-4 border p-4 text-left transition-all ${
                    audioMode === mode
                      ? "border-signal/70 bg-signal-bg shadow-[inset_3px_0_0_#4fc3f7]"
                      : "border-ink-600 bg-ink-800/60 hover:border-ink-500 hover:bg-ink-800"
                  }`}
                >
                  <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center border ${audioMode === mode ? "border-signal/40 text-signal" : "border-ink-500 text-mute"}`}>
                    <Icon size={17} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-3">
                      <span className={`text-sm font-medium ${audioMode === mode ? "text-paper" : "text-paper-dim"}`}>{label}</span>
                      {audioMode === mode && <Check size={16} className="shrink-0 text-signal" />}
                    </span>
                    <span className="mt-1 block text-xs leading-5 text-mute">{description}</span>
                  </span>
                </button>
              ))}
            </div>

            <div className="mt-8 grid gap-3 sm:grid-cols-2">
              <div>
                <label className="field-label" htmlFor="caller-id">Caller identity</label>
                <input id="caller-id" value={callerId} onChange={(e) => setCallerId(e.target.value)} className="field-input" required maxLength={120} />
              </div>
              <div>
                <label className="field-label" htmlFor="recipient-id">Protected desk</label>
                <input id="recipient-id" value={recipientId} onChange={(e) => setRecipientId(e.target.value)} className="field-input" required maxLength={120} />
              </div>
            </div>

            {error && <p role="alert" className="mt-4 border border-danger/40 bg-danger-bg px-3 py-3 text-xs leading-5 text-danger">{error}</p>}

            <button type="submit" disabled={connecting || !callerId.trim() || !recipientId.trim()} className="mt-6 flex w-full items-center justify-center gap-2 bg-signal px-4 py-3 text-sm font-semibold text-ink-950 transition-all hover:bg-[#83d9ff] disabled:cursor-not-allowed disabled:opacity-50">
              {connecting ? "Opening secure monitor..." : "Start monitored call"}
              {!connecting && <ArrowRight size={16} />}
            </button>
            <p className="mt-3 text-center text-[11px] leading-5 text-mute">The demo uses synthetic frames. Live microphone mode requests browser permission.</p>
          </form>
        </section>
      </div>
    </main>
  );
}
