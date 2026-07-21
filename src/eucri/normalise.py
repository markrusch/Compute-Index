"""Normalisation to the reference unit (methodology-hashed: changes require a version bump).

Input: raw observation rows (sqlite Rows or dicts). Output: observations expressed in
the class reference unit — per-GPU-hour for the class's reference variant (headline:
H100 SXM 80GB), on-demand, EU/EEA datacenter, 8-GPU node — with published per-variant
adjustment factors applied, tagged with the model class, and everything else filtered
out. Variants not listed under any configured model class are excluded.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from eucri.config import Factors


class RowLike(Protocol):
    """Anything indexable by column name (dict, sqlite3.Row)."""

    def __getitem__(self, key: str) -> Any: ...


@dataclass(frozen=True)
class NormalisedObs:
    provider: str
    source: str
    tier: str  # 'executable' | 'list'
    model_class: str  # e.g. 'H100' — the class the observation prices
    gpu_model: str  # the raw variant observed
    gpu_count: int | None
    price_usd: float  # adjusted, per class-reference GPU-hour
    country: str
    last_verified: str | None  # static entries only (parsed from raw_json)


def _last_verified(row: RowLike) -> str | None:
    if row["source"] != "static_yaml":
        return None
    try:
        value = json.loads(row["raw_json"]).get("last_verified")
        return str(value) if value else None
    except (json.JSONDecodeError, TypeError):
        return None


def _variant_map(factors: Factors) -> dict[str, tuple[str, float]]:
    """variant name -> (model class, published adjustment factor)."""
    return {
        variant: (class_name, factor)
        for class_name, mc in factors.model_classes.items()
        for variant, factor in mc.variants.items()
    }


def normalise_observations(rows: Iterable[RowLike], factors: Factors) -> list[NormalisedObs]:
    """Apply the unit definition. Order of checks mirrors METHODOLOGY.md §1."""
    reference = factors.reference_unit
    variants = _variant_map(factors)
    out: list[NormalisedObs] = []
    for row in rows:
        gpu_model = row["gpu_model"]
        entry = variants.get(gpu_model)
        if entry is None:
            continue  # not a configured variant of any observed class
        model_class, factor = entry

        if row["term"] != reference.term:
            continue
        if row["tier"] not in ("executable", "list"):
            continue

        country = row["country"]
        if country not in factors.eu_eea_countries:
            continue

        gpu_count = row["gpu_count"]
        if gpu_count is not None and gpu_count < factors.filters.min_gpu_count:
            continue  # a known sub-node config never matches the unit (any tier)
        if row["tier"] == "executable" and gpu_count is None:
            continue  # executable asks must demonstrably cover the node config
        # list prices with unknown count pass: quoted per-GPU for the standard node

        price = float(row["price_usd_per_gpu_hr"]) * factor
        if not (factors.filters.price_floor_usd <= price <= factors.filters.price_ceiling_usd):
            continue

        out.append(
            NormalisedObs(
                provider=row["provider"],
                source=row["source"],
                tier=row["tier"],
                model_class=model_class,
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                price_usd=price,
                country=country,
                last_verified=_last_verified(row),
            )
        )
    return out
