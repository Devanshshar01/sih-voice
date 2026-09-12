// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title AnchorRoot — append-only evidence-root anchoring with authorization.
///
/// Security model (SIH forensic layer):
///  * Only the contract OWNER (deployer) or an explicitly authorized ANCHOR
///    may submit roots. An arbitrary caller can no longer write fake roots.
///  * Ownership follows OpenZeppelin's Ownable semantics (transfer/renounce)
///    implemented inline to avoid a dependency.
///  * Anchoring is APPEND-ONLY: every root is appended to an array and emits
///    an event; nothing is ever overwritten. Historical roots remain verifiable
///    even after newer ones are anchored (the legacy mutable latestRoot model
///    silently destroyed that property).
///  * Duplicate roots are rejected (an evidence package anchors once).
///  * Reads: latestRoot()/latestAnchor() are preserved for backward
///    compatibility, now derived from the last append. Anchors can also be
///    enumerated and independently verified by index.
contract AnchorRoot {
    // ------------------------------------------------------------------
    // Authorization
    // ------------------------------------------------------------------
    address public owner;
    mapping(address => bool) public authorizedAnchors;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event AnchorAuthorizationSet(address indexed account, bool authorized);

    error Unauthorized();
    error ZeroAddress();

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    modifier onlyAuthorized() {
        if (msg.sender != owner && !authorizedAnchors[msg.sender]) revert Unauthorized();
        _;
    }

    constructor() {
        owner = msg.sender;
        emit OwnershipTransferred(address(0), msg.sender);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function setAnchorAuthorization(address account, bool authorized) external onlyOwner {
        if (account == address(0)) revert ZeroAddress();
        authorizedAnchors[account] = authorized;
        emit AnchorAuthorizationSet(account, authorized);
    }

    // ------------------------------------------------------------------
    // Append-only anchoring
    // ------------------------------------------------------------------
    struct Anchor {
        bytes32 rootHash;
        uint256 blockNumber;
        uint256 timestamp;
    }

    Anchor[] private _anchors;

    event RootAnchored(
        uint256 indexed anchorIndex,
        bytes32 indexed rootHash,
        uint256 blockNumber,
        uint256 timestamp
    );

    error EmptyRoot();
    error DuplicateRoot();

    /// @notice Append a new evidence root. Owner or an authorized anchor only.
    /// @return anchorIndex the index of the appended anchor.
    function anchor(bytes32 rootHash) external onlyAuthorized returns (uint256 anchorIndex) {
        if (rootHash == bytes32(0)) revert EmptyRoot();
        if (rootIndex(rootHash) != type(uint256).max) revert DuplicateRoot();

        anchorIndex = _anchors.length;
        _anchors.push(Anchor({rootHash: rootHash, blockNumber: block.number, timestamp: block.timestamp}));
        emit RootAnchored(anchorIndex, rootHash, block.number, block.timestamp);
    }

    // ------------------------------------------------------------------
    // Views
    // ------------------------------------------------------------------
    function anchorCount() external view returns (uint256) {
        return _anchors.length;
    }

    function getAnchor(uint256 index)
        external
        view
        returns (bytes32 rootHash, uint256 blockNumber, uint256 timestamp)
    {
        Anchor memory a = _anchors[index];
        return (a.rootHash, a.blockNumber, a.timestamp);
    }

    /// @notice Index of a root, or type(uint256).max when not present.
    function rootIndex(bytes32 rootHash) public view returns (uint256) {
        for (uint256 i = 0; i < _anchors.length; i++) {
            if (_anchors[i].rootHash == rootHash) return i;
        }
        return type(uint256).max;
    }

    /// @notice Independent verification: has this exact root been anchored?
    function isAnchored(bytes32 rootHash) external view returns (bool) {
        return rootIndex(rootHash) != type(uint256).max;
    }

    // Backward-compatible latest* views (now derived from the last append).
    function latestRoot() external view returns (bytes32) {
        return _anchors.length == 0 ? bytes32(0) : _anchors[_anchors.length - 1].rootHash;
    }

    function latestBlockNumber() external view returns (uint256) {
        return _anchors.length == 0 ? 0 : _anchors[_anchors.length - 1].blockNumber;
    }

    function latestTimestamp() external view returns (uint256) {
        return _anchors.length == 0 ? 0 : _anchors[_anchors.length - 1].timestamp;
    }

    function latestAnchor()
        external
        view
        returns (uint256 blockNumber, uint256 timestamp, bytes32 rootHash)
    {
        if (_anchors.length == 0) return (0, 0, bytes32(0));
        Anchor memory a = _anchors[_anchors.length - 1];
        return (a.blockNumber, a.timestamp, a.rootHash);
    }
}
