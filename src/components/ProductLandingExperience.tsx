import { useState } from "react";
import {
  Activity,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Download,
  Fingerprint,
  Link,
  Mic,
  Play,
  Shield,
  Star,
  User,
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
import ShapeWaves from "./ShapeWaves";
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
    <div className="relative min-h-screen bg-[#080B11] text-[#0F172A] selection:bg-[#C084FC]/30 selection:text-[#0F172A]">
      {/* ── SECTION 1: CLOUDPILOT VIBRANT PURPLE/VIOLET HERO ─────────── */}
      <section id="overview" className="hero-cloudpilot-bg relative overflow-hidden text-white">
        {/* ShapeWaves Ambient Interactive Wavefield (covers full hero from top:0) */}
        <div className="absolute inset-0 z-0 pointer-events-auto opacity-40">
          <ShapeWaves
            text=""
            shapes="mixed"
            cellSize={14}
            dotSize={0.72}
            color="#7C3AED"
            hoverColor="#E879F9"
            backgroundColor="transparent"
            speed={0.8}
            scale={1.3}
            contrast={0.9}
            brightness={0.32}
            flow={0.15}
            direction={35}
            fade={0.4}
            interactive={true}
            splashRadius={50}
            splashStrength={0.55}
            glow={0.25}
            intro={true}
            introDuration={1.5}
            paused={false}
          />
        </div>

        {/* Ambient luminous glow overlay */}
        <div className="pointer-events-none absolute -top-24 left-1/2 -translate-x-1/2 h-[500px] w-[800px] rounded-full bg-gradient-to-b from-[#A855F7]/25 via-[#EC4899]/15 to-transparent blur-[120px] -z-0" />

        {/* ── TOP NAVBAR (FLOATING GLASSMORPHIC DIRECTLY OVER SHAPEWAVES) ───── */}
        <nav className="sticky top-0 z-50 px-4 py-3 sm:px-6 sm:py-4 transition-all">
          <div className="mx-auto flex max-w-7xl items-center justify-between gap-4 rounded-full border border-white/15 bg-[#080B11]/70 px-6 py-3 shadow-[0_8px_32px_0_rgba(0,0,0,0.45)] backdrop-blur-2xl">
            <div className="flex items-center gap-3">
              {/* Brand Logo: Gradient Circle Icon */}
              <div className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-tr from-[#7C3AED] via-[#A855F7] to-[#EC4899] text-white shadow-[0_0_15px_rgba(168,85,247,0.5)]">
                <Shield size={18} />
              </div>
              <span className="text-lg font-extrabold tracking-tight text-white">SatyaVoice</span>
            </div>

            {/* Nav Dropdown Links */}
            <div className="hidden lg:flex items-center gap-8 text-xs font-semibold text-slate-300">
              <a href="#overview" className="transition-colors hover:text-white flex items-center gap-1">
                <span>Product</span>
                <ChevronDown size={13} className="text-slate-400" />
              </a>
              <a href="#threat" className="transition-colors hover:text-white flex items-center gap-1">
                <span>Solutions</span>
                <ChevronDown size={13} className="text-slate-400" />
              </a>
              <a href="#signals" className="transition-colors hover:text-white">Signals</a>
              <a href="#live-intelligence" className="transition-colors hover:text-white flex items-center gap-1">
                <span>Live Monitor</span>
                <ChevronDown size={13} className="text-slate-400" />
              </a>
              <a href="#forensic-evidence" className="transition-colors hover:text-white">Forensics</a>
              <a href="#verification" className="transition-colors hover:text-white">Verification</a>
            </div>

            {/* Action CTAs: Solid White Pill Button + Profile */}
            <div className="flex items-center gap-3">
              {phase === "active" ? (
                <div className="flex items-center gap-3">
                  <StatusBadge label="Call Monitored" variant="safe" pulse icon />
                  <button
                    onClick={() => {
                      const el = document.getElementById("live-intelligence");
                      el?.scrollIntoView({ behavior: "smooth" });
                    }}
                    className="rounded-full bg-white px-5 py-2 text-xs font-bold text-[#080B11] shadow-lg transition-all hover:bg-slate-100"
                  >
                    Active Session ↓
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <button
                    onClick={() => setShowSetupModal(true)}
                    className="rounded-full bg-white px-5 py-2 text-xs font-bold text-[#080B11] shadow-lg transition-all hover:bg-slate-100 hover:scale-[1.03] active:scale-[0.98]"
                  >
                    Get Started
                  </button>
                  <div className="flex h-8 w-8 items-center justify-center rounded-full border border-white/20 bg-white/10 text-white">
                    <User size={15} />
                  </div>
                </div>
              )}
            </div>
          </div>
        </nav>

        <div className="relative z-10 mx-auto max-w-7xl space-y-16 px-6 pt-10 pb-28 sm:px-8 lg:pt-16 lg:pb-36">
          {/* Hero Content Grid */}
          <div className="grid gap-12 lg:grid-cols-12 lg:items-center">
            {/* Left Headline */}
            <div className="lg:col-span-7 space-y-6">
              {/* Eyebrow Pill */}
              <div className="inline-flex items-center gap-2 rounded-full border border-[#E879F9]/40 bg-[#3B1278]/60 px-3.5 py-1.5 text-xs font-bold text-[#F0ABFC] backdrop-blur-md shadow-[0_0_12px_rgba(232,121,249,0.2)]">
                <span>⚡</span>
                <span className="uppercase tracking-wider">All-In-One Voice Defense Platform</span>
                <span>⚡</span>
              </div>

              {/* Main Headline */}
              <h1 className="text-4xl sm:text-6xl lg:text-[68px] font-black tracking-tight text-white leading-[1.05] drop-shadow-[0_2px_24px_rgba(0,0,0,0.8)]">
                Simplify. <br />
                Protect. <br />
                <span className="bg-gradient-to-r from-[#F0ABFC] via-[#F472B6] to-[#C4B5FD] bg-clip-text text-transparent drop-shadow-none">
                  Secure Your Voice.
                </span> <br />
                All in One Platform.
              </h1>
            </div>

            {/* Right Subtitle & CTAs */}
            <div className="lg:col-span-5 space-y-8 flex flex-col justify-center">
              <p className="text-base sm:text-lg text-white/90 leading-relaxed max-w-md drop-shadow-[0_1px_12px_rgba(0,0,0,0.7)]">
                SatyaVoice empowers teams to detect voice deepfakes, verify caller biometrics, and prevent wire fraud in real-time — faster than ever.
              </p>

              {/* CTAs */}
              <div className="flex flex-wrap items-center gap-4">
                <button
                  onClick={() => setShowSetupModal(true)}
                  className="rounded-full bg-white px-7 py-3.5 text-sm font-extrabold text-[#080B11] shadow-2xl transition-all hover:bg-slate-100 hover:scale-[1.03] active:scale-[0.98]"
                >
                  Start Free Trial
                </button>

                <a
                  href="#live-intelligence"
                  className="flex items-center gap-2 rounded-full px-6 py-3.5 text-sm font-bold text-white transition-all hover:text-[#C084FC]"
                >
                  <span>Watch Demo</span>
                  <div className="flex h-7 w-7 items-center justify-center rounded-full bg-white/20 text-white">
                    <Play size={12} fill="white" />
                  </div>
                </a>
              </div>
            </div>
          </div>

          {/* Bottom Hero Strip: Reviews & 3D Floating Feature Cards */}
          <div className="grid gap-8 lg:grid-cols-12 items-center pt-8 border-t border-white/10">
            {/* Left Customer Review Strip */}
            <div className="lg:col-span-5 flex flex-wrap items-center gap-6">
              {/* Avatar Stack */}
              <div className="flex -space-x-2">
                <div className="h-9 w-9 rounded-full border-2 border-[#080B11] bg-gradient-to-tr from-purple-400 to-indigo-500 flex items-center justify-center text-xs font-bold">
                  JS
                </div>
                <div className="h-9 w-9 rounded-full border-2 border-[#080B11] bg-gradient-to-tr from-pink-400 to-rose-500 flex items-center justify-center text-xs font-bold">
                  RK
                </div>
                <div className="h-9 w-9 rounded-full border-2 border-[#080B11] bg-gradient-to-tr from-blue-400 to-cyan-500 flex items-center justify-center text-xs font-bold">
                  AN
                </div>
              </div>

              <div>
                <div className="flex items-center gap-1 text-[#FBBF24]">
                  {[...Array(5)].map((_, i) => (
                    <Star key={i} size={14} fill="#FBBF24" />
                  ))}
                </div>
                <p className="text-xs font-bold text-slate-200 mt-0.5">12,540+ calls protected</p>
              </div>

              <a href="#signals" className="text-xs font-bold text-white underline underline-offset-4 hover:text-[#E879F9]">
                Explore Platform →
              </a>
            </div>

            {/* Right 3 Floating 3D Cards */}
            <div className="lg:col-span-7 grid grid-cols-3 gap-4">
              {/* Card 1: Purple 3D Cloud */}
              <div className="relative aspect-square rounded-2xl bg-gradient-to-br from-[#A855F7] to-[#7C3AED] p-4 flex flex-col items-center justify-center shadow-xl hover:scale-[1.04] transition-all">
                <div className="h-12 w-12 rounded-2xl bg-white/20 backdrop-blur-md flex items-center justify-center text-white shadow-inner">
                  <Mic size={24} />
                </div>
                <span className="mt-2 text-[11px] font-bold text-white/90">Acoustic AI</span>
              </div>

              {/* Card 2: Pink 3D Layers */}
              <div className="relative aspect-square rounded-2xl bg-gradient-to-br from-[#EC4899] to-[#F43F5E] p-4 flex flex-col items-center justify-center shadow-xl hover:scale-[1.04] transition-all">
                <div className="h-12 w-12 rounded-2xl bg-white/20 backdrop-blur-md flex items-center justify-center text-white shadow-inner">
                  <Fingerprint size={24} />
                </div>
                <span className="mt-2 text-[11px] font-bold text-white/90">Identity Match</span>
              </div>

              {/* Card 3: Indigo 3D Analytics */}
              <div className="relative aspect-square rounded-2xl bg-gradient-to-br from-[#6366F1] to-[#3B82F6] p-4 flex flex-col items-center justify-center shadow-xl hover:scale-[1.04] transition-all">
                <div className="h-12 w-12 rounded-2xl bg-white/20 backdrop-blur-md flex items-center justify-center text-white shadow-inner">
                  <Activity size={24} />
                </div>
                <span className="mt-2 text-[11px] font-bold text-white/90">Risk Fusion</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 2: SMART SOLUTIONS (ABOUT US) ────────────────────── */}
      <section id="threat" className="dot-pattern relative border-b border-slate-200 bg-white px-6 py-24 sm:px-8">
        <div className="mx-auto max-w-7xl space-y-16">
          <div className="grid gap-12 lg:grid-cols-12">
            {/* Left Headline */}
            <div className="lg:col-span-6 space-y-4">
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-100 px-3 py-1 text-[11px] font-bold text-slate-800 uppercase tracking-wider">
                <span>:: ABOUT SATYAVOICE</span>
              </div>

              <h2 className="text-3xl sm:text-5xl font-black text-[#0F172A] leading-tight">
                Smart Solutions <br />
                Designed to{" "}
                <span className="bg-gradient-to-r from-[#7C3AED] via-[#A855F7] to-[#EC4899] bg-clip-text text-transparent">
                  Drive Your Defense.
                </span>
              </h2>

              <div className="pt-8 flex items-center gap-4">
                <div className="h-12 w-12 rounded-full bg-gradient-to-tr from-purple-500 to-pink-500 flex items-center justify-center text-white font-bold text-sm shadow-md">
                  SV
                </div>
                <p className="text-xs font-semibold text-slate-600 max-w-xs leading-relaxed">
                  "Everything you need to secure, monitor, and cryptographically audit high-value voice transactions in one place."
                </p>
              </div>
            </div>

            {/* Right Content */}
            <div className="lg:col-span-6 space-y-8 flex flex-col justify-center">
              <p className="text-base text-slate-600 leading-relaxed">
                We empower businesses and financial institutions with powerful real-time voice intelligence to stop executive impersonation, wire transfer fraud, and synthetic speech coercion.
              </p>

              <div className="rounded-3xl border border-slate-200 bg-slate-50 p-6 space-y-3">
                <h3 className="text-xl font-extrabold text-[#0F172A]">Why SatyaVoice?</h3>
                <p className="text-sm text-slate-600 leading-relaxed">
                  From sub-second acoustic anti-spoofing to immutable on-chain Merkle audit trails, SatyaVoice provides a complete suite built for modern security teams. Focus on what matters most while we defend the line.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 3: FEATURED TOOLS (3D GRADIENT CARDS) ─────────────── */}
      <section id="signals" className="border-b border-slate-200 bg-slate-50/60 px-6 py-24 sm:px-8">
        <div className="mx-auto max-w-7xl space-y-16">
          {/* Header */}
          <div className="flex flex-col md:flex-row md:items-end justify-between gap-6">
            <div className="space-y-3">
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-bold text-slate-800 uppercase tracking-wider">
                <span>:: FEATURED INTELLIGENCE TOOLS</span>
              </div>
              <h2 className="text-3xl sm:text-5xl font-black text-[#0F172A]">
                Powerful Tools <br />
                Built for{" "}
                <span className="bg-gradient-to-r from-[#7C3AED] to-[#EC4899] bg-clip-text text-transparent">
                  Your Security
                </span>
              </h2>
            </div>

            <div className="space-y-4 max-w-md">
              <p className="text-sm text-slate-600 leading-relaxed">
                Explore our suite of neural tools designed to simplify fraud detection, improve verification speeds, and drive auditable outcomes.
              </p>
              <button
                onClick={() => setShowSetupModal(true)}
                className="rounded-full bg-[#0F172A] px-6 py-2.5 text-xs font-bold text-white shadow-md hover:bg-slate-800 transition-all"
              >
                View All Tools
              </button>
            </div>
          </div>

          {/* 3 Large 3D Gradient Cards */}
          <div className="grid gap-8 md:grid-cols-3">
            {/* Card 1: FlowMaster / Acoustic */}
            <div className="group relative aspect-[4/5] rounded-[2rem] bg-gradient-to-b from-[#C084FC] via-[#A855F7] to-[#7C3AED] p-6 shadow-xl transition-all duration-300 hover:scale-[1.02] flex flex-col justify-between overflow-hidden">
              <div className="flex justify-end">
                <div className="h-8 w-8 rounded-full bg-white/20 backdrop-blur-md flex items-center justify-center text-white">
                  <Mic size={16} />
                </div>
              </div>

              {/* 3D Center Cloud Illustration */}
              <div className="my-auto flex flex-col items-center justify-center text-center space-y-2">
                <div className="h-24 w-24 rounded-3xl bg-white/30 backdrop-blur-xl flex items-center justify-center text-white shadow-2xl">
                  <Mic size={48} className="drop-shadow" />
                </div>
              </div>

              {/* Glass Bottom Label */}
              <div className="rounded-2xl bg-white/20 backdrop-blur-md px-4 py-3 text-center border border-white/20">
                <span className="text-sm font-extrabold text-white tracking-wide">FlowMaster · Acoustic AI</span>
                <p className="text-[11px] text-white/80 font-medium">MMS-300M Anti-Deepfake</p>
              </div>
            </div>

            {/* Card 2: InsightPro / Identity */}
            <div className="group relative aspect-[4/5] rounded-[2rem] bg-gradient-to-b from-[#F472B6] via-[#EC4899] to-[#E11D48] p-6 shadow-xl transition-all duration-300 hover:scale-[1.02] flex flex-col justify-between overflow-hidden">
              <div className="flex justify-end">
                <div className="h-8 w-8 rounded-full bg-white/20 backdrop-blur-md flex items-center justify-center text-white">
                  <Fingerprint size={16} />
                </div>
              </div>

              {/* 3D Center Bars Illustration */}
              <div className="my-auto flex flex-col items-center justify-center text-center space-y-2">
                <div className="h-24 w-24 rounded-3xl bg-white/30 backdrop-blur-xl flex items-center justify-center text-white shadow-2xl">
                  <Fingerprint size={48} className="drop-shadow" />
                </div>
              </div>

              {/* Glass Bottom Label */}
              <div className="rounded-2xl bg-white/20 backdrop-blur-md px-4 py-3 text-center border border-white/20">
                <span className="text-sm font-extrabold text-white tracking-wide">InsightPro · Biometrics</span>
                <p className="text-[11px] text-white/80 font-medium">ECAPA-TDNN 192D Embedding</p>
              </div>
            </div>

            {/* Card 3: TeamSync / Context */}
            <div className="group relative aspect-[4/5] rounded-[2rem] bg-gradient-to-b from-[#818CF8] via-[#6366F1] to-[#3B82F6] p-6 shadow-xl transition-all duration-300 hover:scale-[1.02] flex flex-col justify-between overflow-hidden">
              <div className="flex justify-end">
                <div className="h-8 w-8 rounded-full bg-white/20 backdrop-blur-md flex items-center justify-center text-white">
                  <Zap size={16} />
                </div>
              </div>

              {/* 3D Center Spheres Illustration */}
              <div className="my-auto flex flex-col items-center justify-center text-center space-y-2">
                <div className="h-24 w-24 rounded-3xl bg-white/30 backdrop-blur-xl flex items-center justify-center text-white shadow-2xl">
                  <Zap size={48} className="drop-shadow" />
                </div>
              </div>

              {/* Glass Bottom Label */}
              <div className="rounded-2xl bg-white/20 backdrop-blur-md px-4 py-3 text-center border border-white/20">
                <span className="text-sm font-extrabold text-white tracking-wide">TeamSync · Intent Engine</span>
                <p className="text-[11px] text-white/80 font-medium">faster-whisper ASR</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 4: LIVE VOICE INTELLIGENCE (INTERACTIVE WORKSPACE) ── */}
      <section id="live-intelligence" className="border-b border-slate-200 bg-white px-6 py-24 sm:px-8">
        <div className="mx-auto max-w-7xl space-y-12">
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
            <div className="space-y-2">
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-100 px-3 py-1 text-[11px] font-bold text-slate-800 uppercase tracking-wider">
                <span>:: LIVE TELEMETRY STREAM</span>
              </div>
              <h2 className="text-3xl sm:text-4xl font-black text-[#0F172A]">
                Live Voice Protection Workspace
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
            <div className="rounded-3xl border border-slate-200 bg-slate-50/80 p-6 sm:p-10 space-y-8 shadow-sm overflow-hidden">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 border-b border-slate-200 pb-6">
                <div className="space-y-2">
                  <span className="hud-badge hud-badge-safe">LIVE PROTECTION READY</span>
                  <h3 className="text-2xl sm:text-3xl font-extrabold text-[#0F172A]">
                    Start Monitoring an Incoming Audio Stream
                  </h3>
                  <p className="text-sm text-slate-600 max-w-xl">
                    Connect your microphone to evaluate live voice authenticity, view real-time spectral energy, and monitor fused threat indices.
                  </p>
                </div>
                <button
                  onClick={() => setShowSetupModal(true)}
                  className="rounded-full bg-[#0F172A] px-8 py-3.5 text-sm font-extrabold text-white shadow-lg transition-all hover:bg-slate-800 hover:scale-[1.03] active:scale-[0.98] self-start md:self-center shrink-0"
                >
                  START LIVE PROTECTION NOW
                </button>
              </div>

              {/* Simulated Live Preview Card */}
              <div className="grid gap-6 lg:grid-cols-12 items-start">
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

      {/* ── SECTION 5: HOW ANALYSIS WORKS ────────────────────────────── */}
      <section id="process" className="border-b border-slate-200 bg-slate-50 px-6 py-24 sm:px-8">
        <div className="mx-auto max-w-7xl space-y-12">
          <div className="max-w-2xl space-y-3">
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-bold text-slate-800 uppercase tracking-wider">
              <span>:: ARCHITECTURAL PIPELINE</span>
            </div>
            <h2 className="text-3xl sm:text-4xl font-black text-[#0F172A]">
              How the Analysis Works
            </h2>
            <p className="text-sm text-slate-600">
              From raw microphone PCM audio to an immutable on-chain cryptographic proof package.
            </p>
          </div>

          {/* 7-Step Process Diagram */}
          <div className="grid gap-4 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-7">
            {[
              { step: "01", name: "AUDIO", desc: "16 kHz Mono PCM" },
              { step: "02", name: "VAD", desc: "Silero Filter" },
              { step: "03", name: "ANTI-SPOOF", desc: "MMS-300M" },
              { step: "04", name: "ASR", desc: "faster-whisper" },
              { step: "05", name: "SPEAKER", desc: "ECAPA-TDNN" },
              { step: "06", name: "RISK", desc: "Dynamic Fusion" },
              { step: "07", name: "EVIDENCE", desc: "Polygon Anchor" },
            ].map((item, idx) => (
              <div key={idx} className="surface-card p-5 flex flex-col justify-between space-y-3 hover:border-[#7C3AED] transition-all">
                <div className="flex items-center justify-between font-mono text-xs">
                  <span className="font-bold text-[#7C3AED]">{item.step}</span>
                  {idx < 6 && <ChevronRight size={14} className="text-slate-400 hidden lg:block" />}
                </div>
                <div>
                  <h4 className="font-bold text-[#0F172A] text-sm">{item.name}</h4>
                  <p className="text-[11px] text-slate-500 mt-1">{item.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── SECTION 6: FORENSIC EVIDENCE & VERIFICATION ──────────────── */}
      <section id="forensic-evidence" className="border-b border-slate-200 bg-white px-6 py-24 sm:px-8">
        <div className="mx-auto max-w-7xl space-y-12">
          <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-4">
            <div className="space-y-2">
              <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-100 px-3 py-1 text-[11px] font-bold text-slate-800 uppercase tracking-wider">
                <span>:: INVESTIGATION WORKSPACE</span>
              </div>
              <h2 className="text-3xl sm:text-4xl font-black text-[#0F172A]">
                Digital Forensic Evidence Dossier
              </h2>
            </div>
            <button
              onClick={handleDownloadPdf}
              disabled={downloadingReport}
              className="flex items-center gap-2 rounded-full bg-[#7C3AED] px-6 py-2.5 text-xs font-bold text-white shadow-md hover:bg-[#6D28D9] transition-all"
            >
              <Download size={14} />
              <span>{downloadingReport ? "Generating PDF..." : "EXPORT PDF REPORT"}</span>
            </button>
          </div>

          {phase === "ended" ? (
            <ForensicsView session={session} />
          ) : (
            <div className="surface-card p-8 space-y-6">
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-slate-200 pb-4">
                <div>
                  <span className="text-xs text-slate-500 uppercase font-mono">CASE DOSSIER PREVIEW</span>
                  <h3 className="text-xl font-bold text-[#0F172A] font-mono mt-0.5">SV-2026-9842-DEMO</h3>
                </div>
                <span className="hud-badge hud-badge-safe font-mono">STANDBY FOR CASE CAPTURE</span>
              </div>

              <div className="grid gap-6 md:grid-cols-3 font-mono text-xs">
                <div className="space-y-1 bg-slate-50 p-4 rounded-2xl border border-slate-200">
                  <span className="text-slate-500 text-[10px] uppercase font-bold">SHA-256 Digest</span>
                  <p className="text-[#0F172A] truncate">7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069</p>
                </div>
                <div className="space-y-1 bg-slate-50 p-4 rounded-2xl border border-slate-200">
                  <span className="text-slate-500 text-[10px] uppercase font-bold">Merkle Root</span>
                  <p className="text-[#0F172A] truncate">4b89c211a76e9f12d8a5522b109e44319082a5c1d6e7f80b91a2c3d4e5f6a7b8</p>
                </div>
                <div className="space-y-1 bg-slate-50 p-4 rounded-2xl border border-slate-200">
                  <span className="text-slate-500 text-[10px] uppercase font-bold">Blockchain Anchor</span>
                  <p className="text-emerald-600 font-bold">Polygon Amoy (Chain 80002)</p>
                </div>
              </div>
            </div>
          )}

          {/* Verification Actions */}
          <div id="verification" className="surface-card p-8 flex flex-col sm:flex-row sm:items-center justify-between gap-6 border-t-2 border-t-[#7C3AED]">
            <div>
              <h3 className="text-xl font-bold text-[#0F172A]">Verify Cryptographic Certificate</h3>
              <p className="text-xs text-slate-600 mt-1">
                Execute independent cryptographic integrity validation against local hashes and on-chain ledgers.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={handleVerifyIntegrityClick}
                disabled={verifyingApi}
                className="flex items-center gap-2 rounded-full bg-[#7C3AED] px-6 py-3 text-xs font-bold text-white shadow-md transition-all hover:bg-[#6D28D9]"
              >
                <CheckCircle2 size={15} />
                <span>{verifyingApi ? "Verifying..." : "VERIFY INTEGRITY"}</span>
              </button>
              <button
                onClick={handleVerifyChainClick}
                disabled={verifyingApi}
                className="flex items-center gap-2 rounded-full border border-slate-200 bg-white px-6 py-3 text-xs font-bold text-[#0F172A] transition-all hover:border-[#7C3AED]"
              >
                <Link size={15} className="text-[#7C3AED]" />
                <span>VERIFY CHAIN</span>
              </button>
            </div>
          </div>
        </div>
      </section>

      {/* ── SECTION 7: FINAL CTA & FOOTER ────────────────────────────── */}
      <section className="relative px-6 py-28 text-center bg-[#080B11] text-white">
        <div className="mx-auto max-w-4xl space-y-8">
          <h2 className="text-4xl sm:text-6xl font-black text-white leading-tight">
            Simplify. Protect. <br />
            <span className="bg-gradient-to-r from-[#C084FC] via-[#E879F9] to-[#818CF8] bg-clip-text text-transparent">
              Secure Your Voice.
            </span>
          </h2>

          <div className="flex flex-wrap items-center justify-center gap-4 pt-4">
            <button
              onClick={() => setShowSetupModal(true)}
              className="rounded-full bg-white px-8 py-4 text-sm font-extrabold text-[#080B11] shadow-2xl transition-all hover:bg-slate-100 hover:scale-[1.03] active:scale-[0.98]"
            >
              Start Live Protection
            </button>

            <a
              href="#verification"
              className="rounded-full border border-white/20 bg-white/10 px-8 py-4 text-sm font-bold text-white transition-all hover:border-[#C084FC]"
            >
              View Verification
            </a>
          </div>

          <footer className="pt-20 border-t border-white/10 text-xs text-slate-400 flex flex-col sm:flex-row items-center justify-between gap-4 font-mono">
            <div className="flex items-center gap-2">
              <Shield size={14} className="text-[#C084FC]" />
              <span className="font-bold text-white">SatyaVoice AI Fraud Intelligence</span>
              <span>© 2026</span>
            </div>
            <div className="flex items-center gap-4">
              <span>Polygon Amoy (80002)</span>
              <span>·</span>
              <span>16 kHz Mono PCM</span>
              <span>·</span>
              <span className="text-emerald-400 font-bold">ALL SYSTEMS NOMINAL</span>
            </div>
          </footer>
        </div>
      </section>

      {/* ── CALL SETUP MODAL ────────────────────────────────────────── */}
      {showSetupModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-md overflow-y-auto">
          <div className="relative w-full max-w-4xl max-h-[90vh] overflow-y-auto rounded-3xl border border-slate-200 bg-white p-6 shadow-2xl">
            <button
              onClick={() => setShowSetupModal(false)}
              className="absolute top-5 right-5 rounded-full border border-slate-200 bg-slate-100 p-2 text-slate-600 hover:text-black hover:border-slate-400"
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
          <div className="w-full max-w-lg rounded-3xl border border-slate-200 bg-white p-6 space-y-4 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-200 pb-3">
              <span className="font-mono text-xs font-bold text-[#7C3AED]">CRYPTOGRAPHIC INTEGRITY REPORT</span>
              <button
                onClick={() => setShowIntegrityResultModal(false)}
                className="text-slate-400 hover:text-black"
              >
                ✕
              </button>
            </div>
            <pre className="font-mono text-xs bg-slate-50 p-4 rounded-2xl text-slate-800 overflow-x-auto max-h-60 border border-slate-200">
              {JSON.stringify(verificationResult, null, 2)}
            </pre>
            <button
              onClick={() => setShowIntegrityResultModal(false)}
              className="w-full rounded-full bg-[#7C3AED] py-3 text-xs font-bold text-white shadow-md hover:bg-[#6D28D9]"
            >
              Close Verification Audit
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
