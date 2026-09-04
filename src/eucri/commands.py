# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
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
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from pathlib import Path

from eucri import config, db, weights
from eucri.collectors import base
from eucri.collectors.azure_retail import AzureRetailCollector
from eucri.collectors.fx import collect_fx, rate_for
from eucri.collectors.gpuhunt_ import GpuHuntCollector
from eucri.collectors.runpod import RunPodCollector
from eucri.collectors.scaleway import ScalewayCollector
from eucri.collectors.static_yaml import StaticYamlCollector
from eucri.collectors.vast_ai import VastAiCollector
from eucri.index import compute_print
from eucri.models import Constituent, IndexPrint
from eucri.normalise import NormalisedObs, normalise_observations

log = logging.getLogger("eucri.commands")

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "site" / "data" / "index_history.csv"

HEADLINE = "EU-CRI-H100"
SERIES_7D = "EU-CRI-H100-7D"
COMPOSITE = "EU-CRI-COMPUTE"
SERIES_BY_CLASS = {
    "H100": "EU-CRI-H100", "H200": "EU-CRI-H200", "B200": "EU-CRI-B200",
    "B300": "EU-CRI-B300", "A100": "EU-CRI-A100", "H100P": "EU-CRI-H100-PCIE",
}


def collectors_for_daily() -> list[base.Collector]:
    return [
        VastAiCollector(), RunPodCollector(), GpuHuntCollector(), StaticYamlCollector(),
        ScalewayCollector(), AzureRetailCollector(),
    ]


# (model class, market-segment population, extra predicate)
SeriesDef = tuple[str, frozenset[str], Callable[[NormalisedObs], bool]]


