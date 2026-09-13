# Blockchain Production Configuration

SatyaVoice uses an optional public blockchain (Polygon Amoy testnet) as a tamper-evident root of trust for finalized forensic evidence packages. 

## Supported Network

The current supported network is **Polygon Amoy** (testnet). 

## Security Boundaries

- **Backend-Only:** Only the backend `evidence_anchor` service is authorized to submit transactions. The frontend/browser *never* holds the private key or interacts directly with the blockchain.
- **Contract Access Control:** The `AnchorRoot` smart contract implements an `onlyOwner` modifier. Only the wallet address that deployed the contract can successfully call `anchor()`.
- **Replay & Cross-Chain Protection:** 
  - The contract rejects duplicate root hashes (`require(_rootIndex[rootHash] == 0)`).
  - The backend verifies that the connected node's `chain_id` matches `BLOCKCHAIN_CHAIN_ID` before signing the transaction, preventing cross-chain replay attacks.
  - Zero hashes (`0x0000...`) are rejected by both the backend and the contract.
- **Append-Only:** The contract stores roots in an append-only array. New roots do not overwrite previous ones.

## Environment Variables & Secret Requirements

Blockchain anchoring is enabled and configured entirely via environment variables. **Do not hardcode or commit these values.**

| Variable | Description | Example / Required |
|----------|-------------|--------------------|
| `BLOCKCHAIN_ANCHORING_ENABLED` | Set to `true` to enable public anchoring. | `true` or `false` |
| `BLOCKCHAIN_NETWORK` | Human-readable network name. | `polygon-amoy` |
| `BLOCKCHAIN_CHAIN_ID` | The numeric Chain ID for the target network. | `80002` (Amoy) |
| `BLOCKCHAIN_RPC_URL` | HTTPS RPC endpoint URL (e.g., Infura/Alchemy). | *Required if enabled* |
| `BLOCKCHAIN_CONTRACT_ADDRESS` | Address of the deployed `AnchorRoot` contract. | *Required if enabled* |
| `BLOCKCHAIN_PRIVATE_KEY` | Hex-encoded private key for the authorized signer wallet. | *Required if enabled* |
| `BLOCKCHAIN_GAS_LIMIT` | Maximum gas for the transaction. | Default: `200000` |

## Deployment Steps

1. **Deploy the Smart Contract:** Deploy `contracts/AnchorRoot.sol` to Polygon Amoy using Hardhat, Foundry, or Remix. Note the deployed contract address.
2. **Configure Environment:** In your production environment (e.g., Render), configure the environment variables listed above. Ensure the private key corresponds to the address that deployed the contract.
3. **Start the Backend:** When `BLOCKCHAIN_ANCHORING_ENABLED=true` and all required variables are present, the backend will automatically initialize the `PolygonAmoyAnchorAdapter`.

## Disabled Behavior

If `BLOCKCHAIN_ANCHORING_ENABLED=false` (or if it's misconfigured), the system degrades gracefully to the `NoopAnchorAdapter`.
- The local SQLite/PostgreSQL evidence ledger remains fully operational.
- Evidence packages will indicate an anchor status of `"unavailable"`.
- This ensures the core application does not crash or block evidence generation if the blockchain is unreachable.

## Transaction States

An evidence package's blockchain anchor will pass through several states:

- `unavailable`: Anchoring disabled or misconfigured.
- `pending`: Transaction submitted to the network, awaiting confirmation.
- `anchored`: Transaction confirmed (status 1) and included in a block.
- `failed`: Transaction reverted on-chain, or an RPC/submission error occurred.

## Verification Process

The `/api/v1/evidence/verify` endpoint uses the local ledger to verify package integrity.
If an anchor exists, the backend also queries the public contract independently (via the RPC) to verify that the `local_chain_root` exists on-chain. It does not trust client-provided claims.
