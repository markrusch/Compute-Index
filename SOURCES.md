# EU-CRI Data Sources

Collection conduct (all sources): public pages and public APIs only; no scraping behind
logins; robots.txt respected; **1 request per source per day**; honest User-Agent
(`EU-CRI-collector/x.y.z (research index; contact: rusch.mh@gmail.com)`); every collector
fails soft (log + continue — a source outage never fabricates or blocks a print).
Where a page is hostile to scraping, a manually refreshed static entry with a visible
`last_verified` date is used instead — more credible than a brittle scraper.

| Source | Endpoint | Auth | IOSCO tier | robots/ToS basis | Status | Last reviewed |
|---|---|---|---|---|---|---|
| Vast.ai | `POST https://console.vast.ai/api/v0/bundles/` | none | executable | Public search API used by the site's own search UI; scope = datacenter-verified hosts only (verification=verified AND hosting_type=1); offers stored globally, EU filter in the calculation path | live | 2026-07-18 |
| Static EU neoclouds (8) | Public pricing pages (nebius, datacrunch→Verda, scaleway, ovhcloud, hetzner, genesis_cloud, seeweb, leaseweb) | none | list | Manual reads of public pages; entries carry `last_verified`, warned at 45d, excluded at 90d. 3 priced (nebius, datacrunch, seeweb); 5 null with documented reasons (JS-only pages, no H100 product, monthly-only, 404) | live | 2026-07-18 |
| ECB FX (frankfurter.dev) | `GET https://api.frankfurter.dev/v1/latest?from=EUR&to=USD` | none | FX only | Free public API redistributing ECB reference rates (frankfurter.app 301s here) | live | 2026-07-18 |
| RunPod | `POST https://api.runpod.io/graphql` (gpuTypes/securePrice) | none | executable | Public GraphQL endpoint; secure cloud only; secure pricing is region-flat and deliverable from EU-RO/EU-SE/EU-NL — observations recorded against EU-RO by convention. If auth becomes required, collector is retired (no workarounds) | live | 2026-07-18 |
| gpuhunt (dstack) | pip package; aws/azure/gcp catalogs, 8-GPU H100 instances | none | list | Open-source package redistributing public catalog prices. Known gap: the azure catalog carried no H100 rows on 2026-07-18 — azure is currently absent from the constituent set | live | 2026-07-18 |
| Shadeform | aggregator API | free key | list | Optional; only with an issued key per their terms | not built (key needed) | — |
| ENTSO-E Transparency | REST API, day-ahead prices NL / DE-LU / FR / SE3 | free token | overlay only — **never an index input** | Public data platform; collector skips cleanly until ENTSOE_TOKEN is set | built, token pending | 2026-07-18 |

Validation-only cross-checks (never ingested): computeprices.com, cloud-gpus.com,
Silicon Data public prints, Kalshi/Ornn public levels.

Review cadence: each row's ToS basis re-checked when a collector changes, and at the
annual methodology review at the latest.
