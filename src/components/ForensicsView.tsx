import { useMemo, useState, type ReactNode } from "react";
import {
  AlertOctagon,
  CheckCircle2,
  ClipboardCheck,
  Cpu,
  Download,
  ExternalLink,
  FileWarning,
  Fingerprint,
  Layers,
  LockKeyhole,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  UserRound,
  Waves,
  XCircle,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { UseCallSession } from "../hooks/useCallSession";
import {
  downloadForensicReportPdf,
  HttpStatusError,
  registerForensicsEvidence,
  verifyEvidenceIntegrity,
  verifyForensicsEvidence,
} from "../lib/api";
import { buildEvidenceSnapshot, buildTechnicalEvidenceReport } from "../lib/forensicPdf";
import {
  ledgerLabel,
  verificationAnchorText,
} from "../lib/forensicsDisplay";
import type { ForensicsIntegritySummary, ForensicsVerificationResponse } from "../types";
import HashDisplay from "./HashDisplay";
import StatusBadge from "./StatusBadge";

interface ForensicsViewProps {
  session: UseCallSession;
}

const formatTime = (timestamp?: number) =>
  timestamp
    ? new Date(timestamp * 1000).toLocaleTimeString([], {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      })
    : "—";

const statusLabel = (value: string) => value.replace(/_/g, " ");

function EvidenceSection({
  title,
  eyebrow,
  icon,
  badge,
  children,
  className = "",
}: {
  title: string;
  eyebrow: string;
  icon: ReactNode;
  badge?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-2xl border border-ink-700/40 bg-ink-900/90 p-5 shadow-panel ${className}`}>
      <div className="mb-4 flex items-start justify-between gap-3 border-b border-ink-700/40 pb-3.5">
        <div>
          <p className="eyebrow text-signal">{eyebrow}</p>
          <h2 className="mt-0.5 text-sm font-bold tracking-tight text-paper-bright">
            {title}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {badge}
          <div className="text-signal">{icon}</div>
        </div>
      </div>
      {children}
    </section>
  );
}

function DataField({
  label,
  value,
  mono = false,
  tone = "text-paper-bright",
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
  tone?: string;
}) {
  return (
    <div className="flex items-start justify-between gap-4 border-t border-ink-700/30 py-2.5 first:border-t-0 text-xs">
      <span className="text-paper-muted font-sans">{label}</span>
      <span
        className={`max-w-[65%] break-all text-right ${tone} ${
          mono ? "font-mono font-medium" : "font-medium"
        }`}
      >
        {value}
      </span>
    </div>
  );
}

function SignalProgress({
  label,
  value,
  max = 100,
}: {
  label: string;
  value: number;
  max?: number;
}) {
  const pct = Math.min(100, Math.max(0, Math.round((value / max) * 100)));
  const tone =
    pct >= 70 ? "bg-danger text-danger" : pct >= 40 ? "bg-warn text-warn" : "bg-safe text-safe";

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs font-mono">
        <span className="text-paper-dim">{label}</span>
        <span className="font-bold">{pct}%</span>
      </div>
      <div className="h-2 w-full rounded-full bg-ink-800 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${tone.split(" ")[0]}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export default function ForensicsView({ session }: ForensicsViewProps) {
  const {
    meta,
    telemetryHistory,
    serverRiskSnapshot,
    durationSeconds,
    liveTranscript,
    startOver,
  } = session;

  const [verificationResult, setVerificationResult] =
    useState<ForensicsVerificationResponse | null>(null);
  const [verifyingChain, setVerifyingChain] = useState(false);
  const [verificationError, setVerificationError] = useState<string | null>(null);

  const [integrity, setIntegrity] = useState<ForensicsIntegritySummary | null>(null);
  const [verifyingIntegrity, setVerifyingIntegrity] = useState(false);
  const [integrityError, setIntegrityError] = useState<string | null>(null);

  const [exporting, setExporting] = useState(false);
  const [exportSuccess, setExportSuccess] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const chartData = useMemo(() => {
    const t0 = telemetryHistory[0]?.timestamp ?? 0;
    return telemetryHistory.map((p) => ({
      t: Number((p.timestamp - t0).toFixed(1)),
      score: p.risk_score,
      acoustic: Math.round(p.acoustic_score * 100),
      intent: Math.round(p.intent_score * 100),
    }));
  }, [telemetryHistory]);

  const maxScore = telemetryHistory.reduce((max, p) => Math.max(max, p.risk_score), 0);
  const flaggedEvents = telemetryHistory.filter((p) => p.status !== "ALLOW");
  const finalPoint = telemetryHistory[telemetryHistory.length - 1];
  const incidentDetected = maxScore >= 70;
  const transitions = telemetryHistory
    .slice(1)
    .filter((point, index) => telemetryHistory[index].status !== point.status);
  const acousticPeak = telemetryHistory.reduce((max, p) => Math.max(max, p.acoustic_score), 0);

  /**
   * Export the authoritative forensic report PDF.
   */
  const handleExport = async () => {
    if (!meta || exporting) return;
    setExporting(true);
    setExportSuccess(false);
    setExportError(null);
    try {
      const report = await buildTechnicalEvidenceReport({
        callId: meta.callId,
        callerId: meta.callerId,
        recipientId: meta.recipientId,
        durationSeconds,
        maxRiskScore: maxScore,
        exportedAt: new Date().toISOString(),
        operatorIdentity: meta.callerId || "operator",
        telemetryHistory,
        modelVersionMetadata: {
          detector_mode: meta.audioMode,
          audio_pipeline: serverRiskSnapshot
            ? "WebSocket PCM + sliding windows + server-side risk snapshot"
            : "WebSocket PCM + sliding windows",
          server_risk_snapshot: serverRiskSnapshot,
        },
      });

      try {
        await registerForensicsEvidence(meta.callId, buildEvidenceSnapshot(report));
      } catch (error) {
        if (!(error instanceof HttpStatusError && error.status === 409)) throw error;
      }

      const { blob } = await downloadForensicReportPdf(meta.callId);
      const url = URL.createObjectURL(blob);
      try {
        const link = document.createElement("a");
        link.href = url;
        link.download = `satyavoice-forensic-report-${meta.callId}.pdf`;
        document.body.appendChild(link);
        link.click();
        link.remove();
        setExportSuccess(true);
        setTimeout(() => setExportSuccess(false), 5000);
      } finally {
        URL.revokeObjectURL(url);
      }
    } catch (error) {
      setExportError(
        error instanceof Error ? error.message : "The forensic report could not be generated."
      );
    } finally {
      setExporting(false);
    }
  };

  const handleVerifyChain = async () => {
    if (!meta || verifyingChain) return;
    setVerifyingChain(true);
    setVerificationError(null);
    try {
      const res = await verifyForensicsEvidence(meta.callId);
      setVerificationResult(res);
    } catch (error) {
      setVerificationError(
        error instanceof Error ? error.message : "Chain verification could not be completed."
      );
      setVerificationResult(null);
    } finally {
      setVerifyingChain(false);
    }
  };

  const handleIntegrityCheck = async () => {
    if (!meta || verifyingIntegrity) return;
    setVerifyingIntegrity(true);
    setIntegrityError(null);
    try {
      const res = await verifyEvidenceIntegrity(meta.callId);
      setIntegrity(res);
    } catch (error) {
      setIntegrityError(
        error instanceof Error ? error.message : "Integrity verification could not be completed."
      );
      setIntegrity(null);
    } finally {
      setVerifyingIntegrity(false);
    }
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6 sm:py-6 lg:px-8 bg-ink-950">
      <div className="mx-auto max-w-[1440px] space-y-6">
        {/* Case Header & Actions Bar */}
        <header className="rounded-3xl border border-ink-700/50 bg-ink-900/90 p-6 sm:p-8 shadow-elevated">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <span
                  className={`h-2.5 w-2.5 rounded-full ${
                    incidentDetected ? "bg-danger animate-pulse" : "bg-safe"
                  }`}
                />
                <span className="font-mono text-xs text-signal uppercase tracking-wider font-bold">
                  Digital Forensic Case Dossier
                </span>
                <span className="text-paper-muted font-mono text-xs">/ Post-Session Chain of Custody</span>
              </div>

              <h1 className="mt-2 text-2xl font-extrabold tracking-tight text-paper-bright sm:text-3xl">
                {incidentDetected
                  ? "Voice Deepfake Incident & Biometric Spoof Dossier"
                  : "Authentic Voice Session Forensic Summary"}
              </h1>

              <div className="mt-2.5 flex flex-wrap items-center gap-2.5 text-xs font-mono text-paper-muted">
                <span className="text-paper-bright font-semibold">{meta?.callerId ?? "Unknown Caller"}</span>
                <span>→</span>
                <span className="text-paper-dim">{meta?.recipientId ?? "Protected Desk"}</span>
                <span className="text-ink-600">·</span>
                <span>Case ID: <span className="text-signal font-semibold">{meta?.callId ?? "—"}</span></span>
              </div>
            </div>

            {/* Forensic Actions Ribbon */}
            <div className="flex flex-wrap items-center gap-2.5">
              {/* Verify Chain Button */}
              <button
                type="button"
                onClick={handleVerifyChain}
                disabled={verifyingChain}
                className="flex items-center gap-2 rounded-xl border border-signal/40 bg-signal-bg px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-signal transition-all hover:bg-signal/20 disabled:opacity-50"
              >
                {verifyingChain ? (
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-signal border-t-transparent" />
                ) : (
                  <ClipboardCheck size={15} />
                )}
                <span>{verifyingChain ? "Verifying..." : "Verify Chain"}</span>
              </button>

              {/* Verify Integrity Button */}
              <button
                type="button"
                onClick={handleIntegrityCheck}
                disabled={verifyingIntegrity}
                className="flex items-center gap-2 rounded-xl border border-ink-700/60 bg-ink-850 px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-paper-bright transition-all hover:border-signal hover:text-signal disabled:opacity-50"
              >
                {verifyingIntegrity ? (
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-paper border-t-transparent" />
                ) : (
                  <Fingerprint size={15} />
                )}
                <span>{verifyingIntegrity ? "Verifying..." : "Verify Integrity"}</span>
              </button>

              {/* Export PDF Report */}
              <button
                type="button"
                onClick={handleExport}
                disabled={exporting}
                className="flex items-center gap-2 rounded-xl border border-safe/40 bg-safe-bg px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-safe transition-all hover:bg-safe/20 disabled:opacity-50"
              >
                {exporting ? (
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-safe border-t-transparent" />
                ) : (
                  <Download size={15} />
                )}
                <span>{exporting ? "Generating PDF..." : "Export Forensic PDF"}</span>
              </button>

              {/* Start New Call Button */}
              <button
                type="button"
                onClick={startOver}
                aria-label="Start new session"
                title="Initialize New Monitored Session"
                className="flex items-center gap-1.5 rounded-xl border border-ink-700/50 bg-ink-850 px-3.5 py-2.5 text-xs text-paper-muted hover:border-ink-500 hover:text-paper-bright transition-colors"
              >
                <RotateCcw size={15} />
                <span className="hidden sm:inline">New Session</span>
              </button>
            </div>
          </div>

          {/* Feedback alerts for export/verification */}
          {exportError && (
            <div className="mt-4 rounded-xl border border-danger/40 bg-danger-bg p-3.5 text-xs text-danger">
              {exportError}
            </div>
          )}
          {exportSuccess && (
            <div className="mt-4 rounded-xl border border-safe/40 bg-safe-bg p-3.5 text-xs text-safe flex items-center gap-2.5">
              <CheckCircle2 size={16} />
              <span>Official 5-page forensic evidence PDF downloaded with QR verification tag and SHA-256 seal.</span>
            </div>
          )}
          {verificationError && (
            <div className="mt-4 rounded-xl border border-danger/40 bg-danger-bg p-3.5 text-xs text-danger">
              {verificationError}
            </div>
          )}
          {integrityError && (
            <div className="mt-4 rounded-xl border border-danger/40 bg-danger-bg p-3.5 text-xs text-danger">
              {integrityError}
            </div>
          )}

          {/* Summary Metadata Strip */}
          <div className="mt-6 grid grid-cols-2 gap-3.5 sm:grid-cols-3 lg:grid-cols-5 border-t border-ink-700/40 pt-5 text-xs font-mono">
            <div className="rounded-xl border border-ink-700/30 bg-ink-850/50 p-3">
              <span className="text-[10px] text-paper-muted uppercase block">Case Disposition</span>
              <span
                className={`mt-1 font-bold text-sm block ${
                  incidentDetected ? "text-danger" : "text-safe"
                }`}
              >
                {incidentDetected ? "CONTAINED / INTERCEPTED" : "NOMINAL / ARCHIVED"}
              </span>
            </div>

            <div className="rounded-xl border border-ink-700/30 bg-ink-850/50 p-3">
              <span className="text-[10px] text-paper-muted uppercase block">Peak Threat Score</span>
              <span
                className={`mt-1 font-bold text-sm block ${
                  maxScore >= 70 ? "text-danger" : maxScore >= 40 ? "text-warn" : "text-safe"
                }`}
              >
                {Math.round(maxScore)} / 100
              </span>
            </div>

            <div className="rounded-xl border border-ink-700/30 bg-ink-850/50 p-3">
              <span className="text-[10px] text-paper-muted uppercase block">Monitored Duration</span>
              <span className="mt-1 font-bold text-sm text-paper-bright block">
                {Math.floor(durationSeconds / 60)}m {(durationSeconds % 60).toString().padStart(2, "0")}s
              </span>
            </div>

            <div className="rounded-xl border border-ink-700/30 bg-ink-850/50 p-3">
              <span className="text-[10px] text-paper-muted uppercase block">Analysis Windows</span>
              <span className="mt-1 font-bold text-sm text-paper-bright block">
                {telemetryHistory.length} windows (4s rolling)
              </span>
            </div>

            <div className="rounded-xl border border-ink-700/30 bg-ink-850/50 p-3">
              <span className="text-[10px] text-paper-muted uppercase block">Final Policy State</span>
              <span className="mt-1 font-bold text-sm text-paper-bright block">
                {statusLabel(finalPoint?.status ?? "PENDING")}
              </span>
            </div>
          </div>
        </header>

        {/* Verification Matrix Ribbon */}
        <section className="rounded-3xl border border-ink-700/40 bg-ink-900/90 p-6 shadow-panel">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-700/40 pb-3.5">
            <div className="flex items-center gap-2.5">
              <ShieldCheck size={18} className="text-signal" />
              <h2 className="text-sm font-bold text-paper-bright">
                Four-Layer Cryptographic Verification Matrix
              </h2>
            </div>
            <span className="font-mono text-xs text-paper-muted">
              Independent deterministic validation
            </span>
          </div>

          <div className="mt-4 grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-4 font-mono text-xs">
            {/* Layer 1: Local Integrity */}
            <div className="rounded-2xl border border-ink-700/30 bg-ink-850/60 p-4">
              <div className="flex items-center justify-between">
                <span className="text-paper-muted text-[11px]">1. Local Hash Integrity</span>
                {verificationResult ? (
                  verificationResult.evidence_hash_integrity ? (
                    <CheckCircle2 size={16} className="text-safe" />
                  ) : (
                    <XCircle size={16} className="text-danger" />
                  )
                ) : (
                  <span className="text-[10px] text-paper-muted">UNCHECKED</span>
                )}
              </div>
              <span className="mt-2.5 block font-bold text-sm">
                {verificationResult
                  ? verificationResult.evidence_hash_integrity
                    ? "PASS (SHA-256 MATCH)"
                    : "FAIL (CORRUPTED HASH)"
                  : "RUN VERIFY CHAIN"}
              </span>
            </div>

            {/* Layer 2: Ledger Chain */}
            <div className="rounded-2xl border border-ink-700/30 bg-ink-850/60 p-4">
              <div className="flex items-center justify-between">
                <span className="text-paper-muted text-[11px]">2. Ledger Chain Continuity</span>
                {verificationResult ? (
                  verificationResult.local_chain_integrity ? (
                    <CheckCircle2 size={16} className="text-safe" />
                  ) : (
                    <XCircle size={16} className="text-danger" />
                  )
                ) : (
                  <span className="text-[10px] text-paper-muted">UNCHECKED</span>
                )}
              </div>
              <span className="mt-2.5 block font-bold text-sm">
                {verificationResult
                  ? verificationResult.local_chain_integrity
                    ? `VERIFIED (${verificationResult.ledger_record_count} NODES)`
                    : "CHAIN CONTINUITY BROKEN"
                  : "RUN VERIFY CHAIN"}
              </span>
            </div>

            {/* Layer 3: Merkle Root */}
            <div className="rounded-2xl border border-ink-700/30 bg-ink-850/60 p-4">
              <div className="flex items-center justify-between">
                <span className="text-paper-muted text-[11px]">3. Merkle Tree Root</span>
                {integrity ? (
                  integrity.merkle_root ? (
                    <CheckCircle2 size={16} className="text-safe" />
                  ) : (
                    <XCircle size={16} className="text-warn" />
                  )
                ) : (
                  <span className="text-[10px] text-paper-muted">UNCHECKED</span>
                )}
              </div>
              <span className="mt-2.5 block font-bold text-sm">
                {integrity
                  ? integrity.merkle_root
                    ? "SEALED MERKLE ROOT"
                    : "PENDING ROOT DERIVATION"
                  : "RUN VERIFY INTEGRITY"}
              </span>
            </div>

            {/* Layer 4: Blockchain Anchor */}
            <div className="rounded-2xl border border-ink-700/30 bg-ink-850/60 p-4">
              <div className="flex items-center justify-between">
                <span className="text-paper-muted text-[11px]">4. Polygon Amoy Anchor</span>
                {verificationResult ? (
                  verificationResult.public_anchor_consistent ? (
                    <CheckCircle2 size={16} className="text-safe" />
                  ) : (
                    <AlertOctagon size={16} className="text-warn" />
                  )
                ) : (
                  <span className="text-[10px] text-paper-muted">UNCHECKED</span>
                )}
              </div>
              <span className="mt-2.5 block font-bold text-sm">
                {verificationResult
                  ? verificationResult.public_anchor_consistent
                    ? "ON-CHAIN ANCHOR CONFIRMED"
                    : verificationAnchorText(verificationResult)
                  : "RUN VERIFY CHAIN"}
              </span>
            </div>
          </div>
        </section>

        {/* Main 2-Column Forensic Analysis Deck */}
        <div className="grid grid-cols-1 gap-6 xl:grid-cols-12">
          {/* Left Column: Chronology, Chart, Acoustic & Speaker Evidence */}
          <div className="space-y-6 xl:col-span-7">
            {/* Risk Trajectory Chart */}
            <EvidenceSection
              eyebrow="Temporal Risk Trajectory"
              title="Continuous Multi-Window Threat Progression"
              icon={<ShieldAlert size={16} />}
              badge={
                <span className="font-mono text-xs text-paper-muted">
                  Thresholds: 40% Warn · 70% Lock
                </span>
              }
            >
              <div className="h-64 w-full pt-2">
                {chartData.length ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={chartData} margin={{ top: 8, right: 12, left: -20, bottom: 0 }}>
                      <CartesianGrid stroke="#383838" vertical={false} />
                      <ReferenceArea y1={0} y2={40} fill="#E6E6E6" fillOpacity={0.03} />
                      <ReferenceArea y1={40} y2={70} fill="#8E8E8E" fillOpacity={0.06} />
                      <ReferenceArea y1={70} y2={100} fill="#FFFFFF" fillOpacity={0.10} />
                      <XAxis
                        dataKey="t"
                        tickFormatter={(v) => `T+${v}s`}
                        stroke="#8E8E8E"
                        fontSize={11}
                        fontFamily="'JetBrains Mono', monospace"
                      />
                      <YAxis
                        domain={[0, 100]}
                        stroke="#8E8E8E"
                        fontSize={11}
                        fontFamily="'JetBrains Mono', monospace"
                      />
                      <Tooltip
                        contentStyle={{
                          background: "#141414",
                          borderRadius: "12px",
                          border: "1px solid #383838",
                          fontFamily: "'JetBrains Mono', monospace",
                          fontSize: 12,
                          color: "#E6E6E6",
                        }}
                        labelFormatter={(v) => `Time: T+${v}s`}
                        formatter={(val: number, name: string) => [
                          `${val}%`,
                          name === "score"
                            ? "Fused Risk"
                            : name === "acoustic"
                              ? "Acoustic Spoof"
                              : "Intent Pressure",
                        ]}
                      />
                      <Line
                        type="monotone"
                        dataKey="score"
                        stroke="#FFFFFF"
                        strokeWidth={2.5}
                        dot={false}
                        name="score"
                      />
                      <Line
                        type="monotone"
                        dataKey="acoustic"
                        stroke="#E6E6E6"
                        strokeWidth={1.5}
                        strokeDasharray="3 3"
                        dot={false}
                        name="acoustic"
                      />
                      <Line
                        type="monotone"
                        dataKey="intent"
                        stroke="#8E8E8E"
                        strokeWidth={1.5}
                        strokeDasharray="4 2"
                        dot={false}
                        name="intent"
                      />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex h-full items-center justify-center font-mono text-xs text-paper-muted">
                    No timeline telemetry captured for this call.
                  </div>
                )}
              </div>

              {/* Chart Legend & Summary Stats */}
              <div className="mt-4 grid grid-cols-3 gap-2 border-t border-ink-700/40 pt-3 font-mono text-xs">
                <div>
                  <span className="text-paper-muted text-[10px] block">PEAK RISK</span>
                  <span
                    className={`font-bold ${
                      maxScore >= 70 ? "text-danger" : maxScore >= 40 ? "text-warn" : "text-safe"
                    }`}
                  >
                    {Math.round(maxScore)}%
                  </span>
                </div>
                <div>
                  <span className="text-paper-muted text-[10px] block">FLAGGED FRAMES</span>
                  <span className="text-paper-bright font-semibold">
                    {flaggedEvents.length} of {telemetryHistory.length}
                  </span>
                </div>
                <div>
                  <span className="text-paper-muted text-[10px] block">POLICY SHIFTS</span>
                  <span className="text-paper-bright font-semibold">{transitions.length}</span>
                </div>
              </div>
            </EvidenceSection>

            {/* Acoustic & Biometric Evidence */}
            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <EvidenceSection
                eyebrow="Acoustic Forensics"
                title="Synthetic Vocoder Analysis"
                icon={<Waves size={16} />}
              >
                <div className="space-y-3.5">
                  <SignalProgress label="Peak Anti-Spoof Signal" value={acousticPeak * 100} />
                  <DataField label="Audio Capture" value="16.0 kHz PCM · Silero VAD" mono />
                  <DataField label="Analysis Window" value="4.0s rolling window" mono />
                  <DataField
                    label="Backbone Model"
                    value="Meta MMS-300M (nii-yamagishilab)"
                    mono
                  />
                  <DataField
                    label="Spectral Assessment"
                    value={
                      acousticPeak >= 0.7
                        ? "Critical synthetic vocoder artifacts detected"
                        : acousticPeak >= 0.4
                          ? "Elevated phase dissonance observed"
                          : "Nominal human vocal dynamics"
                    }
                    tone={
                      acousticPeak >= 0.7
                        ? "text-danger font-semibold"
                        : acousticPeak >= 0.4
                          ? "text-warn font-semibold"
                          : "text-safe font-semibold"
                    }
                  />
                </div>
              </EvidenceSection>

              <EvidenceSection
                eyebrow="Speaker Biometrics"
                title="Voiceprint Reference Baseline"
                icon={<UserRound size={16} />}
              >
                <div className="space-y-3">
                  <div className="rounded-xl border border-ink-700/40 bg-ink-850/60 p-3">
                    <span className="font-mono text-[10px] uppercase text-paper-muted block">
                      Enrolled Voiceprint Match
                    </span>
                    <p className="mt-1 text-xs text-paper-dim leading-relaxed">
                      {session.telemetry?.speaker_score != null
                        ? `Similarity index: ${Math.round(session.telemetry.speaker_score * 100)}%`
                        : "No enrolled biometric reference found for this caller profile."}
                    </p>
                  </div>
                  <DataField
                    label="Enrollment Status"
                    value={session.telemetry?.speaker_score != null ? "ENROLLED" : "UNENROLLED"}
                    mono
                  />
                  <DataField
                    label="Identity Mismatch Risk"
                    value={
                      session.telemetry?.identity_mismatch != null
                        ? `${Math.round(session.telemetry.identity_mismatch * 100)}%`
                        : "NEUTRAL (0%)"
                    }
                    mono
                    tone={
                      session.telemetry?.identity_mismatch &&
                      session.telemetry.identity_mismatch >= 0.7
                        ? "text-danger font-bold"
                        : "text-paper-bright"
                    }
                  />
                  <DataField
                    label="Analyst Guidance"
                    value="Requires out-of-band MFA for sensitive transfer approval"
                  />
                </div>
              </EvidenceSection>
            </div>

            {/* Context & Transcript Evidence */}
            <EvidenceSection
              eyebrow="Conversational Extortion Log"
              title="ASR Transcript &amp; Dialogue Context"
              icon={<FileWarning size={16} />}
            >
              <div className="rounded-xl border border-ink-700/40 bg-ink-850/60 p-3.5">
                <span className="font-mono text-[10px] text-paper-muted uppercase block">
                  Persisted Dialogue Transcript
                </span>
                <p className="mt-1.5 font-sans text-xs leading-relaxed text-paper-bright italic">
                  “{liveTranscript || "No real-time transcript input logged during this monitoring window."}”
                </p>
              </div>

              <div className="mt-3.5 space-y-2">
                <span className="font-semibold text-xs text-paper-dim block">
                  Observed Speech-Acts &amp; Rationale:
                </span>
                {session.telemetry?.rationale && session.telemetry.rationale.length > 0 ? (
                  session.telemetry.rationale.map((r, i) => (
                    <div
                      key={`${r}-${i}`}
                      className="rounded-lg border border-danger/25 bg-danger-bg px-3 py-2 text-xs text-paper-bright"
                    >
                      {r}
                    </div>
                  ))
                ) : (
                  <p className="text-xs text-paper-muted">No flagged intent triggers registered.</p>
                )}
              </div>
            </EvidenceSection>

            {/* Chronological Event Log */}
            <EvidenceSection
              eyebrow="Forensic Audit Log"
              title="Sequential Decision Frames"
              icon={<Layers size={16} />}
            >
              <div className="max-h-72 overflow-y-auto space-y-2 pr-1">
                {telemetryHistory.length === 0 ? (
                  <p className="font-mono text-xs text-paper-muted">No telemetry frames recorded.</p>
                ) : (
                  telemetryHistory.map((ev, i) => (
                    <div
                      key={`${ev.timestamp}-${i}`}
                      className="flex items-start gap-3 rounded-xl border border-ink-700/30 bg-ink-850/50 p-2.5 font-mono text-xs"
                    >
                      <span
                        className={`mt-1.5 h-2 w-2 rounded-full shrink-0 ${
                          ev.status === "LOCK_VERIFY"
                            ? "bg-danger"
                            : ev.status === "WARN"
                              ? "bg-warn"
                              : "bg-safe"
                        }`}
                      />
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="font-bold text-paper-bright">
                            Frame #{i + 1} · {statusLabel(ev.status)} ({Math.round(ev.risk_score)}%)
                          </span>
                          <span className="text-paper-muted">{formatTime(ev.timestamp)}</span>
                        </div>
                        <p className="mt-1 font-sans text-xs text-paper-dim">
                          {ev.rationale[0] ?? "Nominal audio parameters"}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </EvidenceSection>
          </div>

          {/* Right Column: Cryptographic Chain of Custody, Merkle Tree, Blockchain Anchoring */}
          <div className="space-y-6 xl:col-span-5">
            {/* Cryptographic Integrity Panel */}
            <EvidenceSection
              eyebrow="Chain of Custody"
              title="SHA-256 Ledger &amp; Integrity Hashes"
              icon={<Fingerprint size={16} />}
            >
              <div className="space-y-1 font-mono">
                <HashDisplay
                  label="Authoritative Evidence Hash"
                  value={verificationResult?.evidence_hash}
                  status={verificationResult?.evidence_hash_integrity ? "ok" : null}
                />
                <HashDisplay
                  label="Local Chain Merkle Root"
                  value={verificationResult?.local_chain_root}
                  status={verificationResult?.local_chain_integrity ? "ok" : null}
                />
                <HashDisplay
                  label="Canonical Package SHA-256"
                  value={integrity?.package_sha256}
                  status={integrity?.package_sha256 ? "ok" : null}
                />
                <HashDisplay
                  label="Forensic Report SHA-256"
                  value={integrity?.report?.sha256}
                  status={integrity?.report?.sha256 ? "ok" : null}
                />
                <DataField
                  label="Ledger Record Count"
                  value={`${verificationResult?.ledger_record_count ?? telemetryHistory.length} frames`}
                  mono
                />
                <DataField
                  label="Ledger Continuity Check"
                  value={ledgerLabel(integrity)}
                  mono
                  tone={
                    integrity?.ledger?.valid
                      ? "text-safe font-semibold"
                      : integrity?.ledger
                        ? "text-danger font-semibold"
                        : "text-paper-muted"
                  }
                />
              </div>
            </EvidenceSection>

            {/* Public Blockchain Anchor (Polygon Amoy) */}
            <EvidenceSection
              eyebrow="Public Ledger Commitment"
              title="Polygon Amoy Blockchain Anchor"
              icon={<LockKeyhole size={16} />}
              badge={
                <StatusBadge
                  label={
                    verificationResult?.public_anchor_consistent
                      ? "Anchored"
                      : verificationResult
                        ? "Pending"
                        : "Standby"
                  }
                  variant={
                    verificationResult?.public_anchor_consistent
                      ? "safe"
                      : verificationResult
                        ? "warn"
                        : "neutral"
                  }
                  size="sm"
                />
              }
            >
              <div className="space-y-1">
                <DataField
                  label="Network"
                  value={verificationResult?.blockchain_network ?? "Polygon Amoy Testnet (Chain ID 80002)"}
                  mono
                />
                <DataField
                  label="Anchor Status"
                  value={verificationAnchorText(verificationResult)}
                  mono
                  tone={
                    verificationResult?.public_anchor_consistent ? "text-safe font-bold" : "text-warn"
                  }
                />
                <HashDisplay
                  label="Smart Contract Address"
                  value={verificationResult?.contract_address ?? "0x0000000000000000000000000000000000000000"}
                  truncateLength={{ lead: 12, tail: 8 }}
                />
                <HashDisplay
                  label="Transaction Hash (TxID)"
                  value={verificationResult?.tx_hash}
                  truncateLength={{ lead: 14, tail: 10 }}
                  status={verificationResult?.tx_hash ? "ok" : null}
                />
                <DataField
                  label="Anchor Timestamp"
                  value={verificationResult?.anchor_timestamp ?? "Pending blockchain confirmation"}
                  mono
                />
                {verificationResult?.tx_hash && (
                  <div className="pt-2.5 border-t border-ink-700/40">
                    <a
                      href={`https://amoy.polygonscan.com/tx/${verificationResult.tx_hash}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 text-xs font-mono text-signal hover:underline"
                    >
                      <span>Inspect on Polygonscan Explorer</span>
                      <ExternalLink size={13} />
                    </a>
                  </div>
                )}
              </div>
            </EvidenceSection>

            {/* Model Provenance & Environment */}
            <EvidenceSection
              eyebrow="Provenance &amp; Compliance"
              title="Model Provenance &amp; Runtime Stack"
              icon={<Cpu size={16} />}
            >
              <div className="space-y-1 font-mono text-xs">
                <DataField label="Platform Version" value="SatyaVoice Defense Suite v0.1.0" mono />
                <DataField label="Detector Execution" value={meta?.audioMode ?? "cloud"} mono />
                <DataField label="Audio Sampling" value="16,000 Hz 16-bit Mono PCM" mono />
                <DataField label="Acoustic Model" value="MMS-300M (Fine-Tuned Anti-Deepfake)" mono />
                <DataField label="Intent Stage" value="Multilingual ASR + Keyword Extortion Regex" mono />
                <DataField label="VAD Engine" value="Silero Voice Activity Detector" mono />
                <DataField label="Auditing Operator" value={meta?.callerId || "SOC-ANALYST-01"} mono />
              </div>
            </EvidenceSection>

            {/* Forensic Analyst Sign-off Advisory */}
            <div className="rounded-2xl border border-ink-700/40 bg-ink-900/60 p-4 font-mono text-xs">
              <span className="font-bold text-paper-bright uppercase block">
                Forensic Closeout Protocol:
              </span>
              <p className="mt-1.5 text-paper-muted leading-relaxed font-sans text-xs">
                Incident closeout requires deterministic agreement across local package hashes,
                sequential ledger integrity, and Polygon Amoy public anchor confirmation. All
                reported evidence is frozen upon session closeout and cannot be modified.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
