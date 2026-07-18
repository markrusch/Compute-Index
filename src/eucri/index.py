"""EU-CRI index calculation (methodology-hashed: changes require a version bump).

Pure functions — no database access — so the whole calculation is golden-file testable.
Implements METHODOLOGY.md §3 exactly:

1. representative price per provider = min surviving executable ask, else min list price
2. staleness exclusion for static entries (> staleness.exclude_days)
3. winsorise at nearest-rank p5/p95, clamping to the boundary value
4. weight = min(sum of qualifying listed GPUs, capacity_cap) else default_capacity,
   x executable_multiplier for executable tier
5. lower weighted median: first price whose cumulative weight reaches 50% of total
6. publish gate: fewer than min_providers included -> value None, 'insufficient_sources'
"""

from __future__ import annotations

import math
from datetime import date as date_type
from datetime import datetime

from eucri.config import Factors
from eucri.models import Constituent, IndexPrint
from eucri.normalise import NormalisedObs


def nearest_rank(sorted_values: list[float], pct: float) -> float:
    """Nearest-rank percentile: value at rank ceil(pct/100 * n), 1-indexed."""
    if not sorted_values:
        raise ValueError("empty value list")
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_values)))
    return sorted_values[min(rank, len(sorted_values)) - 1]


def winsorise(
    values: list[float], pct_lo: float, pct_hi: float
) -> tuple[list[float], float, float]:
    """Clamp values outside [p_lo, p_hi] to the boundary. Returns (clamped, lo, hi)."""
    ordered = sorted(values)
    lo = nearest_rank(ordered, pct_lo)
    hi = nearest_rank(ordered, pct_hi)
    return [min(max(v, lo), hi) for v in values], lo, hi


def weighted_median(pairs: list[tuple[float, float]]) -> float:
    """Lower weighted median of (price, weight) pairs.

    Sort by price ascending (caller guarantees a deterministic secondary order);
    return the first price at which cumulative weight >= 50% of total weight.
    """
    if not pairs:
        raise ValueError("empty constituent list")
    ordered = sorted(pairs, key=lambda p: p[0])
    total = sum(w for _, w in ordered)
    cumulative = 0.0
    for price, weight in ordered:
        cumulative += weight
        if cumulative >= 0.5 * total:
            return price
    return ordered[-1][0]  # floating-point safety net


def _staleness_days(last_verified: str, on_date: str) -> int:
    lv = datetime.strptime(last_verified, "%Y-%m-%d").date()
    d = date_type.fromisoformat(on_date)
    return (d - lv).days


def representative_constituents(
    observations: list[NormalisedObs], factors: Factors, on_date: str
) -> list[Constituent]:
    """One candidate constituent per provider, with exclusions recorded, not dropped."""
    by_provider: dict[str, list[NormalisedObs]] = {}
    for obs in observations:
        by_provider.setdefault(obs.provider, []).append(obs)

    constituents: list[Constituent] = []
    for provider in sorted(by_provider):
        group = by_provider[provider]
        executable = [o for o in group if o.tier == "executable"]
        chosen_pool = executable if executable else group
        best = min(chosen_pool, key=lambda o: o.price_usd)
        tier = best.tier

        # capacity: sum of qualifying listed GPUs where observable, else default
        counts = [o.gpu_count for o in chosen_pool if o.gpu_count is not None]
        capacity = sum(counts) if counts else factors.weights.default_capacity
        weight = float(min(capacity, factors.weights.capacity_cap))
        if tier == "executable":
            weight *= factors.weights.executable_multiplier

        exclusion: str | None = None
        if best.last_verified is not None:
            if _staleness_days(best.last_verified, on_date) > factors.staleness.exclude_days:
                exclusion = "stale"

        constituents.append(
            Constituent(
                provider=provider,
                source=best.source,
                tier=tier,
                price_usd=best.price_usd,
                weight=weight,
                included=exclusion is None,
                exclusion_reason=exclusion,
            )
        )
    return constituents


def compute_print(
    date: str,
    series: str,
    observations: list[NormalisedObs],
    factors: Factors,
    fx: tuple[float, str] | None,
    prev_prices: dict[str, float] | None = None,
) -> IndexPrint:
    """Compute one print. prev_prices (provider -> last included price) drives jump flags."""
    candidates = representative_constituents(observations, factors, date)
    included = [c for c in candidates if c.included]

    # jump flags: >jump_flag_pct% day-over-day move flags for review, never excludes
    flagged: list[Constituent] = []
    prev = prev_prices or {}
    for c in candidates:
        flags = c.flags
        last = prev.get(c.provider)
        if (
            c.included
            and last is not None
            and last > 0
            and abs(c.price_usd - last) / last * 100.0 > factors.jump_flag_pct
        ):
            flags = "jump" if not flags else f"{flags},jump"
        flagged.append(
            Constituent(
                provider=c.provider, source=c.source, tier=c.tier, price_usd=c.price_usd,
                weight=c.weight, included=c.included,
                exclusion_reason=c.exclusion_reason, flags=flags,
            )
        )
    candidates = flagged
    included = [c for c in candidates if c.included]

    n_sources = len(included)
    n_executable = sum(1 for c in included if c.tier == "executable")

    if n_sources < factors.aggregation.min_providers:
        return IndexPrint(
            date=date, series=series, value_usd=None, value_eur=None,
            fx_rate=fx[0] if fx else None, fx_date=fx[1] if fx else None,
            n_sources=n_sources, n_executable=n_executable,
            flags="insufficient_sources", constituents=tuple(candidates),
        )

    prices = [c.price_usd for c in included]
    clamped, lo, hi = winsorise(
        prices, factors.aggregation.winsorise_pct[0], factors.aggregation.winsorise_pct[1]
    )

    # deterministic order: (clamped price, provider name); mark clamped constituents
    audit: list[Constituent] = []
    pairs: list[tuple[float, float, str]] = []
    clamp_map = dict(zip([c.provider for c in included], clamped, strict=True))
    for c in candidates:
        if not c.included:
            audit.append(c)
            continue
        clamped_price = clamp_map[c.provider]
        reason = c.exclusion_reason
        if clamped_price != c.price_usd:
            reason = "winsorised"  # included=1: value clamped, constituent stays in
        audit.append(
            Constituent(
                provider=c.provider, source=c.source, tier=c.tier, price_usd=c.price_usd,
                weight=c.weight, included=True, exclusion_reason=reason, flags=c.flags,
            )
        )
        pairs.append((clamped_price, c.weight, c.provider))

    ordered = sorted(pairs, key=lambda p: (p[0], p[2]))
    value_usd = weighted_median([(price, weight) for price, weight, _ in ordered])
    value_eur = round(value_usd / fx[0], 6) if fx else None

    return IndexPrint(
        date=date, series=series, value_usd=round(value_usd, 6), value_eur=value_eur,
        fx_rate=fx[0] if fx else None, fx_date=fx[1] if fx else None,
        n_sources=n_sources, n_executable=n_executable, flags="",
        constituents=tuple(audit),
    )
