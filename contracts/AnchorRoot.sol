// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

contract AnchorRoot {
    bytes32 public latestRoot;
    uint256 public latestBlockNumber;
    uint256 public latestTimestamp;

    event RootAnchored(bytes32 indexed rootHash, uint256 indexed blockNumber, uint256 timestamp);

    function anchor(bytes32 rootHash) external returns (uint256) {
        latestRoot = rootHash;
        latestBlockNumber = block.number;
        latestTimestamp = block.timestamp;

        emit RootAnchored(rootHash, latestBlockNumber, latestTimestamp);

        return latestBlockNumber;
    }

    function latestAnchor() external view returns (uint256, uint256, bytes32) {
        return (latestBlockNumber, latestTimestamp, latestRoot);
    }
}
