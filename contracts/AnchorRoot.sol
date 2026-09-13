// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title AnchorRoot
 * @notice Append-only evidence root anchoring for SatyaVoice forensic packages.
 *
 * SECURITY MODEL:
 *   Only the contract owner (the deploying account) can anchor new roots.
 *   This prevents arbitrary callers from overwriting or polluting the anchor
 *   history. The backend evidence service is the sole authorized submitter.
 *
 * APPEND-ONLY DESIGN:
 *   Root hashes are stored in an ordered array. Anchoring a new root appends
 *   to the history — it does NOT overwrite the previous root. This makes the
 *   on-chain history tamper-evident: every anchored root is permanently
 *   visible and queryable.
 *
 * REPLAY PREVENTION:
 *   Anchoring the same root hash twice is rejected (reverts). Each unique
 *   evidence digest can only be anchored once.
 *
 * ZERO-VALUE PREVENTION:
 *   A zero bytes32 root hash is rejected. This guards against accidental
 *   anchoring of uninitialized or empty hash values.
 *
 * EVENTS:
 *   RootAnchored is emitted for every successful anchor. Off-chain verifiers
 *   can reconstruct the full anchor history from events alone.
 *
 * OWNERSHIP TRANSFER:
 *   The owner can transfer ownership to a new address using transferOwnership().
 *   Ownership cannot be renounced (set to zero address) to ensure there is
 *   always an authorized submitter.
 *
 * CHAIN ID NOTE:
 *   This contract does not verify chain ID in Solidity — chain ID confusion
 *   is handled at the application layer (app/services/anchor_adapter.py
 *   verifies web3.eth.chain_id matches BLOCKCHAIN_CHAIN_ID before signing).
 */
contract AnchorRoot {
    // -------------------------------------------------------------------------
    // State
    // -------------------------------------------------------------------------

    address public owner;

    // Append-only anchor history. Index 0 = first anchor.
    bytes32[] public roots;
    uint256[] public blockNumbers;
    uint256[] public timestamps;

    // Reverse mapping: root hash -> index+1 (0 means not anchored).
    mapping(bytes32 => uint256) private _rootIndex;

    // -------------------------------------------------------------------------
    // Events
    // -------------------------------------------------------------------------

    event RootAnchored(
        bytes32 indexed rootHash,
        uint256 indexed anchorIndex,
        uint256 blockNumber,
        uint256 timestamp
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
}
