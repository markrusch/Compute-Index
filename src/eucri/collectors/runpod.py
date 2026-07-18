"""RunPod public GraphQL (no auth) — secure-cloud executable per-GPU rates.

Collection scope (SOURCES.md): secure cloud only; community tier is outside the index
universe. RunPod's secure-cloud pricing is region-flat and deliverable from its EU
secure-cloud datacenters (EU-RO / EU-SE / EU-NL); observations are recorded against
EU-RO by convention (documented — the API exposes no per-region price).

Schema verified against a live response on 2026-07-18: gpuTypes[].securePrice is the
secure-cloud on-demand $/GPU-hr; lowestPrice(input:{gpuCount:8}).stockStatus
demonstrates 8-GPU pod availability. If the endpoint ever requires auth, this
collector is retired — no workarounds.
"""

from __future__ import annotations

import json
import logging

import requests

from eucri.collectors.base import TIMEOUT_SECONDS
from eucri.db import utc_now_iso
from eucri.models import Observation

log = logging.getLogger("eucri.collectors.runpod")

URL = "https://api.runpod.io/graphql"

QUERY = """
query {
  gpuTypes {
    id displayName memoryInGb secureCloud communityCloud
    securePrice communityPrice
    lowestPrice(input: {gpuCount: 8}) {
      minimumBidPrice uninterruptablePrice stockStatus
    }
  }
}
"""

GPU_MODEL_MAP = {
    "NVIDIA H100 80GB HBM3": ("H100_SXM", "NVLink"),
    "NVIDIA H100 NVL": ("H100_NVL_94GB", "NVL"),
    "NVIDIA A100-SXM4-80GB": ("A100_SXM", "NVLink"),
}


class RunPodCollector:
    name = "runpod"

    def collect(self, session: requests.Session) -> list[Observation]:
        resp = session.post(URL, json={"query": QUERY}, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            raise RuntimeError(f"runpod graphql errors: {payload['errors'][:1]}")
        gpu_types = payload["data"]["gpuTypes"]
        ts = utc_now_iso()
        out: list[Observation] = []
        for gt in gpu_types:
            model_map = GPU_MODEL_MAP.get(gt.get("id", ""))
            if model_map is None:
                continue
            if not gt.get("secureCloud") or not gt.get("securePrice"):
                continue
            gpu_model, interconnect = model_map
            lowest = gt.get("lowestPrice") or {}
            has_8x_stock = bool(lowest.get("stockStatus"))
            out.append(
                Observation(
                    ts_utc=ts,
                    source=self.name,
                    provider="runpod",
                    gpu_model=gpu_model,
                    # 8x pods demonstrated by stockStatus; else count unknown -> the
                    # normaliser excludes executable asks without node-config evidence
                    gpu_count=8 if has_8x_stock else None,
                    price_usd_per_gpu_hr=float(gt["securePrice"]),
                    region="secure-cloud EU (EU-RO/EU-SE/EU-NL)",
                    country="RO",
                    interconnect=interconnect,
                    tier="executable",
                    term="on_demand",
                    raw_json=json.dumps(gt),
                )
            )
        log.info("runpod: %d gpu types kept (secure cloud)", len(out))
        return out
