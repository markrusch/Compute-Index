"""Static site generation: the published EU-CRI pages, rendered from the DB + the docs.

WHY a generator and not hand-maintained HTML: the dashboard has to be correct the morning
after every daily run, and a page whose numbers are typed by hand is a page that will one
day disagree with `daily_index`. Everything numeric here is read out of SQLite at build
time and baked into the markup, so the pages are complete with JavaScript disabled.

Design contract (DESIGN.md, site/assets/tokens.css, site/components.html):
  * no external requests — tokens.css and site.css are inlined, fonts are system stacks,
    every graphic is inline SVG;
  * light + dark from one token file, explicit stamp beating the OS in both directions;
  * charts are hand-rolled SVG, greyscale by default, accent on the current value only;
  * a gap is published as a gap. No interpolation across a missing print, no stale value
    dressed as live.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta
from html import escape
from math import ceil, floor
from pathlib import Path

import yaml

from eucri import DISCLAIMER
from eucri.commands import COMPOSITE, HEADLINE, SERIES_7D
from eucri.config import Factors, load_factors, load_sovereign
from eucri.db import utc_now_iso
from eucri.outputs import markdown
from eucri.outputs.webdata import provider_links, sources_panel

log = logging.getLogger("eucri.outputs.site")

REPO_ROOT = Path(__file__).resolve().parents[3]
SITE_DIR = REPO_ROOT / "site"
ASSETS = SITE_DIR / "assets"
RESEARCH_SRC = REPO_ROOT / "research"

WINDOW_DAYS = 30

NAV: tuple[tuple[str, str], ...] = (
    ("index.html", "Index"),
    ("methodology.html", "Methodology"),
    ("research.html", "Research"),
    ("governance.html", "Governance"),
)

# Ticker order: the headline first, then its companions. Presentational only.
TICKER = (HEADLINE, SERIES_7D, "EU-CRI-H100-CLOUD", "EU-CRI-H100-MKT", COMPOSITE)

# The sub-index tiles, in publication order.
TILES = (
    "EU-CRI-H200", "EU-CRI-B300", "EU-CRI-A100", "EU-CRI-H100-PCIE",
    "EU-CRI-H100-SOV", "EU-CRI-H100-MKT", "EU-CRI-H100-NC", "EU-CRI-H100-HS",
)

SERIES_LABEL: dict[str, str] = {
    HEADLINE: "H100 SXM 80GB, on-demand, EU/EEA",
    SERIES_7D: "7-day mean of the headline",
    "EU-CRI-H100-CLOUD": "List-tier (cloud) sources only",
    "EU-CRI-H100-MKT": "Marketplace segment only",
    "EU-CRI-H100-NC": "Neocloud segment only",
    "EU-CRI-H100-HS": "Hyperscaler catalog segment",
    "EU-CRI-H100-SOV": "EU/EEA-headquartered operators",
    "EU-CRI-H100-PCIE": "H100 PCIe — priced as its own class",
    "EU-CRI-H200": "H200 SXM 141GB",
    "EU-CRI-B300": "B300 SXM",
    "EU-CRI-A100": "A100 SXM 80GB",
    COMPOSITE: "Chain-linked class composite (level, not $/hr)",
}

# Why a print gapped, in words. Colour is never the only channel and neither is a flag
# string: every gap on the page says what the gate was.
FLAG_TEXT: dict[str, str] = {
    "insufficient_sources": "below the provider gate",
    "insufficient_offers": "below the offer gate",
    "insufficient_history": "too few days in the window",
    "no_linkable_series": "no class linked on both endpoints",
    "no_executable_input": "list prices only, no executable quote",
    "bootstrap_weights": "bootstrap weighting",
    "correction": "revised",
    "base": "base value",
    "stale": "source older than the staleness limit",
    "no_print": "no print computed for this session",
}

# Constituent exclusion reasons, as short flag codes. A truncated word is not a flag.
EXCLUSION_CODE: dict[str, str] = {
    "out_of_population": "OOP",
    "insufficient_sources": "GATE",
    "insufficient_offers": "GATE",
    "stale": "STALE",
    "no_print": "NOPRINT",
    "excluded": "EXCL",
}

ICON = {
    "up": '<path d="M8 13V3.6M3.9 7.6 8 3.3l4.1 4.3" fill="none" stroke="currentColor"'
          ' stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>',
    "down": '<path d="M8 3v9.4M3.9 8.4 8 12.7l4.1-4.3" fill="none" stroke="currentColor"'
            ' stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"/>',
    "flat": '<path d="M3 8h10" fill="none" stroke="currentColor" stroke-width="1.9"'
            ' stroke-linecap="round"/>',
    "check": '<path d="M2.5 8.5 6.2 12.2 13.5 4.4" fill="none" stroke="currentColor"'
             ' stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"/>',
    "warn": '<path d="M8 1.6 15.2 14H0.8Z" fill="none" stroke="currentColor"'
            ' stroke-width="1.6" stroke-linejoin="round"/><path d="M8 6v3.4"'
            ' stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>'
            '<circle cx="8" cy="11.9" r="1" fill="currentColor"/>',
    "lock": '<rect x="2.8" y="6.9" width="10.4" height="7.3" rx="1" fill="none"'
            ' stroke="currentColor" stroke-width="1.5"/><path d="M5.4 6.9V4.8a2.6 2.6 0'
            ' 0 1 5.2 0v2.1" fill="none" stroke="currentColor" stroke-width="1.5"/>',
    "ext": '<path d="M6.5 3H3.2v9.8H13V9.5M9.4 2.6H13.4V6.6M13.2 2.8 7.4 8.6" fill="none"'
           ' stroke="currentColor" stroke-width="1.5" stroke-linecap="round"'
           ' stroke-linejoin="round"/>',
    "gap": '<path d="M2.5 8h3M10.5 8h3" fill="none" stroke="currentColor"'
           ' stroke-width="1.8" stroke-linecap="round"/>',
}

WORDMARK_SVG = (
    '<svg class="wordmark__mark" viewBox="0 0 24 24" width="20" height="20"'
    ' aria-hidden="true" focusable="false">'
    '<rect x="1.5" y="1.5" width="21" height="21" rx="2" fill="none" stroke="currentColor"'
    ' stroke-width="1.6"/>'
    '<path d="M6 16.5 10 10.5 14 13.5 18 7.5" fill="none" stroke="currentColor"'
    ' stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

FAVICON = (
    "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'"
    "%3E%3Crect width='32' height='32' rx='6' fill='%2317191c'/%3E%3Cpath d='M7 21 L13 13"
    " L18 17 L25 9' fill='none' stroke='%232fd6c3' stroke-width='2.6' stroke-linecap='round'"
    " stroke-linejoin='round'/%3E%3C/svg%3E"
)


# ==========================================================================
# small helpers
# ==========================================================================


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _icon(name: str, size: int = 12, cls: str = "ico") -> str:
    return (
        f'<svg class="{cls}" viewBox="0 0 16 16" width="{size}" height="{size}"'
        f' aria-hidden="true" focusable="false">{ICON[name]}</svg>'
    )


def _num(value: float | None, dp: int = 2, dash: str = "&#8212;") -> str:
    """Fixed-decimal so a live cell never reflows, and a missing value is never a zero."""
    return dash if value is None else f"{value:,.{dp}f}"


def _pct(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return (new - old) / old * 100.0


def _delta(pct: float | None, dp: int = 2) -> str:
    """Sign + arrow + colour. Three channels, so colour is never load-bearing alone."""
    if pct is None:
        return '<span class="delta delta--flat"><span class="u">n/a</span></span>'
    if abs(pct) < 0.005:
        return (
            f'<span class="delta delta--flat">{_icon("flat")}'
            f'<span class="num">&#177;0.00%</span></span>'
        )
    kind, arrow = ("up", "up") if pct > 0 else ("down", "down")
    sign = "+" if pct > 0 else "&#8722;"
    return (
        f'<span class="delta delta--{kind}">{_icon(arrow)}'
        f'<span class="num">{sign}{abs(pct):.{dp}f}%</span></span>'
    )


def _human_date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b %Y").lstrip("0")


def _flag_words(flags: str | None) -> str:
    parts = [f.strip() for f in (flags or "").split(",") if f.strip()]
    return " · ".join(FLAG_TEXT.get(f, f.replace("_", " ")) for f in parts)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ==========================================================================
# data access — always the latest revision of a (date, series)
# ==========================================================================


@dataclass(frozen=True)
class Point:
    """One session on the published curve. `value` None means the print gapped."""

    date: str
    value: float | None
    value_eur: float | None = None
    flags: str = ""


def series_history(
    conn: sqlite3.Connection, series: str, *, since: str | None = None
) -> list[Point]:
    """Published history for one series, one row per date, latest revision only.

    A correction is stored as a NEW revision rather than an edit (db triggers enforce
    append-only), so any read that forgets `MAX(revision)` silently republishes a value
    that was already withdrawn. Every read path on the site goes through here.
    """
    sql = (
        "SELECT d.date, d.value_usd, d.value_eur, d.flags FROM daily_index d JOIN ("
        "  SELECT date, series, MAX(revision) AS rev FROM daily_index"
        "  WHERE series = ? GROUP BY date, series"
        ") m ON d.date = m.date AND d.series = m.series AND d.revision = m.rev"
        " WHERE d.series = ?"
    )
    params: list[object] = [series, series]
    if since is not None:
        sql += " AND d.date >= ?"
        params.append(since)
    sql += " ORDER BY d.date"
    return [
        Point(r["date"], r["value_usd"], r["value_eur"], r["flags"] or "")
        for r in conn.execute(sql, params)
    ]


def latest_print(conn: sqlite3.Connection, series: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM daily_index WHERE series = ? ORDER BY date DESC, revision DESC LIMIT 1",
        (series,),
    ).fetchone()


def previous_published(
    conn: sqlite3.Connection, series: str, before: str
) -> tuple[str, float] | None:
    row = conn.execute(
        "SELECT d.date, d.value_usd FROM daily_index d JOIN ("
        "  SELECT date, MAX(revision) AS rev FROM daily_index WHERE series = ? GROUP BY date"
        ") m ON d.date = m.date AND d.revision = m.rev"
        " WHERE d.series = ? AND d.date < ? AND d.value_usd IS NOT NULL"
        " ORDER BY d.date DESC LIMIT 1",
        (series, series, before),
    ).fetchone()
    return (row["date"], row["value_usd"]) if row else None


def constituents_for(conn: sqlite3.Connection, series: str, date: str) -> list[sqlite3.Row]:
    rev = conn.execute(
        "SELECT MAX(revision) AS rev FROM daily_index WHERE date = ? AND series = ?",
        (date, series),
    ).fetchone()
    if rev is None or rev["rev"] is None:
        return []
    return list(
        conn.execute(
            "SELECT * FROM constituents WHERE date = ? AND series = ? AND revision = ?"
            " ORDER BY included DESC, price_usd",
            (date, series, rev["rev"]),
        )
    )


def _window(end: str, days: int = WINDOW_DAYS) -> list[str]:
    last = date_type.fromisoformat(end)
    return [(last - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def _windowed(points: list[Point], dates: list[str]) -> list[Point]:
    """Align a sparse series onto a full calendar window; absent days become gaps."""
    by_date = {p.date: p for p in points}
    return [by_date.get(d, Point(d, None, None, "no_print")) for d in dates]


# ==========================================================================
# charts — hand-rolled SVG, no libraries
# ==========================================================================

PL, PR, PT, PB = 8.0, 816.0, 16.0, 268.0  # plot box; tick text lives in the 816..880 gutter


def _nice_step(raw: float) -> float:
    from math import log10

    if raw <= 0:
        return 1.0
    mag = 10 ** floor(log10(raw))
    for mult in (1, 2, 2.5, 5, 10):
        if raw <= mult * mag:
            return mult * mag
    return 10 * mag


def _bounds(values: list[float]) -> tuple[float, float, float]:
    """(lo, hi, step) for a truncated axis. Truncated, so the chart is a LINE, never an area."""
    lo, hi = min(values), max(values)
    if hi == lo:
        pad = max(abs(hi) * 0.02, 0.05)
        lo, hi = lo - pad, hi + pad
    else:
        pad = (hi - lo) * 0.30
        lo, hi = lo - pad, hi + pad
    step = _nice_step((hi - lo) / 4)
    return floor(lo / step) * step, ceil(hi / step) * step, step


def line_chart(points: list[Point], *, symbol: str, ccy: str = "$", dp: int = 2) -> str:
    """A single-series time-series chart. Greyscale line, accent only on the current value.

    Gaps are drawn as gaps: the path breaks, and each missing session gets a hollow tick
    on the baseline. Nothing is interpolated across a session the index did not publish.
    """
    n = len(points)
    vals = [p.value for p in points if p.value is not None]
    if not vals:
        return (
            '<div class="gapnote">' + _icon("warn", 14)
            + f"<p>No published value for <strong>{_e(symbol)}</strong> anywhere in the last"
            f" {n} sessions. The series is gapped, not flat — see the table view below.</p></div>"
        )
    lo, hi, step = _bounds(vals)
    dx = (PR - PL) / max(1, n - 1)

    def x(i: int) -> float:
        return round(PL + i * dx, 1)

    def y(v: float) -> float:
        return round(PB - (v - lo) / (hi - lo) * (PB - PT), 1)

    grid, ticks = [], []
    t = lo
    while t <= hi + step / 2:
        gy = y(t)
        grid.append(f'<line class="ch-grid" x1="{PL}" y1="{gy}" x2="{PR}" y2="{gy}"/>')
        ticks.append(f'<text class="ch-tick" x="826" y="{gy + 4}">{ccy}{t:,.{dp}f}</text>')
        t += step

    # Segments join only calendar-adjacent published sessions.
    segments: list[list[tuple[float, float]]] = []
    run: list[tuple[float, float]] = []
    for i, p in enumerate(points):
        if p.value is None:
            if len(run) > 1:
                segments.append(run)
            run = []
        else:
            run.append((x(i), y(p.value)))
    if len(run) > 1:
        segments.append(run)
    paths = "".join(
        '<path class="ch-line" d="M'
        + " L".join(f"{px} {py}" for px, py in seg)
        + '"/>'
        for seg in segments
    )
    # An isolated print (both neighbours gapped) would otherwise draw nothing at all.
    isolated = "".join(
        f'<circle class="ch-marker-ring" cx="{x(i)}" cy="{y(p.value)}" r="4.5"/>'
        f'<circle cx="{x(i)}" cy="{y(p.value)}" r="2.6" fill="var(--chart-line)"/>'
        for i, p in enumerate(points)
        if p.value is not None
        and (i == 0 or points[i - 1].value is None)
        and (i == n - 1 or points[i + 1].value is None)
    )
    gapmarks = "".join(
        f'<line class="ch-gapmark" x1="{x(i)}" y1="{PB - 4}" x2="{x(i)}" y2="{PB + 4}"/>'
        for i, p in enumerate(points)
        if p.value is None
    )

    published_idx = [(i, p.value) for i, p in enumerate(points) if p.value is not None]
    last_i, last_v = published_idx[-1]
    low_i, low_v = min(published_idx, key=lambda iv: iv[1])
    ly = y(last_v)
    labels = [
        f'<text class="ch-cur" x="{min(x(last_i) - 8, PR - 8)}" y="{ly - 12}"'
        f' text-anchor="end">{ccy}{last_v:,.{dp}f}</text>'
    ]
    if low_i != last_i:
        anchor = "start" if low_i < n / 2 else "end"
        labels.append(
            f'<text class="ch-note" x="{x(low_i) + (8 if anchor == "start" else -8)}"'
            f' y="{y(low_v) + 20}" text-anchor="{anchor}">'
            f"{n}-day low {ccy}{low_v:,.{dp}f}</text>"
        )

    hits = []
    hw = min(28.0, dx)
    for i, p in enumerate(points):
        if p.value is None:
            continue
        px, py = x(i), y(p.value)
        flip = px > PR - 190
        tx = px - 164 if flip else px + 12
        ty = max(PT, min(py - 24, PB - 50))
        hits.append(
            f'<g class="hp" tabindex="0" role="img" aria-label="{_e(_human_date(p.date))}:'
            f' {ccy}{p.value:,.{dp}f} per GPU-hour">'
            f'<line class="hp-cross" x1="{px}" y1="{PT}" x2="{px}" y2="{PB}"/>'
            f'<circle class="hp-dot" cx="{px}" cy="{py}" r="4.5"/>'
            f'<g class="hp-tip" transform="translate({round(tx, 1)} {round(ty, 1)})">'
            f'<rect class="hp-box" width="152" height="46" rx="3"/>'
            f'<line class="hp-key" x1="11" y1="18" x2="25" y2="18"/>'
            f'<text class="hp-val" x="31" y="22">{ccy}{p.value:,.{dp}f}</text>'
            f'<text class="hp-lab" x="11" y="37">{_e(_human_date(p.date))}</text></g>'
            f'<rect class="hp-hit" x="{round(px - hw / 2, 1)}" y="{PT}" width="{round(hw, 1)}"'
            f' height="{PB - PT}"/></g>'
        )

    xlabels = []
    for i in (0, n // 4, n // 2, (3 * n) // 4, n - 1):
        anchor = "start" if i == 0 else "end" if i == n - 1 else "middle"
        stamp = datetime.strptime(points[i].date, "%Y-%m-%d").strftime("%d %b").lstrip("0")
        xlabels.append(
            f'<text class="ch-tick" x="{x(i)}" y="288" text-anchor="{anchor}">{stamp}</text>'
        )

    gapped = sum(1 for p in points if p.value is None)
    summary = (
        f"{symbol}, {n} sessions to {_human_date(points[-1].date)}."
        f" {n - gapped} published, {gapped} gapped."
        f" Latest {ccy}{last_v:,.{dp}f}."
    )
    return (
        '<div class="scroll-x"><svg class="chart" viewBox="0 0 880 300" role="group"'
        f' aria-label="{_e(summary)}">'
        f'<g aria-hidden="true">{"".join(grid)}'
        f'<line class="ch-axis" x1="{PL}" y1="{PB}" x2="{PR}" y2="{PB}"/></g>'
        f"{paths}{isolated}"
        f'<g aria-hidden="true">{gapmarks}{"".join(ticks)}{"".join(xlabels)}'
        f'{"".join(labels)}</g>'
        f'<line class="ch-marker-rule" x1="{PL}" y1="{ly}" x2="{x(last_i)}" y2="{ly}"/>'
        f'<circle class="ch-marker-ring" cx="{x(last_i)}" cy="{ly}" r="6"/>'
        f'<circle class="ch-marker" cx="{x(last_i)}" cy="{ly}" r="4"/>'
        f'<g class="hp-layer">{"".join(hits)}</g>'
        "</svg></div>"
    )


def sparkline(points: list[Point]) -> str:
    """A 96x28 trend for a tile. Rendered only when at least two sessions published."""
    vals = [(i, p.value) for i, p in enumerate(points) if p.value is not None]
    if len(vals) < 2:
        return ""
    lo = min(v for _, v in vals)
    hi = max(v for _, v in vals)
    span = (hi - lo) or 1.0
    n = max(1, len(points) - 1)

    def sx(i: int) -> float:
        return round(4 + i / n * 88, 1)

    def sy(v: float) -> float:
        return round(24 - (v - lo) / span * 20, 1)

    d = " L".join(f"{sx(i)} {sy(v)}" for i, v in vals)
    ex, ey = sx(vals[-1][0]), sy(vals[-1][1])
    return (
        '<svg class="spark" viewBox="0 0 96 28" width="96" height="28" aria-hidden="true"'
        f' focusable="false"><path class="spark__line" d="M{d}"/>'
        f'<circle class="spark__ring" cx="{ex}" cy="{ey}" r="4.5"/>'
        f'<circle class="spark__dot" cx="{ex}" cy="{ey}" r="2.8"/></svg>'
    )


# ==========================================================================
# page shell
# ==========================================================================

_THEME_HEAD = (
    "(function(){try{var t=localStorage.getItem('eucri-theme');"
    "if(t==='light'||t==='dark')document.documentElement.setAttribute('data-theme',t);}"
    "catch(e){}"
    # Marks the document as scripted, before body paints. The one-shot fade-in CSS
    # (.js-boot body, see site.css) only fires when this class is present, so with
    # scripting off the class is never added and the page renders at full opacity
    # immediately — nothing to skip, nothing to wait for.
    "document.documentElement.classList.add('js-boot');"
    "})();"
)

_THEME_BODY = (
    "(function(){var r=document.documentElement;"
    "var v=r.getAttribute('data-theme')||'auto';"
    "var el=document.getElementById('th-'+v);if(el)el.checked=true;"
    "document.addEventListener('change',function(e){var t=e.target;"
    "if(!t||t.name!=='theme')return;"
    "if(t.value==='auto'){r.removeAttribute('data-theme');"
    "try{localStorage.removeItem('eucri-theme');}catch(x){}}"
    "else{r.setAttribute('data-theme',t.value);"
    "try{localStorage.setItem('eucri-theme',t.value);}catch(x){}}});})();"
)

# Same-origin refresh: re-stamps the ticker and the hero if the pipeline has published
# since the page was served. Pure enhancement — every value is already in the markup.
_REFRESH_JS = """(function(){
var stamp=document.getElementById('asof'),hero=document.getElementById('hero-usd');
if(!stamp||!hero)return;
var baked=stamp.getAttribute('data-generated');
function paint(d){
 var s=d.series&&d.series['EU-CRI-H100'];if(!s||s.value_usd==null)return;
 var v=s.value_usd.toFixed(2);
 if(v!==hero.textContent){hero.textContent=v;hero.classList.remove('is-ticked');
  void hero.offsetWidth;hero.classList.add('is-ticked');}
 var eur=document.getElementById('hero-eur');
 if(eur&&s.value_eur!=null)eur.textContent=s.value_eur.toFixed(2);
 stamp.textContent='AS OF '+d.generated_at.replace('T',' ').replace('Z',' UTC');
 stamp.setAttribute('data-generated',d.generated_at);}
function poll(){fetch('data/latest.json',{cache:'no-store'}).then(function(r){
 return r.ok?r.json():null;}).then(function(d){
 if(d&&d.generated_at&&d.generated_at!==baked){baked=d.generated_at;paint(d);}
 }).catch(function(){});}
document.addEventListener('visibilitychange',function(){
 if(document.visibilityState==='visible')poll();});
setInterval(poll,300000);})();"""


def _css() -> str:
    return _read(ASSETS / "tokens.css") + "\n" + _read(ASSETS / "site.css")


def _masthead(current: str, prefix: str, ticker: str) -> str:
    links = "".join(
        f'<a href="{prefix}{href}"'
        + (' aria-current="page"' if href == current else "")
        + f">{_e(label)}</a>"
        for href, label in NAV
    )
    return f"""<header class="masthead">
  <div class="masthead__bar">
    <div class="wrap masthead__inner">
      <a class="wordmark" href="{prefix}index.html">{WORDMARK_SVG}
        <span class="wordmark__text">EU&#8209;CRI</span>
        <span class="wordmark__sub">European Compute Reference Index</span>
      </a>
      <nav class="nav" aria-label="Primary">{links}</nav>
      <div class="masthead__tools">
        <fieldset class="seg seg--theme">
          <legend class="vh">Colour theme</legend>
          <input type="radio" id="th-auto" name="theme" value="auto" checked>
          <label for="th-auto">Auto</label>
          <input type="radio" id="th-light" name="theme" value="light">
          <label for="th-light">Light</label>
          <input type="radio" id="th-dark" name="theme" value="dark">
          <label for="th-dark">Dark</label>
        </fieldset>
      </div>
    </div>
  </div>
{ticker}</header>"""


def _footer(ctx: SiteContext, prefix: str) -> str:
    return f"""<footer class="footer">
  <div class="wrap footer__inner">
    <div class="footer__cols">
      <div class="footer__brand">
        <span class="wordmark__text">EU&#8209;CRI</span>
        <p class="footer__tag">A daily, reproducible reference price for renting AI compute
        delivered from the EU/EEA. Every print is recomputable from public sources using the
        published code.</p>
      </div>
      <nav class="footer__nav" aria-label="Footer, index">
        <h4>Index</h4>
        <a href="{prefix}index.html">Headline &amp; sub&#8209;indices</a>
        <a href="{prefix}index.html#constituents">Constituents</a>
        <a href="{prefix}index.html#quality">Data quality</a>
      </nav>
      <nav class="footer__nav" aria-label="Footer, governance">
        <h4>Governance</h4>
        <a href="{prefix}methodology.html">Methodology v{_e(ctx.version)}</a>
        <a href="{prefix}governance.html">Oversight &amp; complaints</a>
        <a href="{prefix}methodology.html#lock">Methodology lock</a>
      </nav>
      <nav class="footer__nav" aria-label="Footer, access">
        <h4>Access</h4>
        <a href="{prefix}data/latest.json">latest.json</a>
        <a href="{prefix}data/index_history.csv">index_history.csv</a>
        <a href="{prefix}research.html">Research notes</a>
      </nav>
    </div>
    <div class="disclaimer">
      <h4 class="disclaimer__h">Important information</h4>
      <p>{_e(DISCLAIMER)}</p>
      <p>EU&#8209;CRI is a <strong>price-transparency benchmark, not a settlement
      benchmark</strong>. It is not transaction-based, is not administered by an authorised
      benchmark administrator, and must not be referenced in a financial contract. Values are
      derived from third-party public price surfaces believed to be reliable but are
      <strong>not independently verified</strong>; observed prices may differ materially from
      prices actually obtainable. Past values are not indicative of future values. A session
      with too few qualifying providers is <strong>published as a gap</strong> — never
      back-filled, never carried forward.</p>
      <p class="disclaimer__meta num">EU&#8209;CRI&#8209;M v{_e(ctx.version)} &#183;
      methodology hash sha256:{_e(ctx.lock_hash[:12])}&#8230; &#183; generated
      {_e(ctx.generated_at)} &#183; administrator Mark Rusch &#183; USD primary, EUR companion
      at the ECB reference rate dated on or before the print date.</p>
    </div>
  </div>
