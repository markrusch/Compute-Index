# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Dropout sensitivity on a controlled dataset."""

from __future__ import annotations

import sqlite3

import requests

from eucri.collectors import base
from eucri.db import utc_now_iso
from eucri.models import Observation
from eucri.validate import dropout_sensitivity

DATE = "2026-07-18"


class _SourceCollector:
    def __init__(self, name: str, providers: list[tuple[str, float]]) -> None:
        self.name = name
        self._providers = providers

    def collect(self, session: requests.Session) -> list[Observation]:
        return [
            Observation(
                ts_utc=utc_now_iso(), source=self.name, provider=provider,
                gpu_model="H100_SXM", gpu_count=8, price_usd_per_gpu_hr=price,
                region=None, country="NL", interconnect="NVLink", tier="list",
                term="on_demand", raw_json="{}",
            )
            for provider, price in self._providers
        ]


def test_dropout_sensitivity(conn: sqlite3.Connection) -> None:
    base.run_collector(
        conn, _SourceCollector("src_a", [("a1", 2.0), ("a2", 2.2), ("a3", 2.4)]), DATE
    )
    base.run_collector(
        conn, _SourceCollector("src_b", [("b1", 2.6), ("b2", 2.8), ("b3", 3.0)]), DATE
    )
    results = dropout_sensitivity(conn, DATE)
    by_source = {r["source"]: r for r in results}
    assert set(by_source) == {"src_a", "src_b"}
    # equal weights: base median (6 providers) = 3rd price = 2.4
    assert by_source["src_a"]["base"] == 2.4
    # dropping either source leaves 3 providers < min 5 -> the print gaps, honestly
    assert by_source["src_a"]["without"] is None
    assert by_source["src_a"]["deviation_pct"] is None


def test_dropout_deviation_computed(conn: sqlite3.Connection) -> None:
    base.run_collector(
        conn,
        _SourceCollector(
            "src_big",
            [("p1", 2.0), ("p2", 2.2), ("p3", 2.4), ("p4", 2.6), ("p5", 2.8), ("p6", 3.0)],
        ),
        DATE,
    )
    base.run_collector(conn, _SourceCollector("src_high", [("hx", 9.0)]), DATE)
    results = {r["source"]: r for r in dropout_sensitivity(conn, DATE)}
    # 7 providers, equal weight: median = 4th = 2.6; without src_high: 6 -> 3rd = 2.4
    assert results["src_high"]["base"] == 2.6
    assert results["src_high"]["without"] == 2.4
    assert abs(results["src_high"]["deviation_pct"] - (2.4 - 2.6) / 2.6 * 100) < 1e-9
