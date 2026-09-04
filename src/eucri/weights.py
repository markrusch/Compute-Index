# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Data-driven weight determination (methodology-hashed: changes require a version bump).

Pure functions — no database access. Three mechanisms, all standard index procedure:

1. Scheduled weight reviews (the mechanism commodity indices use for annual/periodic
   reweighting, here weekly): provider weights are recomputed on a fixed schedule from
   a trailing observation window and held constant between reviews. A provider's review
   weight = median over its observed days of (daily qualifying capacity x tier
   multiplier), scaled by its presence ratio (days observed / collection days in the
   window). No discretion anywhere in the path.
2. Concentration cap: at print time no constituent may exceed a configured share of
   total weight; the excess is redistributed pro-rata over the uncapped constituents,
   iterated to a fixed point. Final weights are expressed as shares summing to 100.
3. Chain linking for the composite (EU-CRI-COMPUTE): a chained Laspeyres-style index
   over class sub-indices, so scheduled reweights shift influence without ever jumping
   the published level.
"""

from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta

from eucri.config import Composite, Factors
from eucri.normalise import NormalisedObs


@dataclass(frozen=True)
class ReviewWeight:
    weight: float  # raw review weight (capacity units x tier multiplier x presence)
    days_observed: int


def review_effective_date(on_date: str, anchor_weekday: int) -> str:
    """Most recent date <= on_date whose ISO weekday equals anchor_weekday."""
    d = date_type.fromisoformat(on_date)
    offset = (d.isoweekday() - anchor_weekday) % 7
    return (d - timedelta(days=offset)).isoformat()


def daily_capacity(
    observations: Sequence[NormalisedObs], factors: Factors
) -> dict[str, tuple[str, int]]:
    """Per provider for one day: (tier, qualifying capacity).

    Mirrors the representative-price rule: executable listings are preferred where a
    provider has both tiers. Capacity is observable only for executable marketplace
    listings (the capped sum of listed GPUs); list-price rows carry the default —
    their multiplicity is region enumeration, not inventory.
    """
    by_provider: dict[str, list[NormalisedObs]] = {}
    for obs in observations:
        by_provider.setdefault(obs.provider, []).append(obs)
    out: dict[str, tuple[str, int]] = {}
    for provider in sorted(by_provider):
        group = by_provider[provider]
        executable = [o for o in group if o.tier == "executable"]
        if executable:
            counts = [o.gpu_count for o in executable if o.gpu_count is not None]
            capacity = sum(counts) if counts else factors.weights.default_capacity
            out[provider] = ("executable", min(capacity, factors.weights.capacity_cap))
        else:
            out[provider] = ("list", factors.weights.default_capacity)
    return out


def provider_review_weights(
    daily: Mapping[str, Mapping[str, tuple[str, int]]], factors: Factors
) -> dict[str, ReviewWeight]:
    """Review weights from a window of daily_capacity() summaries.

    `daily` maps collection date -> {provider: (tier, capacity)} and must contain one
    entry per collection day in the window (empty dict when the class had no
    observations that day, so the presence ratio is honest).
    """
    n_days = len(daily)
    if n_days == 0:
        return {}
    per_provider: dict[str, list[float]] = {}
    for day in daily.values():
        for provider, (tier, capacity) in day.items():
            mult = factors.weights.executable_multiplier if tier == "executable" else 1.0
            per_provider.setdefault(provider, []).append(capacity * mult)
    return {
        provider: ReviewWeight(
            weight=statistics.median(values) * (len(values) / n_days),
            days_observed=len(values),
        )
        for provider, values in sorted(per_provider.items())
    }


def apply_concentration_cap(
    weights: Sequence[float], cap_pct: float
) -> tuple[list[float], frozenset[int]]:
    """Convert raw weights to shares summing to 100, capping any constituent above
    cap_pct with pro-rata redistribution over the uncapped, iterated to a fixed point.

    The cap is relaxed to 100/n when n constituents cannot mathematically satisfy it.
    Returns (shares, indices of capped constituents).
    """
    n = len(weights)
    if n == 0:
        raise ValueError("empty weight list")
    total = sum(weights)
    if total <= 0:
        raise ValueError("non-positive total weight")
    cap = max(cap_pct, 100.0 / n)
    shares = [w / total * 100.0 for w in weights]
    capped: set[int] = set()
    while True:
        over = [i for i in range(n) if i not in capped and shares[i] > cap + 1e-9]
        if not over:
            break
        capped.update(over)
        rest = [i for i in range(n) if i not in capped]
        rest_total = sum(weights[i] for i in rest)
        for i in capped:
            shares[i] = cap
        if not rest or rest_total <= 0:
            for i in range(n):
                shares[i] = 100.0 / n
            capped = set()
            break
        remaining = 100.0 - cap * len(capped)
        for i in rest:
            shares[i] = weights[i] / rest_total * remaining
    return shares, frozenset(capped)


def model_review_shares(
    class_capacity: Mapping[str, float], composite: Composite
) -> dict[str, float]:
    """Class basket shares (%) from aggregate observed capacity over the window.

    Share = class capacity / total capacity. With >=2 eligible classes the published
    floor and cap apply: capped classes hold exactly the cap (pro-rata redistribution,
    as in apply_concentration_cap), then floored classes are raised to exactly the
    floor with the difference scaled out of the unfloored, iterated to a fixed point.
    """
    positive = {c: v for c, v in class_capacity.items() if v > 0}
    if not positive:
        return {}
    names = sorted(positive)
    raw = [positive[c] for c in names]
    shares, _ = apply_concentration_cap(raw, composite.max_class_share_pct)
    if len(names) >= 2:
        floor = composite.min_class_share_pct
        floored: set[int] = set()
        while True:
            under = [
                i for i in range(len(names)) if i not in floored and shares[i] < floor - 1e-9
            ]
            if not under:
                break
            floored.update(under)
            rest = [i for i in range(len(names)) if i not in floored]
            rest_total = sum(shares[i] for i in rest)
            for i in floored:
                shares[i] = floor
            if not rest or rest_total <= 0:
                for i in range(len(names)):
                    shares[i] = 100.0 / len(names)
                break
            remaining = 100.0 - floor * len(floored)
            for i in rest:
                shares[i] = shares[i] / rest_total * remaining
    return dict(zip(names, shares, strict=True))


def chain_link(prev_value: float, links: Sequence[tuple[float, float, float]]) -> float:
    """One chaining step for the composite.

    links: (share, value_now, value_prev) per linkable class; shares are renormalised
    over the linkable classes, so a gapping class drops out of the day's link instead
    of gapping the composite.
    """
    if not links:
        raise ValueError("no linkable classes")
    total_share = sum(share for share, _, _ in links)
    if total_share <= 0:
        raise ValueError("non-positive total share")
    growth = sum(
        (share / total_share) * (now / before) for share, now, before in links
    )
    return prev_value * growth
