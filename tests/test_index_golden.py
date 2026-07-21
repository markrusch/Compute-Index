"""Golden-file test: the full calculation on a hand-computed constituent set.

Every expected number below was computed by hand from METHODOLOGY.md §3.
If this test fails after an intentional methodology change, recompute by hand,
bump the version, and update the CHANGELOG — never just update the numbers.
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
    # vast.ai (executable marketplace, one constituent):
    obs(provider="vast.ai", source="vast_ai", tier="executable",
        gpu_count=8, price_usd_per_gpu_hr=2.20),
    obs(provider="vast.ai", source="vast_ai", tier="executable",
        gpu_count=8, price_usd_per_gpu_hr=2.60),
    obs(provider="vast.ai", source="vast_ai", tier="executable", gpu_model="H100_NVL_94GB",
        gpu_count=16, price_usd_per_gpu_hr=2.00, country="RO"),
    # dropped by normalisation: 4-GPU executable offer, junk price
    obs(provider="vast.ai", source="vast_ai", tier="executable",
        gpu_count=4, price_usd_per_gpu_hr=1.80),
    obs(provider="vast.ai", source="vast_ai", tier="executable",
        gpu_count=8, price_usd_per_gpu_hr=0.10),
    # runpod (executable)
    obs(provider="runpod", source="runpod", tier="executable",
        gpu_count=8, price_usd_per_gpu_hr=2.79),
    # static clouds (list)
    obs(provider="nebius", source="static_yaml", price_usd_per_gpu_hr=3.85,
        country="FI", raw_json=FRESH),
    obs(provider="datacrunch", source="static_yaml", price_usd_per_gpu_hr=3.25,
        country="FI", raw_json=FRESH),
    obs(provider="seeweb", source="static_yaml", price_usd_per_gpu_hr=2.16,
        country="IT", raw_json=FRESH),
    obs(provider="stale_prov", source="static_yaml", price_usd_per_gpu_hr=2.00,
        raw_json=STALE),
    # hyperscaler with unobservable capacity
    obs(provider="azure", source="gpuhunt", gpu_count=None, price_usd_per_gpu_hr=6.98,
        country="IE"),
    # hyperscaler with two catalog rows (region enumeration != capacity):
    obs(provider="aws", source="gpuhunt", gpu_count=8, price_usd_per_gpu_hr=6.55,
        country="SE"),
    obs(provider="aws", source="gpuhunt", gpu_count=8, price_usd_per_gpu_hr=7.10,
        country="IE"),
]

# Hand-computed expectations (bootstrap weighting: no review set passed).
# Raw weights:
# vast.ai: surviving offers 2.20, 2.60, 2.00(NVL x1.0) -> rep 2.00;
#          executable capacity 8+8+16=32 -> min(32,64)=32 x2 = 64
# runpod:  rep 2.79, capacity 8 -> 8 x2 = 16
# seeweb 2.16 w8, datacrunch 3.25 w8, nebius 3.85 w8 (list -> default capacity)
# azure 6.98 w8 (unknown count), aws rep 6.55 w8 (two catalog rows are region
#   enumeration, NOT capacity -> default weight, never a sum)
# stale_prov: EXCLUDED (stale), recorded not dropped (keeps raw weight 8)
# included n=7 (>=5), winsorise 5/95 at n=7: bounds are min/max -> no clamping
# Concentration cap at 25%: raw total 120, vast.ai share 64/120 = 53.3% > 25%
#   -> vast.ai capped at 25; remaining 75 pro-rata over raw 56:
#      runpod 16/56*75 = 21.428571, each list 8/56*75 = 10.714286 (all < 25, stop)
# Weighted median on shares (price asc):
#   2.00 (25.0) cum 25.0 | 2.16 (10.714286) cum 35.714286 |
#   2.79 (21.428571) cum 57.142857 >= 50 -> value 2.79
# EUR: 2.79 / 1.1435 = 2.439878 (round 6)


def _compute(prev: dict[str, float] | None = None):
    normalised = normalise_observations(GOLDEN_ROWS, FACTORS)
    return compute_print(DATE, "EU-CRI-H100", normalised, FACTORS, FX, prev)


def test_golden_headline() -> None:
    result = _compute()
    assert result.value_usd == 2.79
    assert result.value_eur == 2.439878
    assert result.fx_rate == 1.1435 and result.fx_date == "2026-07-17"
    assert result.n_sources == 7
    assert result.n_executable == 2
    assert result.flags == ""


def test_golden_constituent_audit() -> None:
    result = _compute()
    by_provider = {c.provider: c for c in result.constituents}
    assert len(by_provider) == 8  # 7 included + 1 stale, all recorded

    vast = by_provider["vast.ai"]
    assert vast.included and vast.price_usd == 2.0
    assert vast.weight == 25.0  # capped share, was 53.3% raw
    assert vast.flags == "weight_capped"
    assert by_provider["runpod"].weight == pytest.approx(21.428571)
    assert by_provider["azure"].weight == pytest.approx(10.714286)
    aws = by_provider["aws"]
    assert aws.price_usd == 6.55  # min over catalog rows
    assert aws.weight == pytest.approx(10.714286)  # list rows never sum into capacity

    included_total = sum(c.weight for c in result.constituents if c.included)
    assert included_total == pytest.approx(100.0)

    stale = by_provider["stale_prov"]
    assert not stale.included and stale.exclusion_reason == "stale"
    assert stale.weight == 8.0  # excluded rows keep the raw pre-cap weight


def test_golden_review_weight_path() -> None:
    # Effective review weights passed in; azure absent -> default weight + flag.
    # Raw: vast 40, runpod 22, four list 8, azure default 8 (list x1) -> total 102.
    # Cap 25%: vast 39.2% -> capped 25; runpod 22/62*75 = 26.6% -> capped 25;
    # remaining 50 over raw 40 -> each of the five list providers 8/40*50 = 10.
    # Median: 2.00 (25) cum 25 | 2.16 (10) cum 35 | 2.79 (25) cum 60 >= 50 -> 2.79
    review = {"vast.ai": 40.0, "runpod": 22.0, "seeweb": 8.0, "datacrunch": 8.0,
              "nebius": 8.0, "aws": 8.0}
    normalised = normalise_observations(GOLDEN_ROWS, FACTORS)
    result = compute_print(DATE, "EU-CRI-H100", normalised, FACTORS, FX,
                           provider_weights=review)
    by_provider = {c.provider: c for c in result.constituents}
    assert result.value_usd == 2.79
    assert by_provider["vast.ai"].weight == 25.0
    assert by_provider["vast.ai"].flags == "weight_capped"
    assert by_provider["runpod"].weight == 25.0
    assert by_provider["azure"].weight == 10.0
    assert by_provider["azure"].flags == "no_weight_history"
    assert by_provider["seeweb"].weight == 10.0


def test_golden_jump_flag() -> None:
    result = _compute(prev={"vast.ai": 1.40, "nebius": 3.80})
    by_provider = {c.provider: c for c in result.constituents}
    assert by_provider["vast.ai"].flags == "jump,weight_capped"  # 1.40 -> 2.00 is +42.9%
    assert by_provider["nebius"].flags == ""                     # 3.80 -> 3.85 is +1.3%
    assert result.value_usd == 2.79                              # flags never change the value


def test_golden_insufficient_sources() -> None:
    rows = GOLDEN_ROWS[:2] + [
        obs(provider="nebius", source="static_yaml", price_usd_per_gpu_hr=3.85,
            country="FI", raw_json=FRESH),
        obs(provider="seeweb", source="static_yaml", price_usd_per_gpu_hr=2.16,
            country="IT", raw_json=FRESH),
    ]  # only 3 providers
    normalised = normalise_observations(rows, FACTORS)
    result = compute_print(DATE, "EU-CRI-H100", normalised, FACTORS, FX, None)
    assert result.value_usd is None and result.value_eur is None
    assert result.flags == "insufficient_sources"
    assert result.n_sources == 3
    assert len(result.constituents) == 3  # the gap still records its audit trail


def test_golden_winsorise_active_at_scale() -> None:
    rows = [
        obs(provider=f"p{i:02d}", price_usd_per_gpu_hr=float(i), country="NL")
        for i in range(1, 22)  # 21 list providers, prices 1..21, equal weights
    ]
    normalised = normalise_observations(rows, FACTORS)
    result = compute_print(DATE, "X", normalised, FACTORS, FX, None)
    by_provider = {c.provider: c for c in result.constituents}
    # p5 -> clamped up to 2.0, p95 -> clamped down to 20.0; both stay included
    assert by_provider["p01"].included and by_provider["p01"].exclusion_reason == "winsorised"
    assert by_provider["p21"].included and by_provider["p21"].exclusion_reason == "winsorised"
    assert by_provider["p11"].exclusion_reason is None
    # equal weights, cap never binds at 1/21 < 25%: shares 100/21 each
    assert by_provider["p11"].weight == pytest.approx(100.0 / 21, abs=1e-6)
    assert result.value_usd == 11.0  # equal weights, 21 values -> 11th
