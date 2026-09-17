/**
 * Risk-score display helpers.
 *
 * The backend contract is explicit and asymmetric (see app/models/schemas.py):
 *   - RiskTelemetry.risk_score  : int,  0-100  (fused session risk)
 *   - acoustic_score/intent_score: float, 0-1  (component vectors)
 *
 * So the fused score must NOT be multiplied by 100 again. Doing so is what made
 * the dashboard headline render "3600 / 100" for a real score of 36 while the
 * gauge (which rounds directly) showed "36 / 100".
 */

/** Round a 0-100 fused risk score for display. Never re-scales the value. */
export function formatRiskScore(value: number | null | undefined): number {
  if (value == null || !Number.isFinite(value)) return 0;
  return Math.round(value);
}

/** Render a 0-1 component vector (acoustic/intent) as a whole percentage. */
export function formatVectorPercent(value: number | null | undefined): number {
  if (value == null || !Number.isFinite(value)) return 0;
  return Math.round(value * 100);
}