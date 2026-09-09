"""Blockchain anchoring adapters for the Phase 8 hybrid evidence layer.

This module keeps public-chain integration isolated from the rest of the
application. The default adapter intentionally degrades to a local/demo-safe
unavailable state when Polygon Amoy or the required runtime support is not
configured, so evidence generation and local verification remain functional.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app import config


class BaseAnchorAdapter:
    def anchor_root(self, root_hash: str, evidence_id: str) -> dict[str, Any]:
        raise NotImplementedError


class NoopAnchorAdapter(BaseAnchorAdapter):
    def anchor_root(self, root_hash: str, evidence_id: str) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "network": config.BLOCKCHAIN_NETWORK,
            "contract_address": config.BLOCKCHAIN_CONTRACT_ADDRESS,
            "tx_hash": None,
            "block_number": None,
            "anchor_timestamp": None,
            "failure_reason": (
                "Polygon Amoy anchoring is disabled or unavailable; local forensic evidence remains available."
            ),
        }


class PolygonAmoyAnchorAdapter(BaseAnchorAdapter):
    def __init__(self) -> None:
        self.rpc_url = config.BLOCKCHAIN_RPC_URL
        self.contract_address = config.BLOCKCHAIN_CONTRACT_ADDRESS
        self.private_key = config.BLOCKCHAIN_PRIVATE_KEY
        self.chain_id = config.BLOCKCHAIN_CHAIN_ID
        self.gas_limit = config.BLOCKCHAIN_GAS_LIMIT
        self.abi = [
            {
                "inputs": [{"internalType": "bytes32", "name": "rootHash", "type": "bytes32"}],
                "name": "anchor",
                "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
                "stateMutability": "nonpayable",
                "type": "function",
            }
        ]

    def anchor_root(self, root_hash: str, evidence_id: str) -> dict[str, Any]:
        if not self.rpc_url or not self.contract_address:
            return {
                "status": "unavailable",
                "network": config.BLOCKCHAIN_NETWORK,
                "contract_address": self.contract_address,
                "tx_hash": None,
                "block_number": None,
                "anchor_timestamp": None,
                "failure_reason": "Polygon Amoy RPC URL or contract address is not configured.",
            }

        if not self.private_key:
            return {
                "status": "unavailable",
                "network": config.BLOCKCHAIN_NETWORK,
                "contract_address": self.contract_address,
                "tx_hash": None,
                "block_number": None,
                "anchor_timestamp": None,
                "failure_reason": (
                    "Polygon Amoy is configured, but BLOCKCHAIN_PRIVATE_KEY is missing. "
                    "Local forensic evidence remains available without public-chain anchoring."
                ),
            }

        try:
            from eth_account import Account
            from web3 import Web3
            from web3.exceptions import ContractLogicError
        except Exception as exc:  # pragma: no cover - runtime dependency guard
            return {
                "status": "unavailable",
                "network": config.BLOCKCHAIN_NETWORK,
                "contract_address": self.contract_address,
                "tx_hash": None,
                "block_number": None,
                "anchor_timestamp": None,
                "failure_reason": f"web3 runtime dependencies are not installed: {exc}",
            }

        try:
            normalized_root = root_hash if root_hash.startswith("0x") else f"0x{root_hash}"
            if len(normalized_root) != 66:
                raise ValueError(
                    f"Expected a 32-byte root hash in hex format, received '{root_hash}'."
                )

            web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not web3.is_connected():
                return {
                    "status": "unavailable",
                    "network": config.BLOCKCHAIN_NETWORK,
                    "contract_address": self.contract_address,
                    "tx_hash": None,
                    "block_number": None,
                    "anchor_timestamp": None,
                    "failure_reason": "Polygon Amoy RPC endpoint is unreachable.",
                }

            account = Account.from_key(self.private_key)
            contract = web3.eth.contract(address=self.contract_address, abi=self.abi)

            nonce = web3.eth.get_transaction_count(account.address)
            tx = contract.functions.anchor(normalized_root).build_transaction(
                {
                    "from": account.address,
                    "nonce": nonce,
                    "gas": self.gas_limit,
                    "gasPrice": web3.eth.gas_price,
                    "chainId": web3.eth.chain_id,
                }
            )
            signed_tx = Account.sign_transaction(tx, private_key=self.private_key)
            tx_hash = web3.eth.send_raw_transaction(signed_tx.raw_transaction)
            receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

            if receipt.status != 1:
                return {
                    "status": "failed",
                    "network": config.BLOCKCHAIN_NETWORK,
                    "contract_address": self.contract_address,
                    "tx_hash": web3.to_hex(tx_hash),
                    "block_number": receipt.blockNumber,
                    "anchor_timestamp": None,
                    "failure_reason": "Polygon Amoy transaction was mined but returned a failed status.",
                }

            block = web3.eth.get_block(receipt.blockNumber)
            block_timestamp = datetime.fromtimestamp(block["timestamp"], timezone.utc)

            return {
                "status": "anchored",
                "network": config.BLOCKCHAIN_NETWORK,
                "contract_address": self.contract_address,
                "tx_hash": web3.to_hex(tx_hash),
                "block_number": receipt.blockNumber,
                "anchor_timestamp": block_timestamp,
                "failure_reason": None,
            }
        except ContractLogicError as exc:
            return {
                "status": "failed",
                "network": config.BLOCKCHAIN_NETWORK,
                "contract_address": self.contract_address,
                "tx_hash": None,
                "block_number": None,
                "anchor_timestamp": None,
                "failure_reason": f"Polygon Amoy contract reverted: {exc}",
            }
        except Exception as exc:
            return {
                "status": "failed",
                "network": config.BLOCKCHAIN_NETWORK,
                "contract_address": self.contract_address,
                "tx_hash": None,
                "block_number": None,
                "anchor_timestamp": None,
                "failure_reason": f"Polygon Amoy submission failed: {exc}",
            }


def get_anchor_adapter() -> BaseAnchorAdapter:
    if config.BLOCKCHAIN_ANCHORING_ENABLED and config.BLOCKCHAIN_RPC_URL and config.BLOCKCHAIN_CONTRACT_ADDRESS:
        return PolygonAmoyAnchorAdapter()
    return NoopAnchorAdapter()
