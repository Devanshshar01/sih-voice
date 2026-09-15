"""SHA-256 binary Merkle tree with deterministic ordering and inclusion proofs.

CANONICAL LAYOUT (the exact scheme Python and Solidity must both reproduce)
  - Hash function: SHA-256.
  - Leaf:  ``leaf = sha256(0x00 || data)``            (domain-separated leaf)
  - Node:  ``node = sha256(0x01 || min(a,b) || max(a,b))`` (sorted-pair branch)
  - Leaves are sorted by raw 32-byte digest before the tree is built, so the
    same multiset of evidence items always yields the same root, independent of
    insertion order.
  - Odd level: the last node is duplicated (Bitcoin-style) so every level has an
    even node count.

WHY SORTED PAIRS (not position flags)
  Sorting the two children before hashing means a proof is just an ordered list
  of sibling hashes — no left/right position flags are needed. This is exactly
  the semantics of OpenZeppelin's audited ``MerkleProof.verify`` (its
  ``_hashPair`` hashes the pair in ascending order), so the on-chain verifier
  (``contracts/AnchorRoot.sol``) can be a thin, standard implementation instead
  of custom proof-position plumbing.

DOMAIN SEPARATION (0x00 / 0x01 prefixes)
  Without distinct prefixes a 64-byte leaf could be reinterpreted as an internal
  node and an attacker could present a crafted "proof" for a value that was
  never a leaf (second-preimage ambiguity). Prefixing leaves and branches with
  different bytes makes the two roles unambiguous (same defence as RFC 6962).

The implementation is dependency-free so it runs in the offline edge environment
and in unit tests without a blockchain toolchain.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple

__all__ = [
    "MerkleError",
    "MerkleProof",
    "hash_leaf",
    "hash_node",
    "compute_root",
    "build_tree",
    "build_proof",
    "verify_proof",
    "MerkleTree",
]

_LEAF_PREFIX = b"\x00"
_NODE_PREFIX = b"\x01"


class MerkleError(ValueError):
    """Raised for malformed inputs (wrong digest length, bad proof, empty tree)."""


def _expect_32(value: bytes, label: str) -> bytes:
    if not isinstance(value, (bytes, bytearray)):
        raise MerkleError(f"{label} must be raw bytes, got {type(value)!r}")
    if len(value) != 32:
        raise MerkleError(f"{label} must be exactly 32 bytes, got {len(value)}")
    return bytes(value)


def hash_leaf(data: bytes) -> bytes:
    """Return the domain-separated leaf hash of raw *data* (``sha256(0x00||data)``)."""
    if not isinstance(data, (bytes, bytearray)):
        raise MerkleError("Leaf data must be raw bytes.")
    return hashlib.sha256(_LEAF_PREFIX + bytes(data)).digest()


def hash_node(a: bytes, b: bytes) -> bytes:
    """Return the sorted-pair internal node hash (``sha256(0x01||min||max)``)."""
    x = _expect_32(a, "left")
    y = _expect_32(b, "right")
    lo, hi = (x, y) if x <= y else (y, x)
    return hashlib.sha256(_NODE_PREFIX + lo + hi).digest()


def _sorted_leaves(leaves: Iterable[bytes]) -> List[bytes]:
    normalized = [_expect_32(leaf, "leaf") for leaf in leaves]
    return sorted(normalized)


def build_tree(leaf_hashes: Sequence[bytes]) -> List[List[bytes]]:
    """Return the full tree as a list of levels, ``levels[0]`` being sorted leaves.

    An empty input raises ``MerkleError`` — a Merkle root only exists for a
    non-empty leaf set.
    """
    leaves = _sorted_leaves(leaf_hashes)
    if not leaves:
        raise MerkleError("Cannot build a Merkle tree with no leaves.")

    levels: List[List[bytes]] = [leaves]
    current = leaves
    while len(current) > 1:
        if len(current) % 2:
            current = current + [current[-1]]  # duplicate the last node (odd level)
        next_level = [
            hash_node(current[i], current[i + 1]) for i in range(0, len(current), 2)
        ]
        levels.append(next_level)
        current = next_level
    return levels


def compute_root(leaf_hashes: Sequence[bytes]) -> bytes:
    """Return the Merkle root for the given leaf hashes (32 raw bytes)."""
    return build_tree(leaf_hashes)[-1][0]


@dataclass(frozen=True)
class MerkleProof:
    """A Merkle inclusion proof: the leaf, the trusted root, and sibling hashes."""

    leaf: bytes
    root: bytes
    siblings: Tuple[bytes, ...]

    def to_dict(self) -> dict:
        return {
            "leaf": self.leaf.hex(),
            "root": self.root.hex(),
            "siblings": [s.hex() for s in self.siblings],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MerkleProof":
        try:
            return cls(
                leaf=bytes.fromhex(data["leaf"]),
                root=bytes.fromhex(data["root"]),
                siblings=tuple(bytes.fromhex(s) for s in data["siblings"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MerkleError(f"Malformed Merkle proof payload: {exc}") from exc


def build_proof(leaf_hashes: Sequence[bytes], target_leaf: bytes) -> MerkleProof:
    """Build an inclusion proof for *target_leaf*.

    Raises ``MerkleError`` if the target leaf is not present.
    """
    leaves = _sorted_leaves(leaf_hashes)
    target = _expect_32(target_leaf, "target leaf")
    if target not in leaves:
        raise MerkleError("Target leaf is not part of this tree.")

    root = compute_root(leaves)
    siblings: List[bytes] = []

    index = leaves.index(target)
    current = leaves

    while len(current) > 1:
        if len(current) % 2:
            current = current + [current[-1]]
        sibling_index = index + 1 if index % 2 == 0 else index - 1
        siblings.append(current[sibling_index])
        index //= 2
        current = [hash_node(current[i], current[i + 1]) for i in range(0, len(current), 2)]

    return MerkleProof(leaf=target, root=root, siblings=tuple(siblings))


def verify_proof(leaf_hash: bytes, proof: Sequence[bytes], root: bytes) -> bool:
    """Verify an inclusion proof, returning True iff the path rebuilds *root*.

    Mirrors OpenZeppelin's ``MerkleProof.verify(proof, root, leaf)``: the caller
    supplies the trusted root separately; a proof never self-certifies.
    """
    try:
        acc = _expect_32(leaf_hash, "leaf")
        expected_root = _expect_32(root, "root")
    except MerkleError:
        return False

    for sibling in proof:
        try:
            acc = hash_node(acc, _expect_32(sibling, "sibling"))
        except MerkleError:
            return False

    return acc == expected_root


class MerkleTree:
    """Convenience wrapper bundling leaves, root and proof generation."""

    def __init__(self, leaf_hashes: Sequence[bytes]) -> None:
        self.levels = build_tree(leaf_hashes)
        self.leaves = self.levels[0]
        self.root = self.levels[-1][0]

    def proof(self, target_leaf: bytes) -> MerkleProof:
        return build_proof(self.leaves, target_leaf)

    def verify(self, target_leaf: bytes) -> bool:
        """True iff *target_leaf* is a member of this tree (never raises)."""
        try:
            proof = self.proof(target_leaf)
        except MerkleError:
            return False
        return verify_proof(proof.leaf, proof.siblings, self.root)
