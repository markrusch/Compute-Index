# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Collector infrastructure: polite HTTP, fail-soft execution, per-day idempotency.

Rules (SOURCES.md): 1 request per source per day, honest User-Agent, 30s timeout,
and a collector failure is logged and skipped — it never blocks the run and never
fabricates data.
"""

from __future__ import annotations

import logging
import sqlite3
import uuid
from typing import Protocol

import requests

from eucri import USER_AGENT
from eucri.db import utc_now_iso
from eucri.models import Observation

log = logging.getLogger("eucri.collectors")

TIMEOUT_SECONDS = 30


class Collector(Protocol):
    name: str

    def collect(self, session: requests.Session) -> list[Observation]: ...


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def has_ok_run(conn: sqlite3.Connection, source: str, utc_date: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM runs WHERE utc_date = ? AND source = ? AND status = 'ok' LIMIT 1",
        (utc_date, source),
    ).fetchone()
    return row is not None


def run_collector(
    conn: sqlite3.Connection,
    collector: Collector,
    utc_date: str,
    session: requests.Session | None = None,
) -> str:
    """Run one collector fail-soft; returns the resulting run status.

    Skips (idempotency) if an 'ok' run already exists for (source, utc_date).
    Observations are inserted in the same transaction as the run row update.
    """
    if has_ok_run(conn, collector.name, utc_date):
        log.info("%s: already collected for %s, skipping", collector.name, utc_date)
        return "skipped"

    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO runs (run_id, utc_date, source, started_utc, status)"
        " VALUES (?, ?, ?, ?, 'running')",
        (run_id, utc_date, collector.name, utc_now_iso()),
    )
    conn.commit()
    try:
        observations = collector.collect(session or make_session())
    except Exception:
        log.exception("%s: collection failed (fail-soft, continuing)", collector.name)
        with conn:
            conn.execute(
                "UPDATE runs SET status = 'failed', finished_utc = ? WHERE run_id = ?",
                (utc_now_iso(), run_id),
            )
        return "failed"

    with conn:
        conn.executemany(
            "INSERT INTO observations (run_id, ts_utc, source, provider, gpu_model,"
            " gpu_count, price_usd_per_gpu_hr, region, country, interconnect, tier,"
            " term, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id, o.ts_utc, o.source, o.provider, o.gpu_model, o.gpu_count,
                    o.price_usd_per_gpu_hr, o.region, o.country, o.interconnect,
                    o.tier, o.term, o.raw_json,
                )
                for o in observations
            ],
        )
        conn.execute(
            "UPDATE runs SET status = 'ok', finished_utc = ?, notes = ? WHERE run_id = ?",
            (utc_now_iso(), f"{len(observations)} observations", run_id),
        )
    log.info("%s: %d observations", collector.name, len(observations))
    return "ok"
