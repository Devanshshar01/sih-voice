import { useMemo, useState } from "react";
import { CheckCircle2, Download, FileWarning, RotateCcw, ShieldAlert } from "lucide-react";
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
import { registerForensicsEvidence, verifyForensicsEvidence } from "../lib/api";
import { buildTechnicalEvidenceReport, createTechnicalEvidencePdf } from "../lib/forensicPdf";
import type { ForensicsVerificationResponse } from "../types";

interface ForensicsViewProps {
  session: UseCallSession;
}

export default function ForensicsView({ session }: ForensicsViewProps) {
  const { meta, telemetryHistory, serverRiskSnapshot, durationSeconds, startOver } = session;
  const [verificationResult, setVerificationResult] = useState<ForensicsVerificationResponse | null>(null);
  const [verificationError, setVerificationError] = useState<string | null>(null);

  const chartData = useMemo(() => {
    if (telemetryHistory.length === 0) return [];
    const t0 = telemetryHistory[0].timestamp;
    return telemetryHistory.map((point) => ({
      t: Number((point.timestamp - t0).toFixed(1)),
      score: point.risk_score,
    }));
  }, [telemetryHistory]);

  const maxScore = telemetryHistory.reduce((max, p) => Math.max(max, p.risk_score), 0);
  const flaggedEvents = telemetryHistory.filter((p) => p.status !== "ALLOW");
  const finalStatus = telemetryHistory[telemetryHistory.length - 1]?.status ?? "ALLOW";
  const incidentDetected = maxScore >= 70;

  const handleExport = async () => {
    if (!meta) return;

    const report = await buildTechnicalEvidenceReport({
      callId: meta.callId,
      callerId: meta.callerId,
      recipientId: meta.recipientId,
      durationSeconds,
      maxRiskScore: maxScore,
      exportedAt: new Date().toISOString(),
      operatorIdentity: meta.callerId || "demo-operator",
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
      await registerForensicsEvidence(meta.callId, report);
    } catch {
      // Best-effort registration only: the export and local evidence package must remain usable even if the backend is unavailable.
    }

    const blob = await createTechnicalEvidencePdf(report);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `satyavoice-technical-integrity-${meta.callId}.pdf`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleVerify = async () => {
    if (!meta) return;

    try {
      const result = await verifyForensicsEvidence(meta.callId);
      setVerificationResult(result);
      setVerificationError(null);
    } catch (error) {
      setVerificationError(
        error instanceof Error ? error.message : "Verification could not be completed."
      );
      setVerificationResult(null);
    }
  };

  return (
    <div className="console-grid mx-auto max-w-5xl px-4 py-6 sm:px-6 sm:py-8">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="eyebrow">Incident closeout / evidence report</p>
          <h1 className="mt-2 text-2xl font-semibold text-paper">{incidentDetected ? "Impersonation attempt contained" : "Call cleared"}</h1>
          <p className="mt-2 text-sm text-paper-dim">{meta?.callerId ?? "Unknown caller"} <span className="text-mute">→</span> {meta?.recipientId ?? "Protected desk"}</p>
          <p className="mt-1 font-mono text-xs text-mute">{meta?.callId}</p>
        </div>
        <button
          onClick={startOver}
          className="flex items-center gap-2 border border-ink-600 px-3 py-2 text-xs text-paper-dim transition-colors hover:border-signal/50 hover:text-signal"
        >
          <RotateCcw size={14} />
          New call
        </button>
      </div>

      <div className={`mt-6 flex items-start gap-3 border px-4 py-3 ${incidentDetected ? "border-danger/40 bg-danger-bg text-danger" : "border-safe/40 bg-safe-bg text-safe"}`}>
        {incidentDetected ? <ShieldAlert size={18} className="mt-0.5 shrink-0" /> : <CheckCircle2 size={18} className="mt-0.5 shrink-0" />}
        <div>
          <p className="text-sm font-medium">{incidentDetected ? "Sensitive workflow was gated by SatyaVoice." : "No high-risk activity was detected."}</p>
          <p className="mt-1 text-xs opacity-80">Final policy state: {finalStatus.replace("_", " ")} · Evidence is derived from {telemetryHistory.length} analysis windows.</p>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-3 gap-3">
        <div className="panel p-3">
          <p className="text-xs text-mute">Duration</p>
          <p className="tabular mt-1 font-mono text-lg text-paper">
            {Math.floor(durationSeconds / 60)}:{(durationSeconds % 60).toString().padStart(2, "0")}
          </p>
        </div>
        <div className="panel p-3">
          <p className="text-xs text-mute">Peak risk score</p>
          <p
            className={`tabular mt-1 font-mono text-lg ${
              maxScore >= 70 ? "text-danger" : maxScore >= 40 ? "text-warn" : "text-safe"
            }`}
          >
            {maxScore}/100
          </p>
        </div>
        <div className="panel p-3">
          <p className="text-xs text-mute">Flagged windows</p>
          <p className="tabular mt-1 font-mono text-lg text-paper">{flaggedEvents.length}</p>
        </div>
      </div>

      <div className="panel mt-4 p-4">
        <p className="text-sm font-medium text-paper">Risk score timeline</p>
        <div className="mt-3 h-56">
          {chartData.length > 0 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                <CartesianGrid stroke="#1b262e" vertical={false} />
                <ReferenceArea y1={0} y2={40} fill="#1a4a3a" fillOpacity={0.35} />
                <ReferenceArea y1={40} y2={70} fill="#4a3a17" fillOpacity={0.35} />
                <ReferenceArea y1={70} y2={100} fill="#4a2320" fillOpacity={0.35} />
                <XAxis dataKey="t" tickFormatter={(v) => `${v}s`} stroke="#546069" fontSize={11} />
                <YAxis domain={[0, 100]} stroke="#546069" fontSize={11} />
                <Tooltip
                  contentStyle={{ background: "#0f171d", border: "1px solid #25333c", fontSize: 12 }}
                  labelFormatter={(v) => `t = ${v}s`}
                  formatter={(value: number) => [`${value}/100`, "Trust index"]}
                />
                <Line type="monotone" dataKey="score" stroke="#4fc3f7" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <p className="flex h-full items-center justify-center text-sm text-mute">
              No telemetry captured for this call.
            </p>
          )}
        </div>
      </div>

      <div className="panel mt-4 p-4">
        <div className="flex items-center gap-2">
          <FileWarning size={15} className="text-warn" />
          <p className="text-sm font-medium text-paper">Flagged events</p>
        </div>
        {flaggedEvents.length === 0 ? (
          <p className="mt-3 text-sm text-mute">No anomalies were flagged during this call. The monitored workflow remained available.</p>
        ) : (
          <ul className="mt-3 divide-y divide-ink-600">
            {flaggedEvents.map((event, i) => (
              <li key={i} className="py-2.5">
                <div className="flex items-center justify-between">
                  <span
                    className={`text-xs font-medium ${
                      event.status === "LOCK_VERIFY" ? "text-danger" : "text-warn"
                    }`}
                  >
                    {event.status === "LOCK_VERIFY" ? "Locked" : "Warning"} — {event.risk_score}/100
                  </span>
                  <span className="tabular font-mono text-xs text-mute">
                    {new Date(event.timestamp * 1000).toLocaleTimeString()}
                  </span>
                </div>
                <p className="mt-1 text-sm text-paper-dim">{event.rationale[0]}</p>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="mt-4 flex flex-wrap gap-3">
        <button
          onClick={handleExport}
          className="flex items-center gap-2 border border-ink-600 px-4 py-2.5 text-sm text-paper-dim transition-colors hover:border-signal/50 hover:text-signal"
        >
          <Download size={15} />
          Export technical integrity evidence package (PDF)
        </button>
        <button
          onClick={handleVerify}
          className="border border-ink-600 px-4 py-2.5 text-sm text-paper-dim transition-colors hover:border-signal/50 hover:text-signal"
        >
          Verify evidence chain
        </button>
      </div>

      {verificationError && (
        <p className="mt-3 text-sm text-danger">Verification error: {verificationError}</p>
      )}

      {verificationResult && (
        <div className="panel mt-4 p-4">
          <p className="text-sm font-medium text-paper">Verification result</p>
          <div className="mt-3 grid gap-2 text-sm text-paper-dim">
            <p>Evidence hash integrity: {verificationResult.evidence_hash_integrity ? "verified" : "mismatch"}</p>
            <p>Local chain integrity: {verificationResult.local_chain_integrity ? "verified" : "mismatch"}</p>
            <p>Public anchor consistency: {verificationResult.public_anchor_consistent ? "verified" : "not confirmed"}</p>
            <p>Anchor status: {verificationResult.anchor_status}</p>
            <p>Local chain root: {verificationResult.local_chain_root ?? "pending"}</p>
            <p>Blockchain network: {verificationResult.blockchain_network ?? "unavailable"}</p>
            <p>Contract address: {verificationResult.contract_address ?? "unavailable"}</p>
            <p>Transaction hash: {verificationResult.tx_hash ?? "not confirmed"}</p>
            <p>Anchor timestamp: {verificationResult.anchor_timestamp ?? "not confirmed"}</p>
          </div>
        </div>
      )}
    </div>
  );
}
