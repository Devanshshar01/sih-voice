import type { RiskTelemetry } from "../types";

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
  acoustic_score: number | null;
  intent_score: number;
  status: string;
  rationale: string[];
  inference_available?: boolean;
  detector_status?: string;
  detector?: Record<string, unknown>;
  degraded?: Record<string, string>;
  speaker_score?: number | null;
  intent_indicators?: Array<{
    category: string;
    severity: string;
    speech_act: string;
    language: string;
    confidence: number;
  }>;
  derived_data_hash: string;
  previous_hash: string;
  chain_record_hash: string;
}

export interface ForensicsExportReport {
  call_id: string;
  caller_id: string;
  recipient_id: string;
  duration_seconds: number;
  max_risk_score: number | null;
  detection: {
    risk_score: number | null;
    risk_status: string | null;
    model_score: number | null;
    model_status: string;
    speaker_match: number | null;
    contextual: string | null;
    confidence: null;
  };
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

/**
 * F13: This is NOT a cryptographic signing key and the `package_signature`
 * value is NOT a digital signature. It is a keyed SHA-256 INTEGRITY CHECKSUM:
 * a browser-side constant salt bound into the digest so accidental payload
 * mutation is detectable within the exported document. It provides no
 * authenticity, no non-repudiation, and no secret — anyone with this source
 * can reproduce or forge it. Authenticity comes from the SERVER-side evidence
 * hash returned by /forensics/register (and its Merkle/on-chain anchoring).
 */
const LOCAL_SIGNING_KEY = "satyavoice-local-integrity-checksum-salt";
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
  return sha256Hex(`${LOCAL_SIGNING_KEY}:${payload}`);
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function usableAcousticScore(point: RiskTelemetry | undefined): number | null {
  if (!point || typeof point.acoustic_score !== "number" || !Number.isFinite(point.acoustic_score)) {
    return null;
  }
  const detector = asRecord(point.detector);
  if (
    point.inference_available === false ||
    point.detector_status === "unavailable" ||
    point.degraded?.anti_spoof ||
    detector.status === "unavailable" ||
    detector.status === "degraded" ||
    detector.evidence_status === "unavailable"
  ) {
    return null;
  }
  return point.acoustic_score;
}

function detectorSnapshot(point: RiskTelemetry | undefined): Record<string, unknown> {
  const detector = asRecord(point?.detector);
  const fields = [
    "mode",
    "model",
    "model_version_antispoof",
    "revision",
    "status",
    "evidence_status",
    "fake_probability",
    "real_probability",
    "inference_latency_ms",
    "inference_time_ms",
    "evidence_age_ms",
  ];
  return Object.fromEntries(fields
    .filter((key) => detector[key] !== undefined)
    .map((key) => [key, detector[key]]));
}

function intentIndicatorSnapshot(point: RiskTelemetry): AnalysisWindowEvidence["intent_indicators"] {
  return (point.intent_risks ?? []).map((risk) => ({
    category: risk.category,
    severity: risk.severity,
    speech_act: risk.speech_act,
    language: risk.language,
    confidence: risk.confidence,
  }));
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

  const latestPoint = telemetryHistory[telemetryHistory.length - 1];
  const highestRiskPoint = telemetryHistory.reduce<RiskTelemetry | undefined>(
    (highest, point) => !highest || point.risk_score > highest.risk_score ? point : highest,
    undefined
  );
  const latestDetector = detectorSnapshot(latestPoint);
  const modelIdentityPoint = [...telemetryHistory].reverse().find((point) => {
    const detector = detectorSnapshot(point);
    return typeof detector.model === "string" || typeof detector.model_version_antispoof === "string";
  });
  const modelIdentity = detectorSnapshot(modelIdentityPoint);
  const modelId = typeof modelIdentity.model_version_antispoof === "string"
    ? modelIdentity.model_version_antispoof
    : typeof modelIdentity.model === "string" ? modelIdentity.model : null;
  const latestAcousticScore = usableAcousticScore(latestPoint);
  const latestStatus = typeof latestDetector.evidence_status === "string"
    ? latestDetector.evidence_status
    : typeof latestDetector.status === "string"
      ? latestDetector.status
      : latestAcousticScore === null ? "unavailable" : "ok";
  const contextualIndicators = (latestPoint?.intent_risks ?? [])
    .map((risk) => risk.category)
    .filter((category, index, categories) => categories.indexOf(category) === index);
  const contextualSummary = contextualIndicators.length
    ? contextualIndicators.join(", ")
    : latestPoint?.transcript?.trim() ? "No contextual indicators recorded" : null;

  for (let index = 0; index < telemetryHistory.length; index += 1) {
    const point = telemetryHistory[index];
    const relativeSeconds = Math.max(0, point.timestamp - timeZero);
    const derivedData = {
      window_index: index,
      timestamp: point.timestamp,
      synchronized_timestamp: point.timestamp,
      relative_time_seconds: Number(relativeSeconds.toFixed(3)),
      risk_score: point.risk_score,
      acoustic_score: usableAcousticScore(point),
      intent_score: point.intent_score,
      status: point.status,
      rationale: point.rationale,
      inference_available: point.inference_available,
      detector_status: point.detector_status,
      detector: detectorSnapshot(point),
      degraded: point.degraded,
      speaker_score: point.speaker_score ?? null,
      intent_indicators: intentIndicatorSnapshot(point),
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
    max_risk_score: telemetryHistory.length ? maxRiskScore : null,
    detection: {
      risk_score: highestRiskPoint?.risk_score ?? null,
      risk_status: highestRiskPoint?.status ?? null,
      model_score: latestAcousticScore,
      model_status: latestStatus,
      speaker_match: typeof latestPoint?.speaker_score === "number" && Number.isFinite(latestPoint.speaker_score)
        ? latestPoint.speaker_score
        : null,
      contextual: contextualSummary,
      // The detector and risk engine do not emit a calibrated confidence value.
      confidence: null,
    },
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
      ...modelVersionMetadata,
      detector_mode: modelVersionMetadata?.detector_mode ?? "unknown",
      model_id: modelId,
      model_version: typeof modelIdentity.revision === "string"
        ? modelIdentity.revision
        : typeof modelIdentity.model_version === "string" ? modelIdentity.model_version : null,
      detector_status: latestStatus,
      audio_pipeline: modelVersionMetadata?.audio_pipeline ?? "WebSocket PCM + sliding windows",
      telemetry_window_count: telemetryHistory.length,
      generated_at: exportedAt,
    },
    policy_state_transitions: policyStateTransitions,
    analysis_windows: analysisWindows,
    technical_integrity_note:
      "This is a technical integrity evidence package for local analyst review. It is not a legal certification and does not establish IT Act §65B admissibility; any legal certification requires a human/legal process.",
  };

  const evidenceHash = await sha256Hex(JSON.stringify(reportWithoutSignature));
  const packageSignature = {
    // F13: honest algorithm label — this is a local integrity checksum,
    // not an HMAC and not a signature (no secret key is involved).
    algorithm: "SHA-256 local integrity checksum (non-cryptographic)",
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
    `Peak risk score: ${report.max_risk_score === null ? "unavailable" : `${report.max_risk_score}/100`}`,
    `Detection summary: ${compactJson(report.detection)}`,
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
      `- Window ${window.window_index}: t=${window.relative_time_seconds.toFixed(1)}s | risk=${window.risk_score} | acoustic=${window.acoustic_score === null ? "unavailable" : window.acoustic_score.toFixed(4)} | intent=${window.intent_score.toFixed(4)} | status=${window.status}`
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
    `Local integrity checksum (not a signature): ${report.package_signature.algorithm} | produced_by=${report.package_signature.signed_by}`,
    `Checksum value: ${report.package_signature.signature}`,
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

/**
 * Export-scoped report fields: they describe the EXPORT OPERATION, not the
 * evidence itself.
 *
 * PRODUCTION INCIDENT (why this exists): ``exported_at`` was part of the
 * registered payload, so every export of the same finalized call produced a
 * different evidence hash for the same evidence id. Since the evidence id is
 * the primary key of the evidence store, the second export collided on that key
 * and the backend answered HTTP 500 (IntegrityError).
 *
 * The registered identity must be a FROZEN EVIDENCE SNAPSHOT: two exports of the
 * same finalized call must yield the same hash. These fields stay on the
 * exported report/PDF (where they are useful to a human) but are excluded from
 * the registered evidence identity.
 */
export const EXPORT_SCOPED_FIELDS = ["exported_at", "evidence_hash", "package_signature"] as const;

/**
 * Build the frozen, export-invariant evidence snapshot that is registered on the
 * server. Repeated exports of the same finalized call produce identical bytes
 * (and therefore the same registered evidence hash).
 *
 * Excluded: the export-scoped fields above and the export clock inside the model
 * metadata. Included instead: ``evidence_finalized_at``, derived from the last
 * recorded analysis window (the finalized call boundary) — never from the
 * export clock.
 */
export function buildEvidenceSnapshot(report: ForensicsExportReport): Record<string, unknown> {
  const excluded = new Set<string>(EXPORT_SCOPED_FIELDS);
  const snapshot: Record<string, unknown> = {};

  for (const [key, value] of Object.entries(report)) {
    if (excluded.has(key)) continue;
    snapshot[key] = value;
  }

  // `generated_at` in the model metadata is the export time, not the model's.
  const metadata: Record<string, unknown> = { ...(report.model_version_metadata ?? {}) };
  delete metadata.generated_at;
  snapshot.model_version_metadata = metadata;

  // Stable, evidence-derived finalization boundary.
  const lastWindow = report.analysis_windows[report.analysis_windows.length - 1];
  snapshot.evidence_finalized_at = lastWindow
    ? new Date(lastWindow.timestamp * 1000).toISOString()
    : null;

  return snapshot;
}

export async function createTechnicalEvidencePdf(report: ForensicsExportReport): Promise<Blob> {
  const pdf = buildPdfText(report);
  return new Blob([pdf], { type: "application/pdf" });
}
