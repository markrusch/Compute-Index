"""Unit-definition filters (METHODOLOGY.md §1)."""

from __future__ import annotations

from typing import Any

from eucri.config import load_factors
from eucri.normalise import normalise_observations

FACTORS = load_factors()


def obs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "provider": "p", "source": "s", "tier": "executable", "gpu_model": "H100_SXM",
        "gpu_count": 8, "price_usd_per_gpu_hr": 2.0, "country": "NL",
        "term": "on_demand", "raw_json": "{}",
    }
    base.update(overrides)
    return base


def keep(row: dict[str, Any]) -> bool:
    return len(normalise_observations([row], FACTORS)) == 1


def test_reference_row_passes() -> None:
    assert keep(obs())


def test_non_reference_model_without_factor_excluded() -> None:
    assert not keep(obs(gpu_model="A100_SXM"))
    assert not keep(obs(gpu_model="H100_PCIE"))


def test_nvl_adjusted_with_published_factor() -> None:
    out = normalise_observations(
        [obs(gpu_model="H100_NVL_94GB", price_usd_per_gpu_hr=2.0)], FACTORS
    )
    assert len(out) == 1
    assert out[0].price_usd == 2.0 * FACTORS.adjustment_factors["H100_NVL_94GB"]


def test_term_committed_excluded() -> None:
    assert not keep(obs(term="1_month"))


def test_non_eu_excluded() -> None:
    assert not keep(obs(country="US"))
    assert not keep(obs(country=None))


def test_executable_below_node_config_excluded() -> None:
    assert not keep(obs(gpu_count=4))
    assert not keep(obs(gpu_count=None))


def test_list_with_unknown_count_passes() -> None:
    assert keep(obs(tier="list", gpu_count=None))


def test_price_band() -> None:
    assert not keep(obs(price_usd_per_gpu_hr=0.10))   # junk-listing floor
    assert not keep(obs(price_usd_per_gpu_hr=30.0))   # sanity ceiling
    assert keep(obs(price_usd_per_gpu_hr=FACTORS.filters.price_floor_usd))


def test_static_last_verified_parsed_from_raw_json() -> None:
    row = obs(source="static_yaml", tier="list",
              raw_json='{"last_verified": "2026-07-01"}')
    out = normalise_observations([row], FACTORS)
    assert out[0].last_verified == "2026-07-01"
    # non-static sources never carry last_verified
    out2 = normalise_observations([obs(raw_json='{"last_verified": "2026-07-01"}')], FACTORS)
    assert out2[0].last_verified is None
