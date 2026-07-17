"""Append-only guarantees are enforced by the database, not by convention."""

from __future__ import annotations

import sqlite3

import pytest

from eucri import db
from tests.conftest import insert_run


def _insert_observation(conn: sqlite3.Connection) -> None:
    insert_run(conn)
    conn.execute(
        "INSERT INTO observations (run_id, ts_utc, source, provider, gpu_model, gpu_count,"
        " price_usd_per_gpu_hr, country, tier, raw_json)"
        " VALUES ('r1', ?, 'test', 'prov', 'H100_SXM', 8, 2.0, 'NL', 'executable', '{}')",
        (db.utc_now_iso(),),
    )


def test_observations_reject_update(conn: sqlite3.Connection) -> None:
    _insert_observation(conn)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE observations SET price_usd_per_gpu_hr = 0")


def test_observations_reject_delete(conn: sqlite3.Connection) -> None:
    _insert_observation(conn)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM observations")


def test_daily_index_reject_update_and_delete(conn: sqlite3.Connection) -> None:
    insert_run(conn)
    conn.execute(
        "INSERT INTO daily_index (date, series, revision, value_usd, n_sources,"
        " n_executable, methodology_version, computed_at, run_id)"
        " VALUES ('2026-07-18', 'EU-CRI-H100', 1, 2.0, 6, 2, '0.1.0-dev', ?, 'r1')",
        (db.utc_now_iso(),),
    )
    with pytest.raises(sqlite3.IntegrityError, match="revision"):
        conn.execute("UPDATE daily_index SET value_usd = 99")
    with pytest.raises(sqlite3.IntegrityError, match="revision"):
        conn.execute("DELETE FROM daily_index")


def test_migrations_are_idempotent(conn: sqlite3.Connection) -> None:
    assert db.migrate(conn) == []  # conftest already migrated; second pass is a no-op
