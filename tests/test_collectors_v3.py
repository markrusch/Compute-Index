# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Scaleway and Azure Retail collectors. Fixture-driven, no live network.

Both were added in v0.3.0 to widen a panel too thin to clear its own publish gate.
Scaleway matters most: it is EU-incorporated, quotes natively in EUR, and is the
constituent that pushed the headline back over the 5-provider gate.
"""

from __future__ import annotations

import json
from pathlib import Path

import responses

from eucri.collectors import base
from eucri.collectors.azure_retail import REGIONS, AzureRetailCollector
from eucri.collectors.azure_retail import URL as AZURE_URL
from eucri.collectors.scaleway import URL as SCALEWAY_URL
from eucri.collectors.scaleway import ZONES, ScalewayCollector

FIXTURES = Path(__file__).parent / "fixtures"
SCALEWAY_FIXTURE = json.loads((FIXTURES / "scaleway_fr_par_2.json").read_text(encoding="utf-8"))
AZURE_FIXTURE = json.loads((FIXTURES / "azure_westeurope.json").read_text(encoding="utf-8"))


def _scaleway_all_zones(payload: dict | None = None, status: int = 200) -> None:
    for zone in ZONES:
        responses.add(
            responses.GET, SCALEWAY_URL.format(zone=zone),
            json=payload if payload is not None else SCALEWAY_FIXTURE, status=status,
        )


# --- Scaleway -------------------------------------------------------------------------

@responses.activate
def test_scaleway_divides_instance_price_by_gpu_count() -> None:
    """hourly_price is per INSTANCE in EUR — a per-GPU series needs it divided."""
    _scaleway_all_zones()
    out = ScalewayCollector().collect(base.make_session())

    par2 = [o for o in out if o.region == "fr-par-2"]
    by_name = {json.loads(o.raw_json)["instance_name"]: o for o in par2}

    b300_8 = by_name["B300-SXM-8-288G"]
    assert b300_8.gpu_count == 8
    assert b300_8.price_usd_per_gpu_hr == 60.0 / 8  # 7.50, not 60.0
    assert b300_8.gpu_model == "B300_SXM"

    sxm2 = by_name["H100-SXM-2-80G"]
    assert sxm2.price_usd_per_gpu_hr == 6.6198 / 2
    assert sxm2.gpu_model == "H100_SXM"


@responses.activate
def test_scaleway_records_native_currency_for_print_time_conversion() -> None:
    """FX must not be frozen at collection — normalise.py converts at print time."""
    _scaleway_all_zones()
    out = ScalewayCollector().collect(base.make_session())
    raw = json.loads(out[0].raw_json)
    assert raw["currency"] == "EUR"
    assert raw["price_native_per_gpu_hr"] == out[0].price_usd_per_gpu_hr


@responses.activate
def test_scaleway_separates_sxm_from_pcie() -> None:
    """v0.3.0 prices SXM and PCIe as different classes — never folded together."""
    _scaleway_all_zones()
    by_name = {
        json.loads(o.raw_json)["instance_name"]: o
        for o in ScalewayCollector().collect(base.make_session())
    }
    assert by_name["H100-SXM-2-80G"].gpu_model == "H100_SXM"
    assert by_name["H100-1-80G"].gpu_model == "H100_PCIE"
    assert by_name["H100-SXM-2-80G"].interconnect == "NVLink"
    assert by_name["H100-1-80G"].interconnect == "PCIe"


@responses.activate
def test_scaleway_country_from_zone() -> None:
    _scaleway_all_zones()
    out = ScalewayCollector().collect(base.make_session())
    countries = {o.region.split("-")[0]: o.country for o in out}
    assert countries == {"fr": "FR", "nl": "NL", "pl": "PL"}


@responses.activate
def test_scaleway_skips_non_gpu_and_unmapped_instances() -> None:
    _scaleway_all_zones({"servers": {
        "DEV1-S": {"gpu": 0, "hourly_price": 0.01},
        "PLAY2-PICO": {"gpu": None, "hourly_price": 0.02},
        "RENDER-S": {"gpu": 1, "hourly_price": 1.0},
        "H100-SXM-2-80G": {"gpu": 2, "hourly_price": 6.6198},
    }})
    out = ScalewayCollector().collect(base.make_session())
    names = {json.loads(o.raw_json)["instance_name"] for o in out}
    assert names == {"H100-SXM-2-80G"}


@responses.activate
def test_scaleway_never_invents_a_missing_price() -> None:
    _scaleway_all_zones({"servers": {"H100-SXM-2-80G": {"gpu": 2, "hourly_price": None}}})
    assert ScalewayCollector().collect(base.make_session()) == []


@responses.activate
def test_scaleway_one_failing_zone_does_not_kill_the_run() -> None:
    """Nine zones, one source: a single 404 must not lose the other eight."""
    responses.add(responses.GET, SCALEWAY_URL.format(zone=ZONES[0]), status=404)
    for zone in ZONES[1:]:
        responses.add(responses.GET, SCALEWAY_URL.format(zone=zone),
                      json=SCALEWAY_FIXTURE, status=200)
    out = ScalewayCollector().collect(base.make_session())
    assert out, "a single failing zone emptied the whole collection"
    assert {o.region for o in out} == set(ZONES[1:])


# --- Azure Retail ---------------------------------------------------------------------

def _azure_all_regions(payload: dict | None = None) -> None:
    responses.add(
        responses.GET, AZURE_URL,
        json=payload if payload is not None else AZURE_FIXTURE, status=200,
    )


@responses.activate
def test_azure_divides_node_price_by_mapped_gpu_count() -> None:
    _azure_all_regions()
    out = AzureRetailCollector().collect(base.make_session())
    sxm = [o for o in out if o.gpu_model == "H100_SXM"]
    assert sxm, "no H100 SXM rows parsed"
    prices = sorted({round(o.price_usd_per_gpu_hr, 6) for o in sxm})
    assert prices == [round(119.45 / 8, 6), round(132.232 / 8, 6)]  # 14.93125, 16.529
    # the InfiniBand premium, measurable because only the fabric differs
    assert round(prices[1] / prices[0] - 1, 3) == 0.107


@responses.activate
def test_azure_excludes_spot_and_non_hourly() -> None:
    """Spot is an interruptible tier; a monthly reservation is not the on-demand unit."""
    _azure_all_regions()
    out = AzureRetailCollector().collect(base.make_session())
    meters = {json.loads(o.raw_json)["meterName"] for o in out}
    assert not any("Spot" in m for m in meters)
    assert not any("Reserved" in m for m in meters)


@responses.activate
def test_azure_excludes_gb200_pending_verified_accelerator_count() -> None:
    """A guessed denominator would silently corrupt a per-GPU series."""
    _azure_all_regions()
    out = AzureRetailCollector().collect(base.make_session())
    skus = {json.loads(o.raw_json)["armSkuName"] for o in out}
    assert "Standard_ND128isr_NDR_GB200_v6" not in skus


@responses.activate
def test_azure_skips_unmapped_skus_rather_than_guessing() -> None:
    _azure_all_regions()
    skus = {
        json.loads(o.raw_json)["armSkuName"]
        for o in AzureRetailCollector().collect(base.make_session())
    }
    assert "Standard_D8s_v5" not in skus


@responses.activate
def test_azure_records_interconnect_from_sku() -> None:
    _azure_all_regions()
    by_sku = {
        json.loads(o.raw_json)["armSkuName"]: o
        for o in AzureRetailCollector().collect(base.make_session())
    }
    assert by_sku["Standard_ND96isr_H100_v5"].interconnect == "InfiniBand"
    assert by_sku["Standard_ND96is_noIB_H100_v5"].interconnect == "Ethernet"


def test_azure_queries_only_eea_regions() -> None:
    """Switzerland is in EFTA but NOT the EEA; the UK left. Neither may be queried."""
    assert "switzerlandnorth" not in REGIONS
    assert "uksouth" not in REGIONS
    assert "westeurope" in REGIONS and "norwayeast" in REGIONS


@responses.activate
def test_azure_one_failing_region_does_not_kill_the_run() -> None:
    responses.add(responses.GET, AZURE_URL, status=503)
    responses.add(responses.GET, AZURE_URL, json=AZURE_FIXTURE, status=200)
    out = AzureRetailCollector().collect(base.make_session())
    assert out, "a single failing region emptied the whole collection"
