import type {
  CallActionResult,
  CallRiskResponse,
  CallStartResponse,
  VerificationChallengeResponse,
  VerificationRequestResponse,
} from "../types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api/v1";
export const WS_BASE = (import.meta.env.VITE_WS_BASE_URL as string | undefined) ?? "ws://localhost:8000/api/v1";

async function asJson<T>(response: Response): Promise<T> {
  const data = await response.json();
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : response.statusText;
    throw new Error(detail);
  }
  return data as T;
}

export async function startCall(callerId: string, recipientId: string): Promise<CallStartResponse> {
  const res = await fetch(`${API_BASE}/call/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ caller_id: callerId, recipient_id: recipientId }),
  });
  return asJson<CallStartResponse>(res);
}

export function buildStreamUrl(callId: string): string {
  return `${WS_BASE}/call/${callId}/stream`;
}

export async function fetchRisk(callId: string): Promise<CallRiskResponse> {
  const res = await fetch(`${API_BASE}/call/${callId}/risk`);
  return asJson<CallRiskResponse>(res);
}

export async function requestVerificationCode(callId: string): Promise<VerificationRequestResponse> {
  const res = await fetch(`${API_BASE}/verification/request`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ call_id: callId }),
  });
  return asJson<VerificationRequestResponse>(res);
}

export async function submitVerificationCode(
  callId: string,
  code: string
): Promise<VerificationChallengeResponse> {
  const res = await fetch(`${API_BASE}/verification/challenge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ call_id: callId, code }),
  });
  return asJson<VerificationChallengeResponse>(res);
}

export async function attemptAction(
  callId: string,
  action: string,
  amount?: number
): Promise<CallActionResult> {
  const res = await fetch(`${API_BASE}/call/action`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ call_id: callId, action, amount }),
  });
  const data = await res.json();
  return {
    ok: res.ok,
    status: res.status,
    executed: Boolean(data?.executed),
    message: data?.message ?? data?.detail ?? "Unknown response from server.",
  };
}

export async function terminateCall(callId: string): Promise<void> {
  await fetch(`${API_BASE}/call/${callId}/terminate`, { method: "POST" });
}
