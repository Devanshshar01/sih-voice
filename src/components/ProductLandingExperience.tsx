import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Cpu,
  Download,
  FileCheck,
  Fingerprint,
  Globe,
  Link,
  Lock,
  Mic,
  Radio,
  Shield,
  ShieldAlert,
  Zap,
} from "lucide-react";
import Spectrograph from "./Spectrograph";
import TrustGauge from "./TrustGauge";
import ThreatBreakdown from "./ThreatBreakdown";
import CallDashboard from "./CallDashboard";
import ForensicsView from "./ForensicsView";
import StatusBadge from "./StatusBadge";
import StartCallForm from "./StartCallForm";
import VerificationModal from "./VerificationModal";
import {
  verifyForensicsEvidence,
  verifyEvidenceIntegrity,
  downloadForensicReportPdf,
} from "../lib/api";
import type { RiskStatus } from "../types";

interface ProductLandingExperienceProps {
  session: ReturnType<typeof import("../hooks/useCallSession").useCallSession>;
}

export default function ProductLandingExperience({ session }: ProductLandingExperienceProps) {
  const {
    phase,
    meta,
    error,
    telemetry,
    analyser,
    verification,
    startNewCall,
    endCall,
    requestChallenge,
    setVerificationInput,
    submitVerification,
  } = session;

  // State management
  const [showSetupModal, setShowSetupModal] = useState(false);
  const [verifyingApi, setVerifyingApi] = useState(false);
  const [verificationResult, setVerificationResult] = useState<any>(null);
  const [showIntegrityResultModal, setShowIntegrityResultModal] = useState(false);
  const [downloadingReport, setDownloadingReport] = useState(false);
  const [expandTechDetails, setExpandTechDetails] = useState(false);

  // Hero interactive Canvas visualizer
  const heroCanvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = heroCanvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationFrame: number;
    let phaseOffset = 0;

    const renderWave = () => {
      const { width, height } = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.scale(dpr, dpr);

      ctx.clearRect(0, 0, width, height);

      // Multi-layer wave simulation in Blue Forensic colors
      const lines = [
        { color: "rgba(137, 159, 188, 0.85)", speed: 0.02, freq: 0.015, amp: 28 },
        { color: "rgba(204, 211, 224, 0.60)", speed: 0.03, freq: 0.022, amp: 18 },
        { color: "rgba(63, 88, 116, 0.40)", speed: 0.015, freq: 0.008, amp: 38 },
      ];

      phaseOffset += 0.02;

      lines.forEach((line) => {
        ctx.beginPath();
        ctx.lineWidth = 2;
        ctx.strokeStyle = line.color;

        for (let x = 0; x < width; x += 3) {
          const y =
            height / 2 +
            Math.sin(x * line.freq + phaseOffset * line.speed * 50) * line.amp +
            Math.cos(x * 0.005 + phaseOffset * 0.5) * 8;
          if (x === 0) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      });

      animationFrame = requestAnimationFrame(renderWave);
    };

    renderWave();
    return () => cancelAnimationFrame(animationFrame);
  }, []);

  const handleVerifyIntegrityClick = async () => {
    setVerifyingApi(true);
    try {
      const evidenceId = meta?.callId || "SV-2026-9842-DEMO";
      const res = await verifyEvidenceIntegrity(evidenceId);
      setVerificationResult(res);
      setShowIntegrityResultModal(true);
    } catch (e) {
      console.error(e);
    } finally {
      setVerifyingApi(false);
    }
  };

  const handleVerifyChainClick = async () => {
    setVerifyingApi(true);
    try {
      const evidenceId = meta?.callId || "SV-2026-9842-DEMO";
      const res = await verifyForensicsEvidence(evidenceId);
      setVerificationResult(res);
      setShowIntegrityResultModal(true);
    } catch (e) {
      console.error(e);
    } finally {
      setVerifyingApi(false);
    }
  };

  const handleDownloadPdf = async () => {
    const evidenceId = meta?.callId || "SV-2026-9842-DEMO";
    setDownloadingReport(true);
    try {
      const { blob } = await downloadForensicReportPdf(evidenceId);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `satya_voice_forensics_${evidenceId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("PDF report export error", e);
    } finally {
      setDownloadingReport(false);
    }
  };

  // Derive risk numbers from active telemetry or default baseline
  const currentRiskScore = telemetry?.risk_score ?? 18;
  const currentRiskStatus: RiskStatus = (telemetry?.status as RiskStatus) || "ALLOW";
  const acousticScore = telemetry?.acoustic_score ?? 0.14;
  const intentScore = telemetry?.intent_score ?? 0.12;
  const speakerSimilarity = telemetry?.speaker_score ?? 0.94;
  const rationale = telemetry?.rationale ?? [
    "Acoustic feature distribution within expected human thresholds.",
    "Speaker voiceprint matches enrolled baseline profile.",
    "Conversational intent parameters indicate low financial risk.",
  ];

  return (
    <div className="relative min-h-screen bg-forensic-bg text-forensic-text selection:bg-forensic-accent/30 selection:text-white">
      {/* ── STICKY NAVIGATION BAR ────────────────────────────────────── */}
      <nav className="sticky top-0 z-50 border-b border-forensic-border bg-forensic-bg/95 px-4 py-3.5 backdrop-blur-xl sm:px-8 transition-all">
        <div className="mx-auto flex max-w-7xl items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-forensic-accent/40 bg-forensic-surface text-forensic-accent shadow-signal">
              <Shield size={19} />
            </div>
            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <span className="text-base font-extrabold tracking-tight text-white">SatyaVoice</span>
                <span className="rounded-md border border-forensic-accent/30 bg-forensic-surface px-2 py-0.5 font-mono text-[10px] font-bold text-forensic-accent uppercase tracking-wider">
                  Forensic Intelligence
                </span>
              </div>
            </div>
          </div>

          {/* Nav Links */}
          <div className="hidden lg:flex items-center gap-6 text-xs font-semibold text-forensic-muted">
            <a href="#overview" className="transition-colors hover:text-white">Overview</a>
            <a href="#threat" className="transition-colors hover:text-white">The Threat</a>
            <a href="#signals" className="transition-colors hover:text-white">Signals</a>
            <a href="#live-intelligence" className="transition-colors hover:text-white">Live Monitor</a>
            <a href="#forensic-evidence" className="transition-colors hover:text-white">Forensics</a>
            <a href="#verification" className="transition-colors hover:text-white">Verification</a>
            <a href="#privacy" className="transition-colors hover:text-white">Privacy</a>
          </div>

          {/* Action CTAs */}
          <div className="flex items-center gap-3">
            {phase === "active" ? (
              <div className="flex items-center gap-3">
                <StatusBadge label="Call Monitored" variant="safe" pulse icon />
                <button
                  onClick={() => {
                    const el = document.getElementById("live-intelligence");
                    el?.scrollIntoView({ behavior: "smooth" });
                  }}
                  className="rounded-xl border border-forensic-accent/50 bg-forensic-accent/20 px-3.5 py-1.5 text-xs font-bold text-white transition-all hover:bg-forensic-accent hover:text-white"
                >
                  View Active Stream ↓
                </button>
              </div>
            ) : (
              <button
                onClick={() => setShowSetupModal(true)}
                className="flex items-center gap-2 rounded-xl bg-forensic-accent px-4 py-2 text-xs font-bold text-white shadow-signal transition-all hover:bg-sailing-hover hover:scale-[1.02] active:scale-[0.98]"
              >
                <Radio size={14} className="animate-pulse" />
                <span>Start Protection</span>
              </button>
            )}
          </div>
        </div>
      </nav>

      {/* ── SECTION 1: HERO VIEWPORT ─────────────────────────────────── */}
      <section id="overview" className="relative overflow-hidden border-b border-forensic-border px-5 py-20 sm:px-8 lg:py-28">
        <div className="mx-auto grid max-w-7xl gap-12 lg:grid-cols-12 lg:items-center">
          {/* Left Narrative Column */}
          <div className="lg:col-span-7 flex flex-col items-start space-y-6">
            <div className="inline-flex items-center gap-2.5 rounded-full border border-forensic-accent/40 bg-forensic-surface/80 px-3.5 py-1.5 text-xs font-bold text-forensic-accent">
              <span className="h-2 w-2 rounded-full bg-forensic-accent animate-pulse" />
              <span>SATYAVOICE · VOICE INTELLIGENCE / FRAUD DEFENSE</span>
            </div>

            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-black tracking-tight text-white leading-[1.1]">
              Protect the call <br />
              <span className="bg-gradient-to-r from-forensic-accent via-ephemeralBlue to-white bg-clip-text text-transparent">
                before trust becomes action.
              </span>
            </h1>

            <p className="max-w-2xl text-base sm:text-lg text-forensic-muted leading-relaxed">
              Real-time voice deepfake detection and financial call-fraud intelligence combining anti-spoofing, speaker verification, contextual intent analysis, and cryptographically verifiable forensics.
            </p>

            {/* Hero CTAs */}
            <div className="flex flex-wrap items-center gap-4 pt-2">
              <button
                onClick={() => setShowSetupModal(true)}
                className="flex items-center gap-2.5 rounded-xl bg-forensic-accent px-6 py-3.5 text-sm font-extrabold text-white shadow-signal transition-all hover:bg-sailing-hover hover:scale-[1.02] active:scale-[0.98]"
              >
                <Radio size={16} className="animate-pulse" />
                <span>START LIVE PROTECTION</span>
                <ArrowRight size={16} />
              </button>

              <a
                href="#forensic-evidence"
                className="flex items-center gap-2 rounded-xl border border-forensic-border bg-forensic-surface/60 px-6 py-3.5 text-sm font-bold text-forensic-text transition-all hover:border-forensic-accent hover:bg-forensic-surface"
              >
                <FileCheck size={16} className="text-forensic-accent" />
                <span>EXPLORE FORENSICS</span>
              </a>
            </div>

            {/* Trust Architecture Strip */}
            <div className="pt-6 border-t border-forensic-border/60 w-full">
              <span className="text-[11px] font-bold uppercase tracking-widest text-forensic-muted font-mono">
                ENGINEERED INTELLIGENCE STACK
              </span>
              <div className="mt-3 flex flex-wrap items-center gap-3 font-mono text-xs font-semibold text-forensic-text">
                <span className="rounded-lg border border-forensic-border bg-forensic-surface/70 px-2.5 py-1">MMS-300M</span>
                <span className="rounded-lg border border-forensic-border bg-forensic-surface/70 px-2.5 py-1">ECAPA-TDNN</span>
                <span className="rounded-lg border border-forensic-border bg-forensic-surface/70 px-2.5 py-1">WHISPER ASR</span>
                <span className="rounded-lg border border-forensic-border bg-forensic-surface/70 px-2.5 py-1">RFC 8785</span>
                <span className="rounded-lg border border-forensic-border bg-forensic-surface/70 px-2.5 py-1">POLYGON AMOY</span>
              </div>
            </div>
          </div>

          {/* Right Visual: Acoustic Waveform Canvas */}
          <div className="lg:col-span-5 relative flex items-center justify-center">
            <div className="relative w-full aspect-square max-w-md rounded-3xl border border-forensic-accent/30 bg-forensic-surface/40 p-6 shadow-elevated backdrop-blur-2xl overflow-hidden flex flex-col justify-between">
              {/* Card Header */}
              <div className="flex items-center justify-between border-b border-forensic-border/60 pb-3">
                <div className="flex items-center gap-2 text-xs font-bold text-white">
                  <Activity size={15} className="text-forensic-accent animate-pulse" />
                  <span>ACOUSTIC SIGNAL FIELD</span>
                </div>
                <span className="hud-badge hud-badge-safe">LIVE PCM MONITOR</span>
              </div>

              {/* Wave Canvas */}
              <div className="relative h-44 w-full my-auto flex items-center justify-center">
                <canvas ref={heroCanvasRef} className="h-full w-full" />
              </div>

              {/* Visual Metrics Footer */}
              <div className="grid grid-cols-3 gap-2 pt-3 border-t border-forensic-border/60 font-mono text-[11px]">
                <div className="flex flex-col">
                  <span className="text-[10px] text-forensic-muted uppercase">Sample Rate</span>
                  <span className="font-semibold text-white">16.0 kHz</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] text-forensic-muted uppercase">Window</span>
                  <span className="font-semibold text-white">4.0 sec</span>
                </div>
                <div className="flex flex-col">
                  <span className="text-[10px] text-forensic-muted uppercase">VAD State</span>
                  <span className="font-semibold text-safe">SPEECH DETECTED</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 2: THE THREAT ────────────────────────────────────── */}
      <section id="threat" className="border-b border-forensic-border bg-forensic-bg/60 px-5 py-20 sm:px-8">
        <div className="mx-auto max-w-7xl">
          <div className="max-w-3xl space-y-4">
            <span className="eyebrow">SECTION 02 · THREAT ANALYSIS</span>
            <h2 className="text-3xl sm:text-4xl lg:text-5xl font-black text-white leading-tight">
              VOICE CAN SOUND HUMAN <br />
              <span className="text-forensic-accent">WITHOUT BEING HUMAN.</span>
            </h2>
            <p className="text-base text-forensic-muted leading-relaxed">
              Generative AI voice cloning technology allows attackers to replicate biometrics, pressure finance teams, and manipulate transaction authorization protocols in seconds.
            </p>
          </div>

          <div className="mt-14 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
            <div className="surface-card p-6 flex flex-col justify-between space-y-4 hover:border-forensic-accent/50 transition-all">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-forensic-panel text-forensic-accent">
                <Mic size={20} />
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">Voice Cloning</h3>
                <p className="mt-2 text-xs text-forensic-muted leading-relaxed">
                  Generative neural acoustic synthesis trained on publicly accessible target audio snippets.
                </p>
              </div>
              <span className="font-mono text-[10px] text-forensic-accent uppercase font-bold">MMS-300M DETECTED</span>
            </div>

            <div className="surface-card p-6 flex flex-col justify-between space-y-4 hover:border-forensic-accent/50 transition-all">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-forensic-panel text-forensic-accent">
                <Zap size={20} />
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">Social Engineering</h3>
                <p className="mt-2 text-xs text-forensic-muted leading-relaxed">
                  High-pressure artificial urgency designed to bypass internal corporate transfer safeguards.
                </p>
              </div>
              <span className="font-mono text-[10px] text-forensic-accent uppercase font-bold">ASR INTENT SCANNED</span>
            </div>

            <div className="surface-card p-6 flex flex-col justify-between space-y-4 hover:border-forensic-accent/50 transition-all">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-forensic-panel text-forensic-accent">
                <Fingerprint size={20} />
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">Impersonation</h3>
                <p className="mt-2 text-xs text-forensic-muted leading-relaxed">
                  Synthetic speaker profiles attempting to mimic trusted executive voice prints.
                </p>
              </div>
              <span className="font-mono text-[10px] text-forensic-accent uppercase font-bold">ECAPA BIOMETRICS</span>
            </div>

            <div className="surface-card p-6 flex flex-col justify-between space-y-4 hover:border-forensic-accent/50 transition-all">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-forensic-panel text-forensic-accent">
                <ShieldAlert size={20} />
              </div>
              <div>
                <h3 className="text-lg font-bold text-white">Transaction Fraud</h3>
                <p className="mt-2 text-xs text-forensic-muted leading-relaxed">
                  Fraudulent wire authorization commands target high-value wire desks and treasury ops.
                </p>
              </div>
              <span className="font-mono text-[10px] text-danger uppercase font-bold">POLICY LOCK TRIGGER</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 3: WHAT SATYAVOICE SEES ──────────────────────────── */}
      <section id="signals" className="border-b border-forensic-border px-5 py-20 sm:px-8">
        <div className="mx-auto max-w-7xl">
          <div className="text-center max-w-2xl mx-auto space-y-3">
            <span className="eyebrow">SECTION 03 · MULTI-SIGNAL DECRYPTION</span>
            <h2 className="text-3xl sm:text-4xl font-black text-white">
              ONE VOICE BECOMES <br />
              <span className="text-forensic-accent">MULTIPLE THREAT SIGNALS.</span>
            </h2>
            <p className="text-sm text-forensic-muted">
              SatyaVoice decomposes incoming audio streams into three independent neural evaluation vectors.
            </p>
          </div>

          <div className="mt-14 grid gap-8 lg:grid-cols-3">
            {/* Pillar 1: Acoustic */}
            <div className="surface-card p-8 flex flex-col justify-between border-t-4 border-t-forensic-accent">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-bold text-forensic-accent">VECTOR 01</span>
                  <span className="hud-badge hud-badge-safe">nii-yamagishilab</span>
                </div>
                <h3 className="text-2xl font-extrabold text-white">ACOUSTIC</h3>
                <p className="text-xs text-forensic-muted leading-relaxed">
                  Evaluates phase anomalies, high-frequency spectral artifacts, and neural synthesis boundaries using the MMS-300M anti-deepfake architecture.
                </p>
              </div>
              <div className="mt-8 pt-4 border-t border-forensic-border/60 flex items-center justify-between font-mono text-xs">
                <span className="text-forensic-muted">Model</span>
                <span className="font-semibold text-white">MMS-300M Classifier</span>
              </div>
            </div>

            {/* Pillar 2: Identity */}
            <div className="surface-card p-8 flex flex-col justify-between border-t-4 border-t-forensic-accent">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-bold text-forensic-accent">VECTOR 02</span>
                  <span className="hud-badge hud-badge-safe">SpeechBrain</span>
                </div>
                <h3 className="text-2xl font-extrabold text-white">IDENTITY</h3>
                <p className="text-xs text-forensic-muted leading-relaxed">
                  Calculates 192-dimensional biometric embeddings using ECAPA-TDNN to compare live vocal resonance against enrolled speaker profiles.
                </p>
              </div>
              <div className="mt-8 pt-4 border-t border-forensic-border/60 flex items-center justify-between font-mono text-xs">
                <span className="text-forensic-muted">Embeddings</span>
                <span className="font-semibold text-white">ECAPA-TDNN 192D</span>
              </div>
            </div>

            {/* Pillar 3: Context */}
            <div className="surface-card p-8 flex flex-col justify-between border-t-4 border-t-forensic-accent">
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-bold text-forensic-accent">VECTOR 03</span>
                  <span className="hud-badge hud-badge-safe">Systran</span>
                </div>
                <h3 className="text-2xl font-extrabold text-white">CONTEXT</h3>
                <p className="text-xs text-forensic-muted leading-relaxed">
                  Transcribes speech in real-time via faster-whisper and scans token sequences for high-coercion transaction pressure indicators.
                </p>
              </div>
              <div className="mt-8 pt-4 border-t border-forensic-border/60 flex items-center justify-between font-mono text-xs">
                <span className="text-forensic-muted">ASR Engine</span>
                <span className="font-semibold text-white">faster-whisper Int8</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 4: LIVE VOICE INTELLIGENCE (INTERACTIVE WORKSPACE) ── */}
      <section id="live-intelligence" className="border-b border-forensic-border bg-forensic-bg/80 px-5 py-20 sm:px-8">
        <div className="mx-auto max-w-7xl space-y-10">
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
            <div>
              <span className="eyebrow">SECTION 04 · LIVE STREAM TELEMETRY</span>
              <h2 className="text-3xl sm:text-4xl font-black text-white">
                LIVE VOICE PROTECTION WORKSPACE
              </h2>
            </div>
            {phase === "active" && (
              <StatusBadge label="STREAMING LIVE TELEMETRY" variant="safe" pulse icon />
            )}
          </div>

          {phase === "active" ? (
            /* Active Call Session Workspace */
            <div className="space-y-6">
              <CallDashboard session={session} />
            </div>
          ) : (
            /* Idle Preview Workspace */
            <div className="surface-hero p-8 sm:p-12 space-y-8">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                <div className="space-y-2">
                  <span className="hud-badge hud-badge-safe">LIVE PROTECTION READY</span>
                  <h3 className="text-2xl sm:text-3xl font-extrabold text-white">
                    Start Monitoring an Incoming Audio Stream
                  </h3>
                  <p className="text-sm text-forensic-muted max-w-xl">
                    Connect your microphone to evaluate live voice authenticity, view real-time spectral energy, and monitor fused threat indices.
                  </p>
                </div>
                <button
                  onClick={() => setShowSetupModal(true)}
                  className="flex items-center gap-2.5 rounded-xl bg-forensic-accent px-6 py-4 text-sm font-extrabold text-white shadow-signal transition-all hover:bg-sailing-hover hover:scale-[1.02] active:scale-[0.98] self-start md:self-center"
                >
                  <Radio size={18} className="animate-pulse" />
                  <span>START LIVE PROTECTION NOW</span>
                </button>
              </div>

              {/* Simulated Live Preview Card */}
              <div className="grid gap-6 lg:grid-cols-12">
                <div className="lg:col-span-8 space-y-6">
                  <Spectrograph analyser={analyser} status={currentRiskStatus} />
                  <ThreatBreakdown
                    acousticScore={acousticScore}
                    intentScore={intentScore}
                    speakerSimilarity={speakerSimilarity}
                    rationale={rationale}
                    status={currentRiskStatus}
                  />
                </div>
                <div className="lg:col-span-4 surface-card p-6 flex flex-col justify-between">
                  <TrustGauge score={currentRiskScore} status={currentRiskStatus} />
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── SECTION 5: HOW ANALYSIS WORKS (PROCESS PIPELINE) ─────────── */}
      <section id="process" className="border-b border-forensic-border px-5 py-20 sm:px-8">
        <div className="mx-auto max-w-7xl space-y-12">
          <div className="max-w-2xl space-y-3">
            <span className="eyebrow">SECTION 05 · ARCHITECTURAL PIPELINE</span>
            <h2 className="text-3xl sm:text-4xl font-black text-white">
              HOW THE ANALYSIS WORKS
            </h2>
            <p className="text-sm text-forensic-muted">
              From raw microphone PCM audio to an immutable on-chain cryptographic proof package.
            </p>
          </div>

          {/* 7-Step Process Diagram */}
          <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-7">
            {[
              { step: "01", name: "AUDIO", desc: "16 kHz Mono PCM" },
              { step: "02", name: "VAD", desc: "Silero Speech Filter" },
              { step: "03", name: "ANTI-SPOOF", desc: "MMS-300M Classifier" },
              { step: "04", name: "ASR", desc: "faster-whisper Int8" },
              { step: "05", name: "SPEAKER", desc: "ECAPA Biometrics" },
              { step: "06", name: "RISK", desc: "Dynamic Risk Engine" },
              { step: "07", name: "EVIDENCE", desc: "RFC 8785 + Polygon" },
            ].map((item, idx) => (
              <div key={idx} className="surface-card p-4 flex flex-col justify-between space-y-3">
                <div className="flex items-center justify-between font-mono text-xs">
                  <span className="font-bold text-forensic-accent">{item.step}</span>
                  {idx < 6 && <ChevronRight size={14} className="text-forensic-muted hidden lg:block" />}
                </div>
                <div>
                  <h4 className="font-bold text-white text-sm">{item.name}</h4>
                  <p className="text-[11px] text-forensic-muted mt-1">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>

          {/* Technical Expandable Specs */}
          <div className="surface-card p-6">
            <button
              onClick={() => setExpandTechDetails(!expandTechDetails)}
              className="flex items-center justify-between w-full text-left font-semibold text-white text-sm"
            >
              <div className="flex items-center gap-2">
                <Cpu size={16} className="text-forensic-accent" />
                <span>Technical Execution Specifications</span>
              </div>
              <ChevronDown size={16} className={`transition-transform ${expandTechDetails ? "rotate-180" : ""}`} />
            </button>

            {expandTechDetails && (
              <div className="mt-4 pt-4 border-t border-forensic-border/60 grid gap-4 sm:grid-cols-3 font-mono text-xs text-forensic-muted">
                <div>
                  <span className="text-[10px] uppercase font-bold text-forensic-accent">Audio Buffering</span>
                  <p className="mt-1 text-white">16 kHz PCM · 4.0s Rolling Window · 0.5s Hop Size</p>
                </div>
                <div>
                  <span className="text-[10px] uppercase font-bold text-forensic-accent">Inference Refresh</span>
                  <p className="mt-1 text-white">~15.0s Heavy GPU Refresh · 30.0s Stale Ceiling</p>
                </div>
                <div>
                  <span className="text-[10px] uppercase font-bold text-forensic-accent">Canonicalization</span>
                  <p className="mt-1 text-white">RFC 8785 JSON · SHA-256 · Merkle Root Audit</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* ── SECTION 6: RISK ENGINE & THREAT CONTINUUM ────────────────── */}
      <section id="risk-engine" className="border-b border-forensic-border bg-forensic-bg/60 px-5 py-20 sm:px-8">
        <div className="mx-auto max-w-7xl space-y-12">
          <div className="text-center max-w-2xl mx-auto space-y-3">
            <span className="eyebrow">SECTION 06 · MULTI-SIGNAL FUSION</span>
            <h2 className="text-3xl sm:text-4xl font-black text-white">
              DYNAMIC RISK ENGINE
            </h2>
            <p className="text-sm text-forensic-muted">
              Weighted mathematical combination of acoustic authenticity, biometric identity match, and threat context.
            </p>
          </div>

          <div className="surface-card p-8 sm:p-12 space-y-8 max-w-4xl mx-auto">
            <div className="flex flex-wrap items-center justify-center gap-4 text-center font-extrabold text-lg text-white">
              <span className="rounded-xl border border-forensic-border bg-forensic-surface px-4 py-2">ACOUSTIC (40%)</span>
              <span className="text-forensic-accent">+</span>
              <span className="rounded-xl border border-forensic-border bg-forensic-surface px-4 py-2">IDENTITY (35%)</span>
              <span className="text-forensic-accent">+</span>
              <span className="rounded-xl border border-forensic-border bg-forensic-surface px-4 py-2">CONTEXT (25%)</span>
              <span className="text-forensic-accent">=</span>
              <span className="rounded-xl border border-forensic-accent bg-forensic-accent/20 px-5 py-2 text-forensic-accent">
                FUSED RISK INDEX
              </span>
            </div>

            <div className="pt-6 border-t border-forensic-border/60">
              <TrustGauge score={currentRiskScore} status={currentRiskStatus} />
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 7: WHEN THINGS GO WRONG (NARRATIVE BRIDGE) ───────── */}
      <section className="border-b border-forensic-border bg-gradient-to-b from-forensic-bg to-forensic-surface/40 px-5 py-24 sm:px-8 text-center">
        <div className="mx-auto max-w-4xl space-y-6">
          <span className="eyebrow">SECTION 07 · DIGITAL EVIDENCE</span>
          <h2 className="text-3xl sm:text-5xl font-black text-white leading-tight">
            WHEN A VOICE BECOMES SUSPICIOUS, <br />
            <span className="text-forensic-accent">SATYAVOICE DOESN'T STOP AT A SCORE.</span>
          </h2>
          <p className="text-base text-forensic-muted max-w-2xl mx-auto leading-relaxed">
            Every detection event triggers an automatic cryptographic evidence capture sequence, building an immutable dossier ready for legal and financial audit.
          </p>

          <div className="pt-6 flex justify-center">
            <div className="flex items-center gap-4 font-mono text-xs font-bold text-forensic-text">
              <span>SUSPICIOUS CALL</span>
              <ArrowRight size={16} className="text-forensic-accent" />
              <span>RISK DECISION</span>
              <ArrowRight size={16} className="text-forensic-accent" />
              <span className="text-forensic-accent">FORENSIC CASE</span>
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 8: FORENSIC EVIDENCE WORKSPACE ──────────────────── */}
      <section id="forensic-evidence" className="border-b border-forensic-border px-5 py-20 sm:px-8">
        <div className="mx-auto max-w-7xl space-y-10">
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
            <div>
              <span className="eyebrow">SECTION 08 · INVESTIGATION WORKSPACE</span>
              <h2 className="text-3xl sm:text-4xl font-black text-white">
                DIGITAL FORENSIC EVIDENCE DOSSIER
              </h2>
            </div>
            <button
              onClick={handleDownloadPdf}
              disabled={downloadingReport}
              className="flex items-center gap-2 rounded-xl bg-forensic-accent px-4 py-2 text-xs font-bold text-white shadow-signal transition-all hover:bg-sailing-hover"
            >
              <Download size={14} />
              <span>{downloadingReport ? "Generating PDF..." : "EXPORT PDF REPORT"}</span>
            </button>
          </div>

          {phase === "ended" ? (
            <ForensicsView session={session} />
          ) : (
            <div className="surface-card p-8 space-y-6">
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-forensic-border/60 pb-4">
                <div>
                  <span className="text-xs text-forensic-muted uppercase font-mono">CASE DOSSIER PREVIEW</span>
                  <h3 className="text-xl font-bold text-white font-mono mt-0.5">SV-2026-9842-DEMO</h3>
                </div>
                <span className="hud-badge hud-badge-safe font-mono">STANDBY FOR CASE CAPTURE</span>
              </div>

              <div className="grid gap-6 md:grid-cols-3 font-mono text-xs">
                <div className="space-y-1 bg-forensic-bg/60 p-4 rounded-xl border border-forensic-border/40">
                  <span className="text-forensic-muted text-[10px] uppercase">SHA-256 Digest</span>
                  <p className="text-white truncate">7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069</p>
                </div>
                <div className="space-y-1 bg-forensic-bg/60 p-4 rounded-xl border border-forensic-border/40">
                  <span className="text-forensic-muted text-[10px] uppercase">Merkle Root</span>
                  <p className="text-white truncate">4b89c211a76e9f12d8a5522b109e44319082a5c1d6e7f80b91a2c3d4e5f6a7b8</p>
                </div>
                <div className="space-y-1 bg-forensic-bg/60 p-4 rounded-xl border border-forensic-border/40">
                  <span className="text-forensic-muted text-[10px] uppercase">Blockchain Anchor</span>
                  <p className="text-safe font-bold">Polygon Amoy (Chain 80002)</p>
                </div>
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── SECTION 9 & 10: CRYPTOGRAPHIC & BLOCKCHAIN PIPELINE ─────── */}
      <section id="verification" className="border-b border-forensic-border bg-forensic-bg/80 px-5 py-20 sm:px-8">
        <div className="mx-auto max-w-7xl space-y-12">
          <div className="text-center max-w-2xl mx-auto space-y-3">
            <span className="eyebrow">SECTION 09 &amp; 10 · CRYPTOGRAPHIC AUDIT &amp; BLOCKCHAIN</span>
            <h2 className="text-3xl sm:text-4xl font-black text-white">
              CRYPTOGRAPHIC TRUST CHAIN
            </h2>
            <p className="text-sm text-forensic-muted">
              RFC 8785 JSON canonicalization guarantees zero-tamper evidence integrity before anchoring to the Polygon Amoy blockchain.
            </p>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            {/* Cryptographic Pipeline Card */}
            <div className="surface-card p-8 space-y-6">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-forensic-panel text-forensic-accent">
                  <Lock size={20} />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-white">RFC 8785 Canonicalization</h3>
                  <span className="text-xs text-forensic-muted">Deterministic Proof Normalization</span>
                </div>
              </div>
              <p className="text-xs text-forensic-muted leading-relaxed">
                Before hashing, telemetry JSON payloads are normalized using RFC 8785 rules to eliminate whitespace and key ordering variance.
              </p>
              <div className="font-mono text-xs bg-forensic-bg p-3 rounded-lg border border-forensic-border/40 text-forensic-accent">
                RAW JSON → RFC 8785 → SHA-256 → MERKLE LEAF
              </div>
            </div>

            {/* Blockchain Card */}
            <div className="surface-card p-8 space-y-6">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-forensic-panel text-forensic-accent">
                  <Globe size={20} />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-white">Polygon Amoy Integrity Anchor</h3>
                  <span className="text-xs text-forensic-muted">Chain ID 80002 Testnet</span>
                </div>
              </div>
              <p className="text-xs text-forensic-muted leading-relaxed">
                Merkle roots are periodically committed to an immutable smart contract ledger, providing publicly verifiable proof of timeline integrity.
              </p>
              <div className="font-mono text-xs bg-forensic-bg p-3 rounded-lg border border-forensic-border/40 text-safe font-bold flex items-center justify-between">
                <span>ON-CHAIN ANCHOR</span>
                <span>CHAIN ID 80002</span>
              </div>
            </div>
          </div>

          {/* Verification Actions */}
          <div className="surface-card p-8 flex flex-col sm:flex-row sm:items-center justify-between gap-6 border-t-2 border-t-forensic-accent">
            <div>
              <h3 className="text-xl font-bold text-white">Verify Cryptographic Certificate</h3>
              <p className="text-xs text-forensic-muted mt-1">
                Execute independent cryptographic integrity validation against local hashes and on-chain ledgers.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={handleVerifyIntegrityClick}
                disabled={verifyingApi}
                className="flex items-center gap-2 rounded-xl bg-forensic-accent px-5 py-3 text-xs font-bold text-white shadow-signal transition-all hover:bg-sailing-hover"
              >
                <CheckCircle2 size={15} />
                <span>{verifyingApi ? "Verifying..." : "VERIFY INTEGRITY"}</span>
              </button>
              <button
                onClick={handleVerifyChainClick}
                disabled={verifyingApi}
                className="flex items-center gap-2 rounded-xl border border-forensic-border bg-forensic-surface px-5 py-3 text-xs font-bold text-forensic-text transition-all hover:border-forensic-accent"
              >
                <Link size={15} className="text-forensic-accent" />
                <span>VERIFY CHAIN</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 13: PRIVACY MODEL ────────────────────────────────── */}
      <section id="privacy" className="border-b border-forensic-border px-5 py-20 sm:px-8">
        <div className="mx-auto max-w-4xl text-center space-y-6">
          <span className="eyebrow">SECTION 13 · ZERO AUDIO RETENTION PRIVACY</span>
          <h2 className="text-3xl sm:text-4xl font-black text-white leading-tight">
            YOUR VOICE DOESN'T NEED TO LIVE ON OUR SERVERS <br />
            <span className="text-forensic-accent">TO BE DEFENDED.</span>
          </h2>
          <p className="text-sm text-forensic-muted max-w-2xl mx-auto leading-relaxed">
            SatyaVoice operates on a transient zero-retention privacy architecture. Raw voice streams are evaluated strictly in volatile RAM memory and immediately discarded.
          </p>

          <div className="pt-6 grid gap-4 sm:grid-cols-4 font-mono text-xs text-left">
            <div className="surface-card p-4">
              <span className="text-[10px] text-forensic-accent uppercase font-bold">STAGE 01</span>
              <p className="text-white font-bold mt-1">RAW AUDIO</p>
              <p className="text-[11px] text-forensic-muted mt-1">Transient 16 kHz PCM stream</p>
            </div>
            <div className="surface-card p-4">
              <span className="text-[10px] text-forensic-accent uppercase font-bold">STAGE 02</span>
              <p className="text-white font-bold mt-1">VOLATILE RAM</p>
              <p className="text-[11px] text-forensic-muted mt-1">Neural feature extraction</p>
            </div>
            <div className="surface-card p-4">
              <span className="text-[10px] text-forensic-accent uppercase font-bold">STAGE 03</span>
              <p className="text-white font-bold mt-1">DERIVED DATA</p>
              <p className="text-[11px] text-forensic-muted mt-1">Mathematical score vectors</p>
            </div>
            <div className="surface-card p-4">
              <span className="text-[10px] text-forensic-accent uppercase font-bold">STAGE 04</span>
              <p className="text-white font-bold mt-1">PROOF COMMIT</p>
              <p className="text-[11px] text-forensic-muted mt-1">Zero raw audio on-chain</p>
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 14 & 15: WHY SATYAVOICE & TECHNICAL STACK ───────── */}
      <section id="tech-stack" className="border-b border-forensic-border bg-forensic-bg/60 px-5 py-20 sm:px-8">
        <div className="mx-auto max-w-7xl space-y-16">
          {/* Why SatyaVoice: 4 Pillars */}
          <div className="space-y-8">
            <div className="space-y-2">
              <span className="eyebrow">SECTION 14 · ARCHITECTURAL PILLARS</span>
              <h2 className="text-3xl sm:text-4xl font-black text-white">WHY SATYAVOICE</h2>
            </div>

            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
              <div className="surface-card p-6 space-y-3">
                <span className="font-mono text-2xl font-black text-forensic-accent">01</span>
                <h3 className="text-lg font-bold text-white">Detect</h3>
                <p className="text-xs text-forensic-muted leading-relaxed">
                  Real-time MMS-300M acoustic deepfake classification catches synthetic speech artifacts instantly.
                </p>
              </div>

              <div className="surface-card p-6 space-y-3">
                <span className="font-mono text-2xl font-black text-forensic-accent">02</span>
                <h3 className="text-lg font-bold text-white">Understand</h3>
                <p className="text-xs text-forensic-muted leading-relaxed">
                  ECAPA biometrics and faster-whisper intent parsing analyze identity and conversational context.
                </p>
              </div>

              <div className="surface-card p-6 space-y-3">
                <span className="font-mono text-2xl font-black text-forensic-accent">03</span>
                <h3 className="text-lg font-bold text-white">Preserve</h3>
                <p className="text-xs text-forensic-muted leading-relaxed">
                  RFC 8785 JSON canonicalization ensures tamper-proof forensic evidence logging.
                </p>
              </div>

              <div className="surface-card p-6 space-y-3">
                <span className="font-mono text-2xl font-black text-forensic-accent">04</span>
                <h3 className="text-lg font-bold text-white">Verify</h3>
                <p className="text-xs text-forensic-muted leading-relaxed">
                  Independent on-chain Polygon Merkle anchoring guarantees legally auditable proof.
                </p>
              </div>
            </div>
          </div>

          {/* Technical Stack Grid */}
          <div className="space-y-6 pt-10 border-t border-forensic-border/60">
            <span className="eyebrow">SECTION 15 · PRODUCTION MODELS &amp; FRAMEWORKS</span>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 font-mono text-xs">
              {[
                "MMS-300M",
                "faster-whisper",
                "ECAPA-TDNN",
                "Silero VAD",
                "FastAPI 0.110+",
                "React / TypeScript",
                "ONNX Web",
                "RFC 8785",
                "SHA-256",
                "Merkle Trees",
                "Polygon Amoy",
                "WebSockets PCM",
              ].map((tech, i) => (
                <div key={i} className="surface-card p-3 text-center font-semibold text-white truncate">
                  {tech}
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 16: FINAL CTA & FOOTER ─────────────────────────── */}
      <section className="relative px-5 py-24 sm:px-8 text-center bg-gradient-to-b from-forensic-bg to-blueWhale-deep">
        <div className="mx-auto max-w-4xl space-y-8">
          <h2 className="text-4xl sm:text-6xl font-black text-white leading-tight">
            VOICE CAN BE CLONED. <br />
            <span className="text-forensic-accent">TRUST SHOULDN'T BE.</span>
          </h2>

          <div className="flex flex-wrap items-center justify-center gap-4 pt-4">
            <button
              onClick={() => setShowSetupModal(true)}
              className="flex items-center gap-2.5 rounded-xl bg-forensic-accent px-8 py-4 text-sm font-extrabold text-white shadow-signal transition-all hover:bg-sailing-hover hover:scale-[1.02] active:scale-[0.98]"
            >
              <Radio size={18} className="animate-pulse" />
              <span>START LIVE PROTECTION</span>
              <ArrowRight size={18} />
            </button>

            <a
              href="#verification"
              className="flex items-center gap-2 rounded-xl border border-forensic-border bg-forensic-surface px-8 py-4 text-sm font-bold text-forensic-text transition-all hover:border-forensic-accent"
            >
              <Lock size={18} className="text-forensic-accent" />
              <span>VIEW FORENSIC VERIFICATION</span>
            </a>
          </div>

          <footer className="pt-20 border-t border-forensic-border/40 text-xs text-forensic-muted flex flex-col sm:flex-row items-center justify-between gap-4 font-mono">
            <div className="flex items-center gap-2">
              <Shield size={14} className="text-forensic-accent" />
              <span className="font-bold text-white">SatyaVoice Forensic Intelligence</span>
              <span>© 2026</span>
            </div>
            <div className="flex items-center gap-4">
              <span>Polygon Amoy (80002)</span>
              <span>·</span>
              <span>16 kHz Mono PCM</span>
              <span>·</span>
              <span className="text-safe font-bold">ALL SYSTEMS NOMINAL</span>
            </div>
          </footer>
        </div>
      </section>

      {/* ── CALL SETUP MODAL ────────────────────────────────────────── */}
      {showSetupModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-md overflow-y-auto">
          <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-3xl border border-forensic-accent/40 bg-forensic-bg p-6 shadow-elevated">
            <button
              onClick={() => setShowSetupModal(false)}
              className="absolute top-5 right-5 rounded-full border border-forensic-border bg-forensic-surface p-2 text-forensic-muted hover:text-white hover:border-forensic-accent"
            >
              ✕
            </button>
            <StartCallForm
              onStart={(c, r, m) => {
                setShowSetupModal(false);
                startNewCall(c, r, m);
              }}
              error={error}
              connecting={phase === "connecting"}
            />
          </div>
        </div>
      )}

      {/* ── VERIFICATION CODE CHALLENGE MODAL (FOR LIVE MFA STEP-UP) ── */}
      {verification.deliveredCode && (
        <VerificationModal
          verification={verification}
          onRequestCode={requestChallenge}
          onInputChange={setVerificationInput}
          onSubmit={submitVerification}
          onTerminate={endCall}
        />
      )}

      {/* ── INTEGRITY / CHAIN RESULT DIALOG ──────────────────────────── */}
      {showIntegrityResultModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-md">
          <div className="w-full max-w-lg rounded-2xl border border-forensic-accent/40 bg-forensic-bg p-6 space-y-4 shadow-elevated">
            <div className="flex items-center justify-between border-b border-forensic-border pb-3">
              <span className="font-mono text-xs font-bold text-forensic-accent">CRYPTOGRAPHIC INTEGRITY REPORT</span>
              <button
                onClick={() => setShowIntegrityResultModal(false)}
                className="text-forensic-muted hover:text-white"
              >
                ✕
              </button>
            </div>
            <pre className="font-mono text-xs bg-forensic-surface p-4 rounded-xl text-white overflow-x-auto max-h-60">
              {JSON.stringify(verificationResult, null, 2)}
            </pre>
            <button
              onClick={() => setShowIntegrityResultModal(false)}
              className="w-full rounded-xl bg-forensic-accent py-2.5 text-xs font-bold text-white shadow-signal"
            >
              Close Verification Audit
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
