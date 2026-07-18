"""Chart generation: 1200x675 PNGs for the weekly post.

Design rules (dataviz): one axis per panel (the energy overlay is two stacked panels,
never dual-axis); identity via direct labels; blue/orange CVD-safe pair for two-series
charts; text in ink colors, never series colors; recessive grid. A chart with no data
is skipped, never faked.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from eucri.config import load_factors

log = logging.getLogger("eucri.outputs.charts")

REPO_ROOT = Path(__file__).resolve().parents[3]
CHART_DIR = REPO_ROOT / "site" / "charts"

# palette: blue/orange CVD-safe pair; grays are ink, never series colors
BLUE = "#2563EB"
ORANGE = "#EA580C"
INK = "#1F2937"
INK_MUTED = "#6B7280"
GRID = "#E5E7EB"

FIGSIZE = (12.0, 6.75)  # x100 dpi = 1200x675


def _style(ax: plt.Axes) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_MUTED, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)


def _footer(fig: plt.Figure) -> None:
    version = load_factors().methodology_version
    fig.text(
        0.01, 0.01, f"EU-CRI — methodology v{version}",
        fontsize=8, color=INK_MUTED, ha="left", va="bottom",
    )


def _latest_series(conn: sqlite3.Connection, series: str) -> list[tuple[str, float | None]]:
    rows = conn.execute(
        "SELECT d.date, d.value_usd FROM daily_index d JOIN ("
        "  SELECT date, series, MAX(revision) AS rev FROM daily_index GROUP BY date, series"
        ") m ON d.date = m.date AND d.series = m.series AND d.revision = m.rev"
        " WHERE d.series = ? ORDER BY d.date",
        (series,),
    ).fetchall()
    return [(r["date"], r["value_usd"]) for r in rows]


def _dates(points: list[tuple[str, float | None]]) -> tuple[list, list]:
    xs = [mdates.datestr2num(d) for d, v in points if v is not None]
    ys = [v for _, v in points if v is not None]
    return xs, ys


def chart_headline(conn: sqlite3.Connection) -> Path | None:
    daily = _latest_series(conn, "EU-CRI-H100")
    smooth = _latest_series(conn, "EU-CRI-H100-7D")
    xs, ys = _dates(daily)
    if not xs:
        log.info("headline chart skipped: no non-null prints yet")
        return None
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=100)
    _style(ax)
    ax.plot(xs, ys, color=BLUE, linewidth=1.2, alpha=0.55, marker="o",
            markersize=4.5, label="daily print")
    sx, sy = _dates(smooth)
    if sx:
        ax.plot(sx, sy, color=BLUE, linewidth=2.2, label="7-day mean")
    if len(xs) < 7:
        ax.set_xlim(min(xs) - 3, max(xs) + 3)  # early history: don't let autoscale sprawl
    ax.legend(frameon=False, fontsize=9, labelcolor=INK)
    ax.set_title("EU-CRI-H100 — EU H100 rental price (USD per GPU-hour)",
                 fontsize=13, color=INK, loc="left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.set_ylabel("USD / GPU-hr", fontsize=9, color=INK_MUTED)
    _footer(fig)
    out = CHART_DIR / "headline_7d.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_dispersion(conn: sqlite3.Connection) -> Path | None:
    row = conn.execute(
        "SELECT date, MAX(revision) AS rev FROM daily_index WHERE series = 'EU-CRI-H100'"
        " GROUP BY date ORDER BY date DESC LIMIT 1"
    ).fetchone()
    if row is None:
        return None
    date, rev = row["date"], row["rev"]
    cons = conn.execute(
        "SELECT provider, price_usd, included, tier FROM constituents"
        " WHERE date = ? AND series = 'EU-CRI-H100' AND revision = ? AND included = 1"
        " ORDER BY price_usd",
        (date, rev),
    ).fetchall()
    if not cons:
        log.info("dispersion chart skipped: no included constituents on %s", date)
        return None
    head = conn.execute(
        "SELECT value_usd FROM daily_index WHERE date = ? AND series = 'EU-CRI-H100'"
        " AND revision = ?",
        (date, rev),
    ).fetchone()

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=100)
    _style(ax)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.yaxis.grid(False)
    names = [c["provider"] for c in cons]
    prices = [c["price_usd"] for c in cons]
    ax.hlines(range(len(cons)), 0, prices, color=GRID, linewidth=1.2)
    ax.plot(prices, range(len(cons)), "o", color=BLUE, markersize=9)
    for i, price in enumerate(prices):
        ax.annotate(f"{price:.2f}", (price, i), xytext=(8, -3),
                    textcoords="offset points", fontsize=9, color=INK)
    ax.set_yticks(range(len(cons)), names, fontsize=10, color=INK)
    if head and head["value_usd"] is not None:
        ax.axvline(head["value_usd"], color=INK_MUTED, linewidth=1.2, linestyle="--")
        ax.text(head["value_usd"], 0.98, f" index {head['value_usd']:.2f}",
                transform=ax.get_xaxis_transform(), fontsize=9, color=INK_MUTED,
                ha="left", va="top")
    ax.set_title(f"Constituent prices — {date} (USD per GPU-hour)",
                 fontsize=13, color=INK, loc="left")
    ax.set_xlim(left=0)
    _footer(fig)
    out = CHART_DIR / "dispersion.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_sovereign(conn: sqlite3.Connection) -> Path | None:
    head = _latest_series(conn, "EU-CRI-H100")
    sov = _latest_series(conn, "EU-CRI-H100-SOV")
    hx, hy = _dates(head)
    sx, sy = _dates(sov)
    if len(hx) < 2 or len(sx) < 2:
        log.info("sovereign chart skipped: needs >=2 days of both series")
        return None
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=100)
    _style(ax)
    ax.plot(hx, hy, color=BLUE, linewidth=2.0, label="EU-CRI-H100")
    ax.plot(sx, sy, color=ORANGE, linewidth=2.0, label="EU-Sovereign")
    ax.annotate("all providers", (hx[-1], hy[-1]), xytext=(8, 0),
                textcoords="offset points", fontsize=9, color=INK)
    ax.annotate("EU-sovereign", (sx[-1], sy[-1]), xytext=(8, 0),
                textcoords="offset points", fontsize=9, color=INK)
    ax.legend(frameon=False, fontsize=9, labelcolor=INK)
    ax.set_title("The price of sovereignty — EU-sovereign vs full constituent set (USD/GPU-hr)",
                 fontsize=13, color=INK, loc="left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    _footer(fig)
    out = CHART_DIR / "sovereign_spread.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_energy_overlay(conn: sqlite3.Connection) -> Path | None:
    """Two stacked panels sharing x — never a dual-axis chart."""
    power = conn.execute(
        "SELECT date, AVG(avg_price_eur_mwh) AS p FROM overlay_power GROUP BY date ORDER BY date"
    ).fetchall()
    head = _latest_series(conn, "EU-CRI-H100")
    hx, hy = _dates(head)
    if len(power) < 2 or len(hx) < 2:
        log.info("energy overlay skipped: needs overlay data and >=2 index days")
        return None
    px = [mdates.datestr2num(r["date"]) for r in power]
    py = [r["p"] for r in power]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=FIGSIZE, dpi=100, sharex=True,
                                   height_ratios=[3, 2])
    for ax in (ax1, ax2):
        _style(ax)
    ax1.plot(hx, hy, color=BLUE, linewidth=2.0)
    ax1.set_title("EU-CRI-H100 (USD/GPU-hr) vs EU day-ahead power (EUR/MWh)",
                  fontsize=13, color=INK, loc="left")
    ax1.set_ylabel("USD / GPU-hr", fontsize=9, color=INK_MUTED)
    ax2.plot(px, py, color=ORANGE, linewidth=2.0)
    ax2.set_ylabel("EUR / MWh", fontsize=9, color=INK_MUTED)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    _footer(fig)
    out = CHART_DIR / "energy_overlay.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def generate_all(conn: sqlite3.Connection) -> list[Path]:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    produced = []
    for fn in (chart_headline, chart_dispersion, chart_sovereign, chart_energy_overlay):
        try:
            path = fn(conn)
            if path:
                produced.append(path)
        except Exception:
            log.exception("%s failed (fail-soft)", fn.__name__)
    log.info("charts: %s", [p.name for p in produced] or "none")
    return produced
