# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Golden-file test: the full v0.3.0 calculation on a hand-computed constituent set.

Every expected number below was computed by hand from METHODOLOGY.md §3 BEFORE being
run. If this test fails after an intentional methodology change, recompute by hand,
bump the version, and update the CHANGELOG — never just paste in what the code printed.
"""

from __future__ import annotations

from typing import Any

import pytest

from eucri.config import load_factors
from eucri.index import compute_print
from eucri.normalise import normalise_observations

FACTORS = load_factors()
DATE = "2026-07-18"
FX = (1.1435, "2026-07-17")
HEADLINE_POP = FACTORS.population_for("headline")


def obs(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "provider": "p", "source": "s", "tier": "list", "gpu_model": "H100_SXM",
        "gpu_count": 8, "price_usd_per_gpu_hr": 2.0, "country": "NL",
        "term": "on_demand", "raw_json": "{}",
    }
    base.update(overrides)
    return base


FRESH = '{"last_verified": "2026-07-18"}'
STALE = '{"last_verified": "2026-01-01"}'  # 198 days before DATE > 90-day threshold

GOLDEN_ROWS = [
    # vast.ai (marketplace, executable) — three surviving offers
    obs(provider="vast.ai", source="vast_ai", tier="executable",
        gpu_count=8, price_usd_per_gpu_hr=2.20),
    obs(provider="vast.ai", source="vast_ai", tier="executable",
        gpu_count=8, price_usd_per_gpu_hr=2.60),
    # v0.3.0: a 4-GPU offer now QUALIFIES (floor is 2, not 8)
    obs(provider="vast.ai", source="vast_ai", tier="executable",
        gpu_count=4, price_usd_per_gpu_hr=1.80),
    # v0.3.0: NVL is no longer normalised into the H100 class — dropped, not adjusted
    obs(provider="vast.ai", source="vast_ai", tier="executable", gpu_model="H100_NVL_94GB",
        gpu_count=16, price_usd_per_gpu_hr=2.00, country="RO"),
    # dropped by the junk-price floor
    obs(provider="vast.ai", source="vast_ai", tier="executable",
        gpu_count=8, price_usd_per_gpu_hr=0.10),
    # runpod (marketplace, executable)
    obs(provider="runpod", source="runpod", tier="executable",
        gpu_count=8, price_usd_per_gpu_hr=2.79),
    # neocloud list prices
    obs(provider="nebius", source="static_yaml", price_usd_per_gpu_hr=3.85,
        country="FI", raw_json=FRESH),
    obs(provider="datacrunch", source="static_yaml", price_usd_per_gpu_hr=3.25,
        country="FI", raw_json=FRESH),
    obs(provider="seeweb", source="static_yaml", price_usd_per_gpu_hr=2.16,
        country="IT", raw_json=FRESH),
    obs(provider="stale_prov", source="static_yaml", price_usd_per_gpu_hr=2.00,
        raw_json=STALE),
    # hyperscalers — excluded from the HEADLINE population (they get EU-CRI-H100-HS)
    obs(provider="azure", source="gpuhunt", gpu_count=None, price_usd_per_gpu_hr=6.98,
        country="IE"),
    obs(provider="aws", source="gpuhunt", gpu_count=8, price_usd_per_gpu_hr=6.55,
        country="SE"),
    obs(provider="aws", source="gpuhunt", gpu_count=8, price_usd_per_gpu_hr=7.10,
        country="IE"),
]

# ---------------------------------------------------------------------------------
# HAND COMPUTATION (headline population = marketplace + neocloud)
#
# Surviving offers:
#   vast.ai   2.20(8), 2.60(8), 1.80(4)   [NVL dropped: no class; 0.10 below floor]
#   runpod    2.79(8)
#   nebius    3.85(8), datacrunch 3.25(8), seeweb 2.16(8)
#   stale_prov EXCLUDED (stale); azure/aws EXCLUDED (out_of_population)
#   -> 5 providers (>=5 gate), 7 offers (>=5 gate)
#
# Stage 1 provider weight = tier multiplier only: vast.ai 2, runpod 2, list names 1 each.
#   sorted order [datacrunch, nebius, runpod, seeweb, vast.ai] -> raw [1,1,2,1,2], total 7
#   shares       [14.2857, 14.2857, 28.5714, 14.2857, 28.5714]
#   cap = max(25, 100/5=20) = 25 -> runpod and vast.ai both capped at 25
#   remaining 50 pro-rata over raw 1+1+1=3 -> each list name 50/3 = 16.666667
#
# Stage 2, vast.ai's 25 spread over its offers by capacity (8, 8, 4; total 20):
#   2.20 -> 10.0,  2.60 -> 10.0,  1.80 -> 5.0
#
# Trim at n=7 -> k=1. Sorted [1.80, 2.16, 2.20, 2.60, 2.79, 3.25, 3.85]
#   lo = 2.16, hi = 3.25  ->  1.80 clamps up to 2.16; 3.85 clamps down to 3.25
#
# Weighted median over clamped offers (total weight 100):
#   2.16 (16.666667) cum 16.666667   [seeweb]
#   2.16 ( 5.0)      cum 21.666667   [vast.ai 1.80 clamped]
#   2.20 (10.0)      cum 31.666667
#   2.60 (10.0)      cum 41.666667
#   2.79 (25.0)      cum 66.666667  >= 50  ->  VALUE = 2.79
#
# EUR = 2.79 / 1.1435 = 2.439878 (6dp)
# vast.ai audit price = weighted median of its OWN raw offers
#   (1.80,5) cum 5 | (2.20,10) cum 15 >= 12.5 -> 2.20
# ---------------------------------------------------------------------------------

EXPECTED_USD = 2.79
EXPECTED_EUR = 2.439878
EXPECTED_LIST_SHARE = pytest.approx(50 / 3, abs=1e-5)


def _compute(prev: dict[str, float] | None = None, population=HEADLINE_POP):
    normalised = normalise_observations(GOLDEN_ROWS, FACTORS)
    return compute_print(
        DATE, "EU-CRI-H100", normalised, FACTORS, FX,
        population=population, prev_prices=prev,
    )


def test_golden_headline() -> None:
    result = _compute()
    assert result.value_usd == EXPECTED_USD
    assert result.value_eur == EXPECTED_EUR
    assert result.fx_rate == 1.1435 and result.fx_date == "2026-07-17"
    assert result.n_sources == 5
    assert result.n_executable == 4  # offers, not providers
    assert result.flags == ""


def test_golden_hyperscalers_excluded_from_headline() -> None:
    """The bimodality control: catalog names are recorded, never averaged in."""
    by_provider = {c.provider: c for c in _compute().constituents}
    for name in ("aws", "azure"):
        assert not by_provider[name].included
        assert by_provider[name].exclusion_reason == "out_of_population"


def test_golden_constituent_audit() -> None:
    result = _compute()
    by_provider = {c.provider: c for c in result.constituents}
    assert len(by_provider) == 8  # 5 included + stale + aws + azure

    vast = by_provider["vast.ai"]
    assert vast.included
    assert vast.price_usd == 2.20, "audit shows the quoted price, not a clamped one"
    assert vast.weight == 25.0
    assert vast.flags == "weight_capped"
    assert vast.exclusion_reason == "trimmed"  # its 1.80 offer was clamped

    assert by_provider["runpod"].weight == 25.0
    assert by_provider["seeweb"].weight == EXPECTED_LIST_SHARE
    assert by_provider["datacrunch"].weight == EXPECTED_LIST_SHARE

    nebius = by_provider["nebius"]
    assert nebius.price_usd == 3.85, "quoted price survives in the audit row"
    assert nebius.exclusion_reason == "trimmed"

    assert by_provider["stale_prov"].exclusion_reason == "stale"
    assert not by_provider["stale_prov"].included


def test_golden_shares_sum_to_100() -> None:
    included = [c for c in _compute().constituents if c.included]
    assert sum(c.weight for c in included) == pytest.approx(100.0, abs=1e-6)


def test_golden_four_gpu_offer_is_included() -> None:
    """The single highest-impact v0.3.0 change: sub-8-GPU marketplace supply counts."""
    normalised = normalise_observations(GOLDEN_ROWS, FACTORS)
    vast_counts = sorted(
        o.gpu_count for o in normalised if o.provider == "vast.ai" and o.model_class == "H100"
    )
    assert vast_counts == [4, 8, 8], "the 4-GPU offer must survive the v0.3.0 floor"


def test_golden_jump_flag() -> None:
    result = _compute(prev={"runpod": 1.50})  # 2.79 vs 1.50 = +86% > 30%
    flags = {c.provider: c.flags for c in result.constituents}
    assert "jump" in flags["runpod"]
    assert "jump" not in flags["seeweb"]


def test_golden_hyperscaler_series_prices_the_catalog_tier() -> None:
    """Hyperscalers are not discarded — they are measured where they belong."""
    result = _compute(population=FACTORS.population_for("hyperscaler"))
    # only aws (2 rows) and azure (1 row) -> 2 providers, below the 5-provider gate
    assert result.value_usd is None
    assert result.flags == "insufficient_sources"
    assert result.n_sources == 2


def test_golden_gate_gaps_rather_than_fabricates() -> None:
    thin = [r for r in GOLDEN_ROWS if r["provider"] in ("nebius", "datacrunch")]
    result = compute_print(
        DATE, "EU-CRI-H100", normalise_observations(thin, FACTORS), FACTORS, FX,
        population=HEADLINE_POP,
    )
    assert result.value_usd is None
    assert result.flags == "insufficient_sources"
