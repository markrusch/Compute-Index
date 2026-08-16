"""Unit-definition filters (METHODOLOGY.md §1)."""

from __future__ import annotations

from typing import Any

import pytest

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


def test_model_class_tagging() -> None:
    assert normalise_observations([obs()], FACTORS)[0].model_class == "H100"
    out = normalise_observations([obs(gpu_model="A100_SXM")], FACTORS)
    assert len(out) == 1 and out[0].model_class == "A100"


def test_unlisted_variant_excluded() -> None:
    assert not keep(obs(gpu_model="V100_SXM"))
    assert not keep(obs(gpu_model="H100_NVL_94GB"))


def test_pcie_is_its_own_class_not_normalised_into_sxm() -> None:
    """v0.3.0: PCIe is a different product, priced separately, never adjusted into SXM."""
    out = normalise_observations([obs(gpu_model="H100_PCIE")], FACTORS)
    assert len(out) == 1
    assert out[0].model_class == "H100P"
    assert out[0].price_usd == 2.0, "no adjustment factor may be applied"


def test_no_assumed_variant_factors_remain() -> None:
    """Every configured variant factor must be exactly 1.0.

    v0.2.0 shipped `H100_NVL_94GB: 1.0  # default until measured` — an unmeasured
    equivalence sitting in the calculation path. A factor may only be introduced once
    measured from same-venue, same-day, same-SKU pairs, and none has yet qualified.
    """
    for name, mc in FACTORS.model_classes.items():
        for variant, factor in mc.variants.items():
            assert factor == 1.0, f"{name}/{variant} carries an unmeasured factor {factor}"
        assert list(mc.variants) == [mc.reference_variant], (
            f"{name} normalises a non-reference variant without a measured factor"
        )


def test_term_committed_excluded() -> None:
    assert not keep(obs(term="1_month"))


def test_non_eu_excluded() -> None:
    assert not keep(obs(country="US"))
    assert not keep(obs(country=None))


def test_executable_below_node_floor_excluded() -> None:
    """v0.3.0 floor is 2 GPUs, not 8 — the 8-GPU floor discarded all price discovery.

    Measured within-venue same-day, the per-GPU discount saturates at 2 GPUs
    (1x=1.000, 2x=0.951, 4x=0.916, 8x=0.916), so 2/4/8 are comparable within ~4% while
    the 1-GPU small-order premium (~9%) stays excluded rather than normalised away.
    """
    assert not keep(obs(gpu_count=1)), "1-GPU carries a small-order premium"
    assert keep(obs(gpu_count=2)), "2-GPU offers are the point of the v0.3.0 change"
    assert keep(obs(gpu_count=4))
    assert keep(obs(gpu_count=8))
    assert not keep(obs(gpu_count=None)), "executable asks must state their size"


def test_list_with_unknown_count_passes() -> None:
    assert keep(obs(tier="list", gpu_count=None))


def test_list_below_node_floor_excluded() -> None:
    assert not keep(obs(tier="list", gpu_count=1))
    assert keep(obs(tier="list", gpu_count=4))


def test_segment_is_tagged() -> None:
    assert normalise_observations([obs(provider="vast.ai")], FACTORS)[0].segment == "marketplace"
    assert normalise_observations([obs(provider="aws")], FACTORS)[0].segment == "hyperscaler"
    assert normalise_observations([obs(provider="nebius")], FACTORS)[0].segment == "neocloud"
    # an unclassified provider defaults to neocloud so it is not silently dropped from
    # the headline population
    assert normalise_observations([obs(provider="brand_new")], FACTORS)[0].segment == "neocloud"


def test_eur_quotes_converted_at_print_time_never_guessed() -> None:
    row = obs(source="scaleway", tier="list", price_usd_per_gpu_hr=3.3099,
              raw_json='{"currency": "EUR", "price_native_per_gpu_hr": 3.3099}')
    # without a rate the row is dropped rather than converted at an invented rate
    assert normalise_observations([row], FACTORS) == []
    out = normalise_observations([row], FACTORS, fx_eur_usd=1.1567)
    assert len(out) == 1
    assert out[0].currency == "EUR"
    assert out[0].price_native == 3.3099
    assert out[0].price_usd == pytest.approx(3.3099 * 1.1567)


def test_unsupported_currency_dropped() -> None:
    row = obs(raw_json='{"currency": "JPY", "price_native_per_gpu_hr": 400.0}')
    assert normalise_observations([row], FACTORS, fx_eur_usd=1.15) == []


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
