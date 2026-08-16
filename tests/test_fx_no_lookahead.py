"""FX must never be dated after the print it prices.

v0.2.0 selected the globally latest stored ECB rate with no date bound. During a backfill
that returns a rate published *after* the print date — a look-ahead. The committed
database carries two such prints (2026-07-18 and 2026-07-19, both stamped fx_date
2026-07-21). These tests pin the fix.
"""

from __future__ import annotations

import sqlite3

import pytest

from eucri.collectors.fx import rate_for

RATES = [
    ("2026-07-17", 1.1435),
    ("2026-07-21", 1.1418),
    ("2026-08-05", 1.1554),
]


@pytest.fixture()
def fx_conn(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executemany(
        "INSERT INTO fx (date, eur_usd, source) VALUES (?, ?, 'test')", RATES
    )
    conn.commit()
    return conn


def test_never_returns_a_rate_dated_after_the_print(fx_conn: sqlite3.Connection) -> None:
    """The exact v0.2.0 defect: a 07-18 print must not use the 07-21 rate."""
    rate, date = rate_for(fx_conn, "2026-07-18")
    assert date <= "2026-07-18"
    assert (rate, date) == (1.1435, "2026-07-17")


def test_exact_date_match_is_used_when_available(fx_conn: sqlite3.Connection) -> None:
    assert rate_for(fx_conn, "2026-07-21") == (1.1418, "2026-07-21")


def test_falls_back_to_most_recent_prior_rate(fx_conn: sqlite3.Connection) -> None:
    """T-1 is the normal case: the ECB publishes ~14:00 UTC, after the 11:00 cut-off."""
    assert rate_for(fx_conn, "2026-07-25") == (1.1418, "2026-07-21")


def test_returns_none_before_any_rate_exists(fx_conn: sqlite3.Connection) -> None:
    assert rate_for(fx_conn, "2026-07-01") is None


@pytest.mark.parametrize("on_date", [d for d, _ in RATES] + ["2026-07-19", "2026-09-01"])
def test_invariant_holds_for_every_date(fx_conn: sqlite3.Connection, on_date: str) -> None:
    result = rate_for(fx_conn, on_date)
    if result is not None:
        assert result[1] <= on_date, "FX date must never exceed the print date"
