"""Tests for the Phase 8 blockchain evidence anchoring."""
from __future__ import annotations

import pytest
from unittest import mock
from typing import Any

from app import config
from app.services.anchor_adapter import (
    BaseAnchorAdapter,
    NoopAnchorAdapter,
    PolygonAmoyAnchorAdapter,
    get_anchor_adapter,
)

# ---------------------------------------------------------------------------
# Test NoopAdapter / Disabled state
# ---------------------------------------------------------------------------

def test_noop_adapter_returns_unavailable() -> None:
    adapter = NoopAnchorAdapter()
    result = adapter.anchor_root("0x1234", "ev-01")
    assert result["status"] == "unavailable"
    assert "disabled or unavailable" in result["failure_reason"]
    
    verify_result = adapter.verify_anchor("0x1234")
    assert verify_result["anchored"] is False
    assert verify_result["status"] == "unavailable"

def test_get_anchor_adapter_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "BLOCKCHAIN_ANCHORING_ENABLED", False)
    adapter = get_anchor_adapter()
    assert isinstance(adapter, NoopAnchorAdapter)

def test_get_anchor_adapter_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "BLOCKCHAIN_ANCHORING_ENABLED", True)
    monkeypatch.setattr(config, "BLOCKCHAIN_RPC_URL", "")
    adapter = get_anchor_adapter()
    assert isinstance(adapter, NoopAnchorAdapter)

# ---------------------------------------------------------------------------
# Test PolygonAmoyAnchorAdapter
# ---------------------------------------------------------------------------

@pytest.fixture
def amoy_adapter(monkeypatch: pytest.MonkeyPatch) -> PolygonAmoyAnchorAdapter:
    monkeypatch.setattr(config, "BLOCKCHAIN_RPC_URL", "https://dummy.rpc")
    monkeypatch.setattr(config, "BLOCKCHAIN_CONTRACT_ADDRESS", "0xDummyContract")
    monkeypatch.setattr(config, "BLOCKCHAIN_PRIVATE_KEY", "0xDummyKey")
    monkeypatch.setattr(config, "BLOCKCHAIN_CHAIN_ID", 80002)
    return PolygonAmoyAnchorAdapter()

def test_amoy_adapter_missing_private_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "BLOCKCHAIN_RPC_URL", "https://dummy.rpc")
    monkeypatch.setattr(config, "BLOCKCHAIN_CONTRACT_ADDRESS", "0xDummyContract")
    monkeypatch.setattr(config, "BLOCKCHAIN_PRIVATE_KEY", "")
    adapter = PolygonAmoyAnchorAdapter()
    
    result = adapter.anchor_root("0x1234", "ev-01")
    assert result["status"] == "unavailable"
    assert "BLOCKCHAIN_PRIVATE_KEY is missing" in result["failure_reason"]

def test_amoy_adapter_invalid_root_hash(amoy_adapter: PolygonAmoyAnchorAdapter) -> None:
    # Too short
    result = amoy_adapter.anchor_root("0x123", "ev-01")
    assert result["status"] == "failed"
    assert "Invalid root hash" in result["failure_reason"]
    
    # Zero hash
    zero_hash = "0x" + "00" * 32
    result = amoy_adapter.anchor_root(zero_hash, "ev-01")
    assert result["status"] == "failed"
    assert "Zero root hash is not permitted" in result["failure_reason"]

@mock.patch("web3.Web3")
def test_amoy_adapter_rpc_unreachable(mock_web3_cls, amoy_adapter: PolygonAmoyAnchorAdapter) -> None:
    mock_web3 = mock.MagicMock()
    mock_web3.is_connected.return_value = False
    mock_web3_cls.return_value = mock_web3
    
    result = amoy_adapter.anchor_root("0x" + "aa" * 32, "ev-01")
    assert result["status"] == "unavailable"
    assert "unreachable" in result["failure_reason"]

@mock.patch("web3.Web3")
def test_amoy_adapter_chain_id_mismatch(mock_web3_cls, amoy_adapter: PolygonAmoyAnchorAdapter) -> None:
    mock_web3 = mock.MagicMock()
    mock_web3.is_connected.return_value = True
    mock_web3.eth.chain_id = 1  # Wrong chain ID
    mock_web3_cls.return_value = mock_web3
    
    result = amoy_adapter.anchor_root("0x" + "aa" * 32, "ev-01")
    assert result["status"] == "failed"
    assert "Chain ID mismatch" in result["failure_reason"]

@mock.patch("eth_account.Account.from_key")
@mock.patch("eth_account.Account.sign_transaction")
@mock.patch("web3.Web3")
def test_amoy_adapter_success(
    mock_web3_cls, mock_sign, mock_from_key, amoy_adapter: PolygonAmoyAnchorAdapter
) -> None:
    mock_web3 = mock.MagicMock()
    mock_web3.is_connected.return_value = True
    mock_web3.eth.chain_id = 80002
    mock_web3.to_hex.return_value = "0xTxHash"
    
    mock_receipt = mock.MagicMock()
    mock_receipt.status = 1
    mock_receipt.blockNumber = 12345
    mock_web3.eth.wait_for_transaction_receipt.return_value = mock_receipt
    
    mock_block = {"timestamp": 1600000000}
    mock_web3.eth.get_block.return_value = mock_block
    
    mock_web3_cls.return_value = mock_web3
    
    mock_contract = mock.MagicMock()
    mock_web3.eth.contract.return_value = mock_contract
    
    result = amoy_adapter.anchor_root("0x" + "aa" * 32, "ev-01")
    
    assert result["status"] == "anchored"
    assert result["tx_hash"] == "0xTxHash"
    assert result["block_number"] == 12345
    assert result["failure_reason"] is None

@mock.patch("web3.Web3")
def test_amoy_adapter_verify_success(mock_web3_cls, amoy_adapter: PolygonAmoyAnchorAdapter) -> None:
    mock_web3 = mock.MagicMock()
    mock_web3.is_connected.return_value = True
    mock_web3.eth.chain_id = 80002
    mock_web3_cls.return_value = mock_web3
    
    mock_contract = mock.MagicMock()
    mock_contract.functions.isAnchored.return_value.call.return_value = True
    mock_web3.eth.contract.return_value = mock_contract
    
    result = amoy_adapter.verify_anchor("0x" + "aa" * 32)
    assert result["anchored"] is True
    assert result["status"] == "anchored"
