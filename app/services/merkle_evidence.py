"""Merkle-root evidence packages (Phase 10).

PURPOSE
  The legacy ``EvidenceAnchorService`` commits a *flat* hash of an opaque
  payload. Phase 10 adds a structured, independently verifiable commitment:

    1. Every evidence item (audio digest, transcript, spoof scores, metadata …)
       is hashed individually: ``item_sha256 = sha256(raw_item_bytes)``.
    2. Those per-item digests become the leaves of a SHA-256 Merkle tree
       (``app/core/merkle.py``), producing a single 32-byte **Merkle root**.
    3. A canonical manifest (RFC 8785, ``app/core/jcs.py``) records the item map
       and provenance; its own hash is the **package hash**.
    4. Only the Merkle root + a hashed evidence id go on-chain
       (``anchorEvidence(root, id)``). No raw audio, transcript or PII is ever
       committed.

WHY THIS IS BETTER THAN A FLAT HASH
  - Partial disclosure: a verifier can prove a single item is part of the
    package with a short Merkle proof, without revealing the other items.
  - Stable identity: the root is order-independent (leaves are sorted), so the
    same evidence always yields the same commitment.
  - Cross-language: ``sha256`` + RFC 8785 are reproducible in Python, JS and
    Solidity, so the root can be re-derived and checked by anyone.

CANONICAL LAYOUT (shared with contracts/MerkleProof.sol)
  leaf = sha256(0x00 || item_sha256_bytes)
  node = sha256(0x01 || min(a,b) || max(a,b))   # sorted pair
  leaves sorted ascending; odd level duplicates the last node.

PRIVACY
  Only digests and the manifest are persisted. ``verify_merkle_package`` never
  trusts a client "verified" flag; every result is recomputed server-side.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import config
from app.core.jcs import CanonicalizationError, canonicalize
from app.core.merkle import MerkleError, MerkleTree, build_proof, compute_root, hash_leaf, verify_proof
from app.db import models as db_models
from app.services.anchor_adapter import evidence_id_to_bytes32, get_anchor_adapter

logger = logging.getLogger("satyavoice.merkle")


SCHEMA_VERSION = "phase10-v1"
PACKAGE_FORMAT = "merkle-integrity-evidence-package"

# Merkle layout descriptor embedded in the manifest so an independent verifier
# knows exactly which construction produced the root.
MERKLE_LAYOUT = {
    "algorithm": "sha256",
    "leaf_prefix": "00",
    "node_prefix": "01",
    "pair_order": "sorted",
    "leaf_encoding": "sha256(raw item bytes)",
    "odd_node_policy": "duplicate_last",
}


class MerkleEvidenceError(ValueError):
    """Raised for malformed Merkle-evidence input (bad items, missing package)."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_evidence_item(raw: bytes) -> str:
    """Return the lowercase hex ``sha256`` of a single raw evidence item."""
    if not isinstance(raw, (bytes, bytearray)):
        raise MerkleEvidenceError("Evidence items must be raw bytes.")
    return hashlib.sha256(bytes(raw)).hexdigest()


def _normalize_items(items: Mapping[str, Any]) -> dict[str, bytes]:
    """Accept {name: bytes} or {name: {"bytes": ...}} and return {name: bytes}.

    Strings are UTF-8 encoded (transcripts); a common convenience so callers do
    not have to encode text themselves.
    """
    if not isinstance(items, Mapping):
        raise MerkleEvidenceError("items must be a mapping of name -> bytes/str.")
    normalized: dict[str, bytes] = {}
    for name, value in items.items():
        if not isinstance(name, str) or not name:
            raise MerkleEvidenceError("Every evidence item needs a non-empty name.")
        if isinstance(value, (bytes, bytearray)):
            normalized[name] = bytes(value)
        elif isinstance(value, str):
            normalized[name] = value.encode("utf-8")
        elif isinstance(value, Mapping) and isinstance(value.get("bytes"), (bytes, bytearray)):
            normalized[name] = bytes(value["bytes"])
        else:
            raise MerkleEvidenceError(
                f"Item '{name}' must be bytes, str, or {{'bytes': ...}}."
            )
    if not normalized:
        raise MerkleEvidenceError("At least one evidence item is required.")
    return normalized


