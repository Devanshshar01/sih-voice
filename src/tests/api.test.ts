import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { fetchRisk, terminateCall } from "../lib/api";

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
