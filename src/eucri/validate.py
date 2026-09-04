# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Validation diagnostics (methodology memo §4): source-dropout sensitivity and an
optional correlation check against a manually entered external series.

Diagnostics only — never part of the calculation path.
"""

from __future__ import annotations

import csv
import logging
import sqlite3
import statistics
from pathlib import Path

from eucri import config
from eucri.commands import HEADLINE, _observations_for_date
from eucri.index import compute_print
from eucri.normalise import normalise_observations

log = logging.getLogger("eucri.validate")

CHECK_SERIES_PATH = Path(__file__).resolve().parents[2] / "config" / "check_series.csv"

DROPOUT_WARN_PCT = 5.0  # memo §4: cap a source's weight if it moves the index > 5%


def dropout_sensitivity(conn: sqlite3.Connection, utc_date: str) -> list[dict]:
    """Recompute the headline excluding each source in turn (production weight path)."""
    factors = config.load_factors()
    rows = _observations_for_date(conn, utc_date)
    normalised = [
        o for o in normalise_observations(rows, factors)
        if o.model_class == factors.headline_class
    ]
    population = factors.population_for("headline")
    base = compute_print(
        utc_date, HEADLINE, normalised, factors, None, population=population
    )
    results: list[dict] = []
    if base.value_usd is None:
        log.warning("dropout: no base value on %s (%s)", utc_date, base.flags)
        return results
    for source in sorted({o.source for o in normalised}):
        subset = [o for o in normalised if o.source != source]
        alt = compute_print(
            utc_date, HEADLINE, subset, factors, None, population=population
        )
        if alt.value_usd is None:
            deviation = None  # dropping this source gaps the print entirely
        else:
            deviation = (alt.value_usd - base.value_usd) / base.value_usd * 100.0
        results.append(
            {"source": source, "base": base.value_usd, "without": alt.value_usd,
             "deviation_pct": deviation, "flags": alt.flags}
        )
    return results


def check_series_correlation(conn: sqlite3.Connection) -> dict | None:
    """Correlation of weekly changes vs config/check_series.csv (date,value), if present."""
    if not CHECK_SERIES_PATH.exists():
        return None
    external: dict[str, float] = {}
    with open(CHECK_SERIES_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            external[row["date"]] = float(row["value"])
    ours: dict[str, float] = {}
    for r in conn.execute(
        "SELECT d.date, d.value_usd FROM daily_index d JOIN ("
        "  SELECT date, MAX(revision) AS rev FROM daily_index WHERE series = ?"
        "  GROUP BY date) m ON d.date = m.date AND d.revision = m.rev"
        " WHERE d.series = ? AND d.value_usd IS NOT NULL",
        (HEADLINE, HEADLINE),
    ):
        ours[r["date"]] = r["value_usd"]
    common = sorted(set(external) & set(ours))
    if len(common) < 4:
        return {"n_common_dates": len(common), "correlation": None,
                "note": "need >=4 overlapping dates for weekly-change correlation"}
    ours_chg = [ours[b] - ours[a] for a, b in zip(common, common[1:], strict=False)]
    ext_chg = [external[b] - external[a] for a, b in zip(common, common[1:], strict=False)]
    corr = statistics.correlation(ours_chg, ext_chg) if len(ours_chg) >= 2 else None
    return {"n_common_dates": len(common), "correlation": corr, "note": ""}


def run_validate(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT MAX(utc_date) AS d FROM runs WHERE source NOT IN ('index') AND status = 'ok'"
    ).fetchone()
    if row is None or row["d"] is None:
        print("no collected data to validate")
        return 1
    utc_date = row["d"]
    print(f"source-dropout sensitivity, {HEADLINE} {utc_date}:")
    worst = 0.0
    for r in dropout_sensitivity(conn, utc_date):
        if r["deviation_pct"] is None:
            print(f"  - without {r['source']:<12}: PRINT GAPS ({r['flags']})")
            continue
        marker = "  <-- exceeds 5% (consider weight cap, GOVERNANCE.md)" if abs(
            r["deviation_pct"]) > DROPOUT_WARN_PCT else ""
        print(f"  - without {r['source']:<12}: {r['without']:.4f} "
              f"({r['deviation_pct']:+.2f}%){marker}")
        worst = max(worst, abs(r["deviation_pct"]))
    print(f"  max deviation: {worst:.2f}%")

    check = check_series_correlation(conn)
    if check is None:
        print("check series: config/check_series.csv not present (optional)")
    else:
        print(f"check series: {check}")
    return 0