</footer>"""


def _shell(
    ctx: SiteContext,
    *,
    title: str,
    description: str,
    current: str,
    body: str,
    prefix: str = "",
    ticker: str = "",
    extra_js: str = "",
) -> str:
    scripts = f"<script>{_THEME_BODY}</script>"
    if extra_js:
        scripts += f"<script>{extra_js}</script>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="{_e(description)}">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" media="(prefers-color-scheme: light)" content="#f3f3f3">
<meta name="theme-color" media="(prefers-color-scheme: dark)" content="#101113">
<link rel="icon" href="{FAVICON}">
<script>{_THEME_HEAD}</script>
<style>
{_css()}
</style>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
{_masthead(current, prefix, ticker)}
{body}
{_footer(ctx, prefix)}
{scripts}
</body>
</html>
"""


# ==========================================================================
# build context
# ==========================================================================


@dataclass
class SiteContext:
    conn: sqlite3.Connection
    factors: Factors
    version: str
    lock_hash: str
    generated_at: str
    head: sqlite3.Row | None
    date: str


def _lock_hash() -> str:
    path = REPO_ROOT / "METHODOLOGY.lock"
    if not path.exists():
        return "unlocked"
    data = yaml.safe_load(_read(path)) or {}
    return str((data.get("current") or {}).get("hash", "unlocked"))


