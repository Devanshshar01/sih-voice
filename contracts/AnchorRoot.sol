// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import {MerkleProof} from "./MerkleProof.sol";

/**
 * @title AnchorRoot
 * @notice Append-only evidence root anchoring for SatyaVoice forensic packages.
 *
 * CONTRACT VERSION: 1.1.0 — reported by `contractVersion()` so
 * verifiers can pin the exact anchoring semantics they are checking against.
 *
 * TWO ANCHORING MODES (both append-only, both onlyOwner):
 *
 *   1. `anchor(bytes32 rootHash)` — the original single-digest commitment. It
 *      commits an opaque evidence root with no associated identifier. Retained
 *      unchanged for backward compatibility with already-deployed integrations.
 *
 *   2. `anchorEvidence(bytes32 evidenceRoot, bytes32 evidenceId)` — the
 *      Merkle-root scheme. It commits a Merkle ROOT together with a stable
 *      `evidenceId`, and records `root -> evidenceId` so a verifier can resolve
 *      a report's root back to the case it belongs to. Emits `EvidenceAnchored`.
 *      Optionally, `anchorEvidenceWithProof` verifies a caller-supplied Merkle
 *      inclusion proof against the root in the SAME transaction, so a specific
 *      evidence leaf is provably bound to the anchored commitment on-chain.
 *
 * SECURITY MODEL:
 *   Only the contract owner (the deploying account) can anchor. This prevents
 *   arbitrary callers from polluting the anchor history. The backend evidence
 *   service is the sole authorized submitter; the privacy-preserving design
 *   keeps raw audio/transcripts off-chain (only commitments are stored).
 *
 * APPEND-ONLY DESIGN:
 *   Roots are stored in ordered arrays. Anchoring appends to the history — it
 *   never overwrites a previous root. Every anchored root stays permanently
 *   visible and queryable.
 *
 * REPLAY PREVENTION:
 *   Anchoring the same root hash twice is rejected (reverts). Each unique
 *   evidence digest can only be anchored once.
 *
 * ZERO-VALUE PREVENTION:
 *   Zero bytes32 roots and IDs are rejected.
 *
 * EVENTS:
 *   `RootAnchored` (legacy) and `EvidenceAnchored` (Merkle scheme) are emitted
 *   so off-chain verifiers can reconstruct the full anchor history from events.
 *
 * OWNERSHIP TRANSFER:
 *   Ownership can be transferred; it cannot be renounced (set to zero) so there
 *   is always an authorized submitter.
 *
 * CHAIN ID NOTE:
 *   Chain-ID confusion is handled at the application layer
 *   (app/services/anchor_adapter.py verifies web3.eth.chain_id matches
 *   BLOCKCHAIN_CHAIN_ID before signing).
 */
