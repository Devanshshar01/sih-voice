import type {
  BlockchainAnchorState,
  ForensicsIntegritySummary,
  ForensicsVerificationResponse,
} from "../types";

/**
 * Display labels for an anchor state. A DRY_RUN (simulated) anchor and an
 * unconfirmed submission must never render like a real, mined anchor, so the
 * label is derived from `simulated`/`confirmed` rather than from `status`
 * alone. "Immutable" is deliberately never used: the claim is only that the
 * commitment is hash-linked and, when confirmed, anchored on-chain.
 *
 * `anchored` is the status string the backend actually stores for a confirmed
 * canonical anchor (`evidence_merkle_packages.anchor_status`) — without it the
 * production "Verify Chain" result fell through to a raw lowercase value
 * instead of reading "Confirmed".
 */
const statusLabel = (value: string) => value.replace(/_/g, " ");

export const ANCHOR_STATUS_LABELS: Record<string, string> = {
  disabled: "Not anchored (disabled)",
  unavailable: "Not anchored",
  dry_run: "Simulated (dry run)",
  pending: "Pending",
  queued: "Queued",
  submitted: "Submitted (awaiting confirmation)",
  anchored: "Confirmed",
  confirmed: "Confirmed",
  failed: "Failed",
  permanently_failed: "Permanently failed",
};

export const anchorLabel = (state?: BlockchainAnchorState | null): string => {
  if (!state) return "PENDING VERIFICATION";
  const base = ANCHOR_STATUS_LABELS[state.status] ?? statusLabel(state.status);
  if (state.simulated) return `SIMULATED — not a blockchain anchor (${base})`;
  return state.confirmed ? `ANCHORED / ${base}` : base;
};

export const ledgerLabel = (integrity?: ForensicsIntegritySummary | null): string => {
  if (!integrity) return "PENDING VERIFICATION";
  if (!integrity.ledger) return "NOT AVAILABLE";
  if (integrity.ledger.valid) return `VERIFIED / ${integrity.ledger.entries_checked} entries`;
  return `MISMATCH / first invalid sequence ${integrity.ledger.first_invalid_sequence ?? "unknown"}`;
};

/**
 * Panel-08 (Verify Chain) anchor status: prefers the nested canonical
 * `blockchain` block and falls back to the flat legacy aliases, so a confirmed
 * production anchor reads "ANCHORED / Confirmed" instead of the raw
 * `anchor_status` enum ("anchored").
 */
export const verificationAnchorText = (
  result?: ForensicsVerificationResponse | null
): string => {
  if (!result) return "PENDING REGISTRATION";
  const block = (result as ForensicsVerificationResponse & { blockchain?: BlockchainAnchorState })
    .blockchain;
  const status = block?.status ?? result.anchor_status ?? "unavailable";
  const confirmed = block?.confirmed ?? result.public_anchor_consistent;
  const simulated = block?.simulated ?? false;
  const base = ANCHOR_STATUS_LABELS[status] ?? statusLabel(status);
  if (simulated) return `SIMULATED — not a blockchain anchor (${base})`;
  return confirmed ? `ANCHORED / ${base}` : base;
};

/**
 * Local package integrity for the integrity panel. The canonical envelope
 * carries a nested `integrity` block (recomputed manifest hash) with `valid`
 * as the overall verdict; only explicit booleans ever render as VERIFIED /
 * MISMATCH — anything unknown stays NOT AVAILABLE.
 */
export const localPackageText = (integrity?: ForensicsIntegritySummary | null): string => {
  if (!integrity) return "PENDING VERIFICATION";
  const nested = integrity.integrity?.package_hash_integrity;
  if (nested === true) return "VERIFIED";
  if (nested === false) return "MISMATCH";
  if (integrity.valid === true) return "VERIFIED";
  if (integrity.valid === false) return "MISMATCH";
  return "NOT AVAILABLE";
};