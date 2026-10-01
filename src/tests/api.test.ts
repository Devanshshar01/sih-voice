import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  downloadForensicReportPdf,
  fetchRisk,
  registerForensicsEvidence,
  terminateCall,
  verifyEvidenceIntegrity,
  verifyForensicsEvidence,
} from "../lib/api";

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("window", { setTimeout, clearTimeout });
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ status: "COMPLETED" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});

it("sends the call JWT as a bearer token when fetching risk", async () => {
  await fetchRisk("test-call", "test-session-jwt");
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toMatch(/\/call\/test-call\/risk$/);
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-session-jwt");
});

it("sends the call JWT as a bearer token when terminating", async () => {
  await terminateCall("test-call", "test-session-jwt");
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toMatch(/\/call\/test-call\/terminate$/);
  expect(init.method).toBe("POST");
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer test-session-jwt");
});

it("reports rejected termination instead of silently treating HTTP 401 as success", async () => {
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ detail: "Invalid or expired token." }), {
    status: 401,
    headers: { "Content-Type": "application/json" },
  }));
  await expect(terminateCall("test-call", "expired-jwt")).rejects.toThrow("Invalid or expired token.");
});

it("registers evidence with the call JWT and preserves the returned evidence ID", async () => {
  fetchMock.mockResolvedValue(new Response(JSON.stringify({ evidence_id: "registered-evidence" }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  }));
  const registration = await registerForensicsEvidence("call-123", { call_id: "call-123" }, "call-jwt");
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toMatch(/\/forensics\/register$/);
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer call-jwt");
  expect(JSON.parse(init.body)).toEqual({ evidence_id: "call-123", payload: { call_id: "call-123" } });
  expect(registration.evidence_id).toBe("registered-evidence");
});

it.each([
  ["POST", verifyForensicsEvidence],
  ["GET", verifyEvidenceIntegrity],
] as const)("authenticates %s evidence verification requests", async (method, verify) => {
  await verify("registered/evidence", "call-jwt");
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toMatch(/\/forensics\/registered%2Fevidence\/verify$/);
  expect(init.method).toBe(method);
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer call-jwt");
});

it("authenticates the authoritative PDF request using the registered evidence ID", async () => {
  fetchMock.mockResolvedValue(new Response(new Blob(["pdf"]), {
    status: 200,
    headers: { "X-Report-SHA256": "digest" },
  }));
  const result = await downloadForensicReportPdf("registered-evidence", "call-jwt");
  const [url, init] = fetchMock.mock.calls[0];
  expect(url).toMatch(/\/forensics\/merkle\/registered-evidence\/report\.pdf$/);
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer call-jwt");
  expect(result.reportSha256).toBe("digest");
  expect(result.blob.size).toBeGreaterThan(0);
});