# ==========================================================================
# dashboard sections
# ==========================================================================


def _ticker(ctx: SiteContext) -> str:
    items = []
    for i, series in enumerate(TICKER):
        row = latest_print(ctx.conn, series)
        if row is None:
            continue
        dot = '<span class="live-dot" aria-hidden="true"></span>' if i == 0 else ""
        short = series.replace("EU-CRI-", "")
        if row["value_usd"] is None:
            body = (
                '<span class="ticker__val u">&#8212;</span>'
                '<span class="ticker__stamp">GAP</span>'
            )
        else:
            prev = previous_published(ctx.conn, series, row["date"])
            dp = 2 if series != COMPOSITE else 1
            body = (
                f'<span class="ticker__val num">{_num(row["value_usd"], dp)}</span>'
                f'{_delta(_pct(row["value_usd"], prev[1] if prev else None))}'
            )
        items.append(
            f'<div class="ticker__item" role="listitem">{dot}'
            f'<span class="ticker__sym">{_e(short)}</span>{body}</div>'
        )
    stamp = (
        f'<div class="ticker__item ticker__item--meta" role="listitem">'
        f'<span class="ticker__stamp num" id="asof" data-generated="{_e(ctx.generated_at)}">'
        f'AS OF {_e(ctx.generated_at.replace("T", " ").replace("Z", " UTC"))}</span></div>'
    )
    return (
        '<div class="ticker"><div class="ticker__track scroll-x" role="list"'
        ' aria-label="EU-CRI series, last published values">'
        + "".join(items)
        + stamp
        + "</div></div>"
    )


