# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mark Rusch
"""Manually verified price entries for EU neoclouds without stable public APIs.

Each config/providers/*.yaml carries a `last_verified` date. Entries are warned at
staleness.warn_days; the index calculation excludes them at staleness.exclude_days
(exclusion happens in index.py so the raw observation is still recorded honestly).
A null price means the provider is skipped entirely — a price is never invented.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import requests

from eucri.config import load_factors, load_static_providers
from eucri.db import utc_now_iso
from eucri.models import Observation

log = logging.getLogger("eucri.collectors.static_yaml")


class StaticYamlCollector:
    name = "static_yaml"

    def collect(self, session: requests.Session) -> list[Observation]:
        factors = load_factors()
        today = datetime.now(UTC).date()
        out: list[Observation] = []
        for p in load_static_providers():
            if p.price_usd_per_gpu_hr is None:
                log.warning("%s: no verified price, skipped", p.provider)
                continue
            if p.last_verified:
                age = (today - datetime.strptime(p.last_verified, "%Y-%m-%d").date()).days
                if age > factors.staleness.warn_days:
                    log.warning(
                        "%s: last_verified %s is %d days old (excluded from index at %d)",
                        p.provider, p.last_verified, age, factors.staleness.exclude_days,
                    )
            out.append(
                Observation(
                    ts_utc=utc_now_iso(),
                    source=self.name,
                    provider=p.provider,
                    gpu_model=p.gpu_model,
                    gpu_count=p.gpu_count,
                    price_usd_per_gpu_hr=float(p.price_usd_per_gpu_hr),
                    region=None,
                    country=p.country,
                    interconnect="NVLink",
                    tier="list",
                    term="on_demand",
                    raw_json=json.dumps(
                        {"url": p.url, "last_verified": p.last_verified,
                         "config_notes": p.config_notes}
                    ),
                )
            )
        return out
