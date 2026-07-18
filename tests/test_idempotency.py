"""Daily runs are idempotent: re-running never duplicates data, recomputes add revisions."""

from __future__ import annotations

import sqlite3

import requests

from eucri.collectors import base
from eucri.commands import compute_all_series
from eucri.db import utc_now_iso
from eucri.models import Observation

DATE = "2026-07-18"


class _FiveProviderCollector:
    """Enough EU constituents to clear the >=5 publish gate."""

    name = "fake_market"

    def __init__(self) -> None:
        self.calls = 0

    def collect(self, session: requests.Session) -> list[Observation]:
        self.calls += 1
        return [
            Observation(
                ts_utc=utc_now_iso(), source=self.name, provider=f"prov{i}",
                gpu_model="H100_SXM", gpu_count=8, price_usd_per_gpu_hr=2.0 + i * 0.1,
                region=None, country="NL", interconnect="NVLink", tier="executable",
                term="on_demand", raw_json="{}",
            )
            for i in range(6)
        ]


def _count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


def test_collector_skipped_on_second_run(conn: sqlite3.Connection) -> None:
    collector = _FiveProviderCollector()
    assert base.run_collector(conn, collector, DATE) == "ok"
    n_obs = _count(conn, "observations")
    assert base.run_collector(conn, collector, DATE) == "skipped"
    assert collector.calls == 1
    assert _count(conn, "observations") == n_obs


def test_recompute_appends_revision_not_duplicate(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO fx (date, eur_usd, source) VALUES ('2026-07-17', 1.1435, 't')")
    base.run_collector(conn, _FiveProviderCollector(), DATE)

    compute_all_series(conn, DATE)
    compute_all_series(conn, DATE)

    revisions = conn.execute(
        "SELECT series, COUNT(*) AS n, MAX(revision) AS maxrev FROM daily_index"
        " WHERE date = ? GROUP BY series",
        (DATE,),
    ).fetchall()
    assert len(revisions) == 5  # headline, 7D, SOV, MKT, CLOUD
    for r in revisions:
        assert r["n"] == 2 and r["maxrev"] == 2  # two revisions, never edits

    head = conn.execute(
        "SELECT * FROM daily_index WHERE date = ? AND series = 'EU-CRI-H100'"
        " ORDER BY revision DESC LIMIT 1",
        (DATE,),
    ).fetchone()
    assert head["value_usd"] is not None
    assert head["n_sources"] == 6

    sov = conn.execute(
        "SELECT * FROM daily_index WHERE date = ? AND series = 'EU-CRI-H100-SOV'"
        " ORDER BY revision DESC LIMIT 1",
        (DATE,),
    ).fetchone()
    assert sov["value_usd"] is None  # fake providers are not in sovereign.yaml
    assert sov["flags"] == "insufficient_sources"
