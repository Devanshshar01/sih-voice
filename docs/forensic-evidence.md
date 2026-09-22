# SatyaVoice Forensic Evidence Pipeline

Deterministic, tamper-evident, testable forensic evidence packaging.

| Claim | Status |
|---|---|
| Cryptographically verifiable | **Yes** |
| Tamper-evident | **Yes** |
| Integrity-verifiable | **Yes** |
| Hash-linked | **Yes** |
| Blockchain-anchored | **Only when anchoring is actually CONFIRMED** |
| Suitable for forensic evidence packaging | **Yes** |
| Court admissible / legally certified / tamper-proof / legally immutable | **NO - see [What is NOT claimed](#what-is-not-claimed)** |

---

## 1. Evidence package model

One canonical, versioned representation: `app/services/evidence_package.py`.

```
EvidencePackage (schema_version = "sv-evidence-v1")
  schema_version          explicit; bumping it invalidates prior hashes by design
  evidence_id             stable identifier (never PII)
  call_id                 session identifier
  created_at              normalized UTC, second precision
  completed_at            normalized UTC, second precision (optional)
  detection               final status, fused risk, policy
  acoustic_evidence       MMS anti-spoof score + model id
  speaker_verification    speaker match + confidence
  contextual_analysis     fraud indicators
  risk_summary            fused policy summary
  audio_artifacts         artifact_id -> artifact metadata (section 2)
  model_metadata          detector mode, model ids/versions, window config
  ledger_metadata         hash-chain sequence numbers
  merkle_metadata         tree_version, leaf_count, root
  blockchain_metadata     anchor status / network / tx (when confirmed)
  verification_metadata   verification policy
```

`build_canonical_evidence_package(...)` returns a **plain dict** - no DB, no
network, no clock read of its own. The result is a pure value; hashing it twice
always yields the same digest.

### Canonical serialization rules

Implemented in `app/core/jcs.py` (RFC 8785 JSON Canonicalization Scheme) and
enforced by `tests/test_evidence_package.py`:

| Rule | Implementation |
|---|---|
| Deterministic bytes | One canonicalizer; every hash goes through it |
| Key order independent of insertion order | Keys sorted by UTF-16 code unit |
| No `NaN` | Rejected by `_reject_bad_numbers` **and** by the canonicalizer |
| No `Infinity` | Same |
| No accidental `null` placeholders | Optional fields omitted, never emitted as `null` |
| Normalized datetimes | `normalize_timestamp` -> UTC, second precision, `+00:00` |
| Deterministic numerics | ECMAScript `Number::toString` (shortest round-trip) |
| Explicit UTF-8 | `canonicalize_bytes` always encodes UTF-8 |
| Explicit schema version | `EVIDENCE_PACKAGE_SCHEMA_VERSION` |
| No volatile fields | No request id, PDF timestamp, random UUID or tx receipt |

Why RFC 8785 and not `json.dumps(sort_keys=True)`: Python's float formatting and
its code-point key sort both differ observably from ECMAScript's, so two honest
implementations of the same data would disagree on the hash. RFC 8785 removes
that ambiguity, so an independent verifier in any language can recompute the
exact bytes we hashed.

### Hash domains

Each hash is computed over a **domain-separated** pre-image, so digests from
different roles can never collide semantically:

| Domain | Constant | Over |
|---|---|---|
| Artifact | `_DOMAIN_ARTIFACT` | raw artifact bytes |
| Package | `_DOMAIN_PACKAGE` | canonical package bytes |

---

## 2. Artifact hashing

Every artifact carries explicit metadata (`build_artifact_metadata`):

```
artifact_id, role, media_type, byte_length, sha256, created_at, source[, sequence]
```

Rules:

- The digest covers the **actual bytes** - never a human-readable label - when
  real bytes exist.
- `byte_length` is stored and cross-checked against real content by
  `verify_artifact`.
- Artifact roles in use: original audio, normalized audio, acoustic inference
  result, speaker verification result, risk event stream, forensic report,

## 3. Hash chain (ledger)

`app/services/evidence_anchor.py` - append-only SHA-256 ledger.

```
genesis:  previous_hash = GENESIS_HASH     (fixed, documented constant)

event_hash = SHA256(domain_separator || previous_hash || canonical_event_bytes)
```

Each record stores at minimum: `sequence_number`, `evidence_id`, `event_type`,
`event_timestamp`, `previous_hash`, `event_hash`, `schema_version`,
`canonical_payload_hash`.

Properties: append-only, monotonic sequence, deterministic hashing, unique
constraints, concurrency-safe append, and a failed transaction never leaves a
half-written link (rollback + retry via `app/db/database.py`).

The head is a **walked** value (`chain_root_hash`), not a mutable
"current hash" column that could be silently overwritten.

`verify_ledger(evidence_id)` returns structured, actionable output:

```json
{
  "valid": true,
  "entries_checked": 3,
  "first_invalid_sequence": null,
  "expected_hash": null,
  "actual_hash": null,
  "reason": null
}
```

It detects a changed payload, changed `previous_hash`, missing event, reordered
event and broken sequence - and reports the **exact failing sequence number**.

---

## 4. Merkle tree construction

`app/core/merkle.py` (dependency-free; runs offline and in unit tests).

```
leaf   = sha256(0x00 || data)
parent = sha256(0x01 || min(a,b) || max(a,b))     # sorted pair
```

- **Leaf ordering**: leaves are sorted by raw 32-byte digest before the tree is
  built, so the same multiset of items always yields the same root - independent
  of insertion order and of process.
- **Odd-node rule (explicit)**: when a level has an odd node count, the final
  node is **duplicated** (Bitcoin-style). Declared in `MERKLE_LAYOUT`
  (`"odd_node_policy": "duplicate_last"`) and embedded in the manifest, so the
  rule is never implicit.
- **Domain separation**: the `0x00`/`0x01` prefixes stop a 64-byte leaf being
  reinterpreted as an internal node (second-preimage ambiguity, RFC 6962-style).

Merkle metadata records `tree_version`, `leaf_count`, `leaf_order_rule`, `root`,
`generated_at` and `evidence_id`.

API: `build_merkle_tree` / `get_merkle_proof` / `verify_merkle_proof`
(`build_tree`, `build_proof`, `verify_proof`).

Proof verification is pure arithmetic - it needs **no database access**. The
caller always supplies the trusted root; a proof never self-certifies (mirrors
OpenZeppelin's `MerkleProof.verify`).

### Why sorted pairs (not position flags)

Sorting the two children before hashing means a proof is just an ordered list of
sibling hashes - no left/right bits - which is exactly the semantics of
OpenZeppelin's audited `MerkleProof._hashPair`, so the on-chain verifier
(`contracts/AnchorRoot.sol` / `contracts/MerkleProof.sol`) can be a thin standard
implementation instead of custom position plumbing.

---

  evidence manifest.

---

## 5. PDF generation

`app/services/forensic_report.py` - **one authoritative representation.**

The report is generated from a **frozen snapshot** (the stored verification dict
plus integrity summary), never from a collection of live mutable queries. A
frozen package always yields the same logical report content.

```
PAGE 1  Cover / status
        SATYAVOICE - FORENSIC VOICE ANALYSIS REPORT
        Evidence ID, Call ID, report status, created/completed, schema version
        "Cryptographically verifiable forensic evidence package"

PAGE 2  Detection summary
        overall risk, anti-spoof result, speaker verification, contextual
        indicators, confidence/score values, model ids + versions, sample rate,
        window configuration, evidence timestamps.
        Model score / fused risk / confidence / status are labelled separately.

PAGE 3  Integrity
        artifact table (artifact, media type, size, SHA-256) then
        Canonical Evidence Package SHA-256, Ledger Head Hash, Merkle Root -
        rendered in monospaced typography, wrapped, never clipped.

PAGE 4  Blockchain anchor
        status (disabled | queued | submitted | confirmed | failed), and when
        confirmed: network, chain id, contract, tx hash, block, timestamp,
        anchored Merkle root. When not anchored, says so explicitly.
        A transaction hash is never invented.

PAGE 5  Verification
        verification endpoint + identifier, evidence id, Merkle root, package
        hash, ledger verification status, blockchain verification status,
        and a QR code pointing at the verification URL (never the whole JSON).

Footer (every page): SatyaVoice, evidence schema version, Page X of Y,
Generated report identifier.
```

Quality contract (enforced by `tests/test_forensic_pdf.py`): no clipped text, no
table overflow, no overlapping elements, no blank pages, no `null` / `undefined`
/ `NaN` / `Infinity`, no raw Python objects, no truncated-without-full-value
hashes, consistent margins and typography, page numbers, report identifier, QR
with caption.

---

## 6. PDF hashing

**No circular hashing.** The PDF does *not* contain its own final byte hash.

```
1. Freeze the evidence package.
2. Generate the PDF.
3. Compute pdf_sha256 over the rendered bytes.
4. Store report_sha256 in evidence_report_records (+ verification API).
```

The PDF may contain the package hash, Merkle root, ledger head and anchor data -
but never its own digest unless a separate manifest model is used.

---

## 7. Blockchain anchoring

`contracts/AnchorRoot.sol` + `app/services/anchor_adapter.py`.

Only **compact cryptographic commitments** go on-chain:
`anchorEvidence(merkle_root, sha256(evidence_id))`. No audio, transcript, phone
number or other PII is ever anchored.

Event emitted on success (the Merkle scheme's own event):

```solidity
event EvidenceAnchored(
    bytes32 indexed evidenceRoot,
    bytes32 indexed evidenceId,
    uint256 timestamp,
    address anchorer
);
```

(The legacy single-digest path emits `RootAnchored`; the forensic pipeline
uses the Merkle scheme above. Both carry only commitments — never PII.)

Guarantees: idempotency (a duplicate `anchorEvidence` returns the existing anchor,
never a contradicting record), replay protection, root/identity immutability,
access-controlled anchoring, explicit contract version, explicit chain-id
handling, and a failed transaction stays visibly failed - **no `"confirmed"`
state exists before receipt confirmation.**

### Adapter modes (section 12)

| Mode | Behaviour |
|---|---|
| `DISABLED` | No blockchain calls. Evidence stays valid; report says "not anchored". |
| `DRY_RUN` | Deterministic simulated metadata, always `status="dry_run"` + `simulated=True`. **Never** represented as confirmed. |
| `LIVE` | Submit tx, wait for receipt, verify receipt, persist confirmed metadata. |

A `DRY_RUN` result is never persisted as a real tx hash and never renders as a
confirmed anchor in the UI or the PDF. Verified by `tests/test_forensic_e2e.py`.

### Offline anchor queue

`app/services/anchor_queue.py`. Explicit states: `OFFLINE` (pending) ->
`PENDING` (submitted) -> `CONFIRMED`, or `FAILED` -> `PERMANENTLY_FAILED`.

Each entry carries: idempotency key, attempt count, last error, next retry time
(exponential backoff), submitted tx hash, confirmed block number, confirmed
timestamp, contract/network, `created_at` / `updated_at`.

A failed anchor is **never silently dropped**. Retries happen only when the error
is retryable; a non-retryable error (contract revert, invalid/zero root, chain-id
mismatch) marks the entry `PERMANENTLY_FAILED` and it is never auto-retried.
Before any resubmission the queue probes the chain for an existing anchor and
uses the idempotency key, so an ambiguous client timeout cannot cause a duplicate
submission.

---



## 8. Verification flow

`GET /api/v1/forensics/{evidence_id}/verify`

```json
{
  "evidence_id": "...",
  "package_hash": "...",
  "merkle_root": "...",
  "ledger":     { "valid": true, "entries_checked": 3, "first_invalid_sequence": null },
  "blockchain": { "status": "...", "confirmed": false },
  "report":     { "sha256": "..." }
}
```

The response is derived from **stored evidence** - it is never regenerated with
new timestamps. The QR code printed on page 5 of the PDF points at this route
(the URL contains only the evidence id, no PII).

### EvidenceIntegritySummary

Six distinct identities are kept separate and are **never collapsed into one
field**:

| # | Identity | Meaning |
|---|---|---|
| 1 | artifact hash | SHA-256 of one artifact's bytes |
| 2 | `package_sha256` | canonical evidence-package hash |
| 3 | `ledger_head` | hash-chain head (walked) |
| 4 | `merkle_root` | commitment over ordered artifact digests |
| 5 | `report_sha256` | SHA-256 of the rendered PDF |
| 6 | `blockchain.tx_hash` | on-chain transaction hash |

---

## 9. End-to-end evidence lifecycle (worked example)

```python
# 1. Audio artifact -> artifact hash (actual bytes)
audio = build_artifact_metadata(
    artifact_id="audio_original", role="original_audio", media_type="audio/wav",
    content=wav_bytes, source="webrtc-capture",
)

# 2. Ledger entry (hash chain)
ledger = EvidenceAnchorService(db).register_evidence_package(payload, evidence_id=eid)
# -> local_chain_status == "verified"

# 3. Merkle package over the frozen evidence items
merkle = MerkleEvidenceService(db).register_merkle_package(
    evidence_id=eid, session_id=call_id,
    items={"audio": wav_bytes, "acoustic_result": scores_json,
           "speaker_result": speaker_json, "risk_stream": risk_json},
    anchor=False,                       # DISABLED mode: local integrity only
)
# -> merkle_root (64 hex chars), leaf_count == 4

# 4. Canonical evidence package -> package hash
package = build_canonical_evidence_package(
    evidence_id=eid, call_id=call_id,
    created_at="2026-03-01T12:00:00+00:00",
    detection={"final_status": "LOCK_VERIFY", "max_risk_score": 88},
    audio_artifacts={"original": audio},
    merkle_metadata={"root": merkle["merkle_root"], "tree_version": "merkle-v1"},
)
package_hash = package_sha256(package)      # deterministic, != merkle_root

# 5. Verification (recomputed server-side, never trusted)
verification = MerkleEvidenceService(db).verify_merkle_package(eid, provided_items=items)
# -> valid is True

# 6. Integrity summary keeps every identity separate
integrity = build_integrity_summary(db, eid)

# 7. PDF -> PDF hash (hashed OUTSIDE the PDF)
pdf = build_forensic_report_pdf(evidence_id=eid, verification=verification, integrity=integrity)
report_sha256 = hashlib.sha256(pdf).hexdigest()     # never embedded in pdf

# 8. Blockchain (DISABLED here; DRY_RUN/LIVE behave as documented above)
anchor = get_anchor_adapter().anchor_root(merkle_root, eid)
# -> "unavailable" (DISABLED) / "dry_run" (DRY_RUN) / "anchored" (LIVE, confirmed only)
```

This exact sequence is executed end-to-end by
`tests/test_forensic_e2e.py::test_end_to_end_forensic_pipeline`.

---

## What cryptographic hashes prove

- The bytes you hold are **byte-identical** to the bytes that were hashed.
- The item set is **unchanged** (Merkle root) and the package is **unchanged**
  (package hash).
- Any single-byte alteration, metadata edit, substitution or reordering is
  **detectable**.
- A Merkle proof shows one item belongs to the packaged set **without revealing
  the other items**.

## What blockchain anchoring proves

- At (or before) the anchor timestamp, **a specific 32-byte commitment existed**
  in a transaction included in a specific block.
- That commitment has not been altered since, because altering it would require
  rewriting a mined block.
- It does **not** prove the underlying evidence is truthful, complete, or
  correctly interpreted - only that the commitment is bound to that time.

## What is NOT claimed

This system does **NOT** claim, and this documentation does not assert:

- court admissibility
- legal certification of any kind
- "tamper-proof" or "legally immutable" status
- statutory forensic-certificate certification of any kind

No formal legal or signing process exists in this repository. Legal
certification remains a **human/legal process** outside this codebase. Anchoring
uses a **testnet** (Polygon Amoy) - not a production mainnet deployment - and the
contract has not been independently audited.

---

## Test matrix

| Area | Tests |
|---|---|
| Canonicalization | `tests/test_evidence_package.py`, `tests/test_jcs.py` |
| Artifact hashing / tamper | `tests/test_evidence_package.py` |
| Ledger (genesis, append, verify, tamper, missing, reorder, concurrency) | `tests/test_forensics_hardening.py`, `tests/test_forensic_e2e.py` |
| Merkle (deterministic root, odd trees, proofs, negatives, vectors) | `tests/test_merkle.py`, `tests/test_merkle_evidence.py` |
| PDF (generation, content, forbidden strings, page count, opens) | `tests/test_forensic_pdf.py` |
| QR / verification API | `tests/test_forensic_e2e.py` |
| Blockchain modes / idempotency / retry / duplicate root | `tests/test_forensic_e2e.py`, `tests/test_anchor_queue.py`, `tests/test_blockchain_anchor.py` |
| Migrations | `tests/test_migrations.py` |
| End-to-end | `tests/test_forensic_e2e.py::test_end_to_end_forensic_pipeline` |

```bash
python -m pytest tests/ -q
```

---

## Privacy rules

- Evidence identifiers never expose phone numbers or other PII.
- Only compact cryptographic commitments go on-chain: **no** phone number,
  transcript, audio or personal identifiers.
- The QR URL carries only the evidence id (no PII).
- Logs must never contain JWTs, raw audio, secrets, private keys or provider
  credentials.
