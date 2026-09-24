import {
  Activity,
  Cpu,
  Fingerprint,
  Languages,
  Radio,
  ShieldAlert,
  ShieldCheck,
  Terminal,
} from "lucide-react";
import type { UseCallSession } from "../hooks/useCallSession";
import { formatRiskScore, formatVectorPercent } from "../lib/riskFormat";
import CallControls from "./CallControls";
import RiskTimeline, { statusLabel } from "./RiskTimeline";
import Spectrograph from "./Spectrograph";
import StatusBadge from "./StatusBadge";
import StatusBanner from "./StatusBanner";
import ThreatBreakdown from "./ThreatBreakdown";
import TrustGauge from "./TrustGauge";
import VerificationModal from "./VerificationModal";
import WireTransferPanel from "./WireTransferPanel";

interface CallDashboardProps {
  session: UseCallSession;
}

interface MetricTileProps {
  label: string;
  value: string;
  detail: string;
  tone?: "safe" | "warn" | "danger" | "signal" | "neutral";
  icon?: React.ReactNode;
}

function MetricTile({ label, value, detail, tone = "neutral", icon }: MetricTileProps) {
  const toneClasses = {
    safe: "text-safe border-safe/25 bg-safe-bg/30",
    warn: "text-warn border-warn/25 bg-warn-bg/30",
    danger: "text-danger border-danger/30 bg-danger-bg/40",
    signal: "text-signal border-signal/25 bg-signal-bg/30",
    neutral: "text-paper-bright border-ink-700/40 bg-ink-850/60",
  };

  const textTone = {
    safe: "text-safe",
    warn: "text-warn",
    danger: "text-danger",
    signal: "text-signal",
    neutral: "text-paper-bright",
  };

  return (
    <div className={`rounded-2xl border p-4 transition-all ${toneClasses[tone]}`}>
      <div className="flex items-center justify-between text-xs text-paper-muted">
        <span className="font-semibold uppercase tracking-wider text-[10px]">{label}</span>
        {icon && <span className="opacity-80">{icon}</span>}
      </div>
      <p className={`mt-2 font-sans text-2xl sm:text-3xl font-extrabold tracking-tight ${textTone[tone]}`}>
        {value}
      </p>
      <p className="mt-1 text-xs text-paper-dim leading-tight">{detail}</p>
    </div>
  );
}