def _print_card(ctx: SiteContext) -> str:
    head = ctx.head
    assert head is not None
    ru = ctx.factors.reference_unit
    desc = (
        f"NVIDIA {ru.gpu_model.replace('_', ' ')} 80GB, {ru.term.replace('_', '-')},"
        f" {ru.location.replace('_', '/')} regions. Weighted median over offers,"
        f" per GPU-hour, ex-VAT."
    )
    gate = ctx.factors.aggregation.min_providers
    published = head["value_usd"] is not None

    if published:
        prev = previous_published(ctx.conn, HEADLINE, head["date"])
        pct = _pct(head["value_usd"], prev[1] if prev else None)
        gap_days = (
            (date_type.fromisoformat(head["date"]) - date_type.fromisoformat(prev[0])).days
            if prev
            else 0
        )
        vs = (
            f'<span class="print__vs">vs {_e(_human_date(prev[0]))} print'
            f"{f' ({gap_days} sessions back)' if gap_days > 1 else ''}</span>"
            if prev
            else '<span class="print__vs">first published print</span>'
        )
        abs_move = (
            f'<span class="print__abs num">{"+" if head["value_usd"] >= prev[1] else "&#8722;"}'
            f'{abs(head["value_usd"] - prev[1]):,.2f}</span>'
            if prev
            else ""
        )
        figure = (
            '<div class="print__figure">'
            '<span class="print__ccy ccy-usd" aria-hidden="true">$</span>'
            '<span class="print__ccy ccy-eur" aria-hidden="true">&#8364;</span>'
            f'<span class="print__value num ccy-usd" id="hero-usd">'
            f'{_num(head["value_usd"])}</span>'
            f'<span class="print__value num ccy-eur" id="hero-eur">'
            f'{_num(head["value_eur"])}</span>'
            '<span class="print__unit">/GPU&#8209;hr</span></div>'
        )
        row = f'<div class="print__row">{_delta(pct)}{abs_move}{vs}</div>'
        status = (
            f'<span class="chip chip--good">{_icon("check")}<span>Index live &#183;'
            f' {head["n_sources"]} of {gate} providers</span></span>'
        )
    else:
        figure = (
            '<div class="print__figure"><span class="print__value num" id="hero-usd"'
            ' aria-label="No value published">&#8212;&#8212;</span>'
            '<span class="print__unit">no print this session</span></div>'
        )
        last = previous_published(ctx.conn, HEADLINE, head["date"])
        row = (
            '<div class="print__row"><span class="print__vs">Last published '
            f'{_e(_human_date(last[0]))} at ${_num(last[1])}. Not carried forward.</span></div>'
            if last
            else '<div class="print__row"><span class="print__vs">No print published yet.'
            "</span></div>"
        )
        status = (
            f'<span class="chip chip--warning">{_icon("warn")}<span>Gapped &#183;'
            f' {_e(_flag_words(head["flags"]))} ({head["n_sources"]} of {gate} providers)'
            "</span></span>"
        )

    chips = (
        f'<div class="print__chips">{status}'
        f'<span class="chip chip--neutral">{_icon("lock")}<span>Hash&#8209;locked'
        f' <span class="num">v{_e(ctx.version)}</span></span></span>'
        f'<span class="chip chip--neutral"><span>{head["n_executable"]} executable'
        f" input{'s' if head['n_executable'] != 1 else ''}</span></span></div>"
    )

    ccy_toggle = (
        '<fieldset class="seg seg--ccy"><legend class="vh">Quote currency</legend>'
        '<input type="radio" id="ccy-usd" name="ccy" value="usd" checked>'
        '<label for="ccy-usd">USD</label>'
        '<input type="radio" id="ccy-eur" name="ccy" value="eur">'
        '<label for="ccy-eur">EUR</label></fieldset>'
        if published
        else ""
    )

    fx = (
        f'{_num(head["fx_rate"], 4)} @ {_e(head["fx_date"])}'
        if head["fx_rate"]
        else "&#8212;"
    )
    eur = f'&#8364;{_num(head["value_eur"], 6)}' if head["value_eur"] is not None else "&#8212;"
    return f"""<section class="print" aria-labelledby="print-h">
  <div class="print__main">
    <div class="print__head">
      <div>
        <div class="eyebrow">Headline index</div>
        <h2 class="print__sym" id="print-h">EU&#8209;CRI&#8209;H100</h2>
        <p class="print__desc">{_e(desc)}</p>
      </div>
      {ccy_toggle}
    </div>
    {figure}
    {row}
    {chips}
  </div>
  <div class="print__meta">
    <dl class="metagrid">
      <div><dt>Print date</dt><dd class="num">{_e(head["date"])}</dd></div>
      <div><dt>EUR companion</dt><dd class="num">{eur}</dd></div>
      <div><dt>ECB EUR/USD</dt><dd class="num">{fx}</dd></div>
      <div><dt>Providers</dt><dd class="num">{head["n_sources"]} in panel</dd></div>
      <div><dt>Estimator</dt><dd>{_e(ctx.factors.aggregation.estimator.replace("_", " "))}</dd>
      </div>
      <div><dt>Methodology</dt><dd><a href="methodology.html">EU&#8209;CRI&#8209;M
        v{_e(ctx.version)}</a></dd></div>
    </dl>
  </div>
</section>"""


def _tiles(ctx: SiteContext) -> str:
    dates = _window(ctx.date, 14)
    out = []
    for series in TILES:
        row = latest_print(ctx.conn, series)
        label = SERIES_LABEL.get(series, series)
        short = series.replace("EU-CRI-", "")
        head = (
            f'<div class="tile__head"><span class="tile__sym">{_e(short)}</span>'
            f'<span class="tile__note">{_e(label)}</span></div>'
        )
        if row is None:
            out.append(
                f'<article class="tile tile--gap">{head}'
                f'<div class="tile__body"><div class="tile__gap">'
                f'<span class="tile__dash">&#8212;&#8212;</span></div></div>'
                f'<div class="tile__foot"><span class="chip chip--neutral">'
                f"<span>Not yet computed</span></span></div></article>"
            )
            continue
        history = _windowed(series_history(ctx.conn, series, since=dates[0]), dates)
        if row["value_usd"] is not None:
            prev = previous_published(ctx.conn, series, row["date"])
            body = (
                f'<div class="tile__num"><span class="tile__ccy" aria-hidden="true">$</span>'
                f'<span class="tile__val num">{_num(row["value_usd"])}</span></div>'
                f"{sparkline(history)}"
            )
            foot = _delta(_pct(row["value_usd"], prev[1] if prev else None))
            cls = "tile"
        else:
            last = previous_published(ctx.conn, series, row["date"])
            last_txt = (
                f"last ${_num(last[1])} on {_e(_human_date(last[0]))}"
                if last
                else "never published"
            )
            body = (
                f'<div class="tile__gap"><span class="tile__dash">&#8212;&#8212;</span>'
                f'<span class="tile__last">{last_txt}</span></div>{sparkline(history)}'
            )
            foot = (
                f'<span class="chip chip--warning">{_icon("gap")}'
                f'<span>{_e(_flag_words(row["flags"]) or "gapped")}</span></span>'
            )
            cls = "tile tile--gap"
        out.append(
            f'<article class="{cls}">{head}'
            f'<div class="tile__body">{body}</div>'
            f'<div class="tile__foot">{foot}</div></article>'
        )
    return '<div class="tiles">' + "".join(out) + "</div>"


def _chart_card(ctx: SiteContext) -> str:
    dates = _window(ctx.date, WINDOW_DAYS)
    points = _windowed(series_history(ctx.conn, HEADLINE, since=dates[0]), dates)
    vals = [p.value for p in points if p.value is not None]
    published = len(vals)
    meta = (
        f"Last ${_num(vals[-1])} &#183; high ${_num(max(vals))} &#183; low ${_num(min(vals))}"
        if vals
        else "No published print in the window"
    )
    rows = "".join(
        f'<tr><td class="num">{_e(_human_date(p.date))}</td>'
        + (
            f'<td class="num ta-r">{_num(p.value)}</td><td>published</td>'
            if p.value is not None
            else '<td class="num ta-r u">&#8212;</td><td>gap &#183; '
            + _e(_flag_words(p.flags) or "not computed")
            + "</td>"
        )
        + "</tr>"
        for p in points
    )
    return f"""<div class="card">
  <div class="card__head">
    <div><h3 class="card__title">EU&#8209;CRI&#8209;H100</h3>
    <p class="card__sub">USD per GPU-hour &#183; {WINDOW_DAYS} sessions to
    {_e(_human_date(ctx.date))} &#183; {published} published, {WINDOW_DAYS - published}
    gapped</p></div>
    <span class="card__meta num">{meta}</span>
  </div>
  <div class="card__body">
    {line_chart(points, symbol="EU-CRI-H100")}
    <p class="ledger__d" style="margin-top:var(--space-4)">A gapped session is drawn as a
    hairline tick on the baseline and the line breaks across it. Nothing is interpolated:
    the index publishes a gap rather than a value it cannot defend.</p>
    <details class="tableview"><summary>Table view &#8212; {WINDOW_DAYS} sessions</summary>
      <div class="tableview__scroll"><table><caption class="vh">Every session in the window,
      published or gapped</caption><thead><tr><th scope="col">Session</th>
      <th scope="col" class="ta-r">USD/GPU-hr</th><th scope="col">State</th></tr></thead>
      <tbody>{rows}</tbody></table></div>
    </details>
  </div>
</div>"""