def _series_definitions(
    sovereign: frozenset[str], headline_class: str, factors: config.Factors
) -> dict[str, SeriesDef]:
    """v0.3.0 series, segregated by market segment rather than by executable/list tier.

    The constituent distribution is bimodal — measured separation 5.4 sd between the
    neocloud/marketplace cluster and the hyperscaler catalog cluster — so the headline
    draws from one side of that gap and the hyperscaler tier gets its own series, where
    it is the correct object of measurement rather than a drag on someone else's print.
    """
    hc = headline_class

    def everything(o: NormalisedObs) -> bool:
        return o.model_class == hc

    return {
        HEADLINE: (hc, factors.population_for("headline"), everything),
        "EU-CRI-H100-MKT": (hc, factors.population_for("marketplace"), everything),
        "EU-CRI-H100-NC": (hc, frozenset({"neocloud"}), everything),
        "EU-CRI-H100-HS": (hc, factors.population_for("hyperscaler"), everything),
        "EU-CRI-H100-SOV": (
            hc,
            factors.population_for("sovereign"),
            lambda o: o.model_class == hc and o.provider in sovereign,
        ),
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


@dataclass(frozen=True)
class ReviewWeights:
    """One effective weight review, as stored in weight_sets."""

    effective_date: str
    window_start: str
    window_end: str
    n_days_window: int
    provider_by_class: dict[str, dict[str, weights.ReviewWeight]]
    model_shares: dict[str, float]


def _collection_dates(conn: sqlite3.Connection, start: str, end: str) -> list[str]:
    """Days in [start, end] with at least one stored observation."""
    return [
        r["utc_date"]
        for r in conn.execute(
            "SELECT DISTINCT r.utc_date AS utc_date FROM runs r"
            " JOIN observations o ON o.run_id = r.run_id"
            " WHERE r.utc_date >= ? AND r.utc_date <= ? ORDER BY r.utc_date",
            (start, end),
        )
    ]


def _load_review(
    conn: sqlite3.Connection, effective_date: str, version: str
) -> ReviewWeights | None:
    row = conn.execute(
        "SELECT MAX(revision) AS rev FROM weight_sets WHERE effective_date = ?",
        (effective_date,),
    ).fetchone()
    if row is None or row["rev"] is None:
        return None
    rows = conn.execute(
        "SELECT * FROM weight_sets WHERE effective_date = ? AND revision = ?",
        (effective_date, row["rev"]),
    ).fetchall()
    if not rows or rows[0]["methodology_version"] != version:
        return None  # recomputed under the current version as a new revision
    provider_by_class: dict[str, dict[str, weights.ReviewWeight]] = {}
    model_shares: dict[str, float] = {}
    for r in rows:
        if r["scope"] == "provider":
            provider_by_class.setdefault(r["model_class"], {})[r["key"]] = weights.ReviewWeight(
                weight=r["weight"], days_observed=r["n_days_observed"]
            )
        else:
            model_shares[r["key"]] = r["weight"]
    return ReviewWeights(
        effective_date=effective_date,
        window_start=rows[0]["window_start"],
        window_end=rows[0]["window_end"],
        n_days_window=rows[0]["n_days_window"],
        provider_by_class=provider_by_class,
        model_shares=model_shares,
    )


def _store_review(conn: sqlite3.Connection, rw: ReviewWeights, version: str) -> None:
    row = conn.execute(
        "SELECT COALESCE(MAX(revision), 0) AS rev FROM weight_sets WHERE effective_date = ?",
        (rw.effective_date,),
    ).fetchone()
    revision = int(row["rev"]) + 1
    now = db.utc_now_iso()
    entries = [
        (rw.effective_date, "provider", cls, provider, r.weight, rw.window_start,
         rw.window_end, r.days_observed, rw.n_days_window, revision, version, now)
        for cls, pset in rw.provider_by_class.items()
        for provider, r in pset.items()
    ] + [
        (rw.effective_date, "model", "", cls, share, rw.window_start,
         rw.window_end, rw.n_days_window, rw.n_days_window, revision, version, now)
        for cls, share in rw.model_shares.items()
    ]
    with conn:
        conn.executemany(
            "INSERT INTO weight_sets (effective_date, scope, model_class, key, weight,"
            " window_start, window_end, n_days_observed, n_days_window, revision,"
            " methodology_version, computed_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            entries,
        )


def _review_weights(
    conn: sqlite3.Connection, utc_date: str, factors: config.Factors
) -> ReviewWeights | None:
    """The weight review in effect for utc_date, computing and storing it when due.

    Returns None (bootstrap) while the trailing window holds fewer collection days
    than weights.review.min_history_days.
    """
    review_cfg = factors.weights.review
    effective = weights.review_effective_date(utc_date, review_cfg.anchor_weekday)
    stored = _load_review(conn, effective, factors.methodology_version)
    if stored is not None:
        return stored

    effective_d = date_type.fromisoformat(effective)
    window_end = (effective_d - timedelta(days=1)).isoformat()
    window_start = (effective_d - timedelta(days=review_cfg.window_days)).isoformat()
    days = _collection_dates(conn, window_start, window_end)
    if len(days) < review_cfg.min_history_days:
        return None

    per_class_daily: dict[str, dict[str, dict[str, tuple[str, int]]]] = {}
    class_capacity: dict[str, float] = {}
    for day in days:
        normalised = normalise_observations(_observations_for_date(conn, day), factors)
        by_class: dict[str, list[NormalisedObs]] = {}
        for o in normalised:
            by_class.setdefault(o.model_class, []).append(o)
        for cls, obs_list in by_class.items():
            summary = weights.daily_capacity(obs_list, factors)
            per_class_daily.setdefault(cls, {})[day] = summary
            class_capacity[cls] = class_capacity.get(cls, 0.0) + sum(
                cap for _, cap in summary.values()
            )

    provider_by_class = {
        cls: weights.provider_review_weights({d: daily.get(d, {}) for d in days}, factors)
        for cls, daily in per_class_daily.items()
    }
    rw = ReviewWeights(
        effective_date=effective,
        window_start=window_start,
        window_end=window_end,
        n_days_window=len(days),
        provider_by_class=provider_by_class,
        model_shares=weights.model_review_shares(class_capacity, factors.composite),
    )
    _store_review(conn, rw, factors.methodology_version)
    log.info(
        "weight review stored: effective %s, window %s..%s (%d collection days)",
        effective, window_start, window_end, len(days),
    )
    return rw


def _latest_value_on(conn: sqlite3.Connection, series: str, date: str) -> float | None:
    row = conn.execute(
        "SELECT value_usd FROM daily_index WHERE date = ? AND series = ?"
        " ORDER BY revision DESC LIMIT 1",
        (date, series),
    ).fetchone()
    return row["value_usd"] if row else None


def _compute_composite(
    conn: sqlite3.Connection, utc_date: str, factors: config.Factors, rw: ReviewWeights
) -> IndexPrint:
    """EU-CRI-COMPUTE: chain-linked over class sub-indices with review basket shares.

    Links renormalise over classes with a published value on both endpoints, so a
    gapping class drops out of the day's link without gapping the composite.
    """
    shares = {cls: s for cls, s in rw.model_shares.items() if cls in SERIES_BY_CLASS}
    prev = conn.execute(
        "SELECT d.date, d.value_usd FROM daily_index d JOIN ("
        "  SELECT date, MAX(revision) AS rev FROM daily_index WHERE series = ?"
        "  GROUP BY date) m ON d.date = m.date AND d.revision = m.rev"
        " WHERE d.series = ? AND d.date < ? AND d.value_usd IS NOT NULL"
        " ORDER BY d.date DESC LIMIT 1",
        (COMPOSITE, COMPOSITE, utc_date),
    ).fetchone()
    today = {cls: _latest_value_on(conn, SERIES_BY_CLASS[cls], utc_date) for cls in shares}

    value: float | None
    if prev is None:
        linked = sorted(cls for cls, v in today.items() if v is not None)
        value = factors.composite.base_value if linked else None
        flags = "base" if linked else "no_linkable_series"
    else:
        prev_vals = {cls: _latest_value_on(conn, SERIES_BY_CLASS[cls], prev["date"])
                     for cls in shares}
        links = [
            (shares[cls], now, before)
            for cls in sorted(shares)
            if (now := today[cls]) is not None
            and (before := prev_vals[cls]) is not None
        ]
        linked = sorted(
            cls for cls in shares
            if today[cls] is not None and prev_vals[cls] is not None
        )
        if links:
            value = round(weights.chain_link(prev["value_usd"], links), 6)
            flags = ""
        else:
            value, flags = None, "no_linkable_series"

    total_linked = sum(shares[cls] for cls in linked)
    constituents = tuple(
        Constituent(
            provider=cls, source="composite", tier="index",
            price_usd=today_val if (today_val := today[cls]) is not None else 0.0,
            weight=round(shares[cls] / total_linked * 100.0, 6)
            if cls in linked and total_linked > 0 else round(shares[cls], 6),
            included=cls in linked,
            exclusion_reason=None if cls in linked else "no_print",
        )
        for cls in sorted(shares)
    )
    return IndexPrint(
        date=utc_date, series=COMPOSITE, value_usd=value, value_eur=None,
        fx_rate=None, fx_date=None, n_sources=len(linked), n_executable=0,
        flags=flags, constituents=constituents,
    )


def compute_all_series(conn: sqlite3.Connection, utc_date: str, correction: bool = False) -> None:
    """Compute and store every series for one date (new revisions, never edits)."""
    factors = config.load_factors()
    sovereign = config.load_sovereign()
    version = factors.methodology_version
    fx = rate_for(conn, utc_date)
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
    # FX is needed during normalisation: providers quoting in EUR (Scaleway) are converted
    # at print time from their native amount, never from a rate frozen at collection.
    normalised = normalise_observations(rows, factors, fx_eur_usd=fx[0] if fx else None)
    rw = _review_weights(conn, utc_date, factors)
    headline_class = factors.headline_class

    common_extra = "correction" if correction else ""
    # v0.3.0 weights providers by tier only, so a missing weight review no longer changes
    # the calculation and the bootstrap flag no longer applies.
    series_extra = common_extra

    definitions = _series_definitions(sovereign, headline_class, factors)
    observed_classes = {o.model_class for o in normalised}
    headline_pop = factors.population_for("headline")
    for cls, series_name in SERIES_BY_CLASS.items():
        if cls != headline_class and cls in observed_classes:
            definitions[series_name] = (
                cls, headline_pop, (lambda c: (lambda o: o.model_class == c))(cls)
            )

    for series, (_cls, population, predicate) in definitions.items():
        subset: list[NormalisedObs] = [o for o in normalised if predicate(o)]
        result = compute_print(
            utc_date, series, subset, factors, fx,
            population=population,
            prev_prices=_prev_prices(conn, series, utc_date),
        )
        revision = _store_print(conn, result, version, run_id, series_extra)
        log.info(
            "%s %s rev%d: %s (n=%d%s)", utc_date, series, revision,
            result.value_usd, result.n_sources,
            f", flags={result.flags}" if result.flags else "",
        )

    if rw is not None:
        composite = _compute_composite(conn, utc_date, factors, rw)
        _store_print(conn, composite, version, run_id, common_extra)
        log.info(
            "%s %s: %s (linked=%d%s)", utc_date, COMPOSITE, composite.value_usd,
            composite.n_sources,
            f", flags={composite.flags}" if composite.flags else "",
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
    _store_print(conn, smoothed, version, run_id, common_extra)

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
    from eucri.collectors.entsoe import collect_overlay

    collect_overlay(conn, session, utc_date)  # overlay only; skips without token
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
    """Charts + post + dashboard data + the published site; never blocks the daily run."""
    from eucri.outputs import charts, post, site, webdata

    try:
        charts.generate_all(conn)
        post.generate_post(conn)
        webdata.generate(conn)
        site.generate(conn)
    except Exception:
        log.exception("output generation failed (fail-soft)")


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


def cmd_weights(args: argparse.Namespace) -> int:
    """Show (computing and storing if due) the weight review in effect for a date."""
    conn = db.connect()
    db.migrate(conn)
    factors = config.load_factors()
    utc_date = args.date or datetime.now(UTC).strftime("%Y-%m-%d")
    effective = weights.review_effective_date(
        utc_date, factors.weights.review.anchor_weekday
    )
    rw = _review_weights(conn, utc_date, factors)
    if rw is None:
        print(
            f"no weight review in effect for {utc_date} (review date {effective}):"
            f" fewer than {factors.weights.review.min_history_days} collection days in the"
            f" trailing {factors.weights.review.window_days}-day window."
            " Bootstrap weighting (same-day capacity) applies; prints are flagged"
            " 'bootstrap_weights'."
        )
        return 0
    print(
        f"weight review effective {rw.effective_date}"
        f" (window {rw.window_start}..{rw.window_end},"
        f" {rw.n_days_window} collection days)"
    )
    for cls in sorted(rw.provider_by_class):
        pset = rw.provider_by_class[cls]
        total = sum(r.weight for r in pset.values())
        print(f"\n{cls} provider review weights (shares shown pre-concentration-cap):")
        header = f"{'provider':<20}{'weight':>10}{'share':>9}{'days':>6}"
        print(header)
        print("-" * len(header))
        for provider, r in sorted(pset.items(), key=lambda kv: -kv[1].weight):
            print(
                f"{provider:<20}{r.weight:>10.2f}{r.weight / total * 100:>8.1f}%"
                f"{r.days_observed:>6}"
            )
    print(f"\nmodel basket shares ({COMPOSITE}):")
    for cls, share in sorted(rw.model_shares.items(), key=lambda kv: -kv[1]):
        print(f"  {cls:<8}{share:>7.2f}%")
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


def cmd_post(args: argparse.Namespace) -> int:
    from eucri.outputs import charts, post

    conn = db.connect()
    charts.generate_all(conn)
    print(post.generate_post(conn))
    return 0


def dispatch(args: argparse.Namespace) -> int:
    if args.command == "daily":
        return cmd_daily(args)
    if args.command == "constituents":
        return cmd_constituents(args)
    if args.command == "backfill":
        return cmd_backfill(args)
    if args.command == "weights":
        return cmd_weights(args)
    if args.command == "post":
        return cmd_post(args)
    if args.command == "validate":
        from eucri.validate import run_validate

        return run_validate(db.connect())
    raise SystemExit(f"command {args.command!r} is not implemented yet")
