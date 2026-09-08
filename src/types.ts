export type RiskStatus = "ALLOW" | "WARN" | "LOCK_VERIFY";

export interface RiskTelemetry {
  timestamp: number;
  risk_score: number;
  acoustic_score: number;
  intent_score: number;
  status: RiskStatus;
  rationale: string[];
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

/** Audio source driving the acoustic pipeline for this call. */
export type AudioMode = "live" | "demo-genuine" | "demo-cloned";

export type CallPhase = "idle" | "connecting" | "active" | "ended";

export interface CallMeta {
  callId: string;
  callerId: string;
  recipientId: string;
  audioMode: AudioMode;
  startedAt: number;
}