def _tier_badge(provider: str, tier: str, factors: Factors) -> tuple[str, str]:
    """L1/L2/L3 is ORDINAL: executable quote > neocloud list > hyperscaler catalog."""
    if tier == "executable":
        return "L1", "Executable marketplace quote"
    if factors.segment_of(provider) == "hyperscaler":
        return "L3", "Hyperscaler catalog list price"
    return "L2", "Published neocloud list price"


def _constituents_card(ctx: SiteContext) -> str:
    rows = constituents_for(ctx.conn, HEADLINE, ctx.date)
    if not rows:
        return (
            '<div class="card"><div class="card__body"><div class="gapnote">'
            + _icon("warn", 14)
            + "<p>No constituent set stored for this session.</p></div></div></div>"
        )
    head = ctx.head
    assert head is not None
    links = provider_links()
    sovereign = load_sovereign()
    max_w = max((r["weight"] for r in rows if r["included"]), default=1.0) or 1.0
    body = []
    for c in rows:
        tier, tier_title = _tier_badge(c["provider"], c["tier"], ctx.factors)
        segment = ctx.factors.segment_of(c["provider"])
        flags = []
        if c["exclusion_reason"] == "trimmed" and c["included"]:
            flags.append(("TRIM", "Clamped to the k-th order statistic by the trim"))
        if "weight_capped" in (c["flags"] or ""):
            flags.append(("CAP", "Weight limited by the 25% concentration cap"))
        if "jump" in (c["flags"] or ""):
            flags.append(("JUMP", "Moved more than the jump threshold day-over-day"))
        if c["provider"] in sovereign:
            flags.append(("SOV", "EU/EEA-headquartered operator"))
        if not c["included"]:
            reason = c["exclusion_reason"] or "excluded"
            flags.append(
                (
                    EXCLUSION_CODE.get(reason, reason.upper().replace("_", " ")[:10]),
                    f"Excluded: {reason.replace('_', ' ')}",
                )
            )
        flag_html = "".join(
            f'<span class="flag" title="{_e(t)}">{_e(f)}</span>' for f, t in flags
        ) or '<span class="u">&#8212;</span>'
        price = (
            f'<td class="ta-r num strong">{_num(c["price_usd"], 4)}</td>'
            if c["price_usd"]
            else '<td class="ta-r u">&#8212;</td>'
        )
        weight = (
            f'<td class="ta-r"><span class="wcell"><span class="num">'
            f'{_num(c["weight"], 1)}%</span><span class="meter" aria-hidden="true">'
            f'<span class="meter__fill" style="width:{c["weight"] / max_w * 100:.1f}%">'
            f"</span></span></span></td>"
            if c["included"]
            else '<td class="ta-r num u">0.0%</td>'
        )
        url = (links.get(c["provider"]) or {}).get("url")
        name = _e(c["source"]) if c["source"] else "page"
        src = (
            f'<td class="ta-r"><a class="srclink" href="{_e(url)}" rel="noopener">'
            f'{name}{_icon("ext")}</a></td>'
            if url
            else f'<td class="ta-r u">{name}</td>'
        )
        body.append(
            f'<tr><th scope="row" class="grid__name">{_e(c["provider"])}</th>'
            f'<td class="u">{_e(segment)}</td>'
            f'<td class="ta-c"><span class="badge badge--{tier.lower()}"'
            f' title="{_e(tier_title)}">{tier}</span></td>'
            f"{price}{weight}"
            f'<td class="grid__flags">{flag_html}</td>{src}</tr>'
        )
    k = ctx.factors.aggregation.trim_for(sum(1 for r in rows if r["included"]))
    total = sum(r["weight"] for r in rows if r["included"])
    value_cell = (
        f'<td class="ta-r num strong">{_num(head["value_usd"], 4)}</td>'
        if head["value_usd"] is not None
        else '<td class="ta-r u">no print</td>'
    )
    return f"""<div class="card card__body--flush">
<div class="scroll-x">
<table class="grid">
  <caption class="vh">EU-CRI-H100 constituents at the {_e(ctx.date)} print</caption>
  <thead><tr>
    <th scope="col">Provider</th>
    <th scope="col">Segment</th>
    <th scope="col" class="ta-c">Tier</th>
    <th scope="col" class="ta-r">Price <span class="u">USD/GPU&#8209;hr</span></th>
    <th scope="col" class="ta-r">Weight</th>
    <th scope="col">Flags</th>
    <th scope="col" class="ta-r">Source</th>
  </tr></thead>
  <tbody>{"".join(body)}</tbody>
  <tfoot><tr>
    <th scope="row" colspan="3">Weighted median over offers</th>
    {value_cell}
    <td class="ta-r num strong">{_num(total, 1)}%</td>
    <td colspan="2" class="u">Trim k={k} each end &#183; 25% concentration cap</td>
  </tr></tfoot>
</table>
</div></div>"""


def _quality_card(ctx: SiteContext) -> str:
    head = ctx.head
    assert head is not None
    agg = ctx.factors.aggregation
    rows = constituents_for(ctx.conn, HEADLINE, ctx.date)
    included = [r for r in rows if r["included"]]
    exec_weight = sum(r["weight"] for r in included if r["tier"] == "executable")
    total_weight = sum(r["weight"] for r in included) or 1.0
    exec_share = exec_weight / total_weight * 100.0
    n = head["n_sources"] or 0
    passes = head["value_usd"] is not None
    dates = _window(ctx.date, WINDOW_DAYS)
    hist = _windowed(series_history(ctx.conn, HEADLINE, since=dates[0]), dates)
    published = sum(1 for p in hist if p.value is not None)
    capped = any("weight_capped" in (r["flags"] or "") for r in rows)
    fx_age = (
        (date_type.fromisoformat(ctx.date) - date_type.fromisoformat(head["fx_date"])).days
        if head["fx_date"]
        else None
    )
    gate_chip = (
        f'<span class="chip chip--good">{_icon("check")}<span>Gate met</span></span>'
        if passes
        else f'<span class="chip chip--warning">{_icon("warn")}<span>Gate not met</span></span>'
    )
    cap_pct = f"{ctx.factors.weights.max_weight_share_pct:,.0f}"
    cap_words = "bound on this print" if capped else "did not bind on this print"
    fx_vintage = f"T&#8722;{fx_age}" if fx_age is not None else "&#8212;"
    return f"""<div class="card" id="quality">
  <div class="card__head">
    <div><h3 class="card__title">Data quality</h3>
    <p class="card__sub">Everything that decides whether this session publishes at all</p>
    </div>
    <span class="card__meta">{gate_chip}</span>
  </div>
  <div class="qgrid">
    <div class="qstat">
      <span class="qstat__k">Publication gate</span>
      <span class="qstat__v">{n}<span class="u"> / {agg.min_providers}</span></span>
      <span class="qstat__n">Qualifying providers against the minimum. Below it the value is
      null and the session is flagged, never estimated.</span>
    </div>
    <div class="qstat">
      <span class="qstat__k">Executable share</span>
      <span class="qstat__v">{exec_share:,.1f}<span class="u">%</span></span>
      <span class="qbar" aria-hidden="true"><i style="width:{min(exec_share, 100):.1f}%"></i>
      </span>
      <span class="qstat__n">Share of index weight from executable marketplace quotes;
      the rest is published list price.</span>
    </div>
    <div class="qstat">
      <span class="qstat__k">Session coverage</span>
      <span class="qstat__v">{published}<span class="u"> / {WINDOW_DAYS}</span></span>
      <span class="qbar" aria-hidden="true">
      <i style="width:{published / WINDOW_DAYS * 100:.1f}%"></i></span>
      <span class="qstat__n">Sessions in the last {WINDOW_DAYS} days that cleared the gate.
      The remainder are published as gaps.</span>
    </div>
    <div class="qstat">
      <span class="qstat__k">FX vintage</span>
      <span class="qstat__v">{fx_vintage}</span>
      <span class="qstat__n">ECB reference rate {_num(head["fx_rate"], 4)} dated
      {_e(head["fx_date"] or "n/a")}. The ECB publishes after the cut-off, so the EUR leg is
      T&#8722;1 by construction.</span>
    </div>
    <div class="qstat">
      <span class="qstat__k">Concentration cap</span>
      <span class="qstat__v">{"BOUND" if capped else "SLACK"}</span>
      <span class="qstat__n">The {cap_pct}% per-provider cap {cap_words}; it is
      mathematically inert at n=4 and binds only from n=5.</span>
    </div>
    <div class="qstat">
      <span class="qstat__k">Trim</span>
      <span class="qstat__v">k={agg.trim_for(len(included))}</span>
      <span class="qstat__n">Count-based: the k highest and k lowest offers are clamped to the
      k-th order statistic. Percentile winsorising is inert at this panel size.</span>
    </div>
  </div>
</div>"""


