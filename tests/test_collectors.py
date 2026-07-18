"""Collector parsing against recorded fixtures + fail-soft behaviour. No live network."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import requests
import responses

from eucri.collectors import base
from eucri.collectors.static_yaml import StaticYamlCollector
from eucri.collectors.vast_ai import GPU_MODEL_MAP, VastAiCollector
from eucri.collectors.vast_ai import URL as VAST_URL
from eucri.models import Observation

FIXTURE = Path(__file__).parent / "fixtures" / "vast_bundles.json"


@responses.activate
def test_vast_parses_fixture() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    responses.add(responses.POST, VAST_URL, json=data, status=200)

    out = VastAiCollector().collect(base.make_session())

    expected = [
        o for o in data["offers"]
        if o.get("verification") == "verified" and o.get("hosting_type") == 1
        and o.get("gpu_name") in GPU_MODEL_MAP and (o.get("num_gpus") or 0) >= 1
        and o.get("dph_total")
    ]
    assert len(out) == len(expected) > 0
    for o in out:
        assert o.provider == "vast.ai" and o.tier == "executable"
        assert o.price_usd_per_gpu_hr > 0
        assert o.country is None or len(o.country) == 2
        raw = json.loads(o.raw_json)
        assert raw["verification"] == "verified" and raw["hosting_type"] == 1
    # per-GPU price = dph_total / num_gpus (verified against the recorded NL 8x node)
    node = next(o for o in out if o.gpu_count == 8 and o.country == "NL")
    raw = json.loads(node.raw_json)
    assert abs(node.price_usd_per_gpu_hr - raw["dph_total"] / 8) < 1e-9


def test_static_yaml_emits_only_priced_entries() -> None:
    out = StaticYamlCollector().collect(base.make_session())
    providers = {o.provider for o in out}
    assert "nebius" in providers and "seeweb" in providers
    assert all(o.tier == "list" and o.price_usd_per_gpu_hr > 0 for o in out)
    assert all(json.loads(o.raw_json).get("last_verified") for o in out)


class _BoomCollector:
    name = "boom"

    def collect(self, session: requests.Session) -> list[Observation]:
        raise RuntimeError("source exploded")


class _OkCollector:
    name = "okc"

    def __init__(self) -> None:
        self.calls = 0

    def collect(self, session: requests.Session) -> list[Observation]:
        self.calls += 1
        return []


def test_fail_soft_records_failure_and_run_continues(conn: sqlite3.Connection) -> None:
    status1 = base.run_collector(conn, _BoomCollector(), "2026-07-18")
    status2 = base.run_collector(conn, _OkCollector(), "2026-07-18")
    assert (status1, status2) == ("failed", "ok")
    rows = {
        r["source"]: r["status"]
        for r in conn.execute("SELECT source, status FROM runs")
    }
    assert rows == {"boom": "failed", "okc": "ok"}


def test_failed_collector_is_retried_next_run(conn: sqlite3.Connection) -> None:
    base.run_collector(conn, _BoomCollector(), "2026-07-18")
    # a failure must not satisfy idempotency — the next daily run retries the source
    status = base.run_collector(conn, _OkCollector(), "2026-07-18")
    assert status == "ok"
    boom_again = base.run_collector(conn, _BoomCollector(), "2026-07-18")
    assert boom_again == "failed"
