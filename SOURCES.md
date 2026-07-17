# EU-CRI Data Sources

Collection conduct (all sources): public pages and public APIs only; no scraping behind
logins; robots.txt respected; **1 request per source per day**; honest User-Agent
(`EU-CRI-collector/x.y.z (research index; contact: rusch.mh@gmail.com)`); every collector
fails soft (log + continue — a source outage never fabricates or blocks a print).
Where a page is hostile to scraping, a manually refreshed static entry with a visible
`last_verified` date is used instead — more credible than a brittle scraper.

| Source | Endpoint | Auth | IOSCO tier | robots/ToS basis | Status | Last reviewed |
|---|---|---|---|---|---|---|
| Vast.ai | `POST https://console.vast.ai/api/v0/bundles/` | none | executable | Public search API used by the site's own search UI; robots.txt does not disallow `/api/` (checked at implementation) | Phase 1 | pending first run |
| Static EU neoclouds (8) | Public pricing pages (nebius, datacrunch, scaleway, ovhcloud, hetzner, genesis_cloud, seeweb, leaseweb) | none | list | Manual reads of public pages; entries carry `last_verified`, stale entries excluded at 90d | Phase 1 | see per-provider YAML |
| ECB FX (frankfurter.app) | `GET https://api.frankfurter.app/latest?from=EUR&to=USD` | none | FX only | Free public API redistributing ECB reference rates | Phase 1 | pending first run |
| RunPod | `POST https://api.runpod.io/graphql` (gpuTypes/lowestPrice) | none | executable | Public GraphQL endpoint; if auth becomes required, collector is retired (no workarounds) | Phase 2 | — |
| gpuhunt (dstack) | pip package; provider catalogs (AWS/Azure/GCP/Lambda/OVH, EU regions) | none | list | Open-source package redistributing public catalog prices; version pinned | Phase 2 | — |
| Shadeform | aggregator API | free key | list | Optional; only with an issued key per their terms | Phase 3 (optional) | — |
| ENTSO-E Transparency | REST API, day-ahead prices NL / DE-LU / FR / SE3 | free token | overlay only — **never an index input** | Public data platform, registered token | Phase 3 | — |

Validation-only cross-checks (never ingested): computeprices.com, cloud-gpus.com,
Silicon Data public prints, Kalshi/Ornn public levels.

Review cadence: each row's ToS basis re-checked when a collector changes, and at the
annual methodology review at the latest.