def _sources_card(ctx: SiteContext) -> str:
    rows = "".join(
        f'<div class="srcs__row"><div><span class="srcs__name">{_e(s["source"])}</span>'
        f'<span class="srcs__label">{_e(s["label"] or "")}</span></div>'
        f'<div class="srcs__ep">{_e(s["endpoint"] or "")}</div>'
        + (
            f'<a class="srclink" href="{_e(s["url"])}" rel="noopener">Site{_icon("ext")}</a>'
            if s.get("url")
            else '<span class="u">&#8212;</span>'
        )
        + "</div>"
        for s in sources_panel()
    )
    return f"""<div class="card" id="sources">
  <div class="card__head">
    <div><h3 class="card__title">Sources</h3>
    <p class="card__sub">Every collector the index reads. Overlay data (power prices) is
    published beside the index and never enters the calculation.</p></div>
  </div>
  <div class="srcs">{rows}</div>
</div>"""


def _model_mix_entries(ctx: SiteContext) -> tuple[str, int, list[sqlite3.Row]] | None:
    """The standing weight review's current row set, scope='model' — shared by the
    full ledger (`_weights_card`) and the compact summary bar (`_model_mix_bar`) so
    the two can never drift onto different revisions of the same basket."""
    row = ctx.conn.execute(
        "SELECT effective_date FROM weight_sets WHERE effective_date <= ?"
        " ORDER BY effective_date DESC LIMIT 1",
        (ctx.date,),
    ).fetchone()
    if row is None:
        return None
    effective = row["effective_date"]
    rev = ctx.conn.execute(
        "SELECT MAX(revision) AS rev FROM weight_sets WHERE effective_date = ?", (effective,)
    ).fetchone()
    entries = list(
        ctx.conn.execute(
            "SELECT * FROM weight_sets WHERE effective_date = ? AND revision = ?"
            " AND scope = 'model' ORDER BY weight DESC",
            (effective, rev["rev"]),
        )
    )
    if not entries:
        return None
    return effective, int(rev["rev"]), entries


def _weights_card(ctx: SiteContext) -> str:
    """The standing weight review — a data update on a fixed schedule, not a discretion."""
    found = _model_mix_entries(ctx)
    if found is None:
        return ""
    effective, revn, entries = found
    total = sum(e["weight"] for e in entries) or 1.0
    body = "".join(
        f'<li class="ledger__row"><span class="ledger__n num">{i:02d}</span>'
        f'<div class="ledger__body"><h4 class="ledger__t">{_e(e["key"])} class share</h4>'
        f'<p class="ledger__d">Share of total observed qualifying capacity over the review '
        f'window, floored at {ctx.factors.composite.min_class_share_pct:.0f}% and capped at '
        f'{ctx.factors.composite.max_class_share_pct:.0f}%.</p></div>'
        f'<span class="ledger__v num">{e["weight"] / total * 100:,.1f}%</span></li>'
        for i, e in enumerate(entries, start=1)
    )
    window = f'{entries[0]["window_start"]} to {entries[0]["window_end"]}'
    return f"""<div class="card">
  <div class="card__head">
    <div><h3 class="card__title">Composite basket, effective {_e(effective)}</h3>
    <p class="card__sub">Window {_e(window)} &#183; {entries[0]["n_days_window"]} collection
    days &#183; recomputed by a fixed published formula, stored append-only</p></div>
    <span class="card__meta num">rev {revn}</span>
  </div>
  <div class="card__body"><ol class="ledger">{body}</ol></div>
</div>"""


def _model_mix_bar(ctx: SiteContext) -> str:
    """A compact composition summary of the same basket `_weights_card` itemises in
    full below it — a stacked bar, not a replacement for the ledger's review-window
    and formula detail. Uses the categorical palette (tokens.css §6c): colour here
    identifies a GPU class across a genuinely multi-part whole, the documented case
    for reaching past the single-hue chart default."""
    found = _model_mix_entries(ctx)
    if found is None:
        return ""
    effective, _revn, entries = found
    total = sum(e["weight"] for e in entries) or 1.0
    shares = [(str(e["key"]), e["weight"] / total * 100) for e in entries]
    # The palette has 8 fixed slots and no ninth — DESIGN.md/tokens.css §6c is explicit
    # that a ninth series folds into "Other" rather than reusing a slot's colour.
    if len(shares) > 8:
        shares, rest = shares[:7], shares[7:]
        shares.append(("Other", sum(pct for _k, pct in rest)))
    segs = "".join(
        f'<span class="mixbar__seg" style="inline-size:{pct:.4f}%;'
        f'background:var(--series-{i + 1})"></span>'
        for i, (_key, pct) in enumerate(shares)
    )
    legend = "".join(
        f'<li><i style="background:var(--series-{i + 1})"></i>'
        f"<span>{_e(key)}</span><span class=\"num\">{pct:,.1f}%</span></li>"
        for i, (key, pct) in enumerate(shares)
    )
    label = ", ".join(f"{key} {pct:.1f}%" for key, pct in shares)
    return f"""<div class="card">
  <div class="card__head">
    <div><h3 class="card__title">Model mix</h3>
    <p class="card__sub">Composite weight by GPU class, effective {_e(effective)} &#183; same
    basket as the ledger below</p></div>
  </div>
  <div class="card__body">
    <div class="mixbar" role="img"
    aria-label="Composite weight by GPU class: {_e(label)}">{segs}</div>
    <ul class="mixlegend">{legend}</ul>
  </div>
</div>"""


# ==========================================================================
# pages
# ==========================================================================


def _dashboard(ctx: SiteContext) -> str:
    if ctx.head is None:
        body = (
            '<main class="wrap" id="main"><section class="section">'
            '<div class="gapnote">' + _icon("warn", 14)
            + "<p>No print has been computed yet. Run the daily pipeline.</p></div>"
            "</section></main>"
        )
        return _shell(
            ctx,
            title="EU-CRI — European Compute Reference Index",
            description="Daily reference price for renting AI compute in the EU/EEA.",
            current="index.html",
            body=body,
        )

    body = f"""<main class="wrap" id="main">
  <h1 class="vh">EU-CRI — European Compute Reference Index, daily print for
  {_e(ctx.date)}</h1>

  <section class="section" aria-labelledby="print-h" style="padding-block:var(--space-6)">
    {_print_card(ctx)}
  </section>

  <section class="section" aria-labelledby="s-sub">
    <div class="section__head"><div>
      <h2 class="section__h" id="s-sub">Sub-indices</h2>
      <p class="section__dek">One tile per published series. A series below the provider gate
      keeps its slot and shows a gap with the reason — the last good value is never promoted
      into the current slot.</p></div></div>
    {_tiles(ctx)}
  </section>

  <section class="section" aria-labelledby="s-chart">
    <div class="section__head"><div>
      <h2 class="section__h" id="s-chart">Headline, {WINDOW_DAYS} sessions</h2>
      <p class="section__dek">Truncated y-axis, so this is a line and never an area fill.
      Hover or tab through the plot for the crosshair readout; it is CSS-only and works with
      scripting disabled.</p></div></div>
    {_chart_card(ctx)}
  </section>

  <section class="section" aria-labelledby="s-cons" id="constituents">
    <div class="section__head"><div>
      <h2 class="section__h" id="s-cons">Constituents at the {_e(ctx.date)} print</h2>
      <p class="section__dek">Every candidate the index saw, including the ones it rejected
      and why. Tier is ordinal: L1 executable quote, L2 neocloud list, L3 hyperscaler
      catalog.</p></div>
      <a class="section__link" href="methodology.html#3-aggregation-exact-algorithm">
      How the median is taken</a></div>
    {_constituents_card(ctx)}
  </section>

  <section class="section" aria-labelledby="s-q">
    <div class="section__head"><div>
      <h2 class="section__h" id="s-q">Data quality and sources</h2>
      <p class="section__dek">The publication gate, the executable share, and the collectors
      behind them. A gap is credible; a fabricated print is fatal.</p></div></div>
    <div class="stack">
      {_quality_card(ctx)}
      {_model_mix_bar(ctx)}
      {_weights_card(ctx)}
      {_sources_card(ctx)}
    </div>
  </section>
</main>"""
    return _shell(
        ctx,
        title=f"EU-CRI — European Compute Reference Index — {ctx.date}",
        description=(
            "EU-CRI: a daily, reproducible reference price for renting AI compute delivered "
            "from the EU/EEA. Weighted median over offers, published with its full "
            "constituent set."
        ),
        current="index.html",
        body=body,
        ticker=_ticker(ctx),
        extra_js=_REFRESH_JS,
    )


def _toc(headings: list[markdown.Heading], top: int = 3) -> str:
    """Two levels of contents, starting at `top`.

    Defaults to 3 because every embedded document is rendered with heading_offset=1 (the
    page already owns its single h1), so the document's own `##` sections land on h3.
    """
    sub = ' class="is-sub"'
    items = "".join(
        f"<li{sub if h.level > top else ''}>"
        f'<a href="#{h.slug}">{_e(h.text)}</a></li>'
        for h in headings
        if top <= h.level <= top + 1
    )
    if not items:
        return ""
    return (
        '<nav class="toc" aria-label="On this page">'
        '<h2 class="toc__h">On this page</h2>'
        f'<ol class="toc__list">{items}</ol></nav>'
    )


