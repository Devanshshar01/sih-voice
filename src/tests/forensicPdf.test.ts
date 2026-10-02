import { describe, expect, it } from "vitest";
import { buildTechnicalEvidenceReport, createTechnicalEvidencePdf } from "../lib/forensicPdf";
import type { RiskTelemetry } from "../types";

const reportInput = (telemetryHistory: RiskTelemetry[]) => ({
  callId: "call-1",
  callerId: "caller",
  recipientId: "recipient",
  durationSeconds: 4,
  maxRiskScore: 12,
  exportedAt: "2026-10-02T00:00:00.000Z",
  operatorIdentity: "operator",
  telemetryHistory,
});

describe("forensic report evidence provenance", () => {
  it("does not report a degraded anti-spoof fallback as a measured score", async () => {
    const telemetry: RiskTelemetry = {
      timestamp: 1_791_292_800,
      risk_score: 12,
      acoustic_score: 0,
      intent_score: 0.1,
      status: "ALLOW",
      rationale: [],
      inference_available: false,
      detector_status: "unavailable",
      degraded: { anti_spoof: "provider unavailable" },
      detector: { model: "claimed-model", status: "unavailable" },
    };

    const report = await buildTechnicalEvidenceReport(reportInput([telemetry]));
    expect(report.detection.model_score).toBeNull();
    expect(report.analysis_windows[0].acoustic_score).toBeNull();
    expect(report.model_version_metadata.model_id).toBe("claimed-model");

    const pdf = await createTechnicalEvidencePdf(report);
    expect(await pdf.text()).toContain("acoustic=unavailable");
  });

  it("keeps risk and model measurements unavailable when no windows exist", async () => {
    const report = await buildTechnicalEvidenceReport(reportInput([]));

    expect(report.max_risk_score).toBeNull();
    expect(report.detection).toMatchObject({
      risk_score: null,
      risk_status: null,
      model_score: null,
      model_status: "unavailable",
      confidence: null,
    });
  });
});
