"""Implementations of the data-facing CLI commands (daily, constituents, backfill, ...).

Database orchestration lives here; the calculation itself (index.py, normalise.py) is
pure and methodology-hashed. Observation day = runs.utc_date (the collection day).
"""

from __future__ import annotations

import argparse
import csv
import logging
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from eucri import config, db
from eucri.collectors import base
from eucri.collectors.fx import collect_fx, latest_rate
from eucri.collectors.static_yaml import StaticYamlCollector
from eucri.collectors.vast_ai import VastAiCollector
from eucri.index import compute_print
from eucri.models import IndexPrint
from eucri.normalise import NormalisedObs, normalise_observations

log = logging.getLogger("eucri.commands")

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "site" / "data" / "index_history.csv"

HEADLINE = "EU-CRI-H100"
SERIES_7D = "EU-CRI-H100-7D"


def collectors_for_daily() -> list[base.Collector]:
    return [VastAiCollector(), StaticYamlCollector()]


def _series_definitions(sovereign: frozenset[str]) -> dict[str, object]:
    return {
        HEADLINE: lambda o: True,
        "EU-CRI-H100-SOV": lambda o: o.provider in sovereign,
        "EU-CRI-H100-MKT": lambda o: o.tier == "executable",
        "EU-CRI-H100-CLOUD": lambda o: o.tier == "list",
    }


def _observations_for_date(conn: sqlite3.Connection, utc_date: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT o.* FROM observations o JOIN runs r ON o.run_id = r.run_id"
        " WHERE r.utc_date = ?",
        (utc_date,),
    ).fetchall()


def _prev_prices(conn: sqlite3.Connection, series: str, before_date: str) -> dict[str, float]:
    row = conn.execute(
        "SELECT date, MAX(revision) AS rev FROM daily_index"
        " WHERE series = ? AND date < ? AND value_usd IS NOT NULL"
        " GROUP BY date ORDER BY date DESC LIMIT 1",
        (series, before_date),
    ).fetchone()
    if row is None:
        return {}
    rows = conn.execute(
        "SELECT provider, price_usd FROM constituents"
        " WHERE date = ? AND series = ? AND revision = ? AND included = 1",
        (row["date"], series, row["rev"]),
    ).fetchall()
    return {r["provider"]: r["price_usd"] for r in rows}


def _next_revision(conn: sqlite3.Connection, date: str, series: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(revision), 0) AS rev FROM daily_index"
        " WHERE date = ? AND series = ?",
        (date, series),
    ).fetchone()
    return int(row["rev"]) + 1


def _store_print(
    conn: sqlite3.Connection, print_: IndexPrint, version: str, run_id: str, flags: str = ""
) -> int:
    revision = _next_revision(conn, print_.date, print_.series)
    all_flags = ",".join(x for x in (print_.flags, flags) if x)
    with conn:
        conn.execute(
            "INSERT INTO daily_index (date, series, revision, value_usd, value_eur,"
            " fx_rate, fx_date, n_sources, n_executable, flags, methodology_version,"
            " computed_at, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                print_.date, print_.series, revision, print_.value_usd, print_.value_eur,
                print_.fx_rate, print_.fx_date, print_.n_sources, print_.n_executable,
                all_flags, version, db.utc_now_iso(), run_id,
            ),
        )
        conn.executemany(
            "INSERT INTO constituents (date, series, revision, provider, source, tier,"
            " price_usd, weight, included, exclusion_reason, flags)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    print_.date, print_.series, revision, c.provider, c.source, c.tier,
                    c.price_usd, c.weight, int(c.included), c.exclusion_reason, c.flags,
                )
                for c in print_.constituents
            ],
        )
    return revision


def _latest_values(conn: sqlite3.Connection, series: str, dates: list[str]) -> list[float | None]:
    out: list[float | None] = []
    for d in dates:
        row = conn.execute(
            "SELECT value_usd FROM daily_index WHERE date = ? AND series = ?"
            " ORDER BY revision DESC LIMIT 1",
            (d, series),
        ).fetchone()
        out.append(row["value_usd"] if row else None)
    return out


