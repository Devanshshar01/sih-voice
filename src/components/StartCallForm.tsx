import { useState } from "react";
import { ArrowRight, Check, Mic, ShieldCheck } from "lucide-react";
import type { AudioMode } from "../types";

interface StartCallFormProps {
  onStart: (callerId: string, recipientId: string, audioMode: AudioMode) => void;
  error: string | null;
  connecting: boolean;
}

const AUDIO_OPTIONS: { mode: AudioMode; label: string; description: string; icon: typeof Mic }[] = [
  {
    mode: "cloud",
    label: "Cloud — full multimodal pipeline",
    description:
      "Streams microphone audio to the backend for anti-spoof, ASR, speaker, and policy fusion.",
    icon: Mic,
  },
  {
    mode: "hybrid",
    label: "Hybrid — local anti-spoof + cloud policy",
    description:
      "Anti-spoof runs in this browser (ONNX, off the UI thread); the backend still does ASR, speaker, and policy fusion on the audio stream.",
    icon: ShieldCheck,
  },
  {
    mode: "edge-local",
    label: "Edge/local — raw audio never leaves this device",
    description:
      "Anti-spoof runs fully in-browser; only derived scores and telemetry are shared. ASR, speaker, and policy fusion are unavailable offline and shown as explicitly degraded.",
    icon: ShieldCheck,
  },
];

export default function StartCallForm({ onStart, error, connecting }: StartCallFormProps) {
  const [callerId, setCallerId] = useState("+91 98450 12233");
  const [recipientId, setRecipientId] = useState("finance-desk-01");
  const [audioMode, setAudioMode] = useState<AudioMode>("cloud");

  return (
    <main className="min-h-[100dvh] bg-black text-neutral-200">
      <div className="mx-auto grid min-h-[100dvh] max-w-[1280px] lg:grid-cols-[0.9fr_1.1fr]">
        <section className="relative flex flex-col justify-between border-b border-neutral-900 px-6 py-10 sm:px-10 lg:border-b-0 lg:border-r lg:px-14 lg:py-12">
          <div className="relative">
            <div className="text-[11px] uppercase tracking-[0.2em] text-neutral-500">
              SatyaVoice
            </div>
            <div className="mt-16 max-w-xl lg:mt-24">
              <h1 className="text-3xl font-normal leading-tight tracking-tight text-neutral-100 sm:text-4xl">
                Stop an impersonation attempt before money moves.
              </h1>
              <p className="mt-5 max-w-md text-sm leading-6 text-neutral-500">
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
                <div key={number} className="border-t border-neutral-900 pt-3">
                  <p className="font-mono text-xs text-neutral-600">{number}</p>
                  <p className="mt-2 text-sm text-neutral-300">{title}</p>
                  <p className="mt-1 text-xs leading-5 text-neutral-600">{description}</p>
                </div>
              ))}
            </div>
          </div>
          <div className="relative mt-16 text-xs text-neutral-700">
            Demo environment · metadata only · audio is never stored
          </div>
        </section>

        <section className="flex items-start px-6 py-10 sm:px-10 lg:items-center lg:px-14 lg:py-12">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              onStart(callerId.trim(), recipientId.trim(), audioMode);
            }}
            className="w-full max-w-lg"
          >
            <div>
              <h2 className="text-lg font-normal tracking-tight text-neutral-100">Choose a monitoring mode</h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-neutral-500">
                Connect live audio for real monitoring with the production-ready pipeline options below.
              </p>
            </div>

            <div id="monitoring-input-label" className="mt-8 text-[10px] font-medium uppercase tracking-[0.16em] text-neutral-600">Monitoring input</div>
            <div role="radiogroup" aria-labelledby="monitoring-input-label" className="mt-3 space-y-2">
              {AUDIO_OPTIONS.map(({ mode, label, description, icon: Icon }) => (
                <button
                  type="button"
                  key={mode}
                  role="radio"
                  aria-checked={audioMode === mode}
                  onClick={() => setAudioMode(mode)}
                  className={`group flex w-full items-start gap-4 border p-4 text-left transition-colors ${
                    audioMode === mode
                      ? "border-neutral-400 bg-neutral-950"
                      : "border-neutral-900 bg-black hover:border-neutral-700"
                  }`}
                >
                  <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center border ${audioMode === mode ? "border-neutral-500 text-neutral-200" : "border-neutral-800 text-neutral-500"}`}>
                    <Icon size={16} strokeWidth={1.5} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-3">
                      <span className={`text-sm ${audioMode === mode ? "text-neutral-100" : "text-neutral-400"}`}>{label}</span>
                      {audioMode === mode && <Check size={14} className="shrink-0 text-neutral-300" strokeWidth={1.5} />}
                    </span>
                    <span className="mt-1 block text-xs leading-5 text-neutral-600">{description}</span>
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

            {error && <p role="alert" className="mt-4 border border-neutral-800 px-3 py-3 text-xs leading-5 text-neutral-400">{error}</p>}

            <button type="submit" disabled={connecting || !callerId.trim() || !recipientId.trim()} className="mt-6 flex w-full items-center justify-center gap-2 border border-neutral-300 bg-white px-4 py-3 text-sm font-medium text-black transition-colors hover:bg-neutral-200 disabled:cursor-not-allowed disabled:border-neutral-800 disabled:bg-neutral-950 disabled:text-neutral-600">
              {connecting ? "Opening secure monitor..." : "Start monitored call"}
              {!connecting && <ArrowRight size={15} strokeWidth={1.5} />}
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
