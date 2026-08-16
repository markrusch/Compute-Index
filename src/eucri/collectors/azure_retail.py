"""Azure Retail Prices API (no auth) — EEA list prices for mapped ND/NC H100/A100/H200 SKUs.

Public, unauthenticated pricing feed (prices.azure.com); one OData query per EEA region,
paginated via NextPageLink and capped at MAX_PAGES_PER_REGION so a stuck region can't
balloon the request count. The API exposes no GPU-count field, so only SKUs hand-mapped
in SKU_MAP (verified against Microsoft's own VM-size docs) are emitted — everything else
is skipped rather than guessed. In particular Standard_ND128isr_NDR_GB200_v6 is
deliberately excluded: its accelerator-per-node count is unverified, and a wrong
denominator would silently corrupt a per-GPU series.

Verified against a live response on 2026-08-15. Spot/Low Priority meters and non-hourly
units are excluded — they sit outside the on-demand, $/GPU-hr unit definition. A region
that errors is logged and skipped; it never takes the other regions down with it.

switzerlandnorth and uksouth are deliberately NOT queried — neither is in the EEA.
"""

from __future__ import annotations

import json
import logging

import requests

from eucri.collectors.base import TIMEOUT_SECONDS
from eucri.db import utc_now_iso
from eucri.models import Observation

log = logging.getLogger("eucri.collectors.azure_retail")

NAME = "azure_retail"

URL = "https://prices.azure.com/api/retail/prices"

MAX_PAGES_PER_REGION = 8

REGIONS = (
    "westeurope", "northeurope", "swedencentral", "francecentral",
    "germanywestcentral", "norwayeast", "norwaywest", "italynorth",
    "polandcentral", "spaincentral",
)

REGION_COUNTRY = {
    "westeurope": "NL", "northeurope": "IE", "swedencentral": "SE",
    "francecentral": "FR", "germanywestcentral": "DE", "norwayeast": "NO",
    "norwaywest": "NO", "italynorth": "IT", "polandcentral": "PL",
    "spaincentral": "ES",
}

# armSkuName -> (canonical gpu variant, GPUs per node). Verified present in a live
# response on 2026-08-15; do not add a SKU here without confirming its GPU count from
# Microsoft's VM-size documentation -- a guessed count corrupts the per-GPU series.
SKU_MAP: dict[str, tuple[str, int]] = {
    "Standard_ND96isr_H100_v5": ("H100_SXM", 8),
    "Standard_ND96is_noIB_H100_v5": ("H100_SXM", 8),
    "Standard_ND96is_H100_v5": ("H100_SXM", 8),
    "Standard_ND96isr_H200_v5": ("H200_SXM", 8),
    "Standard_ND96asr_A100_v4": ("A100_SXM", 8),
    "Standard_ND96amsr_A100_v4": ("A100_SXM", 8),
    "Standard_ND96ams_A100_v4": ("A100_SXM", 8),
    "Standard_NC40ads_H100_v5": ("H100_PCIE", 1),
    "Standard_NC80adis_H100_v5": ("H100_PCIE", 2),
    "Standard_NC24ads_A100_v4": ("A100_PCIE", 1),
    "Standard_NC48ads_A100_v4": ("A100_PCIE", 2),
    "Standard_NC96ads_A100_v4": ("A100_PCIE", 4),
}


def _odata_filter(region: str) -> str:
    return (
        f"serviceName eq 'Virtual Machines' and armRegionName eq '{region}'"
        " and priceType eq 'Consumption'"
    )


def _interconnect(sku: str) -> str:
    if "noIB" in sku:
        return "Ethernet"
    if "isr" in sku:
        return "InfiniBand"
    return "PCIe"


def _fetch_region(session: requests.Session, region: str) -> list[dict]:
    """All Items for one region, following NextPageLink up to MAX_PAGES_PER_REGION."""
    items: list[dict] = []
    resp = session.get(
        URL, params={"$filter": _odata_filter(region)}, timeout=TIMEOUT_SECONDS
    )
    resp.raise_for_status()
    payload = resp.json()
    items.extend(payload.get("Items", []))
    next_link = payload.get("NextPageLink")
    pages = 1
    while next_link and pages < MAX_PAGES_PER_REGION:
        resp = session.get(next_link, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()
        items.extend(payload.get("Items", []))
        next_link = payload.get("NextPageLink")
        pages += 1
    return items


def _to_observation(item: dict, region: str, ts: str) -> Observation | None:
    meter_name = item.get("meterName") or ""
    if "Spot" in meter_name or "Low Priority" in meter_name:
        return None
    if item.get("unitOfMeasure") != "1 Hour":
        return None
    sku = item.get("armSkuName") or ""
    mapped = SKU_MAP.get(sku)
    if mapped is None:
        return None
    retail_price = item.get("retailPrice")
    if retail_price is None:
        return None  # never invent a price
    gpu_model, gpu_count = mapped
    return Observation(
        ts_utc=ts,
        source=NAME,
        provider="azure",
        gpu_model=gpu_model,
        gpu_count=gpu_count,
        price_usd_per_gpu_hr=float(retail_price) / gpu_count,
        region=item.get("armRegionName") or region,
        country=REGION_COUNTRY.get(region),
        interconnect=_interconnect(sku),
        tier="list",
        term="on_demand",
        raw_json=json.dumps(
            {
                "armSkuName": sku,
                "armRegionName": item.get("armRegionName"),
                "retailPrice": retail_price,
                "unitOfMeasure": item.get("unitOfMeasure"),
                "meterName": meter_name,
                "productName": item.get("productName"),
                "currencyCode": item.get("currencyCode"),
                "type": item.get("type"),
            }
        ),
    )


class AzureRetailCollector:
    name = NAME

    def collect(self, session: requests.Session) -> list[Observation]:
        ts = utc_now_iso()
        out: list[Observation] = []
        for region in REGIONS:
            try:
                items = _fetch_region(session, region)
            except requests.RequestException as exc:
                log.warning("azure_retail: region %s failed (%s), skipping", region, exc)
                continue
            for item in items:
                obs = _to_observation(item, region, ts)
                if obs is not None:
                    out.append(obs)
        log.info("azure_retail: %d observations across %d regions", len(out), len(REGIONS))
        return out
