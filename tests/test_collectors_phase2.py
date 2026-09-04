# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""RunPod fixture parsing and gpuhunt transformation. No live network."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import responses

from eucri.collectors import base
from eucri.collectors.gpuhunt_ import GpuHuntCollector, _country
from eucri.collectors.runpod import URL as RUNPOD_URL
from eucri.collectors.runpod import RunPodCollector

FIXTURE = Path(__file__).parent / "fixtures" / "runpod_gputypes.json"


@responses.activate
def test_runpod_parses_fixture() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    responses.add(responses.POST, RUNPOD_URL, json=data, status=200)

    out = RunPodCollector().collect(base.make_session())

    by_model = {o.gpu_model: o for o in out}
    assert "H100_SXM" in by_model
    sxm = by_model["H100_SXM"]
    assert sxm.provider == "runpod" and sxm.tier == "executable"
    assert sxm.price_usd_per_gpu_hr == 2.99  # securePrice, not community
    assert sxm.gpu_count == 8  # largest probed size with stock
    assert sxm.country == "RO"  # documented recording convention (EU secure cloud)
    # NVL secure price captured too; PCIe has no model mapping -> absent
    assert by_model["H100_NVL_94GB"].price_usd_per_gpu_hr == 3.19
    assert "H100_PCIE" not in by_model


def test_runpod_falls_back_to_a_smaller_demonstrated_node_size() -> None:
    """The regression this collector exists to prevent.

    Probing only gpuCount:8 meant that whenever RunPod had no 8-GPU pod the row was
    recorded with gpu_count=None and dropped by normalise.py ("executable asks must
    demonstrably state their size") -- discarding a price that was in hand. Measured
    over the modern collector regime that accounted for 7 of 8 headline gaps, and it
    was verified live on 2026-09-04 (H100_SXM: 8x none, 4x Low, 2x Medium).
    """
    from eucri.collectors.runpod import demonstrated_node_size

    assert demonstrated_node_size({"c8": {"stockStatus": "Low"}}) == 8
    # No 8-GPU pod, but a 4-GPU one: the offer is real and must not be discarded.
    assert demonstrated_node_size(
        {"c8": {"stockStatus": None}, "c4": {"stockStatus": "Low"}}
    ) == 4
    # Largest wins when several sizes have stock.
    assert demonstrated_node_size(
        {"c8": {"stockStatus": "Low"}, "c2": {"stockStatus": "High"}}
    ) == 8
    # Nothing in stock anywhere stays None -- an honest "size not demonstrated",
    # never a fabricated count.
    assert demonstrated_node_size(
        {"c8": {"stockStatus": None}, "c4": {"stockStatus": None},
         "c2": {"stockStatus": None}}
    ) is None
    assert demonstrated_node_size({}) is None
    # 1-GPU offers are never probed: v0.3.0 excludes the ~9% small-order premium
    # rather than normalising it away, so a lone 1x pod must not rescue the row.
    assert demonstrated_node_size({"c1": {"stockStatus": "High"}}) is None


@responses.activate
def test_runpod_records_the_smaller_pod_rather_than_dropping_the_offer() -> None:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    responses.add(responses.POST, RUNPOD_URL, json=data, status=200)

    out = RunPodCollector().collect(base.make_session())

    nvl = {o.gpu_model: o for o in out}["H100_NVL_94GB"]
    # Fixture mirrors the live 2026-09-04 shape: no 8x/4x pod, 2x in stock.
    assert nvl.gpu_count == 2, "a 2-GPU pod is above the min_gpu_count floor and counts"


@dataclass
class _Item:
    provider: str
    instance_name: str
    location: str
    price: float
    gpu_count: int
    gpu_name: str
    gpu_memory: float | None = 80.0


def test_gpuhunt_transform() -> None:
    items = [
        _Item("aws", "p5.48xlarge", "eu-north-1", 63.86, 8, "H100"),
        _Item("gcp", "a3-highgpu-8g", "europe-west4-b", 88.0, 8, "H100"),
        _Item("azure", "ND96isr_H100_v5", "westeurope", 79.0, 8, "H100"),
        _Item("aws", "p5.4xlarge", "eu-west-1", 8.9, 1, "H100"),        # sub-node: dropped
        _Item("aws", "p5.48xlarge", "us-east-1", 55.0, 8, "H100"),      # US: kept, non-EU
        _Item("aws", "p5.48xlarge", "eu-west-2", 71.5, 8, "H100"),      # GB: country None
    ]
    out = GpuHuntCollector().to_observations(items)
    assert len(out) == 5  # only the 1-GPU instance is dropped at collection
    by_key = {(o.provider, o.region): o for o in out}

    aws_eu = by_key[("aws", "eu-north-1")]
    assert aws_eu.country == "SE"
    assert abs(aws_eu.price_usd_per_gpu_hr - 63.86 / 8) < 1e-9
    assert aws_eu.tier == "list"

    assert by_key[("gcp", "europe-west4-b")].country == "NL"  # zone suffix stripped
    assert by_key[("azure", "westeurope")].country == "NL"
    assert by_key[("aws", "us-east-1")].country == "US"       # stored for US-proxy
    assert by_key[("aws", "eu-west-2")].country is None       # GB unmapped -> excluded later


def test_gpuhunt_country_mapping_edges() -> None:
    assert _country("gcp", "europe-west4-c") == "NL"
    assert _country("gcp", "europe-west4") == "NL"
    assert _country("aws", "eu-central-2") is None  # CH deliberately unmapped
    assert _country("azure", "uksouth") is None
