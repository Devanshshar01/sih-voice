export type RiskStatus = "ALLOW" | "WARN" | "LOCK_VERIFY";

export interface LatencyStageStats {
  p50: number;
  p95: number;
  n: number;
}

export interface RiskTelemetry {
  timestamp: number;
  risk_score: number;
  acoustic_score: number;
  intent_score: number;
  status: RiskStatus;
  rationale: string[];
  /** Identity evidence: similarity to enrolled reference (null = unknown/neutral). */
  speaker_score?: number | null;
  /** Derived identity RISK term = 1 - similarity; 0 when identity unknown. */
  identity_mismatch?: number;
  hard_trigger?: boolean;
  /** Stages that failed and fell back to degraded evidence. */
  degraded?: Record<string, string>;
  /** Weighted contributions per component (audit view of the fusion). */
  fusion?: {
    weights: { acoustic: number; intent: number; identity_mismatch: number };
    contributions: { acoustic: number; intent: number; identity_mismatch: number };
    raw_score: number;
  };
  /** Silero VAD stage telemetry (optional for backward compatibility). */
  vad_active?: boolean;
  vad_coverage?: number;
  vad_backend?: "silero" | "energy-fallback" | "disabled";
  vad_skipped?: boolean;
  malformed_frames?: number;
  /** Contextual ASR/intent evidence (SIH multilingual phase). */
  transcript?: string;
  /** ISO code of the detected/requested language (e.g. en, hi, ta, te, bn, mr). */
  detected_language?: string | null;
  /** Structured contextual-risk evidence produced by the intent analyzer. */
  intent_risks?: IntentRiskEvidence[];
  /** Per-window stage timings in ms + rolling p50/p95 per stage. */
  latency_ms?: Record<string, number>;
  latency_stats?: Record<string, LatencyStageStats>;
}

/** One structured piece of contextual-risk evidence from the intent stage. */
export interface IntentRiskEvidence {
  category: "otp" | "upi" | "amount" | "urgency" | string;
  confidence: number;
  evidence: string;
  matched_phrase: string;
  language: string;
  severity: "info" | "elevated" | "critical" | string;
  speech_act: "mention" | "request" | "instruction" | "transaction" | string;
  window_index?: number;
  timestamp?: number;
}

export interface CallStartResponse {
  call_id: string;
  status: string;
  ws_url: string;
  token?: string;
}

export interface RiskTimelinePoint {
  t: number;
  score: number;
}

export interface CallRiskResponse {
  call_id: string;
  current_risk_score: number;
  timeline: RiskTimelinePoint[];
}

export interface VerificationChallengeResponse {
  success: boolean;
  new_risk_state: RiskStatus;
  message: string;
}

export interface VerificationRequestResponse {
  code: string;
  expires_in_seconds: number;
  delivery_channel: string;
}

export interface CallActionResult {
  ok: boolean;
  status: number;
  executed: boolean;
  message: string;
}

export interface ForensicsVerificationResponse {
  evidence_id: string;
  evidence_hash_integrity: boolean;
  local_chain_integrity: boolean;
  public_anchor_consistent: boolean;
  evidence_hash: string;
  local_chain_root: string | null;
  anchor_status: string;
  blockchain_network: string | null;
  contract_address: string | null;
  tx_hash: string | null;
  anchor_timestamp: string | null;
  failure_reason: string | null;
  ledger_record_count: number;
  /** Integrity-summary additions (Phase 13) — present on newer responses. */
  package_sha256?: string | null;
  merkle_root?: string | null;
  report_sha256?: string | null;
  ledger?: { valid?: boolean; entries_checked?: number };
}

/** One cryptographic identity, kept distinct (never collapsed into one field). */
export interface LedgerVerification {
  valid: boolean;
  entries_checked: number;
  first_invalid_sequence: number | null;
  expected_hash: string | null;
  actual_hash: string | null;
  reason: string | null;
}

/** Blockchain anchoring state — DRY_RUN is never representable as confirmed. */
export interface BlockchainAnchorState {
  status: string;
  confirmed: boolean;
  simulated: boolean;
  network: string | null;
  contract: string | null;
  tx_hash: string | null;
  block_number: number | null;
  anchored_at: string | null;
  note: string | null;
}

/**
 * EvidenceIntegritySummary (Phase 5/9) — the one verification summary, served by
 * `GET /forensics/{evidence_id}/verify`. Derived from stored evidence only; no
 * field is regenerated and no fresh timestamp is injected server-side.
 */
export interface ForensicsIntegritySummary {
  evidence_id: string;
  schema_version: string | null;
  package_sha256: string | null;
  merkle_root: string | null;
  ledger_head: string | null;
  ledger: LedgerVerification | null;
  report: { sha256: string | null; generated_at: string | null; schema_version: string | null };
  blockchain: BlockchainAnchorState;
  verification?: { url: string; api_path: string };
}

/** Audio source driving the pipeline for this call. */
// cloud        — raw mic audio -> backend -> full multimodal pipeline
// hybrid       — local anti-spoof in-browser + backend ASR/speaker/policy
// edge-local   — raw audio NEVER leaves the device; only derived results go
//                to the backend (no raw-audio WebSocket)
export type AudioMode = "cloud" | "hybrid" | "edge-local";

/** True for modes where the browser performs anti-spoof locally. */
export function usesLocalInference(mode: AudioMode): boolean {
  return mode === "hybrid" || mode === "edge-local";
}

/** True when raw microphone audio must NOT be transmitted (edge mode). */
export function forbidsRawAudioUpload(mode: AudioMode): boolean {
  return mode === "edge-local";
}

export type CallPhase = "idle" | "connecting" | "active" | "ended";

export interface CallMeta {
  callId: string;
  callerId: string;
  recipientId: string;
  audioMode: AudioMode;
  startedAt: number;
}

/** Local (browser-side) anti-spoof result + model provenance/perf. */
export interface LocalRisk {
  acousticScore: number;
  label: string;
  modelId: string;
  modelLoadMs: number | null;
  inferenceMs: number;
  p50Ms: number | null;
  p95Ms: number | null;
  inferenceCount: number;
  heapUsedMb: number | null;
  windowId: number;
}
