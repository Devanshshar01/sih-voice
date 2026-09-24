import { useState } from "react";
import {
  ArrowRight,
  Check,
  Cpu,
  Fingerprint,
  Layers,
  Lock,
  Mic,
  Radio,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import type { AudioMode } from "../types";
import StatusBadge from "./StatusBadge";

interface StartCallFormProps {
  onStart: (callerId: string, recipientId: string, audioMode: AudioMode) => void;
  error: string | null;
  connecting: boolean;
}

interface AudioOptionConfig {
  mode: AudioMode;
  badge: string;
  badgeVariant: "signal" | "safe" | "warn";
  label: string;
  description: string;
  architecture: string;
  icon: typeof Mic;
}

const AUDIO_OPTIONS: AudioOptionConfig[] = [
  {
    mode: "cloud",
    badge: "FULL MULTIMODAL",
    badgeVariant: "signal",
    label: "Cloud Full Pipeline",
    description:
      "Streams microphone audio via secure WebSocket for MMS-300M acoustic anti-spoofing, multilingual ASR intent evaluation, and dynamic risk fusion.",
    architecture: "16 kHz PCM · Silero VAD · 4s Window · Cloud GPU Fusion",
    icon: Server,
  },
  {
    mode: "hybrid",
    badge: "ONNX ACCELERATED",
    badgeVariant: "safe",
    label: "Hybrid Local + Cloud Policy",
    description:
      "Acoustic anti-spoof inference executes locally in-browser via WebAssembly ONNX Runtime off the main thread; intent analysis and policy fusion occur on the server stream.",
    architecture: "In-Browser WASM · Off-Thread Worker · Cloud Intent",
    icon: Cpu,
  },
  {
    mode: "edge-local",
    badge: "MAXIMUM PRIVACY",
    badgeVariant: "warn",
    label: "Air-Gapped / Zero-Upload",
    description:
      "Raw microphone audio never leaves this device. Only derived local acoustic scores and telemetry are processed locally.",
    architecture: "Strict Air-Gap Audio · Local Inference Only · Zero Audio Upload",
    icon: Lock,
  },
];

const PIPELINE_STEPS = [
  { step: "01", name: "Voice Stream", desc: "16 kHz mono capture & Silero VAD" },
  { step: "02", name: "Acoustic AI", desc: "MMS-300M anti-spoof (4s window)" },
  { step: "03", name: "Intent Analysis", desc: "Multilingual ASR & extortion tokens" },
  { step: "04", name: "Risk Fusion", desc: "Dynamic policy gating & step-up MFA" },
  { step: "05", name: "Forensic Ledger", desc: "SHA-256 Merkle & Polygon Amoy anchor" },
];

export default function StartCallForm({ onStart, error, connecting }: StartCallFormProps) {
  const [callerId, setCallerId] = useState("+91 98450 12233");
  const [recipientId, setRecipientId] = useState("finance-desk-01");
  const [audioMode, setAudioMode] = useState<AudioMode>("cloud");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!callerId.trim() || !recipientId.trim() || connecting) return;
    onStart(callerId.trim(), recipientId.trim(), audioMode);
  };

  return (
    <div className="min-h-[100dvh] bg-ink-950 text-paper flex flex-col selection:bg-signal/20 selection:text-paper-bright">
      {/* ── Nav Header ─────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b border-ink-700/40 bg-ink-950/95 px-6 py-3 backdrop-blur-md sm:px-10">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-signal/30 bg-signal/8 text-signal">
              <Shield size={16} />
            </div>
            <div className="flex items-center gap-2.5">
              <span className="text-sm font-bold tracking-tight text-paper-bright">SatyaVoice</span>
              <span className="rounded-md bg-ink-800 px-2 py-0.5 font-mono text-[10px] font-semibold text-paper-muted uppercase tracking-wider">
                Defense Platform
              </span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge label="System Ready" variant="safe" pulse />
            <span className="hidden font-mono text-xs text-paper-muted sm:inline">
              Polygon Amoy Anchor Active
            </span>
          </div>
        </div>
      </header>

      {/* ── Page Body ──────────────────────────────────────────── */}
      <div className="mx-auto w-full max-w-7xl flex-1 px-6 pt-4 pb-16 sm:px-10 lg:pt-5">

        {/* Hero eyebrow */}
        <div className="inline-flex items-center gap-2 rounded-full border border-signal/25 bg-signal/8 px-3 py-1 text-xs font-medium text-signal">
          <Radio size={11} className="animate-pulse" />
          <span>Real-Time Voice Intelligence &amp; Synthetic Media Interception</span>
        </div>

        {/* ── Two-column grid ──────────────────────────────────── */}
        <div className="mt-6 grid w-full grid-cols-1 items-start gap-10 lg:grid-cols-12 lg:gap-16">

          {/* ── LEFT: Editorial overview ─────────────────────── */}
          <section className="lg:col-span-7 lg:sticky lg:top-24 flex flex-col gap-8">

            {/* Hero headline */}
            <div>
              <h1 className="text-3xl font-extrabold tracking-tight text-paper-bright sm:text-4xl lg:text-[2.75rem] lg:leading-[1.12]">
                Continuous voice analysis,<br className="hidden sm:block" />
                zero-trust fraud defense.
              </h1>
              <p className="mt-4 max-w-xl text-sm leading-relaxed text-paper-dim">
                SatyaVoice safeguards enterprise communications and financial desks from voice clones,
                AI speech synthesis, and social engineering. Acoustic features, conversational intent,
                and speaker biometrics are fused in real time to enforce deterministic policy clearance
                before sensitive actions execute.
              </p>
            </div>

            {/* Pipeline flow */}
            <div>
              <div className="mb-3 flex items-center justify-between">
                <p className="eyebrow flex items-center gap-1.5 text-signal">
                  <Layers size={12} />
                  Continuous Intelligence Pipeline
                </p>
                <span className="font-mono text-[11px] text-paper-muted">Sub-second rolling window</span>
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-5">
                {PIPELINE_STEPS.map((s, idx) => (
                  <div
                    key={s.step}
                    className="relative rounded-xl border border-ink-700/30 bg-ink-900/50 p-3 transition-colors hover:border-signal/30 hover:bg-ink-900"
                  >
                    <div className="flex items-center justify-between font-mono text-[11px]">
                      <span className="text-signal font-semibold">{s.step}</span>
                      {idx < PIPELINE_STEPS.length - 1 && (
                        <span className="hidden text-paper-muted sm:inline">→</span>
                      )}
                    </div>
                    <p className="mt-1.5 text-xs font-semibold text-paper-bright">{s.name}</p>
                    <p className="mt-0.5 text-[11px] text-paper-muted leading-tight">{s.desc}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Security pillars */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-ink-700/30 bg-ink-900/40 p-3.5">
                <div className="flex items-center gap-2 text-safe">
                  <ShieldCheck size={15} />
                  <span className="text-xs font-semibold text-paper-bright">Zero Persistence</span>
                </div>
                <p className="mt-1.5 text-xs text-paper-muted leading-relaxed">
                  Raw voice is strictly ephemeral. Cryptographic hashes and telemetry metrics only.
                </p>
              </div>
              <div className="rounded-xl border border-ink-700/30 bg-ink-900/40 p-3.5">
                <div className="flex items-center gap-2 text-signal">
                  <Sparkles size={15} />
                  <span className="text-xs font-semibold text-paper-bright">MMS-300M Model</span>
                </div>
                <p className="mt-1.5 text-xs text-paper-muted leading-relaxed">
                  Production anti-spoof model detecting vocoder artifacts and synthetic phonemes.
                </p>
              </div>
              <div className="rounded-xl border border-ink-700/30 bg-ink-900/40 p-3.5">
                <div className="flex items-center gap-2 text-intel">
                  <Fingerprint size={15} />
                  <span className="text-xs font-semibold text-paper-bright">Polygon Immutability</span>
                </div>
                <p className="mt-1.5 text-xs text-paper-muted leading-relaxed">
                  SHA-256 Merkle roots committed to Polygon Amoy for court-ready chain of custody.
                </p>
              </div>
            </div>
          </section>

          {/* ── RIGHT: Launch form ───────────────────────────── */}
          <section className="lg:col-span-5">
            <div className="rounded-2xl border border-ink-700/50 bg-ink-900/90 p-6 shadow-elevated">
              {/* Form header */}
              <div className="border-b border-ink-700/40 pb-4 mb-5">
                <p className="eyebrow text-signal">Initialize Defense Session</p>
                <h2 className="mt-1 text-xl font-bold tracking-tight text-paper-bright">
                  Session Configuration
                </h2>
                <p className="mt-1 text-xs text-paper-muted">
                  Choose an inspection execution mode and designate communication parties.
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-5">
                {/* Pipeline selector */}
                <div>
                  <label className="field-label mb-2.5 block">Inspection Execution Pipeline</label>
                  <div className="space-y-2">
                    {AUDIO_OPTIONS.map((opt) => {
                      const isSelected = audioMode === opt.mode;
                      const Icon = opt.icon;
                      return (
                        <button
                          type="button"
                          key={opt.mode}
                          onClick={() => setAudioMode(opt.mode)}
                          className={`group relative flex w-full items-start gap-3 rounded-xl border p-3 text-left transition-all ${
                            isSelected
                              ? "border-signal/70 bg-ink-800 ring-1 ring-signal/20"
                              : "border-ink-700/40 bg-ink-850/40 hover:border-ink-600 hover:bg-ink-800/60"
                          }`}
                        >
                          <div
                            className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg border transition-colors ${
                              isSelected
                                ? "border-signal/50 bg-signal/10 text-signal"
                                : "border-ink-700 bg-ink-800 text-paper-muted group-hover:text-paper"
                            }`}
                          >
                            <Icon size={14} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center justify-between gap-2">
                              <span
                                className={`text-xs font-semibold tracking-tight ${
                                  isSelected ? "text-paper-bright" : "text-paper-dim"
                                }`}
                              >
                                {opt.label}
                              </span>
                              <StatusBadge label={opt.badge} variant={opt.badgeVariant} size="sm" icon={false} />
                            </div>
                            <p className="mt-1 text-[11px] leading-relaxed text-paper-muted">{opt.description}</p>
                            <p className="mt-1 font-mono text-[10px] text-paper-muted/70">{opt.architecture}</p>
                          </div>
                          {isSelected && (
                            <div className="absolute right-3 top-3 text-signal">
                              <Check size={13} />
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Call party inputs */}
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div>
                    <label className="field-label" htmlFor="caller-id">
                      Caller ID / Inbound Line
                    </label>
                    <input
                      id="caller-id"
                      name="caller-id"
                      aria-label="Caller ID or Inbound Line"
                      value={callerId}
                      onChange={(e) => setCallerId(e.target.value)}
                      className="field-input font-mono"
                      required
                      maxLength={120}
                      placeholder="+91..."
                    />
                    <span className="mt-1 block text-[11px] text-paper-muted">Simulated caller number</span>
                  </div>
                  <div>
                    <label className="field-label" htmlFor="recipient-id">
                      Protected Target Desk
                    </label>
                    <input
                      id="recipient-id"
                      name="recipient-id"
                      aria-label="Protected Target Desk"
                      value={recipientId}
                      onChange={(e) => setRecipientId(e.target.value)}
                      className="field-input font-mono"
                      required
                      maxLength={120}
                      placeholder="finance-desk-01"
                    />
                    <span className="mt-1 block text-[11px] text-paper-muted">Authorized terminal</span>
                  </div>
                </div>

                {/* Error */}
                {error && (
                  <div
                    role="alert"
                    className="flex items-start gap-2.5 rounded-xl border border-danger/30 bg-danger/8 p-3 text-xs leading-relaxed text-danger"
                  >
                    <ShieldAlert size={15} className="shrink-0 mt-0.5" />
                    <div>
                      <span className="font-semibold uppercase tracking-wider block">Connection Advisory</span>
                      <span>{error}</span>
                    </div>
                  </div>
                )}

                {/* Submit */}
                <button
                  type="submit"
                  disabled={connecting || !callerId.trim() || !recipientId.trim()}
                  className="group relative flex w-full items-center justify-center gap-2 rounded-xl border border-signal/50 bg-signal px-5 py-3 text-sm font-semibold tracking-wide text-ink-950 transition-all hover:bg-signal/90 hover:shadow-lg active:scale-[0.99] disabled:cursor-not-allowed disabled:border-ink-700 disabled:bg-ink-800 disabled:text-paper-muted"
                >
                  {connecting ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-ink-950 border-t-transparent" />
                      <span>Establishing Secure Stream Channel...</span>
                    </>
                  ) : (
                    <>
                      <span>Initiate Real-Time Voice Protection</span>
                      <ArrowRight size={15} className="transition-transform group-hover:translate-x-1" />
                    </>
                  )}
                </button>
              </form>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
