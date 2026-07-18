"""Paste-ready Substack post (Substack has no public posting API — by design this
produces markdown + the PNGs in site/charts to paste manually)."""

from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from eucri import DISCLAIMER
from eucri.config import load_factors

log = logging.getLogger("eucri.outputs.post")

REPO_ROOT = Path(__file__).resolve().parents[3]
POST_PATH = REPO_ROOT / "site" / "substack_post.md"


def _latest_print(conn: sqlite3.Connection, series: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM daily_index WHERE series = ? ORDER BY date DESC, revision DESC LIMIT 1",
        (series,),
    ).fetchone()


def _value_on(conn: sqlite3.Connection, series: str, date: str) -> float | None:
    row = conn.execute(
        "SELECT value_usd FROM daily_index WHERE series = ? AND date <= ?"
        " AND value_usd IS NOT NULL ORDER BY date DESC, revision DESC LIMIT 1",
        (series, date),
    ).fetchone()
    return row["value_usd"] if row else None


def _pct(new: float, old: float | None) -> str:
    if old is None or old == 0:
        return "n/a"
    return f"{(new - old) / old * 100:+.1f}%"


def _constituent_lines(conn: sqlite3.Connection, date: str) -> list[str]:
    rows = conn.execute(
        "SELECT c.* FROM constituents c JOIN ("
        "  SELECT MAX(revision) AS rev FROM daily_index"
        "  WHERE date = ? AND series = 'EU-CRI-H100') m ON c.revision = m.rev"
        " WHERE c.date = ? AND c.series = 'EU-CRI-H100' ORDER BY c.included DESC, c.price_usd",
        (date, date),
    ).fetchall()
    lines = []
    for c in rows:
        status = "" if c["included"] else f" *(excluded: {c['exclusion_reason']})*"
        flag = " ⚠ jump-flagged" if c["flags"] and "jump" in c["flags"] else ""
        lines.append(f"| {c['provider']} | {c['tier']} | ${c['price_usd']:.2f} |"
                     f" {c['weight']:.0f} |{status}{flag}")
    return lines


def generate_post(conn: sqlite3.Connection) -> Path:
    factors = load_factors()
    head = _latest_print(conn, "EU-CRI-H100")
    POST_PATH.parent.mkdir(parents=True, exist_ok=True)

    if head is None:
        POST_PATH.write_text("No prints yet.\n", encoding="utf-8", newline="\n")
        return POST_PATH

    date = head["date"]
    lines: list[str] = [f"# EU-CRI weekly — {date}", ""]

    if head["value_usd"] is None:
        lines += [
            f"**No index value published for {date}: {head['flags']}** "
            f"(constituents: {head['n_sources']}, minimum required: "
            f"{factors.aggregation.min_providers}). A gap is credible; a fabricated "
            "print is fatal — the constituent table below shows exactly what we saw.",
            "",
        ]
    else:
        d = datetime.strptime(date, "%Y-%m-%d")
        wow = _value_on(conn, "EU-CRI-H100", (d - timedelta(days=7)).strftime("%Y-%m-%d"))
        mom = _value_on(conn, "EU-CRI-H100", (d - timedelta(days=30)).strftime("%Y-%m-%d"))
        lines += [
            f"**EU-CRI-H100: ${head['value_usd']:.2f} / GPU-hour** "
            f"(€{head['value_eur']:.2f} at ECB {head['fx_rate']} on {head['fx_date']})",
            "",
            f"Week-over-week: {_pct(head['value_usd'], wow)} · "
            f"Month-over-month: {_pct(head['value_usd'], mom)} · "
            f"Constituents: {head['n_sources']} ({head['n_executable']} executable-quote)",
            "",
        ]
        smooth = _latest_print(conn, "EU-CRI-H100-7D")
        if smooth and smooth["value_usd"] is not None:
            lines += [f"7-day mean: ${smooth['value_usd']:.2f}", ""]

    lines += ["<!-- EDITORIAL: lead commentary -->", ""]

    cons = _constituent_lines(conn, date)
    if cons:
        prices = [
            float(line.split("$")[1].split(" ")[0]) for line in cons if "excluded" not in line
        ]
        if len(prices) >= 2:
            lines += [
                f"Dispersion: cheapest constituent ${min(prices):.2f}, dearest "
                f"${max(prices):.2f} — a {max(prices) / min(prices):.1f}x spread for the "
                "same reference unit.",
                "",
            ]
        lines += ["| provider | tier | $/GPU-hr | weight |", "|---|---|---|---|"]
        lines += cons
        lines += [""]

    lines += [
        "![EU-CRI-H100 headline](charts/headline_7d.png)",
        "![Constituent dispersion](charts/dispersion.png)",
        "",
        "<!-- EDITORIAL: energy overlay comment -->",
        "",
        "---",
        "",
        f"*Methodology v{factors.methodology_version} — full methodology, constituent-"
        "level audit trail, and source code are public in the repository. "
        "Corrections are published as flagged revisions, never silently.*",
        "",
        f"*{DISCLAIMER}*",
        "",
    ]
    POST_PATH.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    log.info("post: %s", POST_PATH)
    return POST_PATH
