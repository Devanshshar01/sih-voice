// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title MerkleProof
 * @notice On-chain verifier for the SatyaVoice SHA-256 Merkle scheme.
 *
 * This library reproduces, byte-for-byte, the layout implemented off-chain in
 * `app/core/merkle.py`:
 *
 *   leaf = sha256(0x00 || data)
 *   node = sha256(0x01 || min(a, b) || max(a, b))     // sorted-pair branch
 *   leaves are sorted; odd levels duplicate the last node.
 *
 * WHY SHA-256 (and not keccak256)?
 *   The evidence layer is deliberately chain-agnostic: the same root is computed
 *   in Python, in the browser, and (here) on-chain. SHA-256 is available in every
 *   one of those runtimes, so the scheme uses SHA-256 consistently end to end, as
 *   the design requires. The EVM exposes it as the `sha256` precompile.
 *
 * SORTED PAIRS
 *   Hashing the pair in ascending order means a proof is just an ordered list of
 *   sibling hashes — no left/right position bits are stored or transmitted. This
 *   is the same simplification OpenZeppelin's MerkleProof uses (it hashes
 *   `_hashPair` in sorted order); only the hash function differs.
 *
 * DOMAIN SEPARATION (0x00 / 0x01)
 *   `hashLeaf` prefixes 0x00 and `hashNode` prefixes 0x01 so a leaf can never be
 *   reinterpreted as an internal node (second-preimage defence, RFC 6962-style).
 *
 * Callers pass the ALREADY domain-separated leaf digest to `verify`, matching
 * `app.core.merkle.verify_proof(leaf_hash, proof, root)`.
 */
library MerkleProof {
    /**
     * @notice Return the domain-separated leaf digest for raw data.
     */
    function hashLeaf(bytes memory data) internal pure returns (bytes32) {
        return sha256(abi.encodePacked(bytes1(0x00), data));
    }

    /**
     * @notice Return the sorted-pair internal node hash of two children.
     */
    function hashNode(bytes32 a, bytes32 b) internal pure returns (bytes32) {
        (bytes32 lo, bytes32 hi) = a <= b ? (a, b) : (b, a);
        return sha256(abi.encodePacked(bytes1(0x01), lo, hi));
    }

    /**
     * @notice Verify that `leaf` is included in the tree whose root is `root`.
     * @param leaf  The domain-separated leaf digest (32 bytes).
     * @param proof The ordered sibling hashes from the leaf up to the root.
     * @param root  The trusted Merkle root (from the anchored commitment).
     * @return True iff the rebuilt path equals `root`.
     *
     * @dev The root is supplied by the caller and is never derived from the
     *      proof — a proof cannot certify itself.
     */
    function verify(
        bytes32[] memory proof,
        bytes32 root,
        bytes32 leaf
    ) internal pure returns (bool) {
        bytes32 computed = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            computed = hashNode(computed, proof[i]);
        }
        return computed == root;
    }

    /**
     * @notice External-friendly wrapper so an explorer/UI can verify a proof
     *         without a local copy of the library.
     */
    function verifyCalldata(
        bytes32[] calldata proof,
        bytes32 root,
        bytes32 leaf
    ) external pure returns (bool) {
        bytes32 computed = leaf;
        for (uint256 i = 0; i < proof.length; i++) {
            (bytes32 lo, bytes32 hi) = computed <= proof[i]
                ? (computed, proof[i])
                : (proof[i], computed);
            computed = sha256(abi.encodePacked(bytes1(0x01), lo, hi));
        }
        return computed == root;
    }
}
