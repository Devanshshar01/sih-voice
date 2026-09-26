import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  Cpu,
  Fingerprint,
  Lock,
  Mic,
  MicOff,
  Radio,
  Server,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Waves,
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
    label: "Cloud Multimodal Pipeline",
    description:
      "Streams microphone audio via secure WebSocket for MMS-300M acoustic anti-spoofing, multilingual ASR intent evaluation, and dynamic risk fusion.",
    architecture: "16 kHz Mono PCM · Silero VAD · 4s Window · Cloud GPU Fusion",
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

const INTELLIGENCE_CHAIN = [
  { step: "VOICE", label: "Signal Stream", desc: "16 kHz mono PCM stream" },
  { step: "ANALYSIS", label: "Feature Extraction", desc: "MMS-300M & ECAPA biometrics" },
  { step: "SIGNALS", label: "Three Threat Vectors", desc: "Spoof + Identity + Intent" },
  { step: "RISK", label: "Dynamic Fusion", desc: "Weighted risk index calculation" },
  { step: "DECISION", label: "Policy Gating", desc: "ALLOW / WARN / LOCK_VERIFY" },
];

export default function StartCallForm({ onStart, error, connecting }: StartCallFormProps) {
  const [callerId, setCallerId] = useState("+91 98450 12233");
  const [recipientId, setRecipientId] = useState("finance-desk-01");
  const [audioMode, setAudioMode] = useState<AudioMode>("cloud");

  // Mic test / preview state
  const [testingMic, setTestingMic] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const rafRef = useRef<number | null>(null);

  const startMicTest = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      micStreamRef.current = stream;
      const audioCtx = new AudioContext();
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);

      const canvas = canvasRef.current;
      const ctx = canvas?.getContext("2d");
      if (!canvas || !ctx) return;

      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      setTestingMic(true);

      const render = () => {
        analyser.getByteFrequencyData(dataArray);
        const { width, height } = canvas.getBoundingClientRect();
        canvas.width = width * (window.devicePixelRatio || 1);
        canvas.height = height * (window.devicePixelRatio || 1);
        ctx.scale(window.devicePixelRatio || 1, window.devicePixelRatio || 1);

        ctx.clearRect(0, 0, width, height);

        const barWidth = width / dataArray.length;
        dataArray.forEach((val, i) => {
          const barHeight = (val / 255) * (height - 4);
          const x = i * barWidth;
          const y = height - barHeight;

          const gradient = ctx.createLinearGradient(0, y, 0, height);
          gradient.addColorStop(0, "#CCD3E0"); // Ephemeral Blue highlight
          gradient.addColorStop(1, "#899FBC"); // Sailing base

          ctx.fillStyle = gradient;
          ctx.fillRect(x, y, barWidth - 1, barHeight);
        });

        rafRef.current = requestAnimationFrame(render);
      };

      render();
    } catch {
      setTestingMic(false);
    }
  };

  const stopMicTest = () => {
    if (rafRef.current) cancelAnimationFrame(rafRef.current);
    micStreamRef.current?.getTracks().forEach((t) => t.stop());
    audioCtxRef.current?.close();
    setTestingMic(false);
  };

  useEffect(() => {
    return () => {
      stopMicTest();
    };
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!callerId.trim() || !recipientId.trim() || connecting) return;
    stopMicTest();
    onStart(callerId.trim(), recipientId.trim(), audioMode);
  };

  return (
    <div className="min-h-[100dvh] bg-forensic-bg text-forensic-text flex flex-col selection:bg-forensic-accent/30 selection:text-white">
      {/* ── Editorial Top Navigation Bar ─────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b border-forensic-border bg-forensic-bg/95 px-6 py-3.5 backdrop-blur-xl sm:px-10">
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-forensic-accent/40 bg-forensic-panel/60 text-forensic-accent shadow-signal">
              <Shield size={19} />
            </div>
            <div className="flex items-center gap-2.5">
              <span className="text-base font-extrabold tracking-tight text-forensic-text">SatyaVoice</span>
              <span className="rounded-md border border-forensic-accent/30 bg-forensic-panel/80 px-2.5 py-0.5 font-mono text-[10px] font-bold text-forensic-accent uppercase tracking-wider">
                Forensic Intelligence
              </span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <StatusBadge label="Defense Engine Ready" variant="safe" pulse />
            <span className="hidden font-mono text-xs text-forensic-muted sm:inline">
              Polygon Amoy Anchor Active
            </span>
          </div>
        </div>
      </header>

      {/* ── Page Body ──────────────────────────────────────────── */}
      <div className="mx-auto w-full max-w-7xl flex-1 px-6 py-8 sm:px-10 lg:py-12">
        {/* Intelligence Chain Header Ribbon */}
        <div className="mb-8 rounded-2xl border border-forensic-border bg-forensic-surface/60 p-4 shadow-panel backdrop-blur">
          <div className="mb-2 flex items-center justify-between border-b border-forensic-border pb-2">
            <span className="eyebrow flex items-center gap-2">
              <Radio size={12} className="animate-pulse text-forensic-accent" />
              Intelligence Architecture Flow
            </span>
            <span className="font-mono text-[11px] text-forensic-muted">Continuous Multimodal Pipeline</span>
          </div>

          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {INTELLIGENCE_CHAIN.map((item, idx) => (
              <div
                key={item.step}
                className="group relative rounded-xl border border-forensic-border bg-forensic-panel/40 p-3 transition-all hover:border-forensic-accent/50 hover:bg-forensic-panel/80"
              >
                <div className="flex items-center justify-between font-mono text-[11px]">
                  <span className="font-extrabold text-forensic-accent">{item.step}</span>
                  {idx < INTELLIGENCE_CHAIN.length - 1 && (
                    <span className="hidden text-forensic-muted sm:inline">→</span>
                  )}
                </div>
                <p className="mt-1 text-xs font-bold text-forensic-text">{item.label}</p>
                <p className="mt-0.5 text-[11px] text-forensic-muted leading-tight">{item.desc}</p>
              </div>
            ))}
          </div>
        </div>

        {/* ── Main Editorial Asymmetric Grid ──────────────────────────────────── */}
        <div className="grid w-full grid-cols-1 items-start gap-10 lg:grid-cols-12 lg:gap-14">

          {/* ── LEFT: Product Experience & Signal Visualizer Showcase (7 cols) ── */}
          <section className="lg:col-span-7 flex flex-col gap-8">
            {/* Main Headline */}
            <div>
              <h1 className="text-3xl font-extrabold tracking-tight text-forensic-text sm:text-4xl lg:text-[2.85rem] lg:leading-[1.12]">
                Calm, precise, and sophisticated AI voice security.
              </h1>
              <p className="mt-4 max-w-2xl text-sm leading-relaxed text-forensic-muted">
                SatyaVoice secures financial desks, executive communications, and contact centers against
                synthetic deepfakes, AI voice clones, and social engineering extortion. Continuous acoustic
                spectrograms, speaker biometrics, and language intent are fused in real time to produce court-verifiable evidence.
              </p>
            </div>

            {/* Live Voice Signal Waveform Visualizer Section */}
            <div className="rounded-3xl border border-forensic-border bg-forensic-panel/60 p-6 shadow-elevated backdrop-blur">
              <div className="flex items-center justify-between border-b border-forensic-border pb-3.5">
                <div>
                  <p className="eyebrow">Real-Time Signal Engine</p>
                  <h2 className="mt-0.5 text-sm font-bold text-forensic-text">
                    Acoustic Waveform &amp; Spectral Monitor
                  </h2>
                </div>
                <button
                  type="button"
                  onClick={testingMic ? stopMicTest : startMicTest}
                  className={`flex items-center gap-2 rounded-xl border px-3.5 py-1.5 font-mono text-xs font-semibold transition-all ${
                    testingMic
                      ? "border-warn/50 bg-warn-bg text-warn"
                      : "border-forensic-accent/40 bg-forensic-accentMuted text-forensic-text hover:bg-forensic-accent/20"
                  }`}
                >
                  {testingMic ? <MicOff size={14} /> : <Mic size={14} />}
                  <span>{testingMic ? "Stop Mic Test" : "Test Live Signal"}</span>
                </button>
              </div>

              {/* Waveform Canvas */}
              <div className="relative mt-4 h-36 w-full rounded-2xl border border-forensic-border bg-forensic-bg/90 p-3 overflow-hidden">
                <canvas ref={canvasRef} className="h-full w-full rounded-lg" />
                {!testingMic && (
                  <div className="absolute inset-0 flex flex-col items-center justify-center text-center p-4 bg-forensic-bg/40 backdrop-blur-[2px]">
                    <Waves size={24} className="text-forensic-accent animate-pulse mb-1.5" />
                    <span className="font-mono text-xs font-semibold text-forensic-text">
                      16.0 kHz Mono PCM Stream Ready
                    </span>
                    <span className="text-[11px] text-forensic-muted mt-0.5">
                      Click "Test Live Signal" to verify local microphone input
                    </span>
                  </div>
                )}
              </div>

              <div className="mt-3 flex justify-between font-mono text-[10px] text-forensic-muted">
                <span>Base: Sailing #899FBC</span>
                <span>Highlights: Ephemeral Blue #CCD3E0</span>
                <span>VAD Window: 4.0s</span>
              </div>
            </div>

            {/* Three Security Pillars */}
            <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
              <div className="rounded-2xl border border-forensic-border bg-forensic-surface/50 p-4 transition-all hover:bg-forensic-surface">
                <div className="flex items-center gap-2 text-safe">
                  <ShieldCheck size={16} />
                  <span className="text-xs font-bold text-forensic-text">Zero Persistence</span>
                </div>
                <p className="mt-2 text-xs text-forensic-muted leading-relaxed">
                  Raw voice is ephemeral. Only SHA-256 hashes and encrypted vector telemetry are preserved.
                </p>
              </div>

              <div className="rounded-2xl border border-forensic-border bg-forensic-surface/50 p-4 transition-all hover:bg-forensic-surface">
                <div className="flex items-center gap-2 text-forensic-accent">
                  <Sparkles size={16} />
                  <span className="text-xs font-bold text-forensic-text">MMS-300M Model</span>
                </div>
                <p className="mt-2 text-xs text-forensic-muted leading-relaxed">
                  Fine-tuned Meta detector identifying vocoder artifacts, synthetic phase shifts, and neural speech.
                </p>
              </div>

              <div className="rounded-2xl border border-forensic-border bg-forensic-surface/50 p-4 transition-all hover:bg-forensic-surface">
                <div className="flex items-center gap-2 text-forensic-muted">
                  <Fingerprint size={16} />
                  <span className="text-xs font-bold text-forensic-text">Polygon Anchor</span>
                </div>
                <p className="mt-2 text-xs text-forensic-muted leading-relaxed">
                  Cryptographic Merkle tree roots committed to Polygon Amoy for immutable chain of custody.
                </p>
              </div>
            </div>
          </section>

          {/* ── RIGHT: Streamlined Session Setup Panel (5 cols) ───────────────── */}
          <section className="lg:col-span-5 lg:sticky lg:top-24">
            <div className="rounded-3xl border border-forensic-border bg-forensic-panel p-6 sm:p-7 shadow-elevated">
              {/* Panel Header */}
              <div className="border-b border-forensic-border pb-4 mb-5">
                <p className="eyebrow text-forensic-accent">Session Configuration</p>
                <h2 className="mt-1 text-xl font-extrabold tracking-tight text-forensic-text">
                  Target &amp; Monitoring Setup
                </h2>
                <p className="mt-1 text-xs text-forensic-muted">
                  Designate protected lines and select inspection pipeline mode.
                </p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-5">
                {/* Pipeline selector */}
                <div>
                  <label className="field-label mb-2.5 block">Inspection Pipeline Mode</label>
                  <div className="space-y-2">
                    {AUDIO_OPTIONS.map((opt) => {
                      const isSelected = audioMode === opt.mode;
                      const Icon = opt.icon;
                      return (
                        <button
                          type="button"
                          key={opt.mode}
                          onClick={() => setAudioMode(opt.mode)}
                          className={`group relative flex w-full items-start gap-3 rounded-2xl border p-3.5 text-left transition-all ${
                            isSelected
                              ? "border-forensic-accent bg-forensic-surface shadow-signal ring-1 ring-forensic-accent/30"
                              : "border-forensic-border bg-forensic-surface/40 hover:border-forensic-accent/40 hover:bg-forensic-surface/70"
                          }`}
                        >
                          <div
                            className={`mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl border transition-colors ${
                              isSelected
                                ? "border-forensic-accent bg-forensic-accent/20 text-forensic-accent"
                                : "border-forensic-border bg-forensic-surface text-forensic-muted group-hover:text-forensic-text"
                            }`}
                          >
                            <Icon size={14} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <div className="flex items-center justify-between gap-2">
                              <span
                                className={`text-xs font-bold tracking-tight ${
                                  isSelected ? "text-forensic-text" : "text-forensic-muted"
                                }`}
                              >
                                {opt.label}
                              </span>
                              <StatusBadge label={opt.badge} variant={opt.badgeVariant} size="sm" icon={false} />
                            </div>
                            <p className="mt-1 text-[11px] leading-relaxed text-forensic-muted">{opt.description}</p>
                            <p className="mt-1 font-mono text-[10px] text-forensic-muted/80">{opt.architecture}</p>
                          </div>
                          {isSelected && (
                            <div className="absolute right-3.5 top-3.5 text-forensic-accent">
                              <Check size={14} />
                            </div>
                          )}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Call party inputs */}
                <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
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
                    <span className="mt-1 block text-[11px] text-forensic-muted">Caller number identifier</span>
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
                    <span className="mt-1 block text-[11px] text-forensic-muted">Target operational terminal</span>
                  </div>
                </div>

                {/* Error */}
                {error && (
                  <div
                    role="alert"
                    className="flex items-start gap-2.5 rounded-2xl border border-danger/40 bg-danger-bg p-3.5 text-xs leading-relaxed text-danger"
                  >
                    <ShieldAlert size={16} className="shrink-0 mt-0.5" />
                    <div>
                      <span className="font-bold uppercase tracking-wider block">Connection Advisory</span>
                      <span>{error}</span>
                    </div>
                  </div>
                )}

                {/* Submit */}
                <button
                  type="submit"
                  disabled={connecting || !callerId.trim() || !recipientId.trim()}
                  className="group relative flex w-full items-center justify-center gap-2.5 rounded-2xl border border-forensic-accent/60 bg-forensic-accent px-5 py-3.5 text-sm font-extrabold tracking-wide text-forensic-bg transition-all hover:bg-white hover:shadow-lg active:scale-[0.99] disabled:cursor-not-allowed disabled:border-forensic-border disabled:bg-forensic-surface disabled:text-forensic-muted"
                >
                  {connecting ? (
                    <>
                      <span className="h-4 w-4 animate-spin rounded-full border-2 border-forensic-bg border-t-transparent" />
                      <span>Establishing Secure Stream Channel...</span>
                    </>
                  ) : (
                    <>
                      <span>Initiate Real-Time Voice Protection</span>
                      <ArrowRight size={16} className="transition-transform group-hover:translate-x-1" />
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