def compute_all_series(conn: sqlite3.Connection, utc_date: str, correction: bool = False) -> None:
    """Compute and store every series for one date (new revisions, never edits)."""
    factors = config.load_factors()
    sovereign = config.load_sovereign()
    version = factors.methodology_version
    fx = latest_rate(conn)
    if fx is None:
        log.warning("no FX rate stored yet; EUR series will be null")

    run_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO runs (run_id, utc_date, source, started_utc, status)"
        " VALUES (?, ?, 'index', ?, 'running')",
        (run_id, utc_date, db.utc_now_iso()),
    )
    conn.commit()

    rows = _observations_for_date(conn, utc_date)
    normalised = normalise_observations(rows, factors)
    extra_flags = "correction" if correction else ""

    for series, predicate in _series_definitions(sovereign).items():
        subset: list[NormalisedObs] = [o for o in normalised if predicate(o)]  # type: ignore[operator]
        result = compute_print(
            utc_date, series, subset, factors, fx, _prev_prices(conn, series, utc_date)
        )
        revision = _store_print(conn, result, version, run_id, extra_flags)
        log.info(
            "%s %s rev%d: %s (n=%d%s)", utc_date, series, revision,
            result.value_usd, result.n_sources,
            f", flags={result.flags}" if result.flags else "",
        )

    # 7-day mean of the headline (>=4 non-null of the trailing window)
    window = [
        (datetime.strptime(utc_date, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(factors.aggregation.smoothing_days)
    ]
    values = [v for v in _latest_values(conn, HEADLINE, window) if v is not None]
    if len(values) >= 4:
        mean = round(sum(values) / len(values), 6)
        eur = round(mean / fx[0], 6) if fx else None
        smoothed = IndexPrint(
            date=utc_date, series=SERIES_7D, value_usd=mean, value_eur=eur,
            fx_rate=fx[0] if fx else None, fx_date=fx[1] if fx else None,
            n_sources=len(values), n_executable=0, flags="", constituents=(),
        )
    else:
        smoothed = IndexPrint(
            date=utc_date, series=SERIES_7D, value_usd=None, value_eur=None,
            fx_rate=fx[0] if fx else None, fx_date=fx[1] if fx else None,
            n_sources=len(values), n_executable=0, flags="insufficient_history",
            constituents=(),
        )
    _store_print(conn, smoothed, version, run_id, extra_flags)

    with conn:
        conn.execute(
            "UPDATE runs SET status = 'ok', finished_utc = ? WHERE run_id = ?",
            (db.utc_now_iso(), run_id),
        )


def export_csv(conn: sqlite3.Connection, path: Path | None = None) -> Path:
    """Full history, latest revision per (date, series)."""
    target = path or CSV_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT d.* FROM daily_index d JOIN ("
        "  SELECT date, series, MAX(revision) AS rev FROM daily_index GROUP BY date, series"
        ") m ON d.date = m.date AND d.series = m.series AND d.revision = m.rev"
        " ORDER BY d.date, d.series"
    ).fetchall()
    with open(target, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(
            ["date", "series", "value_usd", "value_eur", "fx_rate", "fx_date",
             "n_sources", "n_executable", "flags", "methodology_version", "revision"]
        )
        for r in rows:
            writer.writerow(
                [r["date"], r["series"], r["value_usd"], r["value_eur"], r["fx_rate"],
                 r["fx_date"], r["n_sources"], r["n_executable"], r["flags"],
                 r["methodology_version"], r["revision"]]
            )
    return target


def cmd_daily(args: argparse.Namespace) -> int:
    utc_date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    conn = db.connect()
    db.migrate(conn)

    session = base.make_session()
    collect_fx(conn, session)  # fail-soft; calc falls back to last stored rate
    statuses = {
        c.name: base.run_collector(conn, c, utc_date, session) for c in collectors_for_daily()
    }
    log.info("collector statuses: %s", statuses)
    if all(s == "failed" for s in statuses.values()):
        log.error("every collector failed — aborting without computing")
        return 1

    compute_all_series(conn, utc_date)
    export_csv(conn)
    _maybe_outputs(conn)
    return 0


def _maybe_outputs(conn: sqlite3.Connection) -> None:
    """Charts/post regeneration once Phase 2 lands; never blocks the daily run."""
    import importlib.util

    if importlib.util.find_spec("eucri.outputs.charts") is None:
        return
    import importlib

    charts = importlib.import_module("eucri.outputs.charts")
    try:
        charts.generate_all(conn)
    except Exception:
        log.exception("chart generation failed (fail-soft)")


def cmd_constituents(args: argparse.Namespace) -> int:
    conn = db.connect()
    row = conn.execute(
        "SELECT MAX(revision) AS rev FROM daily_index WHERE date = ? AND series = ?",
        (args.date, args.series),
    ).fetchone()
    if row is None or row["rev"] is None:
        print(f"no print for {args.date} {args.series}")
        return 1
    head = conn.execute(
        "SELECT * FROM daily_index WHERE date = ? AND series = ? AND revision = ?",
        (args.date, args.series, row["rev"]),
    ).fetchone()
    print(
        f"{args.series} {args.date} rev{head['revision']}"
        f" value_usd={head['value_usd']} value_eur={head['value_eur']}"
        f" n_sources={head['n_sources']} flags={head['flags'] or '-'}"
        f" methodology={head['methodology_version']}"
    )
    cols = f"{'provider':<16}{'source':<14}{'tier':<12}{'price_usd':>10}{'weight':>8}  status"
    print(cols)
    print("-" * len(cols))
    for c in conn.execute(
        "SELECT * FROM constituents WHERE date = ? AND series = ? AND revision = ?"
        " ORDER BY included DESC, price_usd",
        (args.date, args.series, row["rev"]),
    ):
        status = "included" if c["included"] else f"EXCLUDED ({c['exclusion_reason']})"
        if c["included"] and c["exclusion_reason"]:
            status += f" ({c['exclusion_reason']})"
        if c["flags"]:
            status += f" [{c['flags']}]"
        print(
            f"{c['provider']:<16}{c['source']:<14}{c['tier']:<12}"
            f"{c['price_usd']:>10.4f}{c['weight']:>8.1f}  {status}"
        )
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    conn = db.connect()
    db.migrate(conn)
    start = datetime.strptime(args.date_from, "%Y-%m-%d")
    end = datetime.strptime(args.date_to, "%Y-%m-%d")
    if end < start:
        raise SystemExit("--to before --from")
    day = start
    while day <= end:
        utc_date = day.strftime("%Y-%m-%d")
        compute_all_series(conn, utc_date, correction=True)
        day += timedelta(days=1)
    export_csv(conn)
    return 0


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "daily":
        return cmd_daily(args)
    if args.command == "constituents":
        return cmd_constituents(args)
    if args.command == "backfill":
        return cmd_backfill(args)
    raise SystemExit(f"command {args.command!r} is not implemented yet")
