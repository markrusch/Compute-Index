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


def latest_rate(conn: sqlite3.Connection) -> tuple[float, str] | None:
    row = conn.execute("SELECT eur_usd, date FROM fx ORDER BY date DESC LIMIT 1").fetchone()
    return (row["eur_usd"], row["date"]) if row else None