export default function CallDashboard({ session }: CallDashboardProps) {
  const {
    meta,
    telemetry,
    telemetryHistory,
    muted,
    onHold,
    analyser,
    verified,
    verification,
    actionFeedback,
    actionPending,
    liveTranscript,
    browserOnnxStatus,
    browserOnnxResult,
    localRisk,
    localModelError,
    endCall,
    toggleMute,
    toggleHold,
    updateLiveTranscript,
    requestChallenge,
    setVerificationInput,
    submitVerification,
    attemptWireTransfer,
  } = session;

  const status = telemetry?.status ?? "ALLOW";
  const score = telemetry?.risk_score ?? 0;
  const acousticScore = telemetry?.acoustic_score ?? 0;
  const intentScore = telemetry?.intent_score ?? 0;
  const rationale = telemetry?.rationale ?? [];
  const identityMismatch = telemetry?.identity_mismatch ?? null;
  const speakerSimilarity = telemetry?.speaker_score ?? null;
  const intentRisks = telemetry?.intent_risks ?? [];
  const detectedLanguage = telemetry?.detected_language ?? null;

  const languageLabel =
    detectedLanguage == null
      ? null
      : detectedLanguage === "en"
        ? "English"
        : detectedLanguage === "hi"
          ? "Hindi"
          : detectedLanguage === "ta"
            ? "Tamil"
            : detectedLanguage === "te"
              ? "Telugu"
              : detectedLanguage === "bn"
                ? "Bengali"
                : detectedLanguage === "mr"
                  ? "Marathi"
                  : detectedLanguage;

  const showVerification = status === "LOCK_VERIFY" && !verified;
  const currentStatus = verified ? "SAFE" : statusLabel(status);
  const statusTone =
    currentStatus === "LOCKED" ? "danger" : currentStatus === "SUSPICIOUS" ? "warn" : "safe";



  return (
    <div className="flex min-h-0 flex-1 flex-col bg-ink-950">
      {/* Scrollable Main Operations Workspace */}
      <main className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-6 lg:px-8">
        <div className="mx-auto max-w-[1440px] space-y-6">
          {/* Top Session Breadcrumb Bar */}
          <div className="flex flex-col gap-3 border-b border-ink-700/40 pb-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span className="inline-flex items-center gap-1.5 rounded-full border border-signal/25 bg-signal-bg px-2.5 py-0.5 text-[10px] font-semibold text-signal uppercase tracking-wider">
                  <Radio size={10} className="animate-pulse" /> Live Telemetry
                </span>
                <span className="text-xs text-paper-muted">
                  Mode: <span className="font-semibold text-paper-bright uppercase">{meta?.audioMode ?? "CLOUD"}</span>
                </span>
              </div>
              <h1 className="mt-1 text-xl font-bold tracking-tight text-paper-bright sm:text-2xl">
                Active Telemetry &amp; Voice Deepfake Protection
              </h1>
            </div>

            <div className="flex items-center gap-3">
              <div className="rounded-xl border border-ink-700/40 bg-ink-900/80 px-3.5 py-1.5 text-right font-mono">
                <span className="block text-[10px] uppercase tracking-wider text-paper-muted">
                  Session ID
                </span>
                <span className="text-xs font-bold text-signal">
                  {meta?.callId ?? "INITIALIZING"}
                </span>
              </div>
              <StatusBadge
                label={currentStatus}
                variant={statusTone}
                pulse={currentStatus === "LOCKED"}
              />
            </div>
          </div>

          {/* Real-time Status Alert Banner */}
          <StatusBanner
            status={verified ? "ALLOW" : status}
            rationale={rationale}
            verified={verified}
          />

          {/* Four Core Telemetry Metric Cards */}
          <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-4">
            <MetricTile
              label="Fused Risk Index"
              value={`${formatRiskScore(score)}%`}
              detail="Weighted acoustic & intent fusion"
              tone={statusTone}
              icon={<ShieldAlert size={16} />}
            />
            <MetricTile
              label="Policy Verdict"
              value={currentStatus}
              detail={verified ? "Out-of-band verified" : "Automated policy clearance"}
              tone={statusTone}
              icon={<ShieldCheck size={16} />}
            />
            <MetricTile
              label="Acoustic Anti-Spoof"
              value={`${formatVectorPercent(acousticScore)}%`}
              detail="MMS-300M vocoder probability"
              tone={acousticScore >= 0.7 ? "danger" : acousticScore >= 0.4 ? "warn" : "safe"}
              icon={<Cpu size={16} />}
            />
            <MetricTile
              label="Conversational Urgency"
              value={`${formatVectorPercent(intentScore)}%`}
              detail="Social engineering pressure"
              tone={intentScore >= 0.7 ? "danger" : intentScore >= 0.4 ? "warn" : "safe"}
              icon={<Terminal size={16} />}
            />
          </div>

          {/* Hero Decision Surface & Spectral Stream */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            {/* Left: Focal Risk Gauge & Verdict Card */}
            <section className="rounded-3xl border border-ink-700/40 bg-ink-900/90 p-6 sm:p-7 shadow-elevated lg:col-span-5 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between border-b border-ink-700/40 pb-3">
                  <p className="eyebrow text-signal">Decision Engine</p>
                  <span className="font-mono text-xs text-paper-muted">Sub-second evaluation</span>
                </div>

                <div className="mt-4 flex flex-col items-center">
                  {telemetry ? (
                    <TrustGauge score={score} status={status} />
                  ) : (
                    <div className="flex h-48 flex-col items-center justify-center font-mono text-xs text-paper-muted">
                      <Activity size={24} className="animate-spin text-signal mb-2" />
                      <span>Calibrating Audio Engine...</span>
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-4 rounded-xl border border-ink-700/30 bg-ink-850/50 p-3 text-xs text-paper-dim leading-relaxed">
                <span className="font-semibold text-paper-bright block mb-0.5">Policy Rationale:</span>
                {rationale.length > 0 ? (
                  <span>{rationale.join("; ")}</span>
                ) : (
                  <span>Acoustic features nominal. No synthetic voice clone indicators detected.</span>
                )}
              </div>
            </section>

            {/* Right: Live Voice Spectrogram & Spectral Ribbon */}
            <section className="lg:col-span-7 flex flex-col justify-between">
              <Spectrograph analyser={analyser} status={status} />

              {/* On-Device / Edge-Local Inference Telemetry */}
              {(meta?.audioMode === "hybrid" || meta?.audioMode === "edge-local") && (
                <div className="mt-4 rounded-2xl border border-signal/30 bg-ink-900/90 p-4 shadow-panel">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="eyebrow text-signal">In-Browser Edge AI</p>
                      <h2 className="mt-0.5 text-xs font-bold text-paper-bright">
                        On-Device ONNX Runtime WebAssembly Accelerator
                      </h2>
                    </div>
                    <StatusBadge
                      label={browserOnnxStatus.toUpperCase()}
                      variant={
                        browserOnnxStatus === "ready"
                          ? "safe"
                          : browserOnnxStatus === "loading"
                            ? "warn"
                            : "danger"
                      }
                      size="sm"
                    />
                  </div>

                  <div className="mt-2.5 rounded-xl border border-ink-700/50 bg-ink-950 p-3 font-mono text-xs text-signal">
                    {browserOnnxStatus === "loading" && "INITIALIZING ONNX WEB WORKER & WEIGHTS..."}
                    {browserOnnxStatus === "ready" && browserOnnxResult && (
                      <div className="space-y-1">
                        <div>
                          SPOOF PROBABILITY:{" "}
                          <span className="font-bold text-paper-bright">
                            {Math.round(browserOnnxResult.score * 100)}%
                          </span>{" "}
                          ({browserOnnxResult.label})
                        </div>
                        {localRisk && (
                          <div className="text-[11px] text-paper-muted flex flex-wrap gap-x-3 gap-y-0.5 pt-1 border-t border-ink-800">
                            <span>MODEL: {localRisk.modelId}</span>
                            <span>INFER: {Math.round(localRisk.inferenceMs)}ms</span>
                            <span>
                              P50: {localRisk.p50Ms ? `${Math.round(localRisk.p50Ms)}ms` : "—"} /
                              P95: {localRisk.p95Ms ? `${Math.round(localRisk.p95Ms)}ms` : "—"}
                            </span>
                            <span>FRAMES: {localRisk.inferenceCount}</span>
                          </div>
                        )}
                      </div>
                    )}
                    {browserOnnxStatus === "error" && (
                      <span className="text-danger">
                        MODEL ERROR: {localModelError ?? "Local inference failed"} — Falling back to cloud pipeline.
                      </span>
                    )}
                    {browserOnnxStatus === "idle" && "WAITING FOR PCM AUDIO STREAM..."}
                  </div>
                </div>
              )}
            </section>
          </div>

          {/* Main Telemetry & Analytics Grid */}
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
            {/* Left Column: Risk Evolution & Conversational ASR */}
            <div className="space-y-6 lg:col-span-7">
              {/* Chronological Risk Timeline */}
              <RiskTimeline points={telemetryHistory} />

              {/* Conversational Context & ASR Intent Stream */}
              <section className="rounded-2xl border border-ink-700/40 bg-ink-900/90 p-5 sm:p-6 shadow-panel">
                <div className="flex items-start justify-between gap-3 border-b border-ink-700/40 pb-3.5">
                  <div>
                    <p className="eyebrow text-signal">Conversational Intelligence</p>
                    <h2 className="mt-0.5 text-sm font-bold text-paper-bright">
                      ASR Transcript &amp; Fraud Intent Markers
                    </h2>
                  </div>
                  <div className="flex items-center gap-2">
                    {languageLabel && (
                      <span className="inline-flex items-center gap-1 rounded-full border border-signal/30 bg-signal-bg px-2.5 py-0.5 text-[11px] font-medium text-signal">
                        <Languages size={11} /> {languageLabel}
                      </span>
                    )}
                  </div>
                </div>

                <div className="mt-4">
                  <label htmlFor="live-transcript" className="field-label">
                    Live Dialogue Input (Multilingual Test Console)
                  </label>
                  <textarea
                    id="live-transcript"
                    value={liveTranscript}
                    onChange={(e) => updateLiveTranscript(e.target.value)}
                    rows={3}
                    placeholder="Type dialogue as it occurs (e.g. 'I need you to wire the ₹50,000 urgently without OTP verification')..."
                    className="field-input mt-1.5 w-full resize-none font-sans text-sm"
                  />
                  <p className="mt-1.5 text-xs text-paper-muted">
                    Real-time intent analyzer extracts extortion cues, sensitive transaction
                    redirects (UPI/OTP), and psychological urgency.
                  </p>

                  {/* Intent Risk Chips */}
                  {intentRisks.length > 0 && (
                    <div className="mt-3.5 space-y-2">
                      <p className="text-[10px] font-semibold uppercase tracking-wider text-paper-muted">
                        Structured Extortion Signals:
                      </p>
                      {intentRisks.map((risk, i) => (
                        <div
                          key={`${risk.category}-${risk.matched_phrase}-${i}`}
                          className="rounded-xl border border-ink-700/40 bg-ink-850/70 p-3"
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span
                              className={`font-mono text-xs font-bold uppercase tracking-wider ${
                                risk.severity === "critical"
                                  ? "text-danger"
                                  : risk.severity === "elevated"
                                    ? "text-warn"
                                    : "text-signal"
                              }`}
                            >
                              Category: {risk.category} · Speech Act: {risk.speech_act}
                            </span>
                            <span className="font-mono text-[10px] text-paper-muted uppercase">
                              {risk.language} · {Math.round(risk.confidence * 100)}% conf
                            </span>
                          </div>
                          <p className="mt-1 text-xs text-paper-bright">
                            “<span className="font-bold text-danger">{risk.matched_phrase}</span>”
                            — <span className="text-paper-dim">{risk.evidence}</span>
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </section>
            </div>

            {/* Right Column: Threat Breakdown & Action Clearance */}
            <div className="space-y-6 lg:col-span-5">
              {/* Identity Verification Posture */}
              <section className="rounded-2xl border border-ink-700/40 bg-ink-900/90 p-5 shadow-panel">
                <div className="flex items-start justify-between gap-3 border-b border-ink-700/40 pb-3">
                  <div>
                    <p className="eyebrow text-signal">Identity Assurance</p>
                    <h2 className="mt-0.5 text-sm font-bold text-paper-bright">
                      Voice Biometric Posture
                    </h2>
                  </div>
                  <Fingerprint size={18} className="text-signal" />
                </div>

                <div className="mt-3.5 space-y-2.5">
                  <div className="flex items-center justify-between border-b border-ink-700/30 pb-2 text-xs">
                    <span className="text-paper-muted">Speaker Similarity</span>
                    <span className="font-mono font-semibold text-paper-bright">
                      {speakerSimilarity != null
                        ? `${Math.round(speakerSimilarity * 100)}%`
                        : "Unknown (Unregistered)"}
                    </span>
                  </div>

                  <div className="flex items-center justify-between border-b border-ink-700/30 pb-2 text-xs">
                    <span className="text-paper-muted">Derived Identity Mismatch</span>
                    <span
                      className={`font-mono font-bold ${
                        identityMismatch && identityMismatch >= 0.7
                          ? "text-danger"
                          : "text-paper-bright"
                      }`}
                    >
                      {identityMismatch != null
                        ? `${Math.round(identityMismatch * 100)}%`
                        : "Neutral"}
                    </span>
                  </div>

                  <div className="flex items-center justify-between text-xs pt-0.5">
                    <span className="text-paper-muted">Step-Up Challenge State</span>
                    <StatusBadge
                      label={verified ? "VERIFIED" : showVerification ? "LOCKED" : "NOT REQUIRED"}
                      variant={verified ? "safe" : showVerification ? "danger" : "neutral"}
                      pulse={showVerification}
                      size="sm"
                    />
                  </div>
                </div>
              </section>

              {/* Threat Signal Breakdown */}
              <ThreatBreakdown
                acousticScore={acousticScore}
                intentScore={intentScore}
                identityMismatch={identityMismatch}
                speakerSimilarity={speakerSimilarity}
                rationale={rationale}
                status={status}
              />

              {/* Wire Transfer Simulation Panel */}
              <WireTransferPanel
                locked={showVerification}
                feedback={actionFeedback}
                pending={actionPending}
                onAttempt={attemptWireTransfer}
              />
            </div>
          </div>
        </div>
      </main>

      {/* Docked Audio & Intervention Controls Footer */}
      <footer className="shrink-0 border-t border-ink-700/40 bg-ink-950/90 px-6 py-3.5 backdrop-blur-md sm:px-8">
        <div className="mx-auto max-w-[1440px]">
          <CallControls
            muted={muted}
            onHold={onHold}
            onToggleMute={toggleMute}
            onToggleHold={toggleHold}
            onEndCall={endCall}
          />
        </div>
      </footer>

      {/* Out-of-Band Step-Up Challenge Modal */}
      {showVerification && (
        <VerificationModal
          verification={verification}
          onRequestCode={requestChallenge}
          onInputChange={setVerificationInput}
          onSubmit={submitVerification}
          onTerminate={endCall}
        />
      )}
    </div>
  );
}
