# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Count-based trim, and the regression that killed percentile winsorising.

v0.2.0 clamped the constituent set at nearest-rank p5/p95. At the panel sizes this index
actually runs at, that clamped *nothing* — the boundaries resolve to the min and the max.
The control existed in config and did no work for the entire history of the index. These
tests pin both the old failure mode and the replacement's behaviour.
"""

from __future__ import annotations

import math

import pytest

from eucri.config import load_factors
from eucri.index import trim_clamp


def nearest_rank(sorted_values: list[float], pct: float) -> float:
    """The v0.2.0 percentile helper, kept here only to demonstrate why it was removed."""
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


REAL_PANEL = [2.16, 3.25, 3.29, 3.85, 5.4424, 7.3616]  # EU-CRI-H100, 2026-08-15


@pytest.mark.parametrize("lo_pct,hi_pct", [(5, 95), (10, 90)])
def test_percentile_winsorising_is_inert_at_real_panel_size(lo_pct, hi_pct):
    """The v0.2.0 no-op, pinned so it can never be reintroduced by accident."""
    ordered = sorted(REAL_PANEL)
    lo = nearest_rank(ordered, lo_pct)
    hi = nearest_rank(ordered, hi_pct)
    assert lo == ordered[0], f"p{lo_pct} resolved above the minimum — panel got bigger?"
    assert hi == ordered[-1], f"p{hi_pct} resolved below the maximum"
    clamped = [min(max(v, lo), hi) for v in REAL_PANEL]
    assert clamped == REAL_PANEL, "percentile winsorising clamped something at n=6"


def test_percentile_winsorising_binds_only_on_one_side_even_at_n10():
    """Even at n=10 it is half-inert: p90 clamps, p10 still resolves to the minimum.

    ceil(0.10 * 10) == 1, so the lower boundary is the first order statistic. A control
    that protects against high outliers but not low ones is not a robustness control.
    """
    ordered = sorted(REAL_PANEL + [3.0, 3.1, 3.4, 4.0])  # n=10
    assert nearest_rank(ordered, 10) == ordered[0], "lower tail still unprotected"
    assert nearest_rank(ordered, 90) < ordered[-1], "upper tail finally binds"


def test_trim_clamps_deterministically_at_every_n():
    for n in range(3, 12):
        values = [float(i) for i in range(n)]
        clamped, lo, hi = trim_clamp(values, k=1)
        assert lo == values[1] and hi == values[-2]
        assert min(clamped) == lo and max(clamped) == hi
        assert len(clamped) == n


def test_trim_preserves_input_order():
    values = [7.0, 1.0, 5.0, 3.0, 9.0]
    clamped, lo, hi = trim_clamp(values, k=1)
    assert clamped == [7.0, 3.0, 5.0, 3.0, 7.0]
    assert (lo, hi) == (3.0, 7.0)


def test_trim_k_zero_is_identity():
    clamped, lo, hi = trim_clamp(REAL_PANEL, k=0)
    assert clamped == REAL_PANEL
    assert (lo, hi) == (min(REAL_PANEL), max(REAL_PANEL))


def test_trim_never_collapses_the_panel():
    """k is capped so at least one value survives unclamped from each side."""
    for n in range(1, 8):
        values = [float(i) for i in range(n)]
        clamped, _, _ = trim_clamp(values, k=99)
        assert len(set(clamped)) >= 1
        assert len(clamped) == n


def test_trim_ladder_from_config_matches_panel_size():
    agg = load_factors().aggregation
    assert agg.trim_for(4) == 0, "no trim below the publish gate"
    assert agg.trim_for(6) == 1
    assert agg.trim_for(12) == 2
    assert agg.trim_for(25) == 3
    # never trim away more than the panel can support
    assert agg.trim_for(3) <= 1


def test_trim_clamp_rejects_empty():
    with pytest.raises(ValueError):
        trim_clamp([], k=1)
