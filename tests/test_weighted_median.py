# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Exact weighted-median semantics (METHODOLOGY.md §3.6): lower weighted median."""

from __future__ import annotations

import pytest

from eucri.index import weighted_median


def test_single_constituent() -> None:
    assert weighted_median([(2.5, 8.0)]) == 2.5


def test_equal_weights_odd() -> None:
    pairs = [(1.0, 1.0), (2.0, 1.0), (3.0, 1.0)]
    assert weighted_median(pairs) == 2.0


def test_equal_weights_even_takes_lower() -> None:
    # cumulative reaches exactly 50% at the 2nd of 4 -> lower median, no interpolation
    pairs = [(1.0, 1.0), (2.0, 1.0), (3.0, 1.0), (4.0, 1.0)]
    assert weighted_median(pairs) == 2.0


def test_heavy_constituent_dominates() -> None:
    pairs = [(1.5, 10.0), (2.0, 1.0), (3.0, 1.0)]
    assert weighted_median(pairs) == 1.5


def test_exact_50_percent_boundary() -> None:
    # first constituent holds exactly half the total weight -> it is the median (>= rule)
    pairs = [(1.0, 5.0), (2.0, 3.0), (3.0, 2.0)]
    assert weighted_median(pairs) == 1.0


def test_input_order_irrelevant() -> None:
    pairs = [(3.0, 1.0), (1.0, 1.0), (2.0, 1.0)]
    assert weighted_median(pairs) == 2.0


def test_empty_raises() -> None:
    with pytest.raises(ValueError):
        weighted_median([])
