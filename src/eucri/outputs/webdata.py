"""site/data/latest.json — the data contract for the static dashboard (site/index.html).

Never part of the calculation path: pure read-and-serialise of what daily_index,
constituents and weight_sets already hold. Fail-soft like charts/post (see
commands._maybe_outputs); the daily run must never fail because the dashboard export did.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import yaml

from eucri import DISCLAIMER, __version__
from eucri.commands import COMPOSITE, SERIES_BY_CLASS
from eucri.config import CONFIG_DIR, load_factors, load_static_providers
from eucri.db import utc_now_iso

log = logging.getLogger("eucri.outputs.webdata")

REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_PATH = REPO_ROOT / "site" / "data" / "latest.json"

ALL_SERIES = [
    "EU-CRI-H100", "EU-CRI-H100-7D", "EU-CRI-H100-SOV", "EU-CRI-H100-MKT",
    "EU-CRI-H100-CLOUD", "EU-CRI-A100", "EU-CRI-B200", COMPOSITE,
]


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


def _prior_print(
    conn: sqlite3.Connection, series: str, before_date: str
) -> tuple[str, float] | None:
    """The most recent (date, value_usd) strictly before before_date, for the print-meta tile."""
    row = conn.execute(
        "SELECT date, value_usd FROM daily_index WHERE series = ? AND date < ?"
        " AND value_usd IS NOT NULL ORDER BY date DESC, revision DESC LIMIT 1",
        (series, before_date),
    ).fetchone()
    return (row["date"], row["value_usd"]) if row else None


def _pct(new: float | None, old: float | None) -> float | None:
    if new is None or old is None or old == 0:
        return None
    return round((new - old) / old * 100.0, 4)


def _load_source_links() -> dict:
    path = CONFIG_DIR / "source_links.yaml"
    if not path.exists():
        return {"providers": {}, "collectors": {}}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _provider_links() -> dict[str, dict]:
    """provider -> {url, note}. Static-yaml providers' own url wins (authoritative)."""
    links = _load_source_links()
    out: dict[str, dict] = {
        name: {"url": entry.get("url"), "note": entry.get("note")}
        for name, entry in (links.get("providers") or {}).items()
    }
    for p in load_static_providers():
        if p.url:
            out[p.provider] = {"url": p.url, "note": p.config_notes or None}
    return out


def _sources_panel() -> list[dict]:
    """Collector-level catalogue for the dashboard's Sources panel."""
    links = _load_source_links()
    return [
        {"source": name, "label": c.get("label"), "url": c.get("url"),
         "endpoint": c.get("endpoint")}
        for name, c in (links.get("collectors") or {}).items()
    ]


def _series_snapshot(conn: sqlite3.Connection) -> dict:
    out: dict = {}
    for series in ALL_SERIES:
        row = _latest_print(conn, series)
        if row is None:
            continue
        entry = {
            "date": row["date"],
            "value_usd": row["value_usd"],
            "value_eur": row["value_eur"],
            "fx_rate": row["fx_rate"],
            "fx_date": row["fx_date"],
            "n_sources": row["n_sources"],
            "n_executable": row["n_executable"],
            "flags": row["flags"],
        }
        if row["value_usd"] is not None:
            d = datetime.strptime(row["date"], "%Y-%m-%d")
            wow_date = (d - timedelta(days=7)).strftime("%Y-%m-%d")
            mom_date = (d - timedelta(days=30)).strftime("%Y-%m-%d")
            entry["wow_pct"] = _pct(row["value_usd"], _value_on(conn, series, wow_date))
            entry["mom_pct"] = _pct(row["value_usd"], _value_on(conn, series, mom_date))
            prior = _prior_print(conn, series, row["date"])
            entry["prev_date"] = prior[0] if prior else None
            entry["prev_value_usd"] = prior[1] if prior else None
        out[series] = entry
    return out


def _constituents(conn: sqlite3.Connection, series: str, date: str) -> list[dict]:
    row = conn.execute(
        "SELECT MAX(revision) AS rev FROM daily_index WHERE date = ? AND series = ?",
        (date, series),
    ).fetchone()
    if row is None or row["rev"] is None:
        return []
    cons = conn.execute(
        "SELECT * FROM constituents WHERE date = ? AND series = ? AND revision = ?"
        " ORDER BY included DESC, price_usd",
        (date, series, row["rev"]),
    ).fetchall()
    links = _provider_links()
    return [
        {
            "provider": c["provider"], "source": c["source"], "tier": c["tier"],
            "price_usd": c["price_usd"], "weight": round(c["weight"], 4),
            "included": bool(c["included"]), "exclusion_reason": c["exclusion_reason"],
            "flags": c["flags"],
            "url": (links.get(c["provider"]) or {}).get("url"),
            "note": (links.get(c["provider"]) or {}).get("note"),
        }
        for c in cons
    ]


def _weight_review(conn: sqlite3.Connection, on_date: str) -> dict | None:
    """Most recent review with effective_date <= on_date, all classes, latest revision."""
    row = conn.execute(
        "SELECT effective_date FROM weight_sets WHERE effective_date <= ?"
        " ORDER BY effective_date DESC LIMIT 1",
        (on_date,),
    ).fetchone()
    if row is None:
        return None
    effective = row["effective_date"]
    rev_row = conn.execute(
        "SELECT MAX(revision) AS rev FROM weight_sets WHERE effective_date = ?",
        (effective,),
    ).fetchone()
    rows = conn.execute(
        "SELECT * FROM weight_sets WHERE effective_date = ? AND revision = ?",
        (effective, rev_row["rev"]),
    ).fetchall()
    if not rows:
        return None
    providers: dict[str, list[dict]] = {}
    model_shares: dict[str, float] = {}
    for r in rows:
        if r["scope"] == "provider":
            providers.setdefault(r["model_class"], []).append(
                {"provider": r["key"], "weight": round(r["weight"], 4),
                 "days_observed": r["n_days_observed"]}
            )
        else:
            model_shares[r["key"]] = round(r["weight"], 4)
    for pset in providers.values():
        pset.sort(key=lambda p: -p["weight"])
    return {
        "effective_date": effective,
        "window_start": rows[0]["window_start"],
        "window_end": rows[0]["window_end"],
        "n_days_window": rows[0]["n_days_window"],
        "providers": providers,
        "model_shares": model_shares,
    }


def generate(conn: sqlite3.Connection) -> Path:
    factors = load_factors()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    head = _latest_print(conn, "EU-CRI-H100")
    payload: dict = {
        "generated_at": utc_now_iso(),
        "eucri_version": __version__,
        "methodology_version": factors.methodology_version,
        "disclaimer": DISCLAIMER,
        "date": head["date"] if head else None,
        "series": _series_snapshot(conn),
        "constituents": {},
        "weight_review": None,
        "sources": _sources_panel(),
    }
    if head is not None:
        for series in SERIES_BY_CLASS.values():
            cons = _constituents(conn, series, head["date"])
            if cons:
                payload["constituents"][series] = cons
        payload["weight_review"] = _weight_review(conn, head["date"])

    OUT_PATH.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    log.info("webdata: %s", OUT_PATH)
    return OUT_PATH
