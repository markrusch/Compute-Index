"""Normalisation to the reference unit (methodology-hashed: changes require a version bump).

Input: raw observation rows (sqlite Rows or dicts). Output: observations expressed in
the reference unit — H100 SXM 80GB per-GPU-hour, on-demand, EU/EEA datacenter, 8-GPU
node — with published adjustment factors applied and everything else filtered out.
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
    gpu_model: str
    gpu_count: int | None
    price_usd: float  # adjusted, per reference GPU-hour
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


def normalise_observations(rows: Iterable[RowLike], factors: Factors) -> list[NormalisedObs]:
    """Apply the unit definition. Order of checks mirrors METHODOLOGY.md §1."""
    reference = factors.reference_unit
    out: list[NormalisedObs] = []
    for row in rows:
        gpu_model = row["gpu_model"]
        if gpu_model == reference.gpu_model:
            factor = 1.0
        elif gpu_model in factors.adjustment_factors:
            factor = factors.adjustment_factors[gpu_model]
        else:
            continue  # not the reference model and no published adjustment

        if row["term"] != reference.term:
            continue
        if row["tier"] not in ("executable", "list"):
            continue

        country = row["country"]
        if country not in factors.eu_eea_countries:
            continue

        gpu_count = row["gpu_count"]
        if row["tier"] == "executable":
            # executable asks must demonstrably cover the node config
            if gpu_count is None or gpu_count < factors.filters.min_gpu_count:
                continue
        # list prices are quoted per-GPU for the standard node; unknown count passes

        price = float(row["price_usd_per_gpu_hr"]) * factor
        if not (factors.filters.price_floor_usd <= price <= factors.filters.price_ceiling_usd):
            continue

        out.append(
            NormalisedObs(
                provider=row["provider"],
                source=row["source"],
                tier=row["tier"],
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                price_usd=price,
                country=country,
                last_verified=_last_verified(row),
            )
        )
    return out
