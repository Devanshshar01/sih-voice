import type { RiskTelemetry } from "../types";

/** Canonical forensic package input (mirrors app/services/evidence_package.py). */
export interface CanonicalEvidencePackageInput {
  schema_version: "forensic-v1";
  package_format: string;
  call_id: string;
  caller_id: string;
  recipient_id: string;
  duration_seconds: number;
  generated_at: string;
  codec: string;
  detected_languages: string[];
  model_provenance: {
    detector_mode: string;
    acoustic_model_id: string;
    acoustic_model_revision: string;
    asr_model: string;
    speaker_model: string;
    speaker_model_version: string;
    model_artifact_hashes: Record<string, string>;
    risk_config_fingerprint: string;
  };
  windows: Array<{
    window_index: number;
    timestamp: number;
    relative_time_seconds: number;
    risk_score: number;
    acoustic_score: number;
    intent_score: number;
    speaker_similarity: number | null;
    identity_mismatch: number | null;
    status: string;
    transcript_hash: string | null;
    language: string | null;
    codec: string | null;
    vad_active: boolean | null;
    rationale: string[];
    intent_findings: Array<{
      category: string;
      confidence: number;
      severity: string;
      speech_act: string;
      matched_phrase: string;
      language: string;
    }>;
  }>;
  peak_risk_score: number;
  fused_risk_score: number;
  action_taken: string;
  verification_result: string | null;
  disposition: string;
  intent_findings: Array<{
    category: string;
    confidence: number;
    severity: string;
    speech_act: string;
    matched_phrase: string;
    language: string;
  }>;
}

/**
 * Build the canonical evidence package INPUT from live telemetry.
 *
 * This is a transport convenience only: the backend validates, completes,
 * hashes, and stores the package. Raw transcripts are converted to SHA-256
 * digests here — transcript text never enters the canonical package.
 */
export async function buildCanonicalEvidencePackage({
  callId,
  callerId,
  recipientId,
  durationSeconds,
  telemetryHistory,
  audioMode,
  actionTaken,
  verificationResult,
}: {
  callId: string;
  callerId: string;
  recipientId: string;
  durationSeconds: number;
  telemetryHistory: RiskTelemetry[];
  audioMode: string;
  actionTaken: string;
  verificationResult: string | null;
}): Promise<CanonicalEvidencePackageInput> {
  const timeZero = telemetryHistory[0]?.timestamp ?? Date.now() / 1000;

  const windows = await Promise.all(
    telemetryHistory.map(async (point, index) => ({
      window_index: index,
      timestamp: point.timestamp,
      relative_time_seconds: Number(Math.max(0, point.timestamp - timeZero).toFixed(3)),
      risk_score: point.risk_score,
      acoustic_score: point.acoustic_score,
      intent_score: point.intent_score,
      speaker_similarity: point.speaker_score ?? null,
      identity_mismatch: point.identity_mismatch ?? null,
      status: point.status,
      transcript_hash: point.transcript ? await sha256Hex(point.transcript) : null,
      language: point.detected_language ?? null,
      codec: null,
      vad_active: point.vad_active ?? null,
      rationale: point.rationale ?? [],
      intent_findings: (point.intent_risks ?? []).map((r) => ({
        category: r.category,
        confidence: r.confidence,
        severity: r.severity,
        speech_act: r.speech_act,
        matched_phrase: r.matched_phrase,
        language: r.language,
      })),
    }))
  );

  // Consolidate dedup intent findings across windows (category + phrase).
  const seenFindings = new Map<string, CanonicalEvidencePackageInput["intent_findings"][number]>();
  for (const w of windows) {
    for (const f of w.intent_findings) {
      const key = `${f.category}:${f.matched_phrase.toLowerCase()}`;
      if (!seenFindings.has(key)) seenFindings.set(key, f);
    }
  }

  return {
    schema_version: "forensic-v1",
    package_format: "satyavoice-technical-integrity-evidence-package",
    call_id: callId,
    caller_id: callerId,
    recipient_id: recipientId,
    duration_seconds: durationSeconds,
    generated_at: new Date().toISOString(),
    codec: "pcm",
    detected_languages: Array.from(
      new Set(windows.map((w) => w.language).filter((l): l is string => Boolean(l)))
    ),
    model_provenance: {
      detector_mode: audioMode,
      acoustic_model_id: "",
      acoustic_model_revision: "",
      asr_model: "",
      speaker_model: "",
      speaker_model_version: "",
      model_artifact_hashes: {},
      risk_config_fingerprint: "",
    },
    windows,
    peak_risk_score: telemetryHistory.reduce((m, p) => Math.max(m, p.risk_score), 0),
    fused_risk_score: telemetryHistory[telemetryHistory.length - 1]?.risk_score ?? 0,
    action_taken: actionTaken,
    verification_result: verificationResult,
    disposition: "closed",
    intent_findings: Array.from(seenFindings.values()),
  };
}

