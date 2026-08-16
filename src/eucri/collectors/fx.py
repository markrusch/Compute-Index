"""ECB EUR/USD reference rate via frankfurter.app (stored in the fx table, not observations)."""

from __future__ import annotations

import logging
import sqlite3

import requests

from eucri.collectors.base import TIMEOUT_SECONDS

log = logging.getLogger("eucri.collectors.fx")

# canonical host: frankfurter.app 301s to frankfurter.dev/v1 (verified 2026-07-18)
URL = "https://api.frankfurter.dev/v1/latest?from=EUR&to=USD"


def collect_fx(conn: sqlite3.Connection, session: requests.Session) -> bool:
    """Fetch and upsert the latest ECB EUR/USD rate. Fail-soft: returns False on error.

    frankfurter returns the most recent ECB business day; on weekends/holidays the
    recorded fx date is older than today — by design (METHODOLOGY.md §3.8).
    """
    try:
        resp = session.get(URL, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        rate = float(data["rates"]["USD"])
        date = str(data["date"])
    except Exception:
        log.exception("fx: fetch failed (fail-soft; will use last stored rate)")
        return False
    with conn:
        conn.execute(
            "INSERT INTO fx (date, eur_usd, source) VALUES (?, ?, 'ECB/frankfurter')"
            " ON CONFLICT(date) DO UPDATE SET eur_usd = excluded.eur_usd",
            (date, rate),
        )
    log.info("fx: EUR/USD %s (%s)", rate, date)
    return True


def rate_for(conn: sqlite3.Connection, on_date: str) -> tuple[float, str] | None:
    """Most recent ECB reference rate published on or before `on_date`.

    The date bound is the point. `ORDER BY date DESC LIMIT 1` with no bound returns the
    globally latest rate, which during a backfill is a rate published *after* the print —
    a look-ahead. Two 2026-07 prints were computed that way (fx_date 2026-07-21 on prints
    dated 07-18 and 07-19). Regression-tested in tests/test_fx_no_lookahead.py.

    The rate is therefore T-1 by construction on most days: the ECB publishes ~14:00 UTC,
    after the 11:00 UTC index cut-off. METHODOLOGY.md states the EUR leg as T-1 rather
    than pretending otherwise.
    """
    row = conn.execute(
        "SELECT eur_usd, date FROM fx WHERE date <= ? ORDER BY date DESC LIMIT 1",
        (on_date,),
    ).fetchone()
    return (row["eur_usd"], row["date"]) if row else None
