"""EU-CRI index calculation (methodology-hashed: changes require a version bump).

Pure functions — no database access — so the whole calculation is golden-file testable.
Implements METHODOLOGY.md §3 exactly.

v0.3.0 aggregates over **offers**, not over one representative price per provider. That
single change is what makes the estimator sound. A weighted median over ~6 providers has
∂I/∂p = 1 for exactly one constituent and 0 for every other, and steps discontinuously when
the 50% crossing point moves between names — measured on the real panel, +10% on four of six
constituents moved the print by 0.00%. A weighted median over many GPU-count-weighted offers
is the SOFR construction: dense enough to be locally smooth, and it always lands on a price
someone actually quoted (which, on this bimodal panel, a mean provably does not — the mean
falls in the empty interval between the neocloud and hyperscaler clusters).

Concentration is controlled in two stages so density does not become capture:
offers are weighted by capacity within a provider, then each provider's *aggregate* share
is capped and redistributed pro-rata, then that share is spread back over its offers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date as date_type
from datetime import datetime

from eucri.config import Factors
from eucri.models import Constituent, IndexPrint
from eucri.normalise import NormalisedObs
from eucri.weights import apply_concentration_cap


def trim_clamp(values: Sequence[float], k: int) -> tuple[list[float], float, float]:
    """Clamp the k highest and k lowest values to the k-th order statistic from each end.

    Count-based, not percentile-based. Nearest-rank percentile winsorising is *inert* at
    this panel size: at n=6 both p5/p95 and p10/p90 resolve to (min, max) and clamp
    nothing, so the shipped `winsorise_pct: [5, 95]` was a no-op for the entire history of
    the index. A count-based trim binds at every n.
    """
    if not values:
        raise ValueError("empty value list")
    ordered = sorted(values)
    if k <= 0:
        return list(values), ordered[0], ordered[-1]
    k = min(k, (len(ordered) - 1) // 2)
    lo, hi = ordered[k], ordered[len(ordered) - 1 - k]
    return [min(max(v, lo), hi) for v in values], lo, hi


def weighted_median(pairs: Sequence[tuple[float, float]]) -> float:
    """Lower weighted median of (price, weight) pairs.

    Sort by price ascending; return the first price at which cumulative weight reaches 50%
    of total weight. Callers guarantee a deterministic secondary order.
    """
    if not pairs:
        raise ValueError("empty observation list")
    ordered = sorted(pairs, key=lambda p: p[0])
    total = sum(w for _, w in ordered)
    if total <= 0:
        raise ValueError("non-positive total weight")
    cumulative = 0.0
    for price, weight in ordered:
        cumulative += weight
        if cumulative >= 0.5 * total:
            return price
    return ordered[-1][0]  # floating-point safety net


def _staleness_days(last_verified: str, on_date: str) -> int:
    lv = datetime.strptime(last_verified, "%Y-%m-%d").date()
    return (date_type.fromisoformat(on_date) - lv).days


def _offer_capacity(obs: NormalisedObs, factors: Factors) -> float:
    """Capacity a single offer contributes.

    Observable only for offers that state their size; a catalog row that does not is
    given the default, because its multiplicity is region enumeration, not inventory.
    """
    if obs.gpu_count is None:
        return float(factors.weights.default_capacity)
    return float(min(obs.gpu_count, factors.weights.capacity_cap))


def provider_offers(
    observations: Sequence[NormalisedObs],
    factors: Factors,
    on_date: str,
    population: frozenset[str] | None = None,
) -> tuple[dict[str, list[NormalisedObs]], dict[str, str]]:
    """Group qualifying offers by provider, and record why any provider was excluded.

    `population` restricts to a set of market segments — the tier-segregation control.
    The constituent distribution is bimodal (measured separation 5.4 sd between the
    neocloud/marketplace cluster and the hyperscaler cluster), so series draw from one
    side of that gap, never across it.
    """
    kept: dict[str, list[NormalisedObs]] = {}
    excluded: dict[str, str] = {}
    for obs in observations:
        if population is not None and obs.segment not in population:
            excluded.setdefault(obs.provider, "out_of_population")
            continue
        if obs.last_verified is not None and (
            _staleness_days(obs.last_verified, on_date) > factors.staleness.exclude_days
        ):
            excluded.setdefault(obs.provider, "stale")
            continue
        kept.setdefault(obs.provider, []).append(obs)
    for provider in kept:
        excluded.pop(provider, None)  # a provider with any surviving offer is not excluded
    return kept, excluded


def compute_print(
    date: str,
    series: str,
    observations: Sequence[NormalisedObs],
    factors: Factors,
    fx: tuple[float, str] | None,
    population: frozenset[str] | None = None,
    prev_prices: Mapping[str, float] | None = None,
    provider_weights: Mapping[str, float] | None = None,
) -> IndexPrint:
    """Compute one print. prev_prices (provider -> last included price) drives jump flags."""
    kept, excluded = provider_offers(observations, factors, date, population)

    n_providers = len(kept)
    n_offers = sum(len(v) for v in kept.values())
    n_executable = sum(
        1 for offers in kept.values() for o in offers if o.tier == "executable"
    )

    def gapped(flag: str) -> IndexPrint:
        audit = tuple(
            Constituent(
                provider=p, source=offers[0].source, tier=offers[0].tier,
                price_usd=min(o.price_usd for o in offers),
                weight=0.0, included=False, exclusion_reason="insufficient_sources",
            )
            for p, offers in sorted(kept.items())
        ) + tuple(
            Constituent(
                provider=p, source="", tier="", price_usd=0.0, weight=0.0,
                included=False, exclusion_reason=reason,
            )
            for p, reason in sorted(excluded.items())
        )
        return IndexPrint(
            date=date, series=series, value_usd=None, value_eur=None,
            fx_rate=fx[0] if fx else None, fx_date=fx[1] if fx else None,
            n_sources=n_providers, n_executable=n_executable,
            flags=flag, constituents=audit,
        )

    if n_providers < factors.aggregation.min_providers:
        return gapped("insufficient_sources")
    if n_offers < factors.aggregation.min_offers:
        return gapped("insufficient_offers")

    # --- stage 1: raw provider weight -------------------------------------------------
    # v0.3.0 weights a provider by TIER ONLY, not by capacity. Capacity is unobservable
    # for every list source — they disclose a rate card, not inventory — so the old
    # `default_capacity: 8` made AWS and Seeweb identical while giving vast.ai, which
    # honestly discloses a real 2-GPU offer, a *lower* weight than either. That inverted
    # the very hierarchy the executable multiplier exists to express. Capacity still
    # drives weighting where it is genuinely observed: between offers within a provider
    # (stage 2). A provider absent from an effective review is not penalised, because
    # under a tier-only rule there is no history to be missing.
    raw_weight: dict[str, float] = {}
    provider_flags: dict[str, str] = {}
    for provider, offers in kept.items():
        executable = any(o.tier == "executable" for o in offers)
        raw_weight[provider] = (
            factors.weights.executable_multiplier if executable else 1.0
        )

    ordered_providers = sorted(kept)
    shares, capped_idx = apply_concentration_cap(
        [raw_weight[p] for p in ordered_providers], factors.weights.max_weight_share_pct
    )
    provider_share = dict(zip(ordered_providers, shares, strict=True))
    for i, provider in enumerate(ordered_providers):
        if i in capped_idx:
            existing = provider_flags.get(provider, "")
            provider_flags[provider] = (
                "weight_capped" if not existing else f"{existing},weight_capped"
            )

    # --- stage 2: spread each provider's share over its offers ------------------------
    offer_pairs: list[tuple[float, float, str]] = []  # (price, weight, provider)
    for provider in ordered_providers:
        offers = kept[provider]
        caps = [_offer_capacity(o, factors) for o in offers]
        total_cap = sum(caps) or float(len(offers))
        share = provider_share[provider]
        for obs, cap in zip(offers, caps, strict=True):
            offer_pairs.append((obs.price_usd, share * (cap / total_cap), provider))

    # --- trim, then weighted median over offers ---------------------------------------
    k = factors.aggregation.trim_for(len(offer_pairs))
    clamped, lo, hi = trim_clamp([p for p, _, _ in offer_pairs], k)
    value_usd = weighted_median(
        sorted(
            ((c, w) for c, (_, w, _) in zip(clamped, offer_pairs, strict=True)),
            key=lambda t: t[0],
        )
    )
    value_eur = round(value_usd / fx[0], 6) if fx else None

    # --- audit rows: one per provider, carrying its aggregate share -------------------
    prev = prev_prices or {}
    audit: list[Constituent] = []
    for provider in ordered_providers:
        offers = kept[provider]
        idx = [i for i, (_, _, p) in enumerate(offer_pairs) if p == provider]
        # audit shows the price the provider ACTUALLY quoted, never the clamped value —
        # the clamp is recorded as a reason instead, so the trim is visible not silent
        rep = (
            weighted_median([(offer_pairs[i][0], offer_pairs[i][1]) for i in idx])
            if idx
            else min(o.price_usd for o in offers)
        )
        flags = provider_flags.get(provider, "")
        last = prev.get(provider)
        if last is not None and last > 0 and abs(rep - last) / last * 100.0 > factors.jump_flag_pct:
            flags = "jump" if not flags else f"{flags},jump"
        reason = None
        if any(clamped[i] != offer_pairs[i][0] for i in idx):
            reason = "trimmed"
        audit.append(
            Constituent(
                provider=provider,
                source=offers[0].source,
                tier="executable" if any(o.tier == "executable" for o in offers) else "list",
                price_usd=round(rep, 6),
                weight=round(provider_share[provider], 6),
                included=True,
                exclusion_reason=reason,
                flags=flags,
            )
        )
    for provider, reason in sorted(excluded.items()):
        audit.append(
            Constituent(
                provider=provider, source="", tier="", price_usd=0.0, weight=0.0,
                included=False, exclusion_reason=reason,
            )
        )

    executable_share = sum(
        w for _, w, p in offer_pairs
        if any(o.tier == "executable" for o in kept[p])
    )
    flags = ""
    if executable_share <= 0:
        flags = "no_executable_input"  # a list-price-only print, and it says so

    return IndexPrint(
        date=date, series=series, value_usd=round(value_usd, 6), value_eur=value_eur,
        fx_rate=fx[0] if fx else None, fx_date=fx[1] if fx else None,
        n_sources=n_providers, n_executable=n_executable, flags=flags,
        constituents=tuple(audit),
    )
