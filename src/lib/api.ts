import type {
  CallActionResult,
  CallRiskResponse,
  CallStartResponse,
  ForensicsVerificationResponse,
  VerificationChallengeResponse,
  VerificationRequestResponse,
} from "../types";

// API base is the single required connection variable. The WebSocket base is
// DERIVED from it unless explicitly overridden — this prevents the common
// deployed-frontend failure where the API points at production but the
// WebSocket silently still points at ws://localhost:8000 (mixed content +
// connection refused, which browsers often report as a CORS error).
const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api/v1";
export const WS_BASE = (import.meta.env.VITE_WS_BASE_URL as string | undefined) ?? API_BASE.replace(/^http/, "ws");

function connectionError(operation: string, err: unknown): Error {
  const detail = err instanceof Error ? err.message : String(err);
  return new Error(
    `Cannot reach the SatyaVoice backend while ${operation} (${detail}). ` +
      `Configured API base: ${API_BASE}. Verify the backend is running and that ` +
      `VITE_API_BASE_URL / VITE_WS_BASE_URL point at the deployed backend, and that ` +
      `the backend's VOICETRUST_CORS_ORIGINS includes this site's origin.`
  );
}

async function request(operation: string, url: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    // fetch() rejects on network/DNS/CORS-blocked failures; translate into a
    // message the operator can act on instead of a bare "Failed to fetch".
    throw connectionError(operation, err);
  }
  return response;
}

async function asJson<T>(_operation: string, response: Response): Promise<T> {
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : response.statusText;
    throw new Error(detail);
  }
  return data as T;
}

export async function startCall(callerId: string, recipientId: string): Promise<CallStartResponse> {
  const response = await request(
    "starting the call",
    `${API_BASE}/call/start`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ caller_id: callerId, recipient_id: recipientId }),
    }
  );
  return asJson<CallStartResponse>("starting the call", response);
}

export function buildStreamUrl(callId: string): string {
  return `${WS_BASE}/call/${callId}/stream`;
}

export async function fetchRisk(callId: string): Promise<CallRiskResponse> {
  const response = await request("loading the risk snapshot", `${API_BASE}/call/${callId}/risk`);
  return asJson<CallRiskResponse>("loading the risk snapshot", response);
}

export async function requestVerificationCode(callId: string): Promise<VerificationRequestResponse> {
  const response = await request("requesting a verification code", `${API_BASE}/verification/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ call_id: callId }),
  });
  return asJson<VerificationRequestResponse>("requesting a verification code", response);
}

export async function submitVerificationCode(
  callId: string,
  code: string
): Promise<VerificationChallengeResponse> {
  const response = await request("submitting the verification code", `${API_BASE}/verification/challenge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ call_id: callId, code }),
  });
  return asJson<VerificationChallengeResponse>("submitting the verification code", response);
}

export async function attemptAction(
  callId: string,
  action: string,
  amount?: number
): Promise<CallActionResult> {
  const response = await request("attempting the protected action", `${API_BASE}/call/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ call_id: callId, action, amount }),
  });
  const data = await response.json().catch(() => null);
  return {
    ok: response.ok,
    status: response.status,
    executed: Boolean(data?.executed),
    message: data?.message ?? data?.detail ?? "Unknown response from server.",
  };
}

export async function registerForensicsEvidence(
  evidenceId: string,
  payload: object
): Promise<Record<string, unknown>> {
  const response = await request("registering evidence", `${API_BASE}/forensics/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ evidence_id: evidenceId, payload }),
  });
  return asJson<Record<string, unknown>>("registering evidence", response);
}

export async function verifyForensicsChain(): Promise<{ integrity: boolean; record_count: number; chain_tip: string | null; reason: string | null }> {
  const response = await request("verifying the ledger chain", `${API_BASE}/forensics/chain/verify`, {
    method: "POST",
  });
  return asJson("verifying the ledger chain", response);
}

/** Fetch the backend-rendered forensic PDF (from the immutable stored package). */
export async function fetchForensicReportPdf(evidenceId: string): Promise<Blob> {
  const response = await request("exporting the forensic report", `${API_BASE}/forensics/${encodeURIComponent(evidenceId)}/report.pdf`);
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(
      typeof detail?.detail === "string" ? detail.detail : `PDF export failed (HTTP ${response.status}).`
    );
  }
  return response.blob();
}

export async function verifyForensicsEvidence(
  evidenceId: string
): Promise<ForensicsVerificationResponse> {
  const response = await request("verifying evidence", `${API_BASE}/forensics/${evidenceId}/verify`, {
    method: "POST",
  });
  return asJson<ForensicsVerificationResponse>("verifying evidence", response);
}

export async function terminateCall(callId: string): Promise<void> {
  await request("terminating the call", `${API_BASE}/call/${callId}/terminate`, { method: "POST" });
}
