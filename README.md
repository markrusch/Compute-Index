# eu-compute-index

**EU-CRI** — a daily, methodology-transparent reference price for renting AI compute in
Europe. Headline series **EU-CRI-H100**: one NVIDIA H100 SXM 80GB GPU-hour, on-demand,
8-GPU NVLink node, delivered from an EU/EEA data centre, in USD (EUR companion at the
ECB reference rate). Sub-indices: EU-sovereign providers, marketplace vs cloud.

The credibility strategy is radical methodological transparency on a regional niche:
every parameter is a visible config value, the methodology document is generated from
that config, raw observations are immutable, and every published print carries a full,
queryable constituent set. Design follows the IOSCO Principles for Financial Benchmarks
(2013) as voluntary best practice — see [GOVERNANCE.md](GOVERNANCE.md),
[METHODOLOGY.md](METHODOLOGY.md), and [SOURCES.md](SOURCES.md).

> EU-CRI is a research publication. It is not investment advice and is not administered
> as a benchmark under EU Regulation 2016/1011; it may not be used as a reference price
> in financial instruments.

## Quickstart

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows; source .venv/bin/activate on Linux
pip install -e .[dev]
python -m eucri.run migrate       # create data/eucri.db
python -m eucri.run daily         # collect today's observations + compute all series
python -m eucri.run constituents --date 2026-07-18
pytest
```

## Commands

| Command | Purpose |
|---|---|
| `migrate` | apply database migrations |
| `daily [--date D]` | run collectors (idempotent per source+day), compute all series, export CSV/charts |
| `constituents --date D [--series S]` | full audit table for a print (IOSCO P13/P16) |
| `backfill --from D --to D` | recompute prints from stored observations (never re-collects) |
| `validate` | source-dropout sensitivity + optional check-series correlation |
| `post` | regenerate the paste-ready Substack post |
| `docs` | regenerate METHODOLOGY.md + METHODOLOGY.lock |

## Layout

- `config/` — all methodology parameters (`factors.yaml`), sovereign constituent list,
  static provider price entries with `last_verified` dates
- `src/eucri/` — collectors (fail-soft, 1 request/source/day, honest User-Agent),
  normalisation, index calculation, outputs
- `data/eucri.db` — SQLite, committed; observations and prints are append-only
  (trigger-enforced)
- `site/` — CSV history and charts, regenerated daily

## Changing the methodology

Not casually. Any change to `config/factors.yaml`, `config/sovereign.yaml`,
`src/eucri/index.py`, or `src/eucri/normalise.py` fails CI unless the version is bumped,
the CHANGELOG has an entry, and the lock is regenerated — and takes effect only after
one publication's notice. Procedure: [GOVERNANCE.md](GOVERNANCE.md).