contract AnchorRoot {
    // -------------------------------------------------------------------------
    // State
    // -------------------------------------------------------------------------

    /// @notice Semantic version of the anchoring semantics (not the compiler).
    string public constant CONTRACT_VERSION = "1.1.0";

    address public owner;

    // Append-only anchor history. Index 0 = first anchor.
    bytes32[] public roots;
    uint256[] public blockNumbers;
    uint256[] public timestamps;

    // Reverse mapping: root hash -> index+1 (0 means not anchored).
    mapping(bytes32 => uint256) private _rootIndex;

    // --- Merkle-root scheme (`anchorEvidence`) ---------------------------------
    // Append-only history of evidence anchors (independent of the legacy array
    // above so the two schemes never interfere).
    bytes32[] public evidenceRoots;
    bytes32[] public evidenceIds;

    // root -> evidenceId, set once (a root is anchored at most once).
    mapping(bytes32 => bytes32) private _evidenceIdOf;
    // evidenceId -> root, so a case id resolves to its committed root.
    mapping(bytes32 => bytes32) private _rootOfEvidenceId;
    // root -> index+1 in the evidence arrays (0 means not anchored).
    mapping(bytes32 => uint256) private _evidenceIndex;

    // -------------------------------------------------------------------------
    // Events
    // -------------------------------------------------------------------------

    event RootAnchored(
        bytes32 indexed rootHash,
        uint256 indexed anchorIndex,
        uint256 blockNumber,
        uint256 timestamp
    );

    /**
     * @notice Emitted for every Merkle-root evidence anchor.
     * @dev Verifiers reconstruct the anchor history from these events alone.
     *      `anchorer` records who submitted (always the owner in practice).
     */
    event EvidenceAnchored(
        bytes32 indexed root,
        bytes32 indexed evidenceId,
        uint256 timestamp,
        address indexed anchorer
    );

    event OwnershipTransferred(
        address indexed previousOwner,
        address indexed newOwner
    );

    // -------------------------------------------------------------------------
    // Modifiers
    // -------------------------------------------------------------------------

    modifier onlyOwner() {
        require(msg.sender == owner, "AnchorRoot: caller is not the owner");
        _;
    }

    // -------------------------------------------------------------------------
    // Constructor
    // -------------------------------------------------------------------------

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    // -------------------------------------------------------------------------
    // Owner management
    // -------------------------------------------------------------------------

    /**
     * @notice Transfer contract ownership to a new address.
     * @param newOwner The address that will become the new owner.
     *        Cannot be the zero address (ownership cannot be renounced).
     */
    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "AnchorRoot: new owner cannot be zero address");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // -------------------------------------------------------------------------
    // Core anchoring
    // -------------------------------------------------------------------------

    /**
     * @notice Anchor a new evidence root hash.
     * @param rootHash A 32-byte evidence root hash produced by the local
     *        integrity ledger. Must be non-zero and must not already be anchored.
     * @return anchorIndex The zero-based index of this anchor in the history.
     */
    function anchor(bytes32 rootHash) external onlyOwner returns (uint256 anchorIndex) {
        require(rootHash != bytes32(0), "AnchorRoot: root hash must not be zero");
        require(_rootIndex[rootHash] == 0, "AnchorRoot: root hash already anchored");

        anchorIndex = roots.length;
        roots.push(rootHash);
        blockNumbers.push(block.number);
        timestamps.push(block.timestamp);

        // Store index+1 so we can distinguish "not anchored" (0) from "anchored at index 0".
        _rootIndex[rootHash] = anchorIndex + 1;

        emit RootAnchored(rootHash, anchorIndex, block.number, block.timestamp);
    }

    // -------------------------------------------------------------------------
    // Core anchoring — Merkle evidence scheme
    // -------------------------------------------------------------------------

    /**
     * @notice Anchor a Merkle root together with its evidence identifier.
     * @param evidenceRoot The Merkle root (32 bytes) over the canonical,
     *        per-item-hashed evidence leaves.
     * @param evidenceId   A stable 32-byte case/evidence identifier
     *        (e.g. keccak256/sha256 of the SatyaVoice case id string).
     * @return evidenceIndex The zero-based index of this anchor in the history.
     *
     * Reverts if either argument is zero, or if the root was already anchored
     * (replay prevention). Emits `EvidenceAnchored`. Only the owner may call.
     */
    function anchorEvidence(
        bytes32 evidenceRoot,
        bytes32 evidenceId
    ) external onlyOwner returns (uint256 evidenceIndex) {
        return _anchorEvidence(evidenceRoot, evidenceId);
    }

    /**
     * @notice Anchor a Merkle root and, in the same transaction, verify that a
     *         specific evidence leaf is included in it.
     * @param evidenceRoot The Merkle root to anchor.
     * @param evidenceId   The case/evidence identifier.
     * @param leaf         The domain-separated leaf digest to prove inclusion of.
     * @param proof        The ordered sibling hashes (leaf -> root).
     *
     * The inclusion check runs BEFORE the write, so a bogus proof reverts the
     * whole transaction: a leaf is only ever bound to a root that provably
     * contains it. Emits `EvidenceAnchored` on success. Only the owner may call.
     */
    function anchorEvidenceWithProof(
        bytes32 evidenceRoot,
        bytes32 evidenceId,
        bytes32 leaf,
        bytes32[] calldata proof
    ) external onlyOwner returns (uint256 evidenceIndex) {
        require(
            MerkleProof.verify(proof, evidenceRoot, leaf),
            "AnchorRoot: Merkle inclusion proof failed"
        );
        return _anchorEvidence(evidenceRoot, evidenceId);
    }

    /**
     * @dev Shared write path for the two public entry points. Validates both
     *      keys, appends to the evidence history, and updates the two-way maps.
     */
    function _anchorEvidence(
        bytes32 evidenceRoot,
        bytes32 evidenceId
    ) private returns (uint256 evidenceIndex) {
        require(evidenceRoot != bytes32(0), "AnchorRoot: root hash must not be zero");
        require(evidenceId != bytes32(0), "AnchorRoot: evidenceId must not be zero");
        require(_evidenceIndex[evidenceRoot] == 0, "AnchorRoot: root hash already anchored");
        require(
            _rootOfEvidenceId[evidenceId] == bytes32(0),
            "AnchorRoot: evidenceId already anchored"
        );

        evidenceIndex = evidenceRoots.length;
        evidenceRoots.push(evidenceRoot);
        evidenceIds.push(evidenceId);

        // Store index+1 so 0 unambiguously means "not anchored".
        _evidenceIndex[evidenceRoot] = evidenceIndex + 1;
        _evidenceIdOf[evidenceRoot] = evidenceId;
        _rootOfEvidenceId[evidenceId] = evidenceRoot;

        emit EvidenceAnchored(evidenceRoot, evidenceId, block.timestamp, msg.sender);
    }

    // -------------------------------------------------------------------------
    // Read functions
    // -------------------------------------------------------------------------

    /**
     * @notice Returns the total number of roots that have been anchored.
     */
    function anchorCount() external view returns (uint256) {
        return roots.length;
    }

    /**
     * @notice Returns the most recently anchored root and its metadata.
     * @dev Reverts if no roots have been anchored yet.
     */
    function latestAnchor() external view returns (
        uint256 anchorIndex,
        uint256 blockNumber,
        uint256 blockTimestamp,
        bytes32 rootHash
    ) {
        require(roots.length > 0, "AnchorRoot: no roots anchored yet");
        anchorIndex = roots.length - 1;
        rootHash = roots[anchorIndex];
        blockNumber = blockNumbers[anchorIndex];
        blockTimestamp = timestamps[anchorIndex];
    }

    /**
     * @notice Retrieve a specific anchor by index.
     * @param index The zero-based index into the anchor history.
     */
    function getAnchor(uint256 index) external view returns (
        bytes32 rootHash,
        uint256 blockNumber,
        uint256 blockTimestamp
    ) {
        require(index < roots.length, "AnchorRoot: index out of bounds");
        rootHash = roots[index];
        blockNumber = blockNumbers[index];
        blockTimestamp = timestamps[index];
    }

    /**
     * @notice Check whether a root hash has been anchored.
     * @param rootHash The root hash to query.
     * @return True if anchored, false otherwise.
     */
    function isAnchored(bytes32 rootHash) external view returns (bool) {
        return _rootIndex[rootHash] != 0;
    }

    /**
     * @notice Return the anchor index for a root hash (reverts if not anchored).
     * @param rootHash The root hash to look up.
     * @return The zero-based anchor index.
     */
    function indexOfRoot(bytes32 rootHash) external view returns (uint256) {
        uint256 stored = _rootIndex[rootHash];
        require(stored != 0, "AnchorRoot: root hash not anchored");
        return stored - 1;
    }

    // --- Merkle evidence scheme reads -----------------------------------------

    /**
     * @notice Returns the total number of Merkle evidence anchors.
     */
    function evidenceAnchorCount() external view returns (uint256) {
        return evidenceRoots.length;
    }

    /**
     * @notice Check whether a Merkle evidence root has been anchored.
     */
    function isEvidenceAnchored(bytes32 evidenceRoot) external view returns (bool) {
        return _evidenceIndex[evidenceRoot] != 0;
    }

    /**
     * @notice Return the evidenceId committed for a root (zero if not anchored).
     */
    function evidenceIdOf(bytes32 evidenceRoot) external view returns (bytes32) {
        return _evidenceIdOf[evidenceRoot];
    }

    /**
     * @notice Return the root committed for an evidenceId (zero if not anchored).
     */
    function rootOfEvidenceId(bytes32 evidenceId) external view returns (bytes32) {
        return _rootOfEvidenceId[evidenceId];
    }

    /**
     * @notice Verify a Merkle inclusion proof against a root anchored here.
     * @dev Returns false (never reverts) when the root is not anchored, so a UI
     *      can call this directly without try/catch.
     */
    function verifyEvidenceProof(
        bytes32 evidenceRoot,
        bytes32 leaf,
        bytes32[] calldata proof
    ) external view returns (bool) {
        if (_evidenceIndex[evidenceRoot] == 0) {
            return false;
        }
        return MerkleProof.verify(proof, evidenceRoot, leaf);
    }
}
