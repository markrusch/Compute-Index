# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Unit tests for the data-driven weight mechanics (METHODOLOGY.md §3.1–3.2)."""

from __future__ import annotations

import pytest

from eucri.config import load_factors
from eucri.normalise import NormalisedObs
from eucri.weights import (
    apply_concentration_cap,
    chain_link,
    daily_capacity,
    model_review_shares,
    provider_review_weights,
    review_effective_date,
)

FACTORS = load_factors()


def nobs(provider: str, tier: str = "executable", gpu_count: int | None = 8,
         model_class: str = "H100", price_usd: float = 2.0,
         segment: str | None = None) -> NormalisedObs:
    return NormalisedObs(
        provider=provider, source="s",
        segment=segment or FACTORS.segment_of(provider),
        tier=tier, model_class=model_class,
        gpu_model="H100_SXM", gpu_count=gpu_count, price_usd=price_usd,
        currency="USD", price_native=price_usd, country="NL",
        last_verified=None,
    )


# --- review schedule -----------------------------------------------------------------

def test_review_effective_date_monday_anchor() -> None:
    assert review_effective_date("2026-07-20", 1) == "2026-07-20"  # a Monday
    assert review_effective_date("2026-07-21", 1) == "2026-07-20"
    assert review_effective_date("2026-07-19", 1) == "2026-07-13"  # Sunday -> prior Monday
    assert review_effective_date("2026-07-26", 1) == "2026-07-20"


# --- daily capacity ------------------------------------------------------------------

def test_daily_capacity_executable_sums_and_caps() -> None:
    out = daily_capacity(
        [nobs("v", gpu_count=8), nobs("v", gpu_count=16), nobs("v", gpu_count=64)],
        FACTORS,
    )
    assert out["v"] == ("executable", 64)  # 88 capped at capacity_cap


def test_daily_capacity_list_defaults_and_executable_preferred() -> None:
    out = daily_capacity(
        [nobs("x", tier="list", gpu_count=None), nobs("y", tier="list"),
         nobs("y", tier="executable", gpu_count=24)],
        FACTORS,
    )
    assert out["x"] == ("list", FACTORS.weights.default_capacity)
    assert out["y"] == ("executable", 24)


# --- provider review weights ---------------------------------------------------------

def test_provider_review_weights_median_and_presence() -> None:
    daily = {
        "d1": {"a": ("executable", 8), "b": ("list", 8)},
        "d2": {"a": ("executable", 16)},
        "d3": {"a": ("executable", 24), "b": ("list", 8)},
        "d4": {"a": ("executable", 16)},
    }
    out = provider_review_weights(daily, FACTORS)
    # a: daily values 16, 32, 48, 32 (x2 executable) -> median 32, presence 4/4
    assert out["a"].weight == pytest.approx(32.0)
    assert out["a"].days_observed == 4
    # b: daily values 8, 8 (list x1) -> median 8, presence 2/4 -> 4.0
    assert out["b"].weight == pytest.approx(4.0)
    assert out["b"].days_observed == 2


def test_provider_review_weights_empty_window() -> None:
    assert provider_review_weights({}, FACTORS) == {}


# --- concentration cap ---------------------------------------------------------------

def test_cap_noop_when_no_share_exceeds() -> None:
    shares, capped = apply_concentration_cap([8.0] * 6, 25.0)
    assert shares == pytest.approx([100.0 / 6] * 6)
    assert capped == frozenset()


def test_cap_single_dominant_constituent() -> None:
    # golden case from the headline: raw [64, 8, 16, 8, 8, 8, 8]
    shares, capped = apply_concentration_cap([64.0, 8.0, 16.0, 8.0, 8.0, 8.0, 8.0], 25.0)
    assert shares[0] == pytest.approx(25.0)
    assert shares[2] == pytest.approx(21.428571, abs=1e-6)
    assert shares[1] == pytest.approx(10.714286, abs=1e-6)
    assert sum(shares) == pytest.approx(100.0)
    assert capped == frozenset({0})


def test_cap_cascades_to_second_constituent() -> None:
    # raw [40, 22, 8, 8, 8, 8, 8]: capping 40 pushes 22 over the cap too
    shares, capped = apply_concentration_cap([40.0, 22.0, 8.0, 8.0, 8.0, 8.0, 8.0], 25.0)
    assert shares[0] == pytest.approx(25.0)
    assert shares[1] == pytest.approx(25.0)
    assert shares[2] == pytest.approx(10.0)
    assert capped == frozenset({0, 1})


def test_cap_relaxes_when_infeasible() -> None:
    # 2 constituents cannot both sit below 25%: cap relaxes to 100/n = 50
    shares, capped = apply_concentration_cap([10.0, 10.0], 25.0)
    assert shares == pytest.approx([50.0, 50.0])
    assert capped == frozenset()


# --- model basket shares -------------------------------------------------------------

def test_model_shares_single_class() -> None:
    assert model_review_shares({"H100": 640.0}, FACTORS.composite) == {"H100": 100.0}


def test_model_shares_cap_applies() -> None:
    shares = model_review_shares({"H100": 970.0, "A100": 30.0}, FACTORS.composite)
    assert shares["H100"] == pytest.approx(75.0)  # capped at max_class_share_pct
    assert shares["A100"] == pytest.approx(25.0)


def test_model_shares_floor_applies() -> None:
    shares = model_review_shares(
        {"H100": 800.0, "A100": 194.0, "B200": 6.0}, FACTORS.composite
    )
    # cap: H100 80% -> 75; A100 194/200*25 = 24.25, B200 0.75 -> floored to 5,
    # remainder 95 scaled pro-rata over (24.25, 75)
    assert shares["B200"] == pytest.approx(5.0)
    assert shares["A100"] == pytest.approx(24.25 / 99.25 * 95, abs=1e-6)
    assert shares["H100"] == pytest.approx(75.0 / 99.25 * 95, abs=1e-6)
    assert sum(shares.values()) == pytest.approx(100.0)


def test_model_shares_ignores_zero_capacity() -> None:
    shares = model_review_shares({"H100": 640.0, "B200": 0.0}, FACTORS.composite)
    assert shares == {"H100": 100.0}


# --- composite chain link ------------------------------------------------------------

def test_chain_link_single_class() -> None:
    assert chain_link(100.0, [(100.0, 2.42, 2.20)]) == pytest.approx(110.0)


def test_chain_link_renormalises_over_linkable() -> None:
    # class B gapped: its 40% share renormalises onto A; A moved +5%
    assert chain_link(200.0, [(60.0, 2.10, 2.00)]) == pytest.approx(210.0)


def test_chain_link_weighted_growth() -> None:
    # A (75%) +10%, B (25%) -10% -> growth 0.75*1.1 + 0.25*0.9 = 1.05
    value = chain_link(100.0, [(75.0, 2.20, 2.00), (25.0, 1.80, 2.00)])
    assert value == pytest.approx(105.0)


def test_chain_link_empty_raises() -> None:
    with pytest.raises(ValueError):
        chain_link(100.0, [])
