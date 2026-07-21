"""End-to-end weight review + composite flow over a multi-day history.

Timeline (2026-07-13 is a Monday):
- collect 6 equal providers daily 2026-07-13..2026-07-20 (prices 2.0..2.5)
- compute 2026-07-20: review effective 2026-07-20 (window 06-22..07-19 holds 7
  collection days >= 5) -> review weighting, composite base print
- collect 2026-07-21 at +10% plus a new entrant; compute: chained composite,
  entrant flagged no_weight_history
"""

from __future__ import annotations

import sqlite3

import pytest
import requests

from eucri.collectors import base
from eucri.commands import COMPOSITE, HEADLINE, compute_all_series
from eucri.db import utc_now_iso
from eucri.models import Observation

BASE_PRICES = [2.0, 2.1, 2.2, 2.3, 2.4, 2.5]


class _MarketCollector:
    def __init__(self, name: str, providers: list[tuple[str, float]]) -> None:
        self.name = name
        self._providers = providers

    def collect(self, session: requests.Session) -> list[Observation]:
        return [
            Observation(
                ts_utc=utc_now_iso(), source=self.name, provider=provider,
                gpu_model="H100_SXM", gpu_count=8, price_usd_per_gpu_hr=price,
                region=None, country="NL", interconnect="NVLink", tier="executable",
                term="on_demand", raw_json="{}",
            )
            for provider, price in self._providers
        ]


def _six(factor: float = 1.0) -> list[tuple[str, float]]:
    return [(f"prov{i}", p * factor) for i, p in enumerate(BASE_PRICES)]


def _latest(conn: sqlite3.Connection, series: str, date: str) -> sqlite3.Row:
    return conn.execute(
        "SELECT * FROM daily_index WHERE date = ? AND series = ?"
        " ORDER BY revision DESC LIMIT 1",
        (date, series),
    ).fetchone()


def _collect_history(conn: sqlite3.Connection) -> None:
    for day in range(13, 21):  # 2026-07-13 .. 2026-07-20
        base.run_collector(conn, _MarketCollector("fake_market", _six()), f"2026-07-{day}")


def test_review_weights_and_composite_chain(conn: sqlite3.Connection) -> None:
    _collect_history(conn)
    compute_all_series(conn, "2026-07-20")

    # the review was stored: 6 provider rows (weight 16 = median(8x2) x presence 1)
    # and one model row (H100 share 100)
    provider_rows = conn.execute(
        "SELECT * FROM weight_sets WHERE effective_date = '2026-07-20'"
        " AND scope = 'provider' ORDER BY key"
    ).fetchall()
    assert len(provider_rows) == 6
    assert all(r["model_class"] == "H100" and r["weight"] == 16.0 for r in provider_rows)
    assert all(r["n_days_observed"] == 7 and r["n_days_window"] == 7 for r in provider_rows)
    model_rows = conn.execute(
        "SELECT * FROM weight_sets WHERE effective_date = '2026-07-20' AND scope = 'model'"
    ).fetchall()
    assert len(model_rows) == 1
    assert model_rows[0]["key"] == "H100" and model_rows[0]["weight"] == 100.0

    head = _latest(conn, HEADLINE, "2026-07-20")
    assert head["value_usd"] == 2.2  # 6 equal weights -> lower weighted median = 3rd
    assert "bootstrap_weights" not in head["flags"]

    comp = _latest(conn, COMPOSITE, "2026-07-20")
    assert comp["value_usd"] == 100.0  # base print
    assert comp["flags"] == "base"
    assert comp["n_sources"] == 1

    # day 2: +10% across the board plus a brand-new provider not in the review
    base.run_collector(
        conn, _MarketCollector("fake_market", _six(1.1)), "2026-07-21"
    )
    base.run_collector(
        conn, _MarketCollector("new_market", [("newp", 3.30)]), "2026-07-21"
    )
    compute_all_series(conn, "2026-07-21")

    head2 = _latest(conn, HEADLINE, "2026-07-21")
    # 7 constituents: six review weights 16, entrant default 8x2=16 -> equal shares;
    # prices [2.20, 2.31, 2.42, 2.53, 2.64, 2.75, 3.30] -> 4th = 2.53
    assert head2["value_usd"] == pytest.approx(2.53)
    entrant = conn.execute(
        "SELECT * FROM constituents WHERE date = '2026-07-21' AND series = ?"
        " AND provider = 'newp' ORDER BY revision DESC LIMIT 1",
        (HEADLINE,),
    ).fetchone()
    assert entrant["flags"] == "no_weight_history"

    comp2 = _latest(conn, COMPOSITE, "2026-07-21")
    assert comp2["value_usd"] == pytest.approx(115.0)  # 100 x 2.53 / 2.20
    assert comp2["flags"] == ""

    # composite audit trail: the H100 link is recorded as a constituent
    link = conn.execute(
        "SELECT * FROM constituents WHERE date = '2026-07-21' AND series = ?"
        " ORDER BY revision DESC LIMIT 1",
        (COMPOSITE,),
    ).fetchone()
    assert link["provider"] == "H100" and link["source"] == "composite"
    assert link["weight"] == 100.0 and link["included"] == 1


def test_review_set_is_idempotent_and_immutable(conn: sqlite3.Connection) -> None:
    _collect_history(conn)
    compute_all_series(conn, "2026-07-20")
    compute_all_series(conn, "2026-07-20")  # recompute: prints get revisions...

    revs = conn.execute(
        "SELECT DISTINCT revision FROM weight_sets WHERE effective_date = '2026-07-20'"
    ).fetchall()
    assert [r["revision"] for r in revs] == [1]  # ...but the review is reused, not re-stored

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("UPDATE weight_sets SET weight = 999 WHERE scope = 'provider'")
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM weight_sets")


def test_bootstrap_below_min_history(conn: sqlite3.Connection) -> None:
    # only 2 collection days in the window -> bootstrap weighting, no review stored
    for day in (18, 19):
        base.run_collector(conn, _MarketCollector("fake_market", _six()), f"2026-07-{day}")
    compute_all_series(conn, "2026-07-19")
    assert conn.execute("SELECT COUNT(*) AS n FROM weight_sets").fetchone()["n"] == 0
    head = _latest(conn, HEADLINE, "2026-07-19")
    assert head["value_usd"] == 2.2
    assert "bootstrap_weights" in head["flags"]
    assert _latest(conn, COMPOSITE, "2026-07-19") is None  # no composite pre-review