def _parameter_ledger(ctx: SiteContext) -> str:
    """The construction, as numbered ledger rows with right-aligned tabular values.

    Every value is read from config/factors.yaml at build time, so the page cannot drift
    from the parameters the calculation actually used.
    """
    f = ctx.factors
    agg, w = f.aggregation, f.weights
    trim = " · ".join(f"n&#8805;{r.min_n}&#8594;k={r.k}" for r in agg.trim_k if r.min_n)
    rows: list[tuple[str, str, str]] = [
        (
            "Reference unit",
            f"One {f.reference_unit.gpu_model.replace('_', ' ')} GPU-hour, "
            f"{f.reference_unit.term.replace('_', '-')}, delivered from the "
            f"{f.reference_unit.location.replace('_', '/')}, per GPU, ex-VAT, excluding "
            "storage and metered egress. A class prices its reference variant only.",
            f"{len(f.model_classes)} classes",
        ),
        (
            "Unit filters",
            f"Offers below {f.filters.min_gpu_count} GPUs are excluded rather than "
            "normalised: the per-GPU discount saturates at 2 GPUs, while a 1-GPU offer "
            "carries a small-order premium. Sanity band "
            f"${f.filters.price_floor_usd:,.2f}&#8211;${f.filters.price_ceiling_usd:,.2f}. "
            f"Excluded tiers: {', '.join(f.filters.exclude_tiers)}.",
            f"&#8805;{f.filters.min_gpu_count} GPU",
        ),
        (
            "Market segment",
            "The constituent distribution is bimodal, so series never average across the "
            "neocloud/hyperscaler gap. The headline draws from "
            f"{', '.join(sorted(f.population_for('headline')))}.",
            f"{len(set(f.segments.values()))} segments",
        ),
        (
            "Staleness",
            f"Manually verified static entries warn at {f.staleness.warn_days} days and are "
            f"excluded at {f.staleness.exclude_days}.",
            f"{f.staleness.exclude_days} d",
        ),
        (
            "Provider weight",
            "A provider with any executable offer is weighted "
            f"{w.executable_multiplier:,.0f}&#215; a list-only provider. Capacity does not "
            "enter at provider level: it is unobservable for every list source.",
            f"&#215;{w.executable_multiplier:,.1f}",
        ),
        (
            "Concentration cap",
            "No provider may exceed this share of total weight; the excess is redistributed "
            "pro-rata to a fixed point. Mathematically inert at n=4; binds from n=5. Every "
            "print publishes whether it bound.",
            f"{w.max_weight_share_pct:,.0f}%",
        ),
        (
            "Offer spread",
            "Each provider's share is spread across its own offers in proportion to observed "
            f"capacity, capped at {w.capacity_cap} GPUs, defaulting to "
            f"{w.default_capacity} where capacity is unobservable.",
            f"cap {w.capacity_cap}",
        ),
        (
            "Trim",
            "Count-based: clamp the k highest and k lowest offer prices to the k-th order "
            "statistic. Percentile winsorising is inert at this panel size — at n=6 both "
            "p5/p95 and p10/p90 resolve to (min, max) and clamp nothing.",
            trim,
        ),
        (
            "Estimator",
            f"{agg.estimator.replace('_', ' ').capitalize()} over {agg.unit}s: the first "
            "price at which cumulative weight reaches 50%. It always lands on a price "
            "someone actually quoted.",
            f"over {agg.unit}s",
        ),
        (
            "Publication gate",
            f"Fewer than {agg.min_providers} qualifying providers or fewer than "
            f"{agg.min_offers} qualifying offers publishes no value, flagged "
            "<code class=\"inline\">insufficient_sources</code> / "
            "<code class=\"inline\">insufficient_offers</code>. There is no fallback "
            "waterfall.",
            f"&#8805;{agg.min_providers} / &#8805;{agg.min_offers}",
        ),
        (
            "EUR companion",
            "USD value divided by the most recent ECB reference rate dated on or before the "
            f"print date, refused beyond {f.fx.max_age_days} days old. The ECB publishes "
            "after the cut-off, so the EUR leg is T&#8722;1 by construction.",
            f"&#8804;{f.fx.max_age_days} d",
        ),
        (
            "Smoothing companion",
            f"The headline's {agg.smoothing_days}-day mean, requiring at least 4 non-null "
            "days. Published beside the headline, never as it.",
            f"{agg.smoothing_days} d",
        ),
        (
            "Composite",
            f"Chain-linked over class sub-indices from a base of {f.composite.base_value:,.0f}, "
            f"class shares floored at {f.composite.min_class_share_pct:,.0f}% and capped at "
            f"{f.composite.max_class_share_pct:,.0f}%. A class that gaps drops out of that "
            "day's link.",
            f"base {f.composite.base_value:,.0f}",
        ),
        (
            "Quality flag",
            f"A constituent moving more than {f.jump_flag_pct:,.0f}% day-over-day is flagged "
            "for review and is never silently excluded.",
            f"{f.jump_flag_pct:,.0f}%",
        ),
        (
            "Revisions",
            "Observations and prints are append-only, enforced by database triggers. An error "
            "is corrected as a new revision flagged <code class=\"inline\">correction</code>; "
            "prior revisions stay queryable forever.",
            "append-only",
        ),
    ]
    body = "".join(
        f'<li class="ledger__row"><span class="ledger__n num">{i:02d}</span>'
        f'<div class="ledger__body"><h4 class="ledger__t">{title}</h4>'
        f'<p class="ledger__d">{desc}</p></div>'
        f'<span class="ledger__v num">{value}</span></li>'
        for i, (title, desc, value) in enumerate(rows, start=1)
    )
    return (
        '<ol class="ledger">'
        '<li class="ledger__row ledger__row--head"><span>#</span><span>Step</span>'
        '<span class="ledger__v">Parameter</span></li>' + body + "</ol>"
    )


def _methodology(ctx: SiteContext) -> str:
    doc = markdown.render(_read(REPO_ROOT / "METHODOLOGY.md"), heading_offset=1)
    lock = ctx.lock_hash
    body = f"""<main class="wrap" id="main">
  <div class="pagehead">
    <div class="eyebrow">EU-CRI-M</div>
    <h1 class="pagehead__h pagehead__h--display">Methodology</h1>
    <p class="pagehead__dek">Everything that can change a published print, and the exact
    order it is applied in. The document below is generated from
    <code class="inline">config/factors.yaml</code>; the parameter ledger is read from the
    same file at build time, so neither can drift from the calculation.</p>
    <div class="pagehead__meta">
      <span>Version <span class="num">v{_e(ctx.version)}</span></span>
      <span id="lock">Lock <span class="num">sha256:{_e(lock[:16])}&#8230;</span></span>
      <span>Print date <span class="num">{_e(ctx.date)}</span></span>
      <span><a href="governance.html">Change procedure</a></span>
    </div>
  </div>
  <div class="doc">
    {_toc(doc.headings)}
    <div>
      <section aria-labelledby="ledger-h" style="margin-bottom:var(--space-8)">
        <div class="card">
          <div class="card__head">
            <div><h2 class="card__title" id="ledger-h">EU-CRI-M &#183; construction</h2>
            <p class="card__sub">Hash-locked. A change to any row requires a version bump, a
            CHANGELOG entry, and one publication's notice.</p></div>
            <span class="card__meta num">v{_e(ctx.version)} &#183;
            sha256:{_e(lock[:8])}&#8230;</span>
          </div>
          <div class="card__body">{_parameter_ledger(ctx)}</div>
        </div>
      </section>
      <section aria-labelledby="audit-h" style="margin-bottom:var(--space-8)">
        <div class="card">
          <div class="card__head"><div>
            <h2 class="card__title" id="audit-h">Audit and governance hooks</h2>
            <p class="card__sub">How a third party checks this print without asking
            us</p></div></div>
          <div class="card__body stack">
            <pre class="code"><code># the full constituent set behind any print
python -m eucri.run constituents --date {_e(ctx.date)} --series EU-CRI-H100

# the weight review in effect on a date, recomputed from stored observations
python -m eucri.run weights --date {_e(ctx.date)}

# regenerate this document and the lock from config
python -m eucri.run docs</code></pre>
            <ol class="ledger">
              <li class="ledger__row"><span class="ledger__n num">A1</span>
                <div class="ledger__body"><h4 class="ledger__t">Methodology lock</h4>
                <p class="ledger__d">A sha256 over factors.yaml, sovereign.yaml, index.py,
                normalise.py and weights.py. CI fails whenever the working tree stops matching
                it.<span class="ledger__k">sha256:{_e(lock)}</span></p></div>
                <span class="ledger__v num">v{_e(ctx.version)}</span></li>
              <li class="ledger__row"><span class="ledger__n num">A2</span>
                <div class="ledger__body"><h4 class="ledger__t">Machine-readable prints</h4>
                <p class="ledger__d">The full published history, latest revision per date and
                series, plus today's snapshot with its constituent set.</p></div>
                <span class="ledger__v num"><a href="data/index_history.csv">CSV</a> &#183;
                <a href="data/latest.json">JSON</a></span></li>
              <li class="ledger__row"><span class="ledger__n num">A3</span>
                <div class="ledger__body"><h4 class="ledger__t">Complaints</h4>
                <p class="ledger__d">Any print may be challenged. Acknowledged within 7 days;
                the outcome is published with the next print, whether it is a correction or a
                rationale for no change.</p></div>
                <span class="ledger__v num"><a href="governance.html#6-complaints">P13</a>
                </span></li>
            </ol>
          </div>
        </div>
      </section>
      <div class="md">{doc.html}</div>
    </div>
  </div>
</main>"""
    return _shell(
        ctx,
        title=f"Methodology v{ctx.version} — EU-CRI",
        description=(
            "The exact EU-CRI construction: unit definition, market segmentation, weighting, "
            "trim, weighted median over offers, and the publication gate."
        ),
        current="methodology.html",
        body=body,
    )


