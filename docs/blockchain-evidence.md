# Merkle-Root Blockchain Anchoring (Phase 10)

Tamper-evident, verifiable evidence anchoring for SatyaVoice: per-item SHA-256
hashes form a Merkle tree whose root is committed on-chain. Only cryptographic
commitments leave the device — **no raw audio, transcript or PII is ever
anchored**.

## Canonical layout (shared by Python, JS and Solidity)

```
leaf = sha256(0x00 || item_sha256_bytes)
node = sha256(0x01 || min(a,b) || max(a,b))   # sorted pair (OpenZeppelin-style)
leaves sorted ascending; odd level duplicates the last node
```

Domain separation (`0x00`/`0x01`) prevents a leaf being reinterpreted as an
internal node (second-preimage defence, RFC 6962-style). Sorting the pair means a
proof is just an ordered list of sibling hashes — no position bits.

| Concern | Choice | Where |
|---|---|---|
| Canonical JSON | RFC 8785 (JCS) | `app/core/jcs.py` |
| Merkle tree / proofs | SHA-256, sorted leaves | `app/core/merkle.py` |
| Contract library | sorted-pair SHA-256 verifier | `contracts/MerkleProof.sol` |
| Anchoring contract | `anchorEvidence(root, id)` | `contracts/AnchorRoot.sol` |
| Evidence service | packages, verify, proofs | `app/services/merkle_evidence.py` |
| Offline queue | OFFLINE→PENDING→CONFIRMED/FAILED | `app/services/anchor_queue.py` |
| PDF + QR | Blockchain Integrity section | `app/services/forensic_report.py` |

## Why a Merkle root (not a flat hash)

- **Partial disclosure** — prove one item is in the package with a short proof,
  without revealing the others.
- **Order independence** — the same evidence always yields the same root.
- **Cross-language reproduction** — `sha256` + RFC 8785 exist in Python, JS and
  Solidity, so any verifier can recompute the root.

## Verification (does not trust the PDF)

1. Recompute per-item SHA-256 from the evidence you hold.
2. Rebuild the Merkle root.
3. Compare with the root printed in the report.
4. Query the contract (`isEvidenceAnchored` / `evidenceIdOf`) to confirm the
   commitment is on-chain and the evidence id matches.
5. Optional: verify a single item with a Merkle proof
   (`verifyEvidenceProof` on-chain, `app.core.merkle.verify_proof` off-chain).

## Lifecycle states

`OFFLINE` (queued while disconnected) → `PENDING` (tx submitted) →
`CONFIRMED` (mined, tx/block recorded) or `FAILED` (retained for retry).
A failed anchor is never silently discarded.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/forensics/merkle/register` | Build + persist + optionally anchor a package |
| POST | `/api/v1/forensics/merkle/{id}/verify` | Recompute root; optional raw items + on-chain check |
| GET | `/api/v1/forensics/merkle/{id}/proof/{item}` | Inclusion proof for one item |
| GET | `/api/v1/forensics/merkle/{id}/report.pdf` | Forensic PDF with Blockchain Integrity + QR |
| GET | `/api/v1/forensics/anchor/queue` | List offline/pending queue entries |
| POST | `/api/v1/forensics/anchor/flush` | Submit queued anchors (call on reconnect) |

## Configuration

Set `VOICETRUST_BLOCKCHAIN_ANCHORING_ENABLED=true` plus `..._RPC_URL`,
`..._CONTRACT_ADDRESS`, `..._PRIVATE_KEY`, `..._CHAIN_ID`. Anchoring is
best-effort: when disabled or misconfigured the local ledger stays fully
functional and evidence packet status is `"unavailable"`.

## Scope / honesty

This provides **tamper-evident integrity verification** — NOT legal admissibility
and NOT a guarantee of guilt. No formal legal or signing process exists in this
repository; statutory forensic certification remains a human/legal process.

Full forensic-pipeline documentation (evidence package model, ledger, Merkle
construction, PDF, anchoring, verification flow, and what each hash does and does
not prove): [`docs/forensic-evidence.md`](forensic-evidence.md).

The legacy flat ledger (`app/services/evidence_anchor.py`) is retained unchanged
so already-anchored evidence keeps verifying.
