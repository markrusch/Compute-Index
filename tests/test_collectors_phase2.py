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
    assert sxm.gpu_count == 8  # stockStatus present for gpuCount 8
    assert sxm.country == "RO"  # documented recording convention (EU secure cloud)
    # NVL secure price captured too; PCIe has no model mapping -> absent
    assert by_model["H100_NVL_94GB"].price_usd_per_gpu_hr == 3.19
    assert "H100_PCIE" not in by_model


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