export interface PolicyTransition {
  from: string;
  to: string;
  observed_at: string;
}

export interface AnalysisWindowEvidence {
  window_index: number;
  timestamp: number;
  relative_time_seconds: number;
  risk_score: number;
  acoustic_score: number;
  intent_score: number;
  status: string;
  rationale: string[];
  derived_data_hash: string;
  previous_hash: string;
  chain_record_hash: string;
}

export interface ForensicsExportReport {
  call_id: string;
  caller_id: string;
  recipient_id: string;
  duration_seconds: number;
  max_risk_score: number;
  exported_at: string;
  operator_identity: string;
  evidence_hash?: string | null;
  local_chain_root?: string | null;
  local_chain_status?: string | null;
  anchoring_status?: string | null;
  blockchain_network?: string | null;
  contract_address?: string | null;
  transaction_hash?: string | null;
  anchoring_timestamp?: string | null;
  model_version_metadata: Record<string, unknown>;
  policy_state_transitions: PolicyTransition[];
  analysis_windows: AnalysisWindowEvidence[];
  package_signature: {
    algorithm: string;
    signed_by: string;
    signature: string;
  };
  technical_integrity_note: string;
}

const DEMO_SIGNING_KEY = "satyavoice-local-demo-signing-key";
const textEncoder = new TextEncoder();

const compactJson = (value: Record<string, unknown>) => JSON.stringify(value).replace(/\s+/g, " ");

const escapePdfText = (value: string) =>
  String(value)
    .replace(/\\/g, "\\\\")
    .replace(/\(/g, "\\(")
    .replace(/\)/g, "\\)")
    .replace(/\r/g, "")
    .replace(/\n/g, " ");

async function sha256Hex(value: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", textEncoder.encode(value));
  return Array.from(new Uint8Array(digest))
    .map((byte) => byte.toString(16).padStart(2, "0"))
    .join("");
}

async function buildPackageSignature(reportWithoutSignature: Omit<ForensicsExportReport, "package_signature">): Promise<string> {
  const payload = JSON.stringify(reportWithoutSignature);
  return sha256Hex(`${DEMO_SIGNING_KEY}:${payload}`);
}

export async function buildTechnicalEvidenceReport({
  callId,
  callerId,
  recipientId,
  durationSeconds,
  maxRiskScore,
  exportedAt,
  operatorIdentity,
  telemetryHistory,
  modelVersionMetadata,
}: {
  callId: string;
  callerId: string;
  recipientId: string;
  durationSeconds: number;
  maxRiskScore: number;
  exportedAt: string;
  operatorIdentity: string;
  telemetryHistory: RiskTelemetry[];
  modelVersionMetadata?: Record<string, unknown>;
}): Promise<ForensicsExportReport> {
  const timeZero = telemetryHistory[0]?.timestamp ?? Date.now() / 1000;
  const analysisWindows: AnalysisWindowEvidence[] = [];

  let previousHash = "GENESIS";

  for (let index = 0; index < telemetryHistory.length; index += 1) {
    const point = telemetryHistory[index];
    const relativeSeconds = Math.max(0, point.timestamp - timeZero);
    const derivedData = {
      window_index: index,
      timestamp: point.timestamp,
      synchronized_timestamp: point.timestamp,
      relative_time_seconds: Number(relativeSeconds.toFixed(3)),
      risk_score: point.risk_score,
      acoustic_score: point.acoustic_score,
      intent_score: point.intent_score,
      status: point.status,
      rationale: point.rationale,
    };

    const derivedDataHash = await sha256Hex(JSON.stringify(derivedData));
    const chainRecordHash = await sha256Hex(`${previousHash}:${derivedDataHash}`);

    analysisWindows.push({
      ...derivedData,
      derived_data_hash: derivedDataHash,
      previous_hash: previousHash,
      chain_record_hash: chainRecordHash,
    });

    previousHash = chainRecordHash;
  }

  const policyStateTransitions: PolicyTransition[] = telemetryHistory.slice(1).map((point, index) => ({
    from: telemetryHistory[index].status,
    to: point.status,
    observed_at: new Date(point.timestamp * 1000).toISOString(),
  }));

  const reportWithoutSignature: Omit<ForensicsExportReport, "package_signature"> = {
    call_id: callId,
    caller_id: callerId,
    recipient_id: recipientId,
    duration_seconds: durationSeconds,
    max_risk_score: maxRiskScore,
    exported_at: exportedAt,
    operator_identity: operatorIdentity,
    evidence_hash: null,
    local_chain_root: null,
    local_chain_status: "pending",
    anchoring_status: "pending",
    blockchain_network: "polygon-amoy",
    contract_address: null,
    transaction_hash: null,
    anchoring_timestamp: null,
    model_version_metadata: {
      app_name: "SatyaVoice",
      app_version: "0.1.0",
      detector_mode: modelVersionMetadata?.detector_mode ?? "demo",
      audio_pipeline: modelVersionMetadata?.audio_pipeline ?? "WebSocket PCM + sliding windows",
      telemetry_window_count: telemetryHistory.length,
      generated_at: exportedAt,
      ...modelVersionMetadata,
    },
    policy_state_transitions: policyStateTransitions,
    analysis_windows: analysisWindows,
    technical_integrity_note:
      "This is a technical integrity evidence package for local/demo review. It is not a legal certification and does not establish IT Act §65B admissibility; any legal certification requires a human/legal process.",
  };

  const evidenceHash = await sha256Hex(JSON.stringify(reportWithoutSignature));
  const packageSignature = {
    algorithm: "HMAC-SHA256 placeholder",
    signed_by: operatorIdentity,
    signature: await buildPackageSignature({
      ...reportWithoutSignature,
      evidence_hash: evidenceHash,
    }),
  };

  return {
    ...reportWithoutSignature,
    evidence_hash: evidenceHash,
    package_signature: packageSignature,
  };
}

