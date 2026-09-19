#!/usr/bin/env python
"""One-time Alembic baseline detection for pre-existing databases.

WHY THIS EXISTS
  The production database was originally bootstrapped with
  Base.metadata.create_all() (app/db/database.py), which creates the current
  ORM schema WITHOUT writing an ``alembic_version`` marker. A plain
  ``alembic upgrade head`` against such a database fails immediately with
  "table already exists", because revision 0001 re-creates existing tables.

  The naive fix — an UNCONDITIONAL ``alembic stamp 0001`` on every boot — is
  also wrong: it resets the version marker on every deploy, forcing revisions
  0002/0003 to re-run. Revision 0003 uses ``op.create_table``, so the SECOND
  boot crashes with "table already exists" and the container crash-loops.

  The correct procedure stamps ONCE, only when needed, choosing the revision
  that matches what the schema actually contains:

    alembic_version table exists            -> stamp nothing (normal flow)
    schema already at head (0003 tables)    -> stamp head
    0001-era tables present, 0003 missing   -> stamp 0001 (0002/0003 then run)
    empty database                          -> stamp nothing (0001..0003 run)

  The result is idempotent: safe on the first boot and on every boot after.

CREDENTIAL SAFETY
  The database URL is never printed or logged. Only table-presence decisions
  are emitted to stdout.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy import create_engine, inspect

# Repository root (this file lives in scripts/). Alembic must run with the
# root as its working directory so alembic.ini and alembic/env.py resolve.
ROOT = Path(__file__).resolve().parent.parent

# Tables whose presence identifies how far the existing schema has progressed.
# evidence_merkle_packages is created by revision 0003 (current head);
# sessions/risk_events are created by revision 0001 (and by create_all).
HEAD_SENTINEL_TABLES = ("evidence_merkle_packages", "anchor_queue_entries")
BASE_SENTINEL_TABLES = ("sessions", "risk_events")


def decide_initial_stamp(inspector) -> Tuple[Optional[str], str]:
    """Return (revision_to_stamp_or_None, human_reason)."""
    tables = set(inspector.get_table_names())

    if "alembic_version" in tables:
        return None, "alembic_version present; database already versioned"

    if all(name in tables for name in HEAD_SENTINEL_TABLES):
        return "head", "schema already contains head-revision tables; baselining at head"

    if all(name in tables for name in BASE_SENTINEL_TABLES):
        return (
            "0001",
            "0001-era schema without version marker; baselining at 0001 "
            "so 0002/0003 apply once",
        )

    return None, "no application tables found; fresh database, 0001..0003 will create everything"


def main() -> int:
    url = os.getenv("VOICETRUST_DATABASE_URL", "sqlite:///./satyavoice.db")
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    engine = create_engine(url, connect_args=connect_args)
    try:
        stamp, reason = decide_initial_stamp(inspect(engine))
    finally:
        engine.dispose()

    print(f"alembic-bootstrap: {reason}")

    if stamp is None:
        return 0

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "stamp", stamp],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        print("alembic-bootstrap: stamp failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
