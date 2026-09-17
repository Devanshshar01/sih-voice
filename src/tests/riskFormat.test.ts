import { describe, expect, it } from "vitest";
import { formatRiskScore, formatVectorPercent } from "../lib/riskFormat";

describe("risk score formatting (dashboard headline vs gauge)", () => {
  it("never re-scales an already 0-100 fused risk score", () => {
    // Regression: headline rendered 3600 / 100 for a real score of 36 while the
    // gauge rendered 36 / 100, because the headline multiplied by 100 again.
    expect(formatRiskScore(36)).toBe(36);
    expect(formatRiskScore(36)).not.toBe(3600);
  });

  it("agrees with the gauge readout for every value in range", () => {
    for (const score of [0, 1, 12, 36, 50, 70, 99, 100]) {
      // TrustGauge renders Math.round(score); the headline must match exactly.
      expect(formatRiskScore(score)).toBe(Math.round(score));
    }
  });

  it("rounds sub-integer scores without scaling them", () => {
    expect(formatRiskScore(36.4)).toBe(36);
    expect(formatRiskScore(36.6)).toBe(37);
  });

  it("clamps unsupported input instead of rendering NaN", () => {
    expect(formatRiskScore(null)).toBe(0);
    expect(formatRiskScore(undefined)).toBe(0);
    expect(formatRiskScore(Number.NaN)).toBe(0);
    expect(formatRiskScore(Number.POSITIVE_INFINITY)).toBe(0);
  });

  it("still scales 0-1 component vectors to whole percentages", () => {
    expect(formatVectorPercent(0)).toBe(0);
    expect(formatVectorPercent(0.5)).toBe(50);
    expect(formatVectorPercent(0.917)).toBe(92);
    expect(formatVectorPercent(1)).toBe(100);
    expect(formatVectorPercent(null)).toBe(0);
  });
});