def _governance(ctx: SiteContext) -> str:
    doc = markdown.render(_read(REPO_ROOT / "GOVERNANCE.md"), heading_offset=1)
    body = f"""<main class="wrap" id="main">
  <div class="pagehead">
    <div class="eyebrow">IOSCO principles, voluntary</div>
    <h1 class="pagehead__h pagehead__h--display">Governance</h1>
    <p class="pagehead__dek">Who administers the index, how a change to it is made, and what
    happens when a print is wrong. EU-CRI is a research publication: it is not licensed for
    use in financial instruments, and any request to hard-wire it into a financial contract
    will be refused. The regulatory position is stated precisely below rather than
    summarised here.</p>
    <div class="pagehead__meta">
      <span>Administrator Mark Rusch</span>
      <span>Methodology <span class="num">v{_e(ctx.version)}</span></span>
      <span>Lock <span class="num">sha256:{_e(ctx.lock_hash[:16])}&#8230;</span></span>
    </div>
  </div>
  <div class="doc">
    {_toc(doc.headings)}
    <div class="md">{doc.html}</div>
  </div>
</main>"""
    return _shell(
        ctx,
        title="Governance — EU-CRI",
        description=(
            "EU-CRI governance: methodology change procedure, correction policy, audit trail, "
            "conflicts of interest, complaints, and cessation."
        ),
        current="governance.html",
        body=body,
    )


# ---- research -------------------------------------------------------------


@dataclass(frozen=True)
class Note:
    """One research note discovered on disk (or a planned one, with source None)."""

    slug: str
    title: str
    dek: str
    date: str
    status: str
    source: Path | None


PLANNED_NOTES: tuple[Note, ...] = (
    Note(
        slug="composition-vs-price",
        title="Composition, not price: what actually moves a European compute benchmark",
        dek=(
            "The headline moved 1.2% between its last two published prints. Almost none of "
            "that was a price change — it was a change in who was in the panel. This note "
            "decomposes the print into a price effect and a composition effect, and argues "
            "that for a panel this thin the composition effect is the story."
        ),
        date="",
        status="In preparation",
        source=None,
    ),
)


def _front_matter(text: str) -> tuple[dict, str]:
    """Optional `---` YAML block at the top of a note. PyYAML is already a dependency."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("\n---", 2)
    if len(parts) < 2:
        return {}, text
    meta = yaml.safe_load(parts[0].lstrip("-\n")) or {}
    return (meta if isinstance(meta, dict) else {}), parts[1].lstrip("\n")


_MONTHS = (
    "january february march april may june july august september october november december"
).split()
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_LONG_DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Z][a-z]+)\s+(\d{4})\b")


def _sniff_date(text: str) -> str:
    """A note's publication date from its own byline — so authors need no front matter."""
    head = "\n".join(text.split("\n")[:12])
    iso = _ISO_RE.search(head)
    if iso:
        return iso.group(0)
    long_form = _LONG_DATE_RE.search(head)
    if long_form and long_form.group(2).lower() in _MONTHS:
        day, month, year = long_form.groups()
        return f"{year}-{_MONTHS.index(month.lower()) + 1:02d}-{int(day):02d}"
    return ""


def _discover_notes() -> list[Note]:
    found: list[Note] = []
    if RESEARCH_SRC.exists():
        for path in sorted(RESEARCH_SRC.glob("*.md")):
            meta, body = _front_matter(_read(path))
            doc = markdown.render(body)
            found.append(
                Note(
                    slug=str(meta.get("slug") or path.stem),
                    title=str(meta.get("title") or doc.title or path.stem),
                    dek=str(meta.get("dek") or doc.lead)[:400],
                    date=str(meta.get("date") or _sniff_date(body)),
                    status=str(meta.get("status") or "Published"),
                    source=path,
                )
            )
    have = {n.slug for n in found}
    found += [n for n in PLANNED_NOTES if n.slug not in have]
    return sorted(found, key=lambda n: (n.date or "0000", n.slug), reverse=True)


def _research_index(ctx: SiteContext, notes: list[Note]) -> str:
    rows = []
    for n in notes:
        chip = (
            f'<span class="chip chip--neutral"><span>{_e(n.status)}</span></span>'
            if n.source is None
            else f'<span class="chip chip--good">{_icon("check")}'
            f"<span>{_e(n.status)}</span></span>"
        )
        when = _human_date(n.date) if _ISO_RE.fullmatch(n.date) else (n.date or "unscheduled")
        rows.append(
            f'<article class="note"><div class="note__when num">'
            f"{_e(when)}</div><div>"
            f'<h3 class="note__t"><a href="research/{_e(n.slug)}.html">{_e(n.title)}</a></h3>'
            f'<p class="note__dek">{_e(n.dek)}</p>'
            f'<div class="note__foot">{chip}'
            f'<span class="u">EU-CRI Research &#183; methodology v{_e(ctx.version)}</span>'
            f"</div></div></article>"
        )
    body = f"""<main class="wrap" id="main">
  <div class="pagehead">
    <div class="eyebrow">EU-CRI Research</div>
    <h1 class="pagehead__h pagehead__h--display">Research notes</h1>
    <p class="pagehead__dek">Notes on what the index measures and what it cannot. Each one is
    reproducible from the published history in
    <code class="inline">site/data/index_history.csv</code> and the stored constituent sets;
    where a note makes a numeric claim, the query that produced it is printed with it.</p>
    <div class="pagehead__meta">
      <span><span class="num">{len(notes)}</span> notes</span>
      <span>Methodology <span class="num">v{_e(ctx.version)}</span></span>
      <span>As of <span class="num">{_e(ctx.date)}</span></span>
    </div>
  </div>
  <div class="section">
    <div class="notes">{"".join(rows)}</div>
  </div>
</main>"""
    return _shell(
        ctx,
        title="Research — EU-CRI",
        description=(
            "EU-CRI research notes: what the index measures, what moves it, and what it "
            "cannot yet say."
        ),
        current="research.html",
        body=body,
    )


def _strip_note_masthead(text: str) -> str:
    """Drop a note's own title block; the page header already publishes it.

    House format is `# Title`, a bold dek, a byline, then a `---` rule before the body.
    Everything above that rule is reproduced in `.pagehead`, so rendering it again gives
    the reader the headline twice. If the note is not in that shape, only the duplicate
    `# Title` line is removed.
    """
    lines = text.split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.strip()), 0)
    if not lines[start].startswith("# "):
        return text
    rule = next(
        (i for i, ln in enumerate(lines[start : start + 10], start) if ln.strip() == "---"),
        None,
    )
    return "\n".join(lines[(rule + 1) if rule is not None else (start + 1) :]).lstrip("\n")


def _research_note(ctx: SiteContext, note: Note) -> str:
    if note.source is not None:
        _, raw = _front_matter(_read(note.source))
        doc = markdown.render(_strip_note_masthead(raw), heading_offset=1)
        content = f'<div class="md">{doc.html}</div>'
        toc = _toc(doc.headings)
    else:
        toc = ""
        content = f"""<div class="slot">
  <h2 class="slot__h">Content slot &#8212; awaiting copy</h2>
  <p><strong>This note has not been written yet.</strong></p>
  <p>This page is the rendered shell for
  <code class="inline">research/{_e(note.slug)}.md</code>. The generator renders that file
  through the in-repo Markdown renderer the moment it exists: headings become the table of
  contents on the left, pipe tables become dense scrollable grids with right-aligned
  numerals, fenced code becomes an inset well, and <code class="inline">[^1]</code>
  footnotes become the note strip at the foot of the page.</p>
  <p>Nothing on this page is fabricated in the meantime. There is no placeholder chart and no
  sample number &#8212; the same rule the index applies to a gapped session applies to a note
  that has not been written.</p>
</div>"""
    body = f"""<main class="wrap" id="main">
  <div class="pagehead">
    <div class="eyebrow"><a class="link-quiet" href="../research.html">EU-CRI Research</a>
    </div>
    <h1 class="pagehead__h pagehead__h--display">{_e(note.title)}</h1>
    <p class="pagehead__dek">{_e(note.dek)}</p>
    <div class="pagehead__meta">
      <span class="num">{_e(_human_date(note.date) if _ISO_RE.fullmatch(note.date)
                          else note.date or "Unscheduled")}</span>
      <span>Methodology <span class="num">v{_e(ctx.version)}</span></span>
      <span>{_e(note.status)}</span>
      <span>Mark Rusch</span>
    </div>
  </div>
  <div class="doc">
    {toc}
    <div>{content}</div>
  </div>
</main>"""
    return _shell(
        ctx,
        title=f"{note.title} — EU-CRI Research",
        description=note.dek[:200],
        current="research.html",
        body=body,
        prefix="../",
    )


# ==========================================================================
# entry point
# ==========================================================================


def generate(conn: sqlite3.Connection) -> list[Path]:
    """Render every page into site/. Returns the paths written, newest content first."""
    factors = load_factors()
    head = latest_print(conn, HEADLINE)
    now = utc_now_iso()
    ctx = SiteContext(
        conn=conn,
        factors=factors,
        version=factors.methodology_version,
        lock_hash=_lock_hash(),
        generated_at=now,
        head=head,
        date=head["date"] if head else now[:10],
    )
    notes = _discover_notes()

    pages: list[tuple[Path, str]] = [
        (SITE_DIR / "index.html", _dashboard(ctx)),
        (SITE_DIR / "methodology.html", _methodology(ctx)),
        (SITE_DIR / "governance.html", _governance(ctx)),
        (SITE_DIR / "research.html", _research_index(ctx, notes)),
    ]
    pages += [
        (SITE_DIR / "research" / f"{n.slug}.html", _research_note(ctx, n)) for n in notes
    ]

    written = []
    for path, html_text in pages:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(html_text, encoding="utf-8", newline="\n")
        written.append(path)
    log.info("site: %d pages -> %s", len(written), SITE_DIR)
    return written
