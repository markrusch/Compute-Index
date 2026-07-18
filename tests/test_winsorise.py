"""Nearest-rank winsorisation (METHODOLOGY.md §3.4).

Documented property: at p95 with n < 20 the upper boundary is the maximum itself, so
winsorisation never clamps small sets — it is defence-in-depth for larger sets and
for the published dispersion stats, not the primary outlier guard (the median is).
"""

from __future__ import annotations

import pytest

from eucri.index import nearest_rank, winsorise


def test_nearest_rank_basic() -> None:
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert nearest_rank(values, 50) == 3.0   # ceil(2.5) = 3rd
    assert nearest_rank(values, 5) == 1.0    # ceil(0.25) -> rank 1
    assert nearest_rank(values, 95) == 5.0   # ceil(4.75) = 5th
    assert nearest_rank(values, 100) == 5.0


def test_no_clamping_below_n20() -> None:
    values = [float(i) for i in range(1, 11)]  # n=10
    clamped, lo, hi = winsorise(values, 5, 95)
    assert clamped == values
    assert (lo, hi) == (1.0, 10.0)


def test_clamping_active_at_n21() -> None:
    values = [float(i) for i in range(1, 22)]  # 1..21
    clamped, lo, hi = winsorise(values, 5, 95)
    assert lo == 2.0    # ceil(0.05*21)=2 -> 2nd value
    assert hi == 20.0   # ceil(0.95*21)=20 -> 20th value
    assert min(clamped) == 2.0 and max(clamped) == 20.0
    assert clamped[0] == 2.0 and clamped[-1] == 20.0
    assert clamped[10] == 11.0  # interior untouched


def test_empty_raises() -> None:
    with pytest.raises(ValueError):
        nearest_rank([], 50)
