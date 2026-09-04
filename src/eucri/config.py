# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Typed loaders for the methodology config.

factors.yaml is the single source of truth for every methodology parameter;
nothing numeric that affects a print may be hard-coded elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


@dataclass(frozen=True)
class ReferenceUnit:
    gpu_model: str
    term: str
    location: str


@dataclass(frozen=True)
class Filters:
    min_gpu_count: int
    price_floor_usd: float
    price_ceiling_usd: float
    datacenter_verified_only: bool
    exclude_tiers: tuple[str, ...]


@dataclass(frozen=True)
class ModelClass:
    reference_variant: str
    variants: dict[str, float]  # variant name -> multiplicative adjustment factor


@dataclass(frozen=True)
class WeightReview:
    anchor_weekday: int  # ISO weekday a review takes effect (1 = Monday)
    window_days: int
    min_history_days: int


@dataclass(frozen=True)
class Weights:
    capacity_cap: int
    default_capacity: int
    executable_multiplier: float
    max_weight_share_pct: float
    review: WeightReview


@dataclass(frozen=True)
class Composite:
    base_value: float
    min_class_share_pct: float
    max_class_share_pct: float


@dataclass(frozen=True)
class TrimRule:
    """One step of the count-based trim ladder: for n >= min_n, clamp k from each end."""

    min_n: int
    k: int


