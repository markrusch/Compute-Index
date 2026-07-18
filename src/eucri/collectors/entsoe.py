"""ENTSO-E Transparency day-ahead prices — overlay data ONLY, never an index input.

Requires a free ENTSOE_TOKEN (env var or .env). Skips cleanly when absent.
Stored in overlay_power, a table the index calculation never reads.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

import requests

from eucri.collectors.base import TIMEOUT_SECONDS

log = logging.getLogger("eucri.collectors.entsoe")

URL = "https://web-api.tp.entsoe.eu/api"

ZONES = {
    "NL": "10YNL----------L",
    "DE-LU": "10Y1001A1001A82H",
    "FR": "10YFR-RTE------C",
    "SE3": "10Y1001A1001A46L",
}


def _token() -> str | None:
    token = os.environ.get("ENTSOE_TOKEN")
    if token:
        return token
    env_file = Path(__file__).resolve().parents[3] / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("ENTSOE_TOKEN=") and line.split("=", 1)[1].strip():
                return line.split("=", 1)[1].strip()
    return None


def _day_ahead_avg(session: requests.Session, token: str, eic: str, utc_date: str) -> float | None:
    start = datetime.strptime(utc_date, "%Y-%m-%d")
    params = {
        "documentType": "A44",
        "in_Domain": eic,
        "out_Domain": eic,
        "periodStart": start.strftime("%Y%m%d0000"),
        "periodEnd": (start + timedelta(days=1)).strftime("%Y%m%d0000"),
        "securityToken": token,
    }
    resp = session.get(URL, params=params, timeout=TIMEOUT_SECONDS)
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    prices = [
        float(el.text)
        for el in root.iter()
        if el.tag.endswith("price.amount") and el.text
    ]
    return sum(prices) / len(prices) if prices else None


def collect_overlay(conn: sqlite3.Connection, session: requests.Session, utc_date: str) -> bool:
    """Fail-soft; returns False when skipped or failed entirely."""
    token = _token()
    if not token:
        log.info("entsoe: no ENTSOE_TOKEN set, overlay skipped (by design)")
        return False
    stored = 0
    for zone, eic in ZONES.items():
        try:
            avg = _day_ahead_avg(session, token, eic, utc_date)
        except Exception:
            log.exception("entsoe %s: failed (fail-soft)", zone)
            continue
        if avg is None:
            log.warning("entsoe %s: no prices for %s", zone, utc_date)
            continue
        with conn:
            conn.execute(
                "INSERT INTO overlay_power (date, zone, avg_price_eur_mwh, raw_json)"
                " VALUES (?, ?, ?, ?) ON CONFLICT(date, zone) DO UPDATE SET"
                " avg_price_eur_mwh = excluded.avg_price_eur_mwh",
                (utc_date, zone, avg, json.dumps({"eic": eic, "doc": "A44"})),
            )
        stored += 1
    log.info("entsoe: %d/%d zones stored for %s", stored, len(ZONES), utc_date)
    return stored > 0
