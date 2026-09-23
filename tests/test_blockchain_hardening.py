"""Production blockchain hardening tests (Phase: forensic E2E fixes).

Covers:
  1. Private-key / contract-address configuration validation — field-specific,
     secret-free errors; whitespace trimming; optional 0x; exact 32-byte key;
     20-byte EIP-55 checksum address.
  2. Sanitized failure logging (never leaks the key or RPC credentials) with
     the improved "Blockchain anchor failed: <reason>" shape.
  3. AnchorRoot.owner() gate before LIVE anchorEvidence() submission:
     match / mismatch (BLOCKCHAIN_OWNER_MISMATCH, permanent) / query failure
     (blocked, retryable).
  4. Queue classification of permanent vs retryable failures.
  5. Canonical /forensics/register invokes anchorEvidence() — never the legacy
     anchor(); duplicate roots yield ONE queue entry; failed receipts never
     become CONFIRMED; DRY_RUN stays simulated; DISABLED stays unavailable.

No real network I/O: web3 / eth-account signing are mocked exactly as in
tests/test_blockchain_anchor.py.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

os.environ.setdefault("VOICETRUST_WS_JWT_SECRET", "test-secret-bchard-xyzzy")
os.environ.setdefault("VOICETRUST_DETECTOR_MODE", "mock")
os.environ.setdefault("HF_ZERO_GPU_SPACE", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eth_account import Account  # noqa: E402

from app import config  # noqa: E402
from app.services.anchor_adapter import (  # noqa: E402
    DryRunAnchorAdapter,
    NoopAnchorAdapter,
    PolygonAmoyAnchorAdapter,
    normalize_contract_address,
    normalize_private_key,
)
from app.services.anchor_queue import (  # noqa: E402
    CONFIRMED,
    FAILED,
    OFFLINE,
    PERMANENTLY_FAILED,
    _is_retryable_failure,
    _status_from_adapter,
)

# Valid-shape credentials for unit tests (network interaction fully mocked).
VALID_KEY = "0x" + "ab" * 32
VALID_ADDRESS = "0xcB5E4E1A318cE5dcaa2B483d020E42f7343cb987"  # prod Amoy AnchorRoot
VALID_ROOT = "0x" + "aa" * 32
SIGNER = Account.from_key(VALID_KEY).address  # deterministic from VALID_KEY


def _live_config(monkeypatch: pytest.MonkeyPatch, *, rpc_url: str | None = None) -> None:
    monkeypatch.setattr(config, "BLOCKCHAIN_RPC_URL", rpc_url or "https://dummy.rpc")
    monkeypatch.setattr(config, "BLOCKCHAIN_CONTRACT_ADDRESS", VALID_ADDRESS)
    monkeypatch.setattr(config, "BLOCKCHAIN_PRIVATE_KEY", VALID_KEY)
    monkeypatch.setattr(config, "BLOCKCHAIN_CHAIN_ID", 80002)
    monkeypatch.setattr(config, "BLOCKCHAIN_ANCHORING_ENABLED", True)
    monkeypatch.setattr(config, "BLOCKCHAIN_MODE", "LIVE")


def _mock_web3(mock_web3_cls, *, owner: str, receipt_status: int = 1):
    """Wire a fully mocked Web3 whose contract owner() returns *owner*."""
    w3 = mock.MagicMock()
    w3.is_connected.return_value = True
    w3.eth.chain_id = 80002
    w3.to_hex.return_value = "0xfeedbeef"
    receipt = mock.MagicMock()
    receipt.status = receipt_status
    receipt.blockNumber = 555
    w3.eth.wait_for_transaction_receipt.return_value = receipt
    w3.eth.get_block.return_value = {"timestamp": 1760000000}
    contract = mock.MagicMock()
    contract.functions.owner.return_value.call.return_value = owner
    w3.eth.contract.return_value = contract
    mock_web3_cls.return_value = w3
    return w3, contract


# ---------------------------------------------------------------------------
# 1. Private key validation
# ---------------------------------------------------------------------------


def test_private_key_valid_with_0x_prefix_and_whitespace():
    key, error = normalize_private_key("  " + VALID_KEY + "\r\n")
    assert error is None
    assert key == VALID_KEY  # normalized 0x-lowercase form


def test_private_key_valid_without_0x_prefix():
    key, error = normalize_private_key("ab" * 32)
    assert error is None
    assert key == "0x" + "ab" * 32


def test_private_key_invalid_hex_rejected():
    key, error = normalize_private_key("zz" * 32)
    assert key is None
    assert "hexadecimal" in error


def test_private_key_wrong_length_rejected():
    key, error = normalize_private_key("0x" + "ab" * 31)
    assert key is None
    assert "32 bytes" in error


# ---------------------------------------------------------------------------
# 7. Canonical /forensics/register -> anchorEvidence() (never legacy anchor())
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """Isolated-DB app client (never touches the developer's evidence store)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import models  # noqa: F401 - registers tables
    from app.db.database import Base, get_db
    from app.main import app

    db_path = tmp_path_factory.mktemp("blockchain-hardening") / "evidence.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False)

    def _override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _payload(evidence_id: str) -> dict:
    return {
        "schema_version": "phase7-v1",
        "evidence_type": "technical-integrity-evidence-package",
        "evidence_id": evidence_id,
        "session_id": evidence_id,
        "caller_id": "caller-hardening",
        "recipient_id": "bank-desk",
        "max_risk_score": 71,
        "final_status": "LOCK_VERIFY",
        "risk_events": [{"t": 2.0, "status": "WARN"}],
        "model_metadata": {"detector_mode": "mock"},
        "created_at": "2026-03-02T10:00:00+00:00",
    }


def test_canonical_register_calls_anchorEvidence_never_legacy_anchor(
    client, monkeypatch
):
    _live_config(monkeypatch)
    evidence_id = "SV-CANON-ANCHOR-1"
    with mock.patch(
        "app.services.merkle_evidence.get_anchor_adapter"
    ) as canonical_factory, mock.patch(
        "app.services.evidence_anchor.get_anchor_adapter"
    ) as legacy_factory:
        canonical = mock.MagicMock()
        canonical.anchor_evidence.return_value = {
            "status": "anchored",
            "network": config.BLOCKCHAIN_NETWORK,
            "contract_address": VALID_ADDRESS,
            "tx_hash": "0xc0ffee",
            "block_number": 987,
            "anchor_timestamp": datetime.now(timezone.utc),
            "evidence_id_bytes32": "0x" + "11" * 32,
            "failure_reason": None,
        }
        canonical_factory.return_value = canonical
        legacy_factory.return_value = mock.MagicMock()

        response = client.post(
            "/api/v1/forensics/register", json={"payload": _payload(evidence_id)}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    # anchorEvidence(canonical Merkle root, deterministic evidence id) — once.
    canonical.anchor_evidence.assert_called_once()
    root_arg, id_arg = canonical.anchor_evidence.call_args[0]
    assert root_arg == f"0x{body['canonical']['merkle_root']}"
    assert id_arg == evidence_id
    # Legacy flat-root anchor() must never run on the new forensic path.
    legacy_factory.return_value.anchor_root.assert_not_called()
    # Canonical outcome mirrored at the response level; queue confirms only
    # after a receipt-gated result.
    assert body["canonical"]["anchor"]["status"] == "anchored"
    assert body["anchor_status"] == "anchored"
    assert body["canonical"]["queue_status"]["queue_status"] == CONFIRMED
    assert body["canonical"]["anchor"]["tx_hash"] == "0xc0ffee"


def test_duplicate_roots_produce_exactly_one_queue_entry(tmp_path, monkeypatch):
    """Same item bytes under two evidence ids -> same root -> ONE queue row.

    (On-chain duplicate-root replay is additionally rejected by AnchorRoot
    itself; here the queue's root-level idempotency is what must hold.)
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.db import models as db_models
    from app.db import models  # noqa: F401 - registers tables
    from app.db.database import Base
    from app.services.merkle_evidence import MerkleEvidenceService

    _live_config(monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path}/duproot.db")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    items = {"audio": b"identical-item-bytes"}
    with mock.patch("app.services.merkle_evidence.get_anchor_adapter") as factory:
        adapter = mock.MagicMock()
        adapter.anchor_evidence.return_value = {
            "status": "anchored",
            "network": config.BLOCKCHAIN_NETWORK,
            "contract_address": VALID_ADDRESS,
            "tx_hash": "0xdup1",
            "block_number": 1,
            "anchor_timestamp": datetime.now(timezone.utc),
            "failure_reason": None,
        }
        factory.return_value = adapter
        first = MerkleEvidenceService(session).register_merkle_package(
            items=items, evidence_id="SV-DUPROOT-A"
        )
        second = MerkleEvidenceService(session).register_merkle_package(
            items=items, evidence_id="SV-DUPROOT-B"
        )
    assert first["status"] == "ok" and second["status"] == "ok"
    assert first["merkle_root"] == second["merkle_root"]
    rows = (
        session.query(db_models.AnchorQueueEntry)
        .filter(db_models.AnchorQueueEntry.root_hash == first["merkle_root"])
        .all()
    )
    assert len(rows) == 1
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# 5. AnchorRoot.owner() gate before LIVE anchorEvidence()
# ---------------------------------------------------------------------------


@mock.patch("eth_account.Account.sign_transaction")
@mock.patch("web3.Web3")
def test_owner_match_allows_live_submission(mock_web3_cls, mock_sign, monkeypatch):
    _live_config(monkeypatch)
    w3, contract = _mock_web3(mock_web3_cls, owner=SIGNER)
    adapter = PolygonAmoyAnchorAdapter()
    result = adapter.anchor_evidence(VALID_ROOT, "EV-OWNER-OK")
    assert result["status"] == "anchored"
    assert result["tx_hash"] == "0xfeedbeef"
    assert result["block_number"] == 555
    contract.functions.owner.return_value.call.assert_called()
    w3.eth.send_raw_transaction.assert_called_once()


@mock.patch("eth_account.Account.sign_transaction")
@mock.patch("web3.Web3")
def test_owner_mismatch_blocks_submission_permanently(
    mock_web3_cls, mock_sign, monkeypatch
):
    _live_config(monkeypatch)
    w3, contract = _mock_web3(mock_web3_cls, owner="0x" + "22" * 20)
    adapter = PolygonAmoyAnchorAdapter()
    result = adapter.anchor_evidence(VALID_ROOT, "EV-OWNER-BAD")
    assert result["status"] == "failed"
    assert result["error_code"] == "BLOCKCHAIN_OWNER_MISMATCH"
    reason = result["failure_reason"]
    assert "BLOCKCHAIN_OWNER_MISMATCH" in reason
    assert SIGNER.lower() in reason.lower()  # public diagnostics only
    assert VALID_KEY not in str(result)  # key never exposed
    # No transaction is built or broadcast on mismatch.
    w3.eth.get_transaction_count.assert_not_called()
    w3.eth.send_raw_transaction.assert_not_called()
    mock_sign.assert_not_called()
    # Permanent: retrying cannot change the wallet/owner relationship.
    assert _is_retryable_failure(reason) is False
    assert _status_from_adapter(result) == PERMANENTLY_FAILED


@mock.patch("eth_account.Account.sign_transaction")
@mock.patch("web3.Web3")
def test_owner_query_failure_blocks_submission_but_stays_retryable(
    mock_web3_cls, mock_sign, monkeypatch
):
    _live_config(monkeypatch)
    w3, contract = _mock_web3(mock_web3_cls, owner=SIGNER)
    contract.functions.owner.return_value.call.side_effect = ValueError(
        "view call failed"
    )
    adapter = PolygonAmoyAnchorAdapter()
    result = adapter.anchor_evidence(VALID_ROOT, "EV-OWNER-QFAIL")
    assert result["status"] == "failed"
    assert "Owner verification query failed" in result["failure_reason"]
    assert result.get("error_code") is None
    w3.eth.send_raw_transaction.assert_not_called()
    assert _is_retryable_failure(result["failure_reason"]) is True
    assert _status_from_adapter(result) == FAILED


# ---------------------------------------------------------------------------
# 6. Queue classification + mode semantics
# ---------------------------------------------------------------------------


def test_permanent_failure_classification():
    assert (
        _is_retryable_failure(
            "Configuration error in VOICETRUST_BLOCKCHAIN_PRIVATE_KEY: "
            "must decode to exactly 32 bytes."
        )
        is False
    )
    assert (
        _is_retryable_failure(
            "BLOCKCHAIN_OWNER_MISMATCH: signing address 0xabc is not the "
            "AnchorRoot owner 0xdef."
        )
        is False
    )
    assert _status_from_adapter(
        {
            "status": "failed",
            "failure_reason": "Configuration error in VOICETRUST_BLOCKCHAIN_CONTRACT_ADDRESS: bad",
        }
    ) == PERMANENTLY_FAILED
    assert _status_from_adapter(
        {"status": "failed", "failure_reason": "BLOCKCHAIN_OWNER_MISMATCH: ..."}
    ) == PERMANENTLY_FAILED
    # Transient failures remain retryable.
    assert (
        _is_retryable_failure("Owner verification query failed (ValueError): boom")
        is True
    )


@mock.patch("eth_account.Account.sign_transaction")
@mock.patch("web3.Web3")
def test_failed_receipt_never_becomes_confirmed(
    mock_web3_cls, mock_sign, monkeypatch
):
    _live_config(monkeypatch)
    _mock_web3(mock_web3_cls, owner=SIGNER, receipt_status=0)
    adapter = PolygonAmoyAnchorAdapter()
    result = adapter.anchor_evidence(VALID_ROOT, "EV-RECEIPT-0")
    assert result["status"] == "failed"
    assert "status=0" in result["failure_reason"]
    assert _status_from_adapter(result) == FAILED
    assert _status_from_adapter(result) != CONFIRMED


def test_dry_run_is_simulated_and_never_confirmed():
    result = DryRunAnchorAdapter().anchor_root(VALID_ROOT, "EV-DRY")
    assert result["status"] == "dry_run"
    assert result["simulated"] is True
    assert result["block_number"] is None
    assert _status_from_adapter(result) == OFFLINE  # never CONFIRMED
    assert DryRunAnchorAdapter().verify_anchor(VALID_ROOT)["anchored"] is False


def test_disabled_is_unavailable_and_submits_nothing():
    result = NoopAnchorAdapter().anchor_evidence(VALID_ROOT, "EV-OFF")
    assert result["status"] == "unavailable"
    assert result["tx_hash"] is None
    assert _status_from_adapter(result) == OFFLINE


# ---------------------------------------------------------------------------
# 2. Contract address validation
# ---------------------------------------------------------------------------


def test_contract_address_valid_checksum_roundtrips():
    address, error = normalize_contract_address(VALID_ADDRESS)
    assert error is None
    assert address == VALID_ADDRESS  # already valid EIP-55


def test_contract_address_dirty_whitespace_is_trimmed_and_checksummed():
    address, error = normalize_contract_address("  " + VALID_ADDRESS.lower() + " \n")
    assert error is None
    assert address == VALID_ADDRESS  # checksummed from lowercase input


def test_contract_address_invalid_rejected():
    short, error = normalize_contract_address("0x1234")
    assert short is None
    assert "20-byte" in error
    junk, error = normalize_contract_address("not-an-address")
    assert junk is None
    assert "20-byte" in error


# ---------------------------------------------------------------------------
# 3. Adapter surfaces field-specific configuration errors (no secrets)
# ---------------------------------------------------------------------------


def test_wrong_length_key_fails_with_named_field_and_never_leaks(monkeypatch, caplog):
    monkeypatch.setattr(config, "BLOCKCHAIN_RPC_URL", "https://dummy.rpc")
    monkeypatch.setattr(config, "BLOCKCHAIN_CONTRACT_ADDRESS", VALID_ADDRESS)
    bad_key = "ab" * 31
    monkeypatch.setattr(config, "BLOCKCHAIN_PRIVATE_KEY", bad_key)
    adapter = PolygonAmoyAnchorAdapter()
    with caplog.at_level(logging.WARNING, logger="satyavoice.anchor"):
        result = adapter.anchor_evidence(VALID_ROOT, "EV-BADKEY")
    assert result["status"] == "failed"
    assert (
        "Configuration error in VOICETRUST_BLOCKCHAIN_PRIVATE_KEY"
        in result["failure_reason"]
    )
    assert "32 bytes" in result["failure_reason"]
    assert bad_key not in result["failure_reason"]
    # Improved log shape: "Blockchain anchor failed ...: <field-specific reason>"
    assert "Blockchain anchor failed" in caplog.text
    assert "VOICETRUST_BLOCKCHAIN_PRIVATE_KEY" in caplog.text
    assert bad_key not in caplog.text  # NEVER log the key value


def test_invalid_contract_address_fails_with_named_field(monkeypatch, caplog):
    monkeypatch.setattr(config, "BLOCKCHAIN_RPC_URL", "https://dummy.rpc")
    monkeypatch.setattr(config, "BLOCKCHAIN_PRIVATE_KEY", VALID_KEY)
    monkeypatch.setattr(config, "BLOCKCHAIN_CONTRACT_ADDRESS", "0x1234")
    adapter = PolygonAmoyAnchorAdapter()
    with caplog.at_level(logging.WARNING, logger="satyavoice.anchor"):
        result = adapter.anchor_root(VALID_ROOT, "EV-BADADDR")
    assert result["status"] == "failed"
    assert (
        "Configuration error in VOICETRUST_BLOCKCHAIN_CONTRACT_ADDRESS"
        in result["failure_reason"]
    )
    assert "Blockchain anchor failed" in caplog.text


def test_missing_key_still_reports_missing_not_invalid(monkeypatch):
    monkeypatch.setattr(config, "BLOCKCHAIN_RPC_URL", "https://dummy.rpc")
    monkeypatch.setattr(config, "BLOCKCHAIN_CONTRACT_ADDRESS", VALID_ADDRESS)
    monkeypatch.setattr(config, "BLOCKCHAIN_PRIVATE_KEY", "")
    adapter = PolygonAmoyAnchorAdapter()
    result = adapter.anchor_evidence(VALID_ROOT, "EV-NOKEY")
    assert result["status"] == "unavailable"
    assert "BLOCKCHAIN_PRIVATE_KEY is missing" in result["failure_reason"]


# ---------------------------------------------------------------------------
# 4. Sanitized failure logging (key + RPC credentials never leave the process)
# ---------------------------------------------------------------------------


@mock.patch("web3.Web3")
def test_exception_diagnostics_are_sanitized(mock_web3_cls, monkeypatch, caplog):
    rpc = "https://secretuser:supersecret@rpc.example.invalid/v2/APIKEYVALUE"
    _live_config(monkeypatch, rpc_url=rpc)
    w3, contract = _mock_web3(mock_web3_cls, owner=SIGNER)
    w3.eth.get_transaction_count.side_effect = ValueError(
        f"node rejected key {VALID_KEY} via {rpc}"
    )
    adapter = PolygonAmoyAnchorAdapter()
    with caplog.at_level(logging.WARNING, logger="satyavoice.anchor"):
        result = adapter.anchor_evidence(VALID_ROOT, "EV-SANITIZE")
    assert result["status"] == "failed"
    assert "ValueError" in caplog.text
    assert VALID_KEY not in caplog.text
    assert "supersecret" not in caplog.text
    assert "APIKEYVALUE" not in caplog.text
    assert "[REDACTED]" in caplog.text
    # The stored failure_reason is sanitized too.
    assert VALID_KEY not in result["failure_reason"]
    assert "supersecret" not in result["failure_reason"]