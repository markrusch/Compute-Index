# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Shared dataclasses."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    """One raw price observation, exactly as collected (persisted immutably)."""

    ts_utc: str
    source: str
    provider: str
    gpu_model: str
    gpu_count: int | None
    price_usd_per_gpu_hr: float
    region: str | None
    country: str | None
    interconnect: str | None
    tier: str  # 'executable' | 'list'
    term: str
    raw_json: str


@dataclass(frozen=True)
class Constituent:
    """A provider's contribution to one print (audit row).

    For included constituents of a published print, `weight` is the final print share
    (all included shares sum to 100, post concentration cap). For excluded candidates
    and gapped prints it is the raw pre-cap weight.
    """

    provider: str
    source: str
    tier: str
    price_usd: float
    weight: float
    included: bool
    exclusion_reason: str | None = None
    flags: str = ""


@dataclass(frozen=True)
class IndexPrint:
    date: str
    series: str
    value_usd: float | None
    value_eur: float | None
    fx_rate: float | None
    fx_date: str | None
    n_sources: int
    n_executable: int
    flags: str
    constituents: tuple[Constituent, ...]
