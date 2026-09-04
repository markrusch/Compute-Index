# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""SQLite connection and migrations.

Raw tables (observations, daily_index) are append-only, enforced by triggers
created in the migrations — corrections happen as new revisions, never edits.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "eucri.db"

_MIGRATION_RE = re.compile(r"^(\d{4})_.+\.sql$")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _migration_files() -> list[tuple[int, str, str]]:
    """Return (number, name, sql) for bundled migrations, sorted."""
    out = []
    for entry in resources.files("eucri.migrations").iterdir():
        m = _MIGRATION_RE.match(entry.name)
        if m:
            out.append((int(m.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    return sorted(out)


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations; returns the names applied. Idempotent."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, applied_utc TEXT NOT NULL)"
    )
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied = []
    for number, name, sql in _migration_files():
        if name in done:
            continue
        with conn:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (id, name, applied_utc) VALUES (?, ?, ?)",
                (number, name, utc_now_iso()),
            )
        applied.append(name)
    return applied