def build_merkle_package(
    *,
    evidence_id: str | None = None,
    session_id: str | None = None,
    items: Mapping[str, Any],
    model_metadata: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a Merkle evidence package (pure, no DB, no network).

    Returns a dict containing:
      evidence_id, package_hash, merkle_root, item_digests (name->hex),
      leaves (name->leaf hex), proofs (name->proof dict), manifest
    """
    eid = evidence_id or str(uuid.uuid4())
    normalized = _normalize_items(items)

    # 1. Per-item digests.
    item_digests = {name: hash_evidence_item(raw) for name, raw in normalized.items()}

    # 2. Canonical manifest (RFC 8785). Only digests + provenance — no raw data.
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "package_format": PACKAGE_FORMAT,
        "evidence_id": eid,
        "created_at": _utc_now_iso(),
        "merkle": MERKLE_LAYOUT,
        "items": {name: f"sha256:{digest}" for name, digest in sorted(item_digests.items())},
        "model_metadata": model_metadata
        or {
            "detector_mode": config.VOICE_DETECTOR_MODE,
            "schema_version": SCHEMA_VERSION,
        },
    }
    if session_id is not None:
        manifest["session_id"] = session_id
    if extra:
        manifest["extra"] = extra

    canonical_manifest = canonicalize(manifest)
    package_hash = hashlib.sha256(canonical_manifest.encode("utf-8")).hexdigest()

    # 3. Merkle tree over leaf = sha256(0x00 || item_sha256_bytes).
    item_names = sorted(normalized.keys())
    leaf_hashes = [hash_leaf(bytes.fromhex(item_digests[name])) for name in item_names]
    tree = MerkleTree(leaf_hashes)
    merkle_root = tree.root.hex()

    leaves = {name: leaf_hashes[item_names.index(name)].hex() for name in item_names}
    proofs = {name: tree.proof(leaf_hashes[item_names.index(name)]).to_dict() for name in item_names}

    return {
        "evidence_id": eid,
        "schema_version": SCHEMA_VERSION,
        "package_format": PACKAGE_FORMAT,
        "manifest": manifest,
        "canonical_manifest": canonical_manifest,
        "package_hash": package_hash,
        "merkle_root": merkle_root,
        "item_digests": item_digests,
        "leaves": leaves,
        "proofs": proofs,
        "leaf_count": len(item_names),
    }


class MerkleEvidenceService:
    """Persistence + verification for Merkle evidence packages."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # -- registration ---------------------------------------------------------

    def register_merkle_package(
        self,
        *,
        items: Mapping[str, Any],
        evidence_id: str | None = None,
        session_id: str | None = None,
        model_metadata: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
        anchor: bool = True,
    ) -> dict[str, Any]:
        """Build + persist a Merkle package, then optionally anchor its root.

        Anchoring is best-effort: a blockchain failure never aborts local
        registration (mirrors the legacy evidence path). Returns a status dict;
        never raises for DB/network errors.
        """
        try:
            package = build_merkle_package(
                evidence_id=evidence_id,
                session_id=session_id,
                items=items,
                model_metadata=model_metadata,
                extra=extra,
            )
        except (MerkleEvidenceError, CanonicalizationError, MerkleError) as exc:
            return {"status": "error", "error": str(exc)}

        eid = package["evidence_id"]

        try:
            # Idempotency: an evidence_id is the logical key. Re-registering the
            # same case returns the existing commitment rather than creating a
            # second row (the manifest's created_at changes each build, so
            # keying on package_hash alone would defeat idempotency).
            existing = (
                self.db.query(db_models.EvidenceMerklePackage)
                .filter(db_models.EvidenceMerklePackage.evidence_id == eid)
                .first()
            )
            if existing is not None:
                return self._serialize(existing, duplicate=True)

            row = db_models.EvidenceMerklePackage(
                evidence_id=eid,
                schema_version=SCHEMA_VERSION,
                package_format=PACKAGE_FORMAT,
                canonical_package=package["canonical_manifest"],
                package_hash=package["package_hash"],
                merkle_root=package["merkle_root"],
                leaf_count=package["leaf_count"],
                leaves_json=json.dumps(package["item_digests"], sort_keys=True),
                evidence_id_bytes32=evidence_id_to_bytes32(eid),
                status="registered",
                blockchain_network=config.BLOCKCHAIN_NETWORK,
                contract_address=config.BLOCKCHAIN_CONTRACT_ADDRESS or None,
                anchor_status="unavailable" if not config.BLOCKCHAIN_ANCHORING_ENABLED else "pending",
            )
            self.db.add(row)
            self.db.flush()

            for name in sorted(package["item_digests"]):
                self.db.add(
                    db_models.EvidenceMerkleLeaf(
                        evidence_id=eid,
                        item_name=name,
                        item_sha256=package["item_digests"][name],
                        leaf_hash=package["leaves"][name],
                        proof_json=json.dumps(package["proofs"][name]),
                    )
                )
            self.db.flush()

            anchor_result: dict[str, Any] | None = None
            if anchor and config.BLOCKCHAIN_ANCHORING_ENABLED:
                anchor_result = self._anchor(eid, package["merkle_root"])
                row.anchor_status = anchor_result.get("status", "failed")
                row.anchor_tx_hash = anchor_result.get("tx_hash")
                row.anchor_block_number = anchor_result.get("block_number")
                row.anchor_timestamp = anchor_result.get("anchor_timestamp")
                row.failure_reason = anchor_result.get("failure_reason")
                row.blockchain_network = anchor_result.get("network") or row.blockchain_network
                row.contract_address = anchor_result.get("contract_address") or row.contract_address
            else:
                row.anchor_status = "unavailable"
                row.failure_reason = (
                    None
                    if anchor
                    else "Anchoring skipped for this registration."
                )

            queue_entry = None
            if config.BLOCKCHAIN_ANCHORING_ENABLED and anchor_result is not None:
                from app.services.anchor_queue import record_anchor_result

                queue_entry = record_anchor_result(self.db, eid, package["merkle_root"], anchor_result)

            self.db.commit()
            self.db.refresh(row)

            result = self._serialize(row, duplicate=False)
            result["merkle_root"] = package["merkle_root"]
            result["package_hash"] = package["package_hash"]
            result["leaf_count"] = package["leaf_count"]
            if anchor_result is not None:
                result["anchor"] = self._safe_anchor_summary(anchor_result)
            if queue_entry is not None:
                result["queue_status"] = queue_entry
            return result

        except SQLAlchemyError as exc:
            logger.error("Merkle evidence DB error: %s", type(exc).__name__)
            self._safe_rollback()
            return {"status": "error", "error": "Merkle evidence registration failed (database)."}
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Merkle evidence unexpected error: %s", type(exc).__name__)
            self._safe_rollback()
            return {"status": "error", "error": "Merkle evidence registration failed unexpectedly."}

    # -- verification ---------------------------------------------------------

    def verify_merkle_package(
        self,
        evidence_id: str,
        provided_items: Mapping[str, Any] | None = None,
        verify_on_chain: bool = True,
    ) -> dict[str, Any]:
        """Verify a Merkle package's integrity end to end.

        Steps:
          1. Re-derive the package hash from the stored canonical manifest.
          2. Rebuild the Merkle root from the stored per-item digests.
          3. If ``provided_items`` is given, recompute each item's digest from the
             supplied raw bytes and confirm it matches the stored digest — this
             is the "the file I hold is the file that was anchored" check.
          4. Optionally re-query the contract to confirm the root is anchored
             on-chain (never trusts local metadata alone).

        Raises ``MerkleEvidenceError`` if the package is unknown.
        """
        row = (
            self.db.query(db_models.EvidenceMerklePackage)
            .filter(db_models.EvidenceMerklePackage.evidence_id == evidence_id)
            .first()
        )
        if row is None:
            raise MerkleEvidenceError(f"Merkle evidence package '{evidence_id}' was not found.")

        # 1. Package-hash integrity (detects manifest tampering).
        recomputed_package_hash = hashlib.sha256(row.canonical_package.encode("utf-8")).hexdigest()
        package_hash_integrity = recomputed_package_hash == row.package_hash

        # 2. Merkle-root integrity (rebuild from stored leaf digests).
        stored_digests: dict[str, str] = json.loads(row.leaves_json or "{}")
        root_integrity = False
        recomputed_root: str | None = None
        if stored_digests:
            try:
                leaf_hashes = [hash_leaf(bytes.fromhex(stored_digests[n])) for n in sorted(stored_digests)]
                recomputed_root = compute_root(leaf_hashes).hex()
                root_integrity = recomputed_root == row.merkle_root
            except (ValueError, MerkleError):
                root_integrity = False

        # 3. Optional raw-item re-derivation.
        items_verified: dict[str, bool] = {}
        items_all_verified: bool | None = None
        if provided_items is not None:
            try:
                normalized = _normalize_items(provided_items)
            except MerkleEvidenceError as exc:
                return {
                    "evidence_id": evidence_id,
                    "status": "error",
                    "error": str(exc),
                    "package_hash_integrity": package_hash_integrity,
                    "merkle_root_integrity": root_integrity,
                }
            for name, raw in normalized.items():
                expected = stored_digests.get(name)
                items_verified[name] = expected is not None and hash_evidence_item(raw) == expected
            items_all_verified = bool(items_verified) and all(items_verified.values())

        # 4. On-chain cross-check.
        on_chain_verified: bool | None = None
        evidence_id_matches: bool | None = None
        if verify_on_chain and config.BLOCKCHAIN_ANCHORING_ENABLED and row.anchor_status not in {"unavailable", None}:
            try:
                adapter = get_anchor_adapter()
                anchor_check = adapter.verify_evidence(row.merkle_root, evidence_id)
                on_chain_verified = bool(anchor_check.get("anchored"))
                evidence_id_matches = anchor_check.get("evidence_id_matches")
            except Exception as exc:  # pragma: no cover - adapter never raises, defensive
                logger.warning("On-chain Merkle verify error for %s: %s", evidence_id, type(exc).__name__)
                on_chain_verified = None

        valid = package_hash_integrity and root_integrity
        if items_all_verified is not None:
            valid = valid and items_all_verified
        if on_chain_verified is not None:
            valid = valid and on_chain_verified

        return {
            "evidence_id": evidence_id,
            "valid": valid,
            "package_hash_integrity": package_hash_integrity,
            "merkle_root_integrity": root_integrity,
            "items_all_verified": items_all_verified,
            "items_verified": items_verified or None,
            "on_chain_verified": on_chain_verified,
            "evidence_id_matches": evidence_id_matches,
            "merkle_root": row.merkle_root,
            "recomputed_merkle_root": recomputed_root,
            "package_hash": row.package_hash,
            "leaf_count": row.leaf_count,
            "leaf_names": sorted(stored_digests.keys()),
            "item_digests": stored_digests,
            "evidence_id_bytes32": row.evidence_id_bytes32,
            "anchor_status": row.anchor_status,
            "blockchain_network": row.blockchain_network,
            "contract_address": row.contract_address,
            "tx_hash": row.anchor_tx_hash,
            "block_number": row.anchor_block_number,
            "anchor_timestamp": row.anchor_timestamp.isoformat() if row.anchor_timestamp else None,
            "failure_reason": row.failure_reason,
        }

    def get_proof(self, evidence_id: str, item_name: str) -> dict[str, Any]:
        """Return the stored inclusion proof for one item (raises if unknown)."""
        leaf = (
            self.db.query(db_models.EvidenceMerkleLeaf)
            .filter(
                db_models.EvidenceMerkleLeaf.evidence_id == evidence_id,
                db_models.EvidenceMerkleLeaf.item_name == item_name,
            )
            .first()
        )
        if leaf is None:
            raise MerkleEvidenceError(
                f"Item '{item_name}' was not found in evidence package '{evidence_id}'."
            )
        package = (
            self.db.query(db_models.EvidenceMerklePackage)
            .filter(db_models.EvidenceMerklePackage.evidence_id == evidence_id)
            .first()
        )
        if package is None:
            raise MerkleEvidenceError(f"Merkle evidence package '{evidence_id}' was not found.")
        proof = json.loads(leaf.proof_json)
        # Independently re-verify the stored proof before returning it so a
        # corrupted proof row is surfaced rather than served.
        proof_ok = verify_proof(
            bytes.fromhex(proof["leaf"]),
            [bytes.fromhex(s) for s in proof["siblings"]],
            bytes.fromhex(package.merkle_root),
        )
        return {
            "evidence_id": evidence_id,
            "item_name": item_name,
            "item_sha256": leaf.item_sha256,
            "leaf_hash": leaf.leaf_hash,
            "merkle_root": package.merkle_root,
            "proof": proof,
            "proof_valid": proof_ok,
        }

    # -- internals ------------------------------------------------------------

    def _anchor(self, evidence_id: str, merkle_root: str) -> dict[str, Any]:
        """Submit the Merkle root to the chain; never raises."""
        try:
            adapter = get_anchor_adapter()
            return adapter.anchor_evidence(f"0x{merkle_root}", evidence_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Anchor adapter error for %s: %s", evidence_id, type(exc).__name__)
            return {
                "status": "failed",
                "network": config.BLOCKCHAIN_NETWORK,
                "contract_address": config.BLOCKCHAIN_CONTRACT_ADDRESS,
                "tx_hash": None,
                "block_number": None,
                "anchor_timestamp": None,
                "failure_reason": f"Adapter error: {type(exc).__name__}",
            }

    @staticmethod
    def _safe_anchor_summary(anchor_result: dict[str, Any]) -> dict[str, Any]:
        """Anchor summary safe to return over the API (no credentials)."""
        return {
            "status": anchor_result.get("status"),
            "network": anchor_result.get("network"),
            "contract_address": anchor_result.get("contract_address"),
            "tx_hash": anchor_result.get("tx_hash"),
            "block_number": anchor_result.get("block_number"),
            "anchor_timestamp": (
                anchor_result["anchor_timestamp"].isoformat()
                if anchor_result.get("anchor_timestamp") is not None
                and hasattr(anchor_result["anchor_timestamp"], "isoformat")
                else anchor_result.get("anchor_timestamp")
            ),
            "failure_reason": anchor_result.get("failure_reason"),
        }

    def _serialize(self, row: db_models.EvidenceMerklePackage, duplicate: bool) -> dict[str, Any]:
        return {
            "status": "ok",
            "duplicate": duplicate,
            "evidence_id": row.evidence_id,
            "package_hash": row.package_hash,
            "merkle_root": row.merkle_root,
            "leaf_count": row.leaf_count,
            "evidence_id_bytes32": row.evidence_id_bytes32,
            "anchor_status": row.anchor_status,
            "blockchain_network": row.blockchain_network,
            "contract_address": row.contract_address,
        }

    def _safe_rollback(self) -> None:
        try:
            self.db.rollback()
        except Exception:
            pass


def build_merkle_proof_for_items(items: Iterable[bytes], target_index: int) -> dict[str, Any]:
    """Standalone helper: build a proof for the item at *target_index*.

    Leaves are ``hash_leaf`` of each provided item's raw bytes; used by callers
    that already hold the raw items and want a proof without a DB round-trip.
    """
    raw_list = [bytes(x) for x in items]
    if not raw_list:
        raise MerkleEvidenceError("At least one item is required to build a proof.")
    if not (0 <= target_index < len(raw_list)):
        raise MerkleEvidenceError("target_index is out of range.")
    leaves = [hash_leaf(x) for x in raw_list]
    proof = build_proof(leaves, leaves[target_index])
    return proof.to_dict()
