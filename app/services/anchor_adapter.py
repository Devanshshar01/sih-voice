"""Blockchain anchoring adapters for the Phase 8 hybrid evidence layer.

SECURITY DESIGN:
  - Only the backend evidence service can submit anchor transactions.
    Private keys, RPC URLs, and contract addresses are sourced exclusively
    from environment variables — never hardcoded, never logged.
  - Chain ID is verified before signing to prevent cross-chain replay attacks.
  - The contract's onlyOwner restriction prevents arbitrary callers from
    anchoring roots directly on-chain.
  - Zero root hashes are rejected at the application layer (pre-submission)
    and at the contract layer (require guard).
  - Duplicate (replay) anchoring is rejected by the contract itself.

ANCHOR STATUS VALUES (used throughout the evidence layer):
  "unavailable"  — blockchain anchoring is disabled or misconfigured.
  "pending"      — transaction submitted, awaiting confirmation.
  "anchored"     — transaction confirmed with status=1.
  "failed"       — transaction reverted, or application/network error.

The default adapter (NoopAnchorAdapter) degrades gracefully to "unavailable"
when Polygon Amoy or required runtime support is not configured, so evidence
generation and local verification remain fully functional.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app import config

logger = logging.getLogger("satyavoice.anchor")


class BaseAnchorAdapter:
    def anchor_root(self, root_hash: str, evidence_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def verify_anchor(self, root_hash: str) -> dict[str, Any]:
        raise NotImplementedError


class NoopAnchorAdapter(BaseAnchorAdapter):
    """Used when blockchain anchoring is disabled or unconfigured."""

    def anchor_root(self, root_hash: str, evidence_id: str) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "network": config.BLOCKCHAIN_NETWORK,
            "contract_address": config.BLOCKCHAIN_CONTRACT_ADDRESS,
            "tx_hash": None,
            "block_number": None,
            "anchor_timestamp": None,
            "failure_reason": (
                "Polygon Amoy anchoring is disabled or unavailable; "
                "local forensic evidence remains available."
            ),
        }

    def verify_anchor(self, root_hash: str) -> dict[str, Any]:
        return {
            "anchored": False,
            "status": "unavailable",
            "failure_reason": "Blockchain anchoring is disabled.",
        }


class PolygonAmoyAnchorAdapter(BaseAnchorAdapter):
    """Polygon Amoy (testnet) adapter using the hardened AnchorRoot contract.

    ABI is kept in sync with contracts/AnchorRoot.sol. If the contract is
    redeployed with a new ABI, update self.abi accordingly and bump the
    contract address in BLOCKCHAIN_CONTRACT_ADDRESS.

    NEVER log self.private_key or the raw RPC URL (which may contain an API
    key) in any error path.
    """

    # ABI for the hardened AnchorRoot.sol contract.
    # Only the functions called by the backend are included here.
    _ABI = [
        {
            "inputs": [{"internalType": "bytes32", "name": "rootHash", "type": "bytes32"}],
            "name": "anchor",
            "outputs": [{"internalType": "uint256", "name": "anchorIndex", "type": "uint256"}],
            "stateMutability": "nonpayable",
            "type": "function",
        },
        {
            "inputs": [{"internalType": "bytes32", "name": "rootHash", "type": "bytes32"}],
            "name": "isAnchored",
            "outputs": [{"internalType": "bool", "name": "", "type": "bool"}],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "inputs": [],
            "name": "latestAnchor",
            "outputs": [
                {"internalType": "uint256", "name": "anchorIndex", "type": "uint256"},
                {"internalType": "uint256", "name": "blockNumber", "type": "uint256"},
                {"internalType": "uint256", "name": "blockTimestamp", "type": "uint256"},
                {"internalType": "bytes32", "name": "rootHash", "type": "bytes32"},
            ],
            "stateMutability": "view",
            "type": "function",
        },
        {
            "anonymous": False,
            "inputs": [
                {"indexed": True, "internalType": "bytes32", "name": "rootHash", "type": "bytes32"},
                {"indexed": True, "internalType": "uint256", "name": "anchorIndex", "type": "uint256"},
                {"indexed": False, "internalType": "uint256", "name": "blockNumber", "type": "uint256"},
                {"indexed": False, "internalType": "uint256", "name": "timestamp", "type": "uint256"},
            ],
            "name": "RootAnchored",
            "type": "event",
        },
    ]

    def __init__(self) -> None:
        self.rpc_url = config.BLOCKCHAIN_RPC_URL
        self.contract_address = config.BLOCKCHAIN_CONTRACT_ADDRESS
        self.private_key = config.BLOCKCHAIN_PRIVATE_KEY
        self.chain_id = config.BLOCKCHAIN_CHAIN_ID
        self.gas_limit = config.BLOCKCHAIN_GAS_LIMIT

    def _fail(self, reason: str, tx_hash: str | None = None, block_number: int | None = None) -> dict[str, Any]:
        """Return a standardised failure payload without leaking credentials."""
        return {
            "status": "failed",
            "network": config.BLOCKCHAIN_NETWORK,
            "contract_address": self.contract_address,
            "tx_hash": tx_hash,
            "block_number": block_number,
            "anchor_timestamp": None,
            "failure_reason": reason,
        }

    def _unavailable(self, reason: str) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "network": config.BLOCKCHAIN_NETWORK,
            "contract_address": self.contract_address,
            "tx_hash": None,
            "block_number": None,
            "anchor_timestamp": None,
            "failure_reason": reason,
        }

    def anchor_root(self, root_hash: str, evidence_id: str) -> dict[str, Any]:
        """Submit a root hash to the on-chain AnchorRoot contract.

        Returns a status dict. Never raises. Never logs private_key.
        """
        # --- Pre-flight configuration checks ---
        if not self.rpc_url or not self.contract_address:
            return self._unavailable(
                "Polygon Amoy RPC URL or contract address is not configured."
            )
        if not self.private_key:
            return self._unavailable(
                "BLOCKCHAIN_PRIVATE_KEY is missing. "
                "Local forensic evidence remains available."
            )

        # --- Import web3 runtime dependencies ---
        try:
            from eth_account import Account
            from web3 import Web3
            from web3.exceptions import ContractLogicError
        except Exception as exc:  # pragma: no cover
            return self._unavailable(
                f"web3 runtime dependencies are not installed: {exc}"
            )

        # --- Validate root hash format ---
        normalized_root: str
        try:
            normalized_root = root_hash if root_hash.startswith("0x") else f"0x{root_hash}"
            if len(normalized_root) != 66:
                raise ValueError(f"Expected 32-byte hex, got length {len(normalized_root)}")
            if normalized_root == "0x" + "00" * 32:
                raise ValueError("Zero root hash is not permitted.")
        except ValueError as exc:
            return self._fail(f"Invalid root hash: {exc}")

        try:
            web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not web3.is_connected():
                return self._unavailable("Polygon Amoy RPC endpoint is unreachable.")

            # --- Chain ID verification (prevents cross-chain replay) ---
            on_chain_id = web3.eth.chain_id
            if on_chain_id != self.chain_id:
                return self._fail(
                    f"Chain ID mismatch: expected {self.chain_id}, "
                    f"connected node reports {on_chain_id}. "
                    f"Transaction aborted to prevent cross-chain replay."
                )

            account = Account.from_key(self.private_key)
            contract = web3.eth.contract(address=self.contract_address, abi=self._ABI)

            nonce = web3.eth.get_transaction_count(account.address)
            root_bytes = bytes.fromhex(normalized_root[2:])

            try:
                gas_estimate = contract.functions.anchor(root_bytes).estimate_gas(
                    {"from": account.address}
                )
                gas = min(gas_estimate + 10_000, self.gas_limit)
            except Exception:
                gas = self.gas_limit

            tx = contract.functions.anchor(root_bytes).build_transaction(
                {
                    "from": account.address,
                    "nonce": nonce,
                    "gas": gas,
                    "gasPrice": web3.eth.gas_price,
                    "chainId": self.chain_id,
                }
            )
            signed_tx = Account.sign_transaction(tx, private_key=self.private_key)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            tx_hash_hex = web3.to_hex(tx_hash)

            if receipt.status != 1:
                return self._fail(
                    "Transaction mined but returned failed status (status=0).",
                    tx_hash=tx_hash_hex,
                    block_number=receipt.blockNumber,
                )

            block = web3.eth.get_block(receipt.blockNumber)
            block_timestamp = datetime.fromtimestamp(block["timestamp"], timezone.utc)

            logger.info(
                "Evidence root anchored on %s: tx=%s block=%s",
                config.BLOCKCHAIN_NETWORK,
                tx_hash_hex,
                receipt.blockNumber,
            )

            return {
                "status": "anchored",
                "network": config.BLOCKCHAIN_NETWORK,
                "contract_address": self.contract_address,
                "tx_hash": tx_hash_hex,
                "block_number": receipt.blockNumber,
                "anchor_timestamp": block_timestamp,
                "failure_reason": None,
            }

        except Exception as exc:
            from web3.exceptions import ContractLogicError
            if isinstance(exc, ContractLogicError):
                logger.warning("AnchorRoot contract reverted (evidence_id=%s): %s", evidence_id, exc)
                return self._fail(f"Contract reverted: {exc}")
            logger.warning("Blockchain anchor failed (evidence_id=%s): %s", evidence_id, type(exc).__name__)
            return self._fail(f"Submission error: {type(exc).__name__}")

    def verify_anchor(self, root_hash: str) -> dict[str, Any]:
        """Query the contract to verify whether a root hash is anchored.

        Used by the backend verification path to independently confirm
        on-chain state without trusting client-provided data.
        Never raises.
        """
        if not self.rpc_url or not self.contract_address:
            return {
                "anchored": False,
                "status": "unavailable",
                "failure_reason": "RPC URL or contract address not configured.",
            }

        try:
            from web3 import Web3
            web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not web3.is_connected():
                return {
                    "anchored": False,
                    "status": "failed",
                    "failure_reason": "RPC endpoint unreachable.",
                }

            # Chain ID check before any read.
            on_chain_id = web3.eth.chain_id
            if on_chain_id != self.chain_id:
                return {
                    "anchored": False,
                    "status": "failed",
                    "failure_reason": (
                        f"Chain ID mismatch: expected {self.chain_id}, got {on_chain_id}."
                    ),
                }

            contract = web3.eth.contract(address=self.contract_address, abi=self._ABI)
            normalized = root_hash if root_hash.startswith("0x") else f"0x{root_hash}"
            root_bytes = bytes.fromhex(normalized[2:])

            is_anchored: bool = contract.functions.isAnchored(root_bytes).call()
            return {
                "anchored": is_anchored,
                "status": "anchored" if is_anchored else "not_anchored",
                "failure_reason": None,
            }

        except Exception as exc:
            return {
                "anchored": False,
                "status": "failed",
                "failure_reason": f"Verification query error: {type(exc).__name__}",
            }


def get_anchor_adapter() -> BaseAnchorAdapter:
    """Factory: return the appropriate adapter based on runtime configuration."""
    if (
        config.BLOCKCHAIN_ANCHORING_ENABLED
        and config.BLOCKCHAIN_RPC_URL
        and config.BLOCKCHAIN_CONTRACT_ADDRESS
    ):
        return PolygonAmoyAnchorAdapter()
    return NoopAnchorAdapter()
