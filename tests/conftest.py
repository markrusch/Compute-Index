from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from eucri import db


@pytest.fixture()
def conn(tmp_path: Path) -> sqlite3.Connection:
    c = db.connect(tmp_path / "test.db")
    db.migrate(c)
    return c


def insert_run(c: sqlite3.Connection, run_id: str = "r1", utc_date: str = "2026-07-18",
               source: str = "test") -> str:
    c.execute(
        "INSERT INTO runs (run_id, utc_date, source, started_utc, status) "
        "VALUES (?, ?, ?, ?, 'ok')",
        (run_id, utc_date, source, db.utc_now_iso()),
    )
    return run_id
