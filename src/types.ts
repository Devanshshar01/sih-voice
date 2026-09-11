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
}

/** Audio source driving the pipeline for this call. */
// cloud        — raw mic audio -> backend -> full multimodal pipeline
// hybrid       — local anti-spoof in-browser + backend ASR/speaker/policy
// edge-local   — raw audio NEVER leaves the device; only derived results go
//                to the backend (no raw-audio WebSocket)
// demo-*       — deterministic scripted scenarios (no microphone)
export type AudioMode =
  | "cloud"
  | "hybrid"
  | "edge-local"
  | "demo-genuine"
  | "demo-cloned";

export function isDemoMode(mode: AudioMode): boolean {
  return mode === "demo-genuine" || mode === "demo-cloned";
}

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
