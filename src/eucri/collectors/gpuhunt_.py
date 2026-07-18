"""Hyperscaler EU list prices via the open-source gpuhunt package (dstack catalogs).

Scope: aws / azure / gcp only (other gpuhunt providers are covered directly or are
out of scope), 8-GPU H100 instances only (the unit is an 8-GPU NVLink node price),
on-demand (spot=False). Catalog item price is per instance-hour -> divide by count.
Regions are mapped to countries below; unmapped regions yield country=None and are
excluded by the normaliser — the safe default for new/unknown regions.
"""

from __future__ import annotations

import json
import logging
from importlib.metadata import PackageNotFoundError, version

import requests

from eucri.db import utc_now_iso
from eucri.models import Observation

log = logging.getLogger("eucri.collectors.gpuhunt")

PROVIDERS = ("aws", "azure", "gcp")

# EU/EEA regions plus main US regions (US rows feed the future US-proxy series and are
# excluded from EU-CRI by the country filter). GB/CH regions deliberately unmapped.
REGION_COUNTRY = {
    # us (stored for the US-proxy comparison, never in EU-CRI)
    "us-east-1": "US", "us-east-2": "US", "us-west-2": "US",
    "eastus": "US", "eastus2": "US", "westus3": "US", "southcentralus": "US",
    "us-east4": "US", "us-east5": "US", "us-central1": "US", "us-west1": "US",
    "us-west4": "US",
    # aws
    "eu-west-1": "IE", "eu-west-3": "FR", "eu-central-1": "DE", "eu-north-1": "SE",
    "eu-south-1": "IT", "eu-south-2": "ES",
    # azure
    "westeurope": "NL", "northeurope": "IE", "germanywestcentral": "DE",
    "francecentral": "FR", "swedencentral": "SE", "italynorth": "IT",
    "spaincentral": "ES", "polandcentral": "PL",
    # gcp (zone suffixes stripped before lookup)
    "europe-west1": "BE", "europe-west3": "DE", "europe-west4": "NL",
    "europe-north1": "FI", "europe-west9": "FR", "europe-southwest1": "ES",
    "europe-west8": "IT", "europe-west12": "IT", "europe-central2": "PL",
}


def _country(provider: str, location: str) -> str | None:
    loc = location.lower()
    if provider == "gcp" and loc.count("-") == 2:
        loc = loc.rsplit("-", 1)[0]  # zone -> region (europe-west4-c -> europe-west4)
    return REGION_COUNTRY.get(loc)


def _gpuhunt_version() -> str:
    try:
        return version("gpuhunt")
    except PackageNotFoundError:
        return "unknown"


class GpuHuntCollector:
    name = "gpuhunt"

    def collect(self, session: requests.Session) -> list[Observation]:
        # session unused: gpuhunt fetches dstack's published catalog files itself
        import gpuhunt

        items = gpuhunt.query(gpu_name=["H100"], provider=list(PROVIDERS), spot=False)
        return self.to_observations(items)

    def to_observations(self, items: list) -> list[Observation]:
        ts = utc_now_iso()
        pkg_version = _gpuhunt_version()
        out: list[Observation] = []
        for item in items:
            gpu_count = int(item.gpu_count or 0)
            if gpu_count < 8:
                continue  # unit is an 8-GPU node; smaller instances never match
            country = _country(item.provider, item.location or "")
            out.append(
                Observation(
                    ts_utc=ts,
                    source=self.name,
                    provider=item.provider,
                    gpu_model="H100_SXM",  # 8x hyperscaler H100 nodes are SXM/HGX
                    gpu_count=gpu_count,
                    price_usd_per_gpu_hr=float(item.price) / gpu_count,
                    region=item.location,
                    country=country,
                    interconnect="NVLink",
                    tier="list",
                    term="on_demand",
                    raw_json=json.dumps(
                        {
                            "instance_name": item.instance_name,
                            "location": item.location,
                            "price_instance_hr": item.price,
                            "gpu_name": item.gpu_name,
                            "gpu_memory": getattr(item, "gpu_memory", None),
                            "gpuhunt_version": pkg_version,
                        }
                    ),
                )
            )
        log.info("gpuhunt: %d 8-GPU H100 instances (all regions)", len(out))
        return out
