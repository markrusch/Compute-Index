# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Normalisation to the reference unit (methodology-hashed: changes require a version bump).

Input: raw observation rows (sqlite Rows or dicts). Output: **one NormalisedObs per
surviving offer** — v0.3.0 aggregates over offers, not over one representative price per
provider, so nothing is collapsed here.

Two v0.3.0 changes carry most of the weight:

1. `filters.min_gpu_count` is 2, not 8. The 8-GPU floor passed 1 of 10 vast.ai collection
   days and discarded every marketplace offer — i.e. all of the index's price discovery.
   Measured within-venue on one day, the per-GPU discount saturates at 2 GPUs
   (1x=1.000, 2x=0.951, 4x=0.916, 8x=0.916), so 2/4/8 are comparable within ~4% and need
   no factor, while the 1-GPU small-order premium (~9%) is excluded rather than assumed away.

2. Variants are no longer normalised into a class by assumed factors. A class prices its
   reference variant only. H100 SXM and H100 PCIe are different products and are priced as
   different classes.

Currency: a row may be quoted in a currency other than USD (Scaleway quotes EUR). The
native amount is authoritative and conversion happens HERE, at print time, with the print's
FX rate — never frozen into the stored observation. Without a usable rate the row is
dropped rather than guessed.
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
    """One qualifying offer, expressed in the class reference unit."""

    provider: str
    source: str
    segment: str  # 'marketplace' | 'neocloud' | 'hyperscaler'
    tier: str  # 'executable' | 'list'
    model_class: str
    gpu_model: str
    gpu_count: int | None
    price_usd: float  # per class-reference GPU-hour, converted to USD
    currency: str  # the currency the offer was quoted in
    price_native: float  # the authoritative quoted amount, per GPU-hour
    country: str
    last_verified: str | None  # static entries only (parsed from raw_json)


def _raw(row: RowLike) -> dict[str, Any]:
    try:
        parsed = json.loads(row["raw_json"])
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _last_verified(row: RowLike, raw: dict[str, Any]) -> str | None:
    if row["source"] != "static_yaml":
        return None
    value = raw.get("last_verified")
    return str(value) if value else None


def _variant_map(factors: Factors) -> dict[str, tuple[str, float]]:
    """variant name -> (model class, published adjustment factor)."""
    return {
        variant: (class_name, factor)
        for class_name, mc in factors.model_classes.items()
        for variant, factor in mc.variants.items()
    }


def normalise_observations(
    rows: Iterable[RowLike],
    factors: Factors,
    fx_eur_usd: float | None = None,
) -> list[NormalisedObs]:
    """Apply the unit definition to every offer. Order of checks mirrors METHODOLOGY.md §1.

    `fx_eur_usd` is USD per 1 EUR (the ECB reference convention). Required only if
    non-USD rows are present; without it those rows are excluded, never converted at a
    guessed rate.
    """
    reference = factors.reference_unit
    variants = _variant_map(factors)
    out: list[NormalisedObs] = []
    for row in rows:
        gpu_model = row["gpu_model"]
        entry = variants.get(gpu_model)
        if entry is None:
            continue  # not the reference variant of any configured class
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
            continue  # below the node-size floor (excludes the 1-GPU small-order premium)
        if row["tier"] == "executable" and gpu_count is None:
            continue  # executable asks must demonstrably state their size

        raw = _raw(row)
        currency = str(raw.get("currency") or "USD").upper()
        native = raw.get("price_native_per_gpu_hr")
        price_native = float(native) if native is not None else float(
            row["price_usd_per_gpu_hr"]
        )

        if currency == "USD":
            price = price_native
        elif currency == "EUR":
            if not fx_eur_usd:
                continue  # no rate available: drop the row rather than invent a rate
            price = price_native * fx_eur_usd
        else:
            continue  # unsupported quote currency — never guessed

        price *= factor
        if not (factors.filters.price_floor_usd <= price <= factors.filters.price_ceiling_usd):
            continue

        out.append(
            NormalisedObs(
                provider=row["provider"],
                source=row["source"],
                segment=factors.segment_of(row["provider"]),
                tier=row["tier"],
                model_class=model_class,
                gpu_model=gpu_model,
                gpu_count=gpu_count,
                price_usd=price,
                currency=currency,
                price_native=price_native,
                country=country,
                last_verified=_last_verified(row, raw),
            )
        )
    return out