const buildPdfText = (report: ForensicsExportReport) => {
  const lines = [
    "SATYAVOICE TECHNICAL INTEGRITY EVIDENCE PACKAGE",
    "",
    `Call ID: ${report.call_id}`,
    `Operator identity: ${report.operator_identity}`,
    `Caller ID: ${report.caller_id}`,
    `Recipient ID: ${report.recipient_id}`,
    `Duration: ${report.duration_seconds.toFixed(1)}s`,
    `Peak risk score: ${report.max_risk_score}/100`,
    `Exported at: ${report.exported_at}`,
    `Evidence hash: ${report.evidence_hash ?? "pending-registration"}`,
    `Local chain/root: ${report.local_chain_root ?? "pending-registration"}`,
    `Anchoring status: ${report.anchoring_status ?? "pending"}`,
    `Blockchain network: ${report.blockchain_network ?? "unavailable"}`,
    `Contract address: ${report.contract_address ?? "unavailable"}`,
    `Transaction hash: ${report.transaction_hash ?? "not-confirmed"}`,
    `Anchor timestamp: ${report.anchoring_timestamp ?? "not-confirmed"}`,
    `Model / version metadata: ${compactJson(report.model_version_metadata)}`,
    "",
    "Policy state transitions:",
  ];

  if (report.policy_state_transitions.length === 0) {
    lines.push("- No transitions observed.");
  } else {
    report.policy_state_transitions.forEach((transition) => {
      lines.push(`- ${transition.from} -> ${transition.to} @ ${transition.observed_at}`);
    });
  }

  lines.push("", "Analysis windows:");

  report.analysis_windows.forEach((window) => {
    lines.push(
      `- Window ${window.window_index}: t=${window.relative_time_seconds.toFixed(1)}s | risk=${window.risk_score} | acoustic=${window.acoustic_score.toFixed(4)} | intent=${window.intent_score.toFixed(4)} | status=${window.status}`
    );
    lines.push(`  rationale=${window.rationale.join(" | ")}`);
    lines.push(`  derived_data_hash=${window.derived_data_hash}`);
    lines.push(`  chain record: previous=${window.previous_hash} | current=${window.chain_record_hash}`);
  });

  lines.push("", "Chain-of-custody summary:");
  report.analysis_windows.forEach((window) => {
    lines.push(`- Window ${window.window_index}: previous_hash=${window.previous_hash} | chain_record_hash=${window.chain_record_hash}`);
  });

  lines.push(
    "",
    `Package signature: ${report.package_signature.algorithm} | signed_by=${report.package_signature.signed_by}`,
    `Signature value: ${report.package_signature.signature}`,
    "",
    `Technical integrity note: ${report.technical_integrity_note}`
  );

  const streamLines = lines
    .map((line, index) => {
      const y = 760 - index * 14;
      return `BT /F1 11 Tf 1 0 0 1 72 ${y} Tm (${escapePdfText(line)}) Tj ET`;
    })
    .join("\n");

  const content = `<< /Length ${streamLines.length} >>\nstream\n${streamLines}\nendstream`;
  const objects = [
    `<< /Type /Catalog /Pages 2 0 R >>`,
    `<< /Type /Pages /Count 1 /Kids [3 0 R] >>`,
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>`,
    content,
    `<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>`,
  ];

  let pdf = "%PDF-1.4\n";
  const offsets = [0];

  for (let index = 0; index < objects.length; index += 1) {
    offsets.push(pdf.length);
    pdf += `${index + 1} 0 obj\n${objects[index]}\nendobj\n`;
  }

  const xrefStart = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;

  for (let index = 1; index <= objects.length; index += 1) {
    pdf += `${String(offsets[index]).padStart(10, "0")} 00000 n \n`;
  }

  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`;

  return pdf;
};

export async function createTechnicalEvidencePdf(report: ForensicsExportReport): Promise<Blob> {
  const pdf = buildPdfText(report);
  return new Blob([pdf], { type: "application/pdf" });
}