@dataclass(frozen=True)
class Aggregation:
    unit: str  # 'offer' — the aggregation unit (v0.3.0: offers, not one price per provider)
    estimator: str
    trim_k: tuple[TrimRule, ...]
    min_providers: int
    min_offers: int
    smoothing_days: int

    def trim_for(self, n: int) -> int:
        """k for a panel of n observations — the last rule whose min_n is satisfied.

        Count-based because percentile winsorising is inert at small n: at n=6 the
        nearest-rank p5/p95 boundaries are the min and max, so nothing is clamped.
        """
        k = 0
        for rule in self.trim_k:
            if n >= rule.min_n:
                k = rule.k
        return min(k, max(0, (n - 1) // 2))  # never trim away the whole panel


@dataclass(frozen=True)
class Continuity:
    publish_chained: bool
    base_value: float
    divergence_review_pct: float


@dataclass(frozen=True)
class Fx:
    max_age_days: int


@dataclass(frozen=True)
class Staleness:
    warn_days: int
    exclude_days: int


@dataclass(frozen=True)
class Factors:
    methodology_version: str
    reference_unit: ReferenceUnit
    model_classes: dict[str, ModelClass]
    segments: dict[str, str]  # provider -> market segment
    series_populations: dict[str, tuple[str, ...]]  # series role -> segments drawn from
    filters: Filters
    weights: Weights
    composite: Composite
    aggregation: Aggregation
    continuity: Continuity
    fx: Fx
    staleness: Staleness
    jump_flag_pct: float
    measured_factors: dict[str, Any]
    eu_eea_countries: frozenset[str]

    @property
    def headline_class(self) -> str:
        """The class whose reference variant is the headline reference unit."""
        for name, mc in self.model_classes.items():
            if mc.reference_variant == self.reference_unit.gpu_model:
                return name
        raise ValueError(
            f"no model class has reference_variant {self.reference_unit.gpu_model!r}"
        )

    def segment_of(self, provider: str) -> str:
        """Market segment for a provider; unlisted providers default to 'neocloud'.

        Defaulting to neocloud rather than hyperscaler is deliberate: a new provider we
        have not classified is far more likely to be a specialist GPU cloud, and the
        hyperscaler segment is excluded from the headline, so the default must not
        silently drop an unknown name out of the headline population.
        """
        return self.segments.get(provider, "neocloud")

    def population_for(self, role: str) -> frozenset[str]:
        """Segments a series role draws from."""
        return frozenset(self.series_populations[role])


@dataclass(frozen=True)
class StaticProvider:
    provider: str
    url: str
    gpu_model: str
    price_usd_per_gpu_hr: float | None
    gpu_count: int
    country: str
    config_notes: str = ""
    last_verified: str | None = None  # YYYY-MM-DD
    extra: dict[str, Any] = field(default_factory=dict)


def load_factors(config_dir: Path | None = None) -> Factors:
    cfg_dir = config_dir or CONFIG_DIR
    raw = yaml.safe_load((cfg_dir / "factors.yaml").read_text(encoding="utf-8"))
    return Factors(
        methodology_version=str(raw["methodology_version"]),
        reference_unit=ReferenceUnit(
            gpu_model=str(raw["reference_unit"]["gpu_model"]),
            term=str(raw["reference_unit"]["term"]),
            location=str(raw["reference_unit"]["location"]),
        ),
        segments={
            provider: segment
            for segment, providers in raw["segments"].items()
            for provider in providers
        },
        series_populations={
            role: tuple(segments) for role, segments in raw["series_populations"].items()
        },
        model_classes={
            name: ModelClass(
                reference_variant=str(mc["reference_variant"]),
                variants={k: float(v) for k, v in mc["variants"].items()},
            )
            for name, mc in raw["model_classes"].items()
        },
        filters=Filters(
            min_gpu_count=int(raw["filters"]["min_gpu_count"]),
            price_floor_usd=float(raw["filters"]["price_floor_usd"]),
            price_ceiling_usd=float(raw["filters"]["price_ceiling_usd"]),
            datacenter_verified_only=bool(raw["filters"]["datacenter_verified_only"]),
            exclude_tiers=tuple(raw["filters"]["exclude_tiers"]),
        ),
        weights=Weights(
            capacity_cap=int(raw["weights"]["capacity_cap"]),
            default_capacity=int(raw["weights"]["default_capacity"]),
            executable_multiplier=float(raw["weights"]["executable_multiplier"]),
            max_weight_share_pct=float(raw["weights"]["max_weight_share_pct"]),
            review=WeightReview(
                anchor_weekday=int(raw["weights"]["review"]["anchor_weekday"]),
                window_days=int(raw["weights"]["review"]["window_days"]),
                min_history_days=int(raw["weights"]["review"]["min_history_days"]),
            ),
        ),
        composite=Composite(
            base_value=float(raw["composite"]["base_value"]),
            min_class_share_pct=float(raw["composite"]["min_class_share_pct"]),
            max_class_share_pct=float(raw["composite"]["max_class_share_pct"]),
        ),
        aggregation=Aggregation(
            unit=str(raw["aggregation"]["unit"]),
            estimator=str(raw["aggregation"]["estimator"]),
            trim_k=tuple(
                TrimRule(min_n=int(r["min_n"]), k=int(r["k"]))
                for r in sorted(raw["aggregation"]["trim_k"], key=lambda r: int(r["min_n"]))
            ),
            min_providers=int(raw["aggregation"]["min_providers"]),
            min_offers=int(raw["aggregation"]["min_offers"]),
            smoothing_days=int(raw["aggregation"]["smoothing_days"]),
        ),
        continuity=Continuity(
            publish_chained=bool(raw["continuity"]["publish_chained"]),
            base_value=float(raw["continuity"]["base_value"]),
            divergence_review_pct=float(raw["continuity"]["divergence_review_pct"]),
        ),
        fx=Fx(max_age_days=int(raw["fx"]["max_age_days"])),
        staleness=Staleness(
            warn_days=int(raw["staleness"]["warn_days"]),
            exclude_days=int(raw["staleness"]["exclude_days"]),
        ),
        jump_flag_pct=float(raw["quality"]["jump_flag_pct"]),
        measured_factors=dict(raw.get("measured_factors") or {}),
        eu_eea_countries=frozenset(raw["eu_eea_countries"]),
    )


def load_sovereign(config_dir: Path | None = None) -> frozenset[str]:
    cfg_dir = config_dir or CONFIG_DIR
    raw = yaml.safe_load((cfg_dir / "sovereign.yaml").read_text(encoding="utf-8"))
    return frozenset(raw["sovereign_providers"])


def load_static_providers(config_dir: Path | None = None) -> list[StaticProvider]:
    cfg_dir = config_dir or CONFIG_DIR
    providers = []
    for path in sorted((cfg_dir / "providers").glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        known = {f for f in StaticProvider.__dataclass_fields__ if f != "extra"}
        kwargs = {k: v for k, v in raw.items() if k in known}
        extra = {k: v for k, v in raw.items() if k not in known}
        lv = kwargs.get("last_verified")
        if lv is not None:
            kwargs["last_verified"] = str(lv)
        providers.append(StaticProvider(**kwargs, extra=extra))
    return providers
