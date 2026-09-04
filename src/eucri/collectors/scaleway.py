# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Scaleway public Instance API (no auth) — EU list prices, zone by zone.

Collection scope (SOURCES.md): scaleway.com/pricing renders GPU prices via JS only, so
Scaleway is also carried as a manually verified static entry (config/providers/
scaleway.yaml, currently a null price — never invented). This collector reads the same
numbers straight from Scaleway's own public product-catalog API instead, one GET per
zone. It shares the 'scaleway' provider name with that static entry, so a live reading
here simply out-competes the static null row (representative_constituents() takes the
min price per provider across all sources) — no special-casing needed.

Schema verified against a live response on 2026-08-15: servers is a dict keyed by
instance name; hourly_price is EUR per *instance*, not per GPU and not USD. Dividing by
gpu gives the EUR-per-GPU native price. FX conversion is normalise.py's job, not ours:
price_usd_per_gpu_hr carries the EUR-per-GPU figure verbatim for now, and raw_json
records the native currency and per-GPU amount so that stopgap stays auditable.

Nine zones, one source, one logical "1 request per source per day" budget — but a
single zone 404ing or timing out must not take the other eight down with it, so each
zone is fetched and parsed independently; failures are logged and skipped.
"""

from __future__ import annotations

import json
import logging

import requests

from eucri.collectors.base import TIMEOUT_SECONDS
from eucri.db import utc_now_iso
from eucri.models import Observation

log = logging.getLogger("eucri.collectors.scaleway")

URL = "https://api.scaleway.com/instance/v1/zones/{zone}/products/servers"

ZONES = (
    "fr-par-1", "fr-par-2", "fr-par-3",
    "nl-ams-1", "nl-ams-2", "nl-ams-3",
    "pl-waw-1", "pl-waw-2", "pl-waw-3",
)

COUNTRY_BY_ZONE_PREFIX = {"fr": "FR", "nl": "NL", "pl": "PL"}


def _map_variant(instance_name: str) -> str | None:
    """Instance name -> canonical GPU variant; consumer/render types return None (skip)."""
    n = instance_name.upper()
    if n.startswith("H100"):
        return "H100_SXM" if "SXM" in n else "H100_PCIE"
    if n.startswith("B300"):
        return "B300_SXM" if "SXM" in n else None  # only the SXM B300 shape is mapped
    if n.startswith("L40S"):
        return "L40S"
    if n.startswith("L4"):
        return "L4"
    if n.startswith("H200"):
        return "H200_SXM"
    if n.startswith("A100"):
        return "A100_SXM" if "SXM" in n else "A100_PCIE"
    return None  # RENDER-*, GPU-3070-*, and other consumer/render types


class ScalewayCollector:
    name = "scaleway"

    def collect(self, session: requests.Session) -> list[Observation]:
        ts = utc_now_iso()
        out: list[Observation] = []
        for zone in ZONES:
            try:
                resp = session.get(URL.format(zone=zone), timeout=TIMEOUT_SECONDS)
                resp.raise_for_status()
                servers = resp.json().get("servers", {})
            except requests.RequestException as exc:
                log.warning("scaleway: zone %s failed (%s), skipping", zone, exc)
                continue
            out.extend(self._zone_observations(zone, servers, ts))
        log.info("scaleway: %d observations across %d zones", len(out), len(ZONES))
        return out

    def _zone_observations(
        self, zone: str, servers: dict, ts: str
    ) -> list[Observation]:
        country = COUNTRY_BY_ZONE_PREFIX.get(zone.split("-")[0])
        out: list[Observation] = []
        for instance_name, spec in servers.items():
            gpu = spec.get("gpu")
            hourly_price = spec.get("hourly_price")
            if not gpu or hourly_price is None:
                continue  # non-GPU instance, or price missing -> never invent one
            gpu_model = _map_variant(instance_name)
            if gpu_model is None:
                continue
            price_native_per_gpu_hr = float(hourly_price) / gpu
            out.append(
                Observation(
                    ts_utc=ts,
                    source=self.name,
                    provider="scaleway",
                    gpu_model=gpu_model,
                    gpu_count=int(gpu),
                    # EUR-per-GPU, not USD -- see module docstring; FX is normalise.py's job
                    price_usd_per_gpu_hr=price_native_per_gpu_hr,
                    region=zone,
                    country=country,
                    interconnect="NVLink" if "SXM" in instance_name.upper() else "PCIe",
                    tier="list",
                    term="on_demand",
                    raw_json=json.dumps(
                        {
                            "instance_name": instance_name,
                            "zone": zone,
                            "hourly_price": hourly_price,
                            "gpu": gpu,
                            "currency": "EUR",
                            "price_native_per_gpu_hr": price_native_per_gpu_hr,
                        }
                    ),
                )
            )
        return out
