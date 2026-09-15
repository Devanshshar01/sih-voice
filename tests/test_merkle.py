"""Merkle tree tests: determinism, proofs, tamper detection, and edge cases.

The scheme under test is the canonical layout shared with contracts/AnchorRoot.sol:
  leaf  = sha256(0x00 || data)
  node  = sha256(0x01 || min(a,b) || max(a,b))   (sorted-pair, OpenZeppelin-style)
  leaves sorted; odd level duplicates last node.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.merkle import (  # noqa: E402
    MerkleError,
    MerkleTree,
    build_proof,
    build_tree,
    compute_root,
    hash_leaf,
    hash_node,
    verify_proof,
)


def _leaves(*payloads: bytes) -> list[bytes]:
    return [hash_leaf(p) for p in payloads]


# ---------------------------------------------------------------------------
# Hashing primitives
# ---------------------------------------------------------------------------

def test_hash_leaf_is_domain_separated():
    data = b"hello"
    assert hash_leaf(data) == hashlib.sha256(b"\x00" + data).digest()
    assert len(hash_leaf(data)) == 32


def test_hash_node_is_sorted_pair_and_domain_separated():
    a = hash_leaf(b"a")
    b = hash_leaf(b"b")
    lo, hi = (a, b) if a <= b else (b, a)
    assert hash_node(a, b) == hashlib.sha256(b"\x01" + lo + hi).digest()
    # Sorted-pair means argument order does not matter.
    assert hash_node(a, b) == hash_node(b, a)
    # Leaf and node spaces are disjoint: a leaf can never masquerade as a node.
    assert hash_leaf(a + b) != hash_node(a, b)


def test_hash_node_rejects_wrong_length():
    with pytest.raises(MerkleError):
        hash_node(b"short", b"\x00" * 32)


# ---------------------------------------------------------------------------
# Root construction
# ---------------------------------------------------------------------------

def test_single_leaf_root_is_the_leaf():
    leaf = hash_leaf(b"only")
    assert compute_root([leaf]) == leaf


def test_two_leaf_root():
    a, b = _leaves(b"a", b"b")
    assert compute_root([a, b]) == hash_node(a, b)


def test_three_leaf_root_duplicates_last():
    leaves = _leaves(b"a", b"b", b"c")
    a, b, c = sorted(leaves)
    expected = hash_node(hash_node(a, b), hash_node(c, c))
    assert compute_root(leaves) == expected


def test_four_leaf_root():
    a, b, c, d = sorted(_leaves(*[bytes([i]) for i in range(4)]))
    expected = hash_node(hash_node(a, b), hash_node(c, d))
    assert compute_root([a, b, c, d]) == expected


def test_root_is_order_independent():
    """Leaves are sorted, so permutation must not change the root."""
    leaves = _leaves(b"x", b"y", b"z", b"w")
    assert compute_root(leaves) == compute_root(list(reversed(leaves)))
    assert compute_root(leaves) == compute_root([leaves[2], leaves[0], leaves[3], leaves[1]])


def test_empty_tree_rejected():
    with pytest.raises(MerkleError):
        compute_root([])


def test_non_32_byte_leaf_rejected():
    with pytest.raises(MerkleError):
        compute_root([b"too short"])


def test_build_tree_level_structure():
    leaves = _leaves(*[bytes([i]) for i in range(5)])
    levels = build_tree(leaves)
    assert len(levels[0]) == 5
    assert len(levels[1]) == 3  # 5 -> duplicate -> 6 -> 3
    assert len(levels[2]) == 2
    assert len(levels[3]) == 1


# ---------------------------------------------------------------------------
# Proofs
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 7, 8, 13])
def test_every_leaf_has_a_valid_proof(n):
    leaves = _leaves(*[f"item-{i}".encode() for i in range(n)])
    root = compute_root(leaves)
    for leaf in leaves:
        proof = build_proof(leaves, leaf)
        assert proof.root == root
        assert verify_proof(proof.leaf, proof.siblings, root) is True


def test_proof_for_missing_leaf_raises():
    leaves = _leaves(b"a", b"b")
    with pytest.raises(MerkleError):
        build_proof(leaves, hash_leaf(b"absent"))


def test_tampered_leaf_fails_verification():
    leaves = _leaves(b"a", b"b", b"c")
    root = compute_root(leaves)
    proof = build_proof(leaves, leaves[0])
    forged = hash_leaf(b"FORGED")
    assert verify_proof(forged, proof.siblings, root) is False


def test_corrupted_sibling_fails_verification():
    leaves = _leaves(*[f"i{i}".encode() for i in range(4)])
    root = compute_root(leaves)
    proof = build_proof(leaves, leaves[2])
    bad = list(proof.siblings)
    bad[0] = bytes(32)  # zero sibling
    assert verify_proof(proof.leaf, bad, root) is False


def test_wrong_root_fails_verification():
    leaves = _leaves(b"a", b"b")
    proof = build_proof(leaves, leaves[0])
    assert verify_proof(proof.leaf, proof.siblings, bytes(32)) is False


def test_empty_proof_verifies_only_for_single_leaf_tree():
    leaf = hash_leaf(b"solo")
    assert verify_proof(leaf, [], leaf) is True
    assert verify_proof(leaf, [], bytes(32)) is False


def test_proof_roundtrips_through_dict():
    from app.core.merkle import MerkleProof

    leaves = _leaves(b"alpha", b"beta", b"gamma")
    proof = build_proof(leaves, leaves[1])
    restored = MerkleProof.from_dict(proof.to_dict())
    assert restored == proof


# ---------------------------------------------------------------------------
# Wrapper
# ---------------------------------------------------------------------------

def test_tree_wrapper_verifies_members_and_rejects_others():
    tree = MerkleTree(_leaves(b"a", b"b", b"c"))
    assert tree.verify(tree.leaves[0]) is True
    assert tree.verify(hash_leaf(b"not-in-tree")) is False
