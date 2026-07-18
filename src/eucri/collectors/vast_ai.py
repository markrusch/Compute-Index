"""Vast.ai public search API (no auth) — executable marketplace asks.

Collection scope (documented in SOURCES.md): datacenter-verified hosts only
(verification == 'verified' AND hosting_type == 1); community/hobbyist inventory is
outside the index universe entirely. Offers are stored globally — EU/EEA, minimum
GPU count, and price-band filters are applied in the calculation path (normalise.py)
so per-day exclusions stay auditable; non-EU rows feed the future US-proxy series.

Field semantics verified against a live response on 2026-07-18:
dph_total is the whole-instance $/hr (divide by num_gpus); geolocation is
'Region, CC'; hosting_type 1 = datacenter.
"""

from __future__ import annotations

import json
import logging

import requests

from eucri.collectors.base import TIMEOUT_SECONDS
from eucri.db import utc_now_iso
from eucri.models import Observation

log = logging.getLogger("eucri.collectors.vast_ai")

URL = "https://console.vast.ai/api/v0/bundles/"

QUERY = {
    "gpu_name": {"in": ["H100 SXM", "H100 NVL", "A100 SXM4"]},
    "rentable": {"eq": True},
    "type": "on-demand",
    "limit": 200,
    "order": [["dph_total", "asc"]],
}

GPU_MODEL_MAP = {
    "H100 SXM": ("H100_SXM", "NVLink"),
    "H100 NVL": ("H100_NVL_94GB", "NVL"),
    "A100 SXM4": ("A100_SXM", "NVLink"),
}

# raw_json keeps the pricing-relevant subset of the ~100-field offer (audit without bloat)
RAW_FIELDS = (
    "id", "ask_contract_id", "machine_id", "host_id", "gpu_name", "num_gpus",
    "dph_total", "dph_base", "discounted_dph_total", "min_bid", "geolocation",
    "geolocode", "verification", "hosting_type", "rentable", "rented", "reliability",
    "gpu_ram", "bw_nvlink", "duration", "static_ip",
)


def _country(geolocation: str | None) -> str | None:
    if not geolocation or "," not in geolocation:
        return None
    code = geolocation.rsplit(",", 1)[-1].strip().upper()
    return code if len(code) == 2 else None


class VastAiCollector:
    name = "vast_ai"

    def collect(self, session: requests.Session) -> list[Observation]:
        resp = session.post(URL, json=QUERY, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        offers = resp.json()["offers"]
        ts = utc_now_iso()
        out: list[Observation] = []
        for offer in offers:
            if offer.get("verification") != "verified" or offer.get("hosting_type") != 1:
                continue
            model_map = GPU_MODEL_MAP.get(offer.get("gpu_name", ""))
            num_gpus = offer.get("num_gpus") or 0
            dph_total = offer.get("dph_total")
            if model_map is None or num_gpus < 1 or not dph_total:
                continue
            gpu_model, interconnect = model_map
            out.append(
                Observation(
                    ts_utc=ts,
                    source=self.name,
                    provider="vast.ai",
                    gpu_model=gpu_model,
                    gpu_count=num_gpus,
                    price_usd_per_gpu_hr=float(dph_total) / num_gpus,
                    region=offer.get("geolocation"),
                    country=_country(offer.get("geolocation")),
                    interconnect=interconnect,
                    tier="executable",
                    term="on_demand",
                    raw_json=json.dumps({k: offer.get(k) for k in RAW_FIELDS}),
                )
            )
        log.info("vast_ai: %d/%d offers kept (datacenter-verified)", len(out), len(offers))
        return out
