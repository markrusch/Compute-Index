"""Chart generation: 1200x675 PNGs for the weekly post and the dashboard.

Design rules (dataviz): one axis per panel (the energy overlay is two stacked panels,
never dual-axis); identity via direct labels; blue/orange CVD-safe pair for two-series
charts; text in ink colors, never series colors; recessive grid. A chart with no data
is skipped, never faked. Every chart renders twice — light and dark — so the dashboard
can swap via `prefers-color-scheme` instead of showing a light chart on a dark page.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

from eucri.config import load_factors

log = logging.getLogger("eucri.outputs.charts")

REPO_ROOT = Path(__file__).resolve().parents[3]
CHART_DIR = REPO_ROOT / "site" / "charts"

FIGSIZE = (12.0, 6.75)  # x100 dpi = 1200x675


@dataclass(frozen=True)
class Theme:
    """A validated light/dark token set (dataviz skill reference palette)."""

    name: str
    surface: str
    ink: str
    ink_muted: str
    grid: str
    blue: str
    orange: str


# CVD-safe categorical slots 1 (blue) and 6 (orange) from the dataviz reference
# palette, each stepped for its own surface — not a separate palette per mode.
LIGHT = Theme(
    name="light", surface="#fcfcfb", ink="#0b0b0b", ink_muted="#898781",
    grid="#e1e0d9", blue="#2a78d6", orange="#eb6834",
)
DARK = Theme(
    name="dark", surface="#1a1a19", ink="#ffffff", ink_muted="#898781",
    grid="#2c2c2a", blue="#3987e5", orange="#d95926",
)
THEMES = (LIGHT, DARK)


def _suffix(theme: Theme) -> str:
    return "" if theme.name == "light" else "_dark"


def _style(ax: plt.Axes, theme: Theme) -> None:
    ax.set_facecolor(theme.surface)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(theme.grid)
    ax.tick_params(colors=theme.ink_muted, labelsize=9)
    ax.yaxis.grid(True, color=theme.grid, linewidth=0.8)
    ax.xaxis.grid(False)
    ax.set_axisbelow(True)


def _figure(theme: Theme, **kwargs: Any) -> tuple[plt.Figure, Any]:
    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=100, **kwargs)
    fig.patch.set_facecolor(theme.surface)
    return fig, ax


def _footer(fig: plt.Figure, theme: Theme) -> None:
    version = load_factors().methodology_version
    fig.text(
        0.01, 0.01, f"EU-CRI — methodology v{version}",
        fontsize=8, color=theme.ink_muted, ha="left", va="bottom",
    )


def _save(fig: plt.Figure, theme: Theme, stem: str) -> Path:
    out = CHART_DIR / f"{stem}{_suffix(theme)}.png"
    fig.savefig(out, bbox_inches="tight", facecolor=theme.surface)
    plt.close(fig)
    return out


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


def chart_headline(conn: sqlite3.Connection, theme: Theme) -> Path | None:
    daily = _latest_series(conn, "EU-CRI-H100")
    smooth = _latest_series(conn, "EU-CRI-H100-7D")
    xs, ys = _dates(daily)
    if not xs:
        log.info("headline chart skipped: no non-null prints yet")
        return None
    fig, ax = _figure(theme)
    _style(ax, theme)
    ax.plot(xs, ys, color=theme.blue, linewidth=1.2, alpha=0.55, marker="o",
            markersize=4.5, label="daily print")
    sx, sy = _dates(smooth)
    if sx:
        ax.plot(sx, sy, color=theme.blue, linewidth=2.2, label="7-day mean")
    if len(xs) < 7:
        ax.set_xlim(min(xs) - 3, max(xs) + 3)  # early history: don't let autoscale sprawl
    ax.legend(frameon=False, fontsize=9, labelcolor=theme.ink)
    ax.set_title("EU-CRI-H100 — EU H100 rental price (USD per GPU-hour)",
                 fontsize=13, color=theme.ink, loc="left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    ax.set_ylabel("USD / GPU-hr", fontsize=9, color=theme.ink_muted)
    _footer(fig, theme)
    return _save(fig, theme, "headline_7d")


def chart_dispersion(conn: sqlite3.Connection, theme: Theme) -> Path | None:
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

    fig, ax = _figure(theme)
    _style(ax, theme)
    ax.xaxis.grid(True, color=theme.grid, linewidth=0.8)
    ax.yaxis.grid(False)
    names = [c["provider"] for c in cons]
    prices = [c["price_usd"] for c in cons]
    ax.hlines(range(len(cons)), 0, prices, color=theme.grid, linewidth=1.2)
    ax.plot(prices, range(len(cons)), "o", color=theme.blue, markersize=9)
    for i, price in enumerate(prices):
        ax.annotate(f"{price:.2f}", (price, i), xytext=(8, -3),
                    textcoords="offset points", fontsize=9, color=theme.ink)
    ax.set_yticks(range(len(cons)), names, fontsize=10, color=theme.ink)
    if head and head["value_usd"] is not None:
        ax.axvline(head["value_usd"], color=theme.ink_muted, linewidth=1.2, linestyle="--")
        ax.text(head["value_usd"], 0.98, f" index {head['value_usd']:.2f}",
                transform=ax.get_xaxis_transform(), fontsize=9, color=theme.ink_muted,
                ha="left", va="top")
    ax.set_title(f"Constituent prices — {date} (USD per GPU-hour)",
                 fontsize=13, color=theme.ink, loc="left")
    ax.set_xlim(left=0)
    _footer(fig, theme)
    return _save(fig, theme, "dispersion")


def chart_sovereign(conn: sqlite3.Connection, theme: Theme) -> Path | None:
    head = _latest_series(conn, "EU-CRI-H100")
    sov = _latest_series(conn, "EU-CRI-H100-SOV")
    hx, hy = _dates(head)
    sx, sy = _dates(sov)
    if len(hx) < 2 or len(sx) < 2:
        log.info("sovereign chart skipped: needs >=2 days of both series")
        return None
    fig, ax = _figure(theme)
    _style(ax, theme)
    ax.plot(hx, hy, color=theme.blue, linewidth=2.0, label="EU-CRI-H100")
    ax.plot(sx, sy, color=theme.orange, linewidth=2.0, label="EU-Sovereign")
    ax.annotate("all providers", (hx[-1], hy[-1]), xytext=(8, 0),
                textcoords="offset points", fontsize=9, color=theme.ink)
    ax.annotate("EU-sovereign", (sx[-1], sy[-1]), xytext=(8, 0),
                textcoords="offset points", fontsize=9, color=theme.ink)
    ax.legend(frameon=False, fontsize=9, labelcolor=theme.ink)
    ax.set_title("The price of sovereignty — EU-sovereign vs full constituent set (USD/GPU-hr)",
                 fontsize=13, color=theme.ink, loc="left")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    _footer(fig, theme)
    return _save(fig, theme, "sovereign_spread")


def chart_energy_overlay(conn: sqlite3.Connection, theme: Theme) -> Path | None:
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
    fig, (ax1, ax2) = _figure(theme, nrows=2, sharex=True, height_ratios=[3, 2])
    for ax in (ax1, ax2):
        _style(ax, theme)
    ax1.plot(hx, hy, color=theme.blue, linewidth=2.0)
    ax1.set_title("EU-CRI-H100 (USD/GPU-hr) vs EU day-ahead power (EUR/MWh)",
                  fontsize=13, color=theme.ink, loc="left")
    ax1.set_ylabel("USD / GPU-hr", fontsize=9, color=theme.ink_muted)
    ax2.plot(px, py, color=theme.orange, linewidth=2.0)
    ax2.set_ylabel("EUR / MWh", fontsize=9, color=theme.ink_muted)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    _footer(fig, theme)
    return _save(fig, theme, "energy_overlay")


def generate_all(conn: sqlite3.Connection) -> list[Path]:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    produced = []
    for fn in (chart_headline, chart_dispersion, chart_sovereign, chart_energy_overlay):
        for theme in THEMES:
            try:
                path = fn(conn, theme)
                if path:
                    produced.append(path)
            except Exception:
                log.exception("%s (%s) failed (fail-soft)", fn.__name__, theme.name)
    log.info("charts: %s", [p.name for p in produced] or "none")
    return produced
