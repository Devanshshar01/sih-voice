#!/usr/bin/env python3
"""Independent evidence verification CLI (SIH forensic layer).

Verifies, without trusting any per-package bookkeeping:
  1. evidence hash  — SHA-256 of the stored canonical package payload
  2. ledger chain   — full append-only walk from GENESIS (global, all packages)
  3. blockchain anchor — read-only on-chain confirmation when configured

Usage:
  python scripts/verify_evidence.py                # full ledger + all packages
  python scripts/verify_evidence.py <evidence_id>  # one package in detail
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.db import models as db_models  # noqa: E402
from app.db.database import SessionLocal  # noqa: E402
from app.services.evidence_anchor import EvidenceAnchorService  # noqa: E402


def _verify_evidence_hash(package) -> bool:
    """Recompute the package hash straight from its canonical payload."""
    recomputed = hashlib.sha256(package.package_payload.encode("utf-8")).hexdigest()
    return recomputed == package.evidence_hash


def main() -> int:
    args = sys.argv[1:]
    db = SessionLocal()
    try:
        service = EvidenceAnchorService(db)

        chain = service.verify_full_chain()
        print("== LEDGER CHAIN ==")
        print(f"  records       : {chain['record_count']}")
        print(f"  integrity     : {'VERIFIED' if chain['integrity'] else 'BROKEN'}")
        if chain["integrity"]:
            print(f"  chain tip     : {chain['chain_tip']}")
        else:
            print(f"  broken at     : record {chain['broken_at_record']}")
            print(f"  reason        : {chain['reason']}")

        query = db.query(db_models.EvidencePackage)
        if args:
            query = query.filter(db_models.EvidencePackage.evidence_id == args[0])
        packages = query.all()
        if args and not packages:
            print(f"\nERROR: evidence package '{args[0]}' not found.")
            return 1

        print("\n== EVIDENCE PACKAGES ==")
        all_ok = chain["integrity"]
        for package in packages:
            verification = service.verify_evidence_package(package.evidence_id)
            ok = (
                _verify_evidence_hash(package)
                and verification["evidence_hash_integrity"]
                and verification["local_chain_integrity"]
            )
            all_ok = all_ok and ok
            print(f"\n  {package.evidence_id}")
            print(f"    evidence hash  : {_fmt_hash(package.evidence_hash)} {'OK' if verification['evidence_hash_integrity'] else 'MISMATCH'}")
            print(f"    chain root     : {_fmt_hash(package.local_chain_root)} {'OK' if verification['local_chain_integrity'] else 'MISMATCH'}")
            print(f"    anchor status  : {verification['anchor_status']}")
            if verification["anchor_status"] == "anchored":
                print(f"    tx hash        : {verification['tx_hash']}")

            # Independent on-chain confirmation when configured.
            if config.BLOCKCHAIN_ANCHORING_ENABLED and verification["local_chain_root"]:
                from app.services.anchor_adapter import get_anchor_adapter

                result = get_anchor_adapter().verify_root(verification["local_chain_root"])
                print(f"    on-chain check : {'CONFIRMED' if result.get('verified') else 'NOT CONFIRMED'}")
                if not result.get("verified"):
                    print(f"      ({result.get('failure_reason')})")
                all_ok = all_ok and bool(result.get("verified"))

        print("\n" + ("ALL CHECKS PASSED" if all_ok else "INTEGRITY FAILURES DETECTED"))
        return 0 if all_ok else 2
    finally:
        db.close()


def _fmt_hash(value: str | None) -> str:
    if not value:
        return "-"
    return value if len(value) <= 24 else f"{value[:16]}...{value[-8:]}"


if __name__ == "__main__":
    raise SystemExit(main())
