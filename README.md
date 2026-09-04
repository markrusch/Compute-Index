# eu-compute-index

**EU-CRI** — a daily, fully reproducible reference price for renting AI compute in the
EU/EEA. Headline series **EU-CRI-H100**: one NVIDIA H100 SXM 80GB GPU-hour, on-demand,
per-GPU, ex-VAT, from an EU/EEA data centre, in USD with a EUR companion at the ECB
reference rate (T-1). Companion series by market segment (`-MKT` marketplace, `-NC`
neocloud, `-HS` hyperscaler catalog, `-SOV` EU-incorporated operators), by generation
(H200, B200, B300, A100, H100-PCIe), and **EU-CRI-COMPUTE**, a chain-linked composite
that follows the observed market across hardware generations.

The credibility strategy is reproducibility, not scale: every parameter is a visible
config value, the methodology document is generated from that config, raw observations
are immutable, every print carries a queryable constituent set, and the whole thing can
be rebuilt from public sources by anyone with the repo. Design follows the IOSCO
Principles for Financial Benchmarks (2013) as voluntary best practice — see
[GOVERNANCE.md](GOVERNANCE.md), [METHODOLOGY.md](METHODOLOGY.md), and
[SOURCES.md](SOURCES.md).

> **EU-CRI is a price-transparency benchmark, not a settlement benchmark.** It is a
> research publication, is not investment advice, and may not be used as a reference
> price in financial instruments. It has **no transaction feed** and does not claim one.
> The conditions that would have to be met before settlement use is credible are
> published in [GOVERNANCE.md](GOVERNANCE.md); as of v0.3.0, six of the seven are unmet.

Why it was rebuilt in v0.3.0, and what was wrong before:
[research/composition-vs-price.md](research/composition-vs-price.md).

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
| `daily [--date D]` | run collectors (idempotent per source+day), compute all series, regenerate the site, CSV and charts |
| `constituents --date D [--series S]` | full audit table for a print (IOSCO P13/P16) |
| `backfill --from D --to D` | recompute prints from stored observations (never re-collects) |
| `weights [--date D]` | show the stored weight review for a date (v0.3.0 weights providers by tier; reviews are retained for audit, not used in the calculation path) |
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
- `site/` — the published site, **regenerated from the database on every daily run** by
  `src/eucri/outputs/site.py`; do not hand-edit the HTML. Six pages: `index.html`
  (dashboard), `methodology.html`, `governance.html`, `research.html` and
  `research/*.html`. Plus `assets/` (the design system: `tokens.css`, `site.css`),
  `data/` (CSV history + `latest.json`), and `charts/` (PNGs used by the Substack post,
  not by the site — the site draws its own inline SVG).
- `site/components.html` — the design-system component gallery. A reference artefact, not
  linked from the site.
- `DESIGN.md` — the design system spec: tokens, chart rules, density, contrast ratios.
- `research/*.md` — research notes, rendered to `site/research/` by the generator.
- `config/source_links.yaml` — reference weblinks for the Sources panel and per-constituent
  links. Presentational only; not part of METHODOLOGY.lock.

## Deploying the dashboard

`site/` is a self-contained static site plus one optional serverless endpoint, so it can
be hosted anywhere that serves static files. Two targets are wired up:

Both targets serve **byte-identical** content. Every link in the generated site is
relative, so the site works equally at a subpath (`markrusch.github.io/Compute-Index/`)
and at a domain root (Vercel), and there are no external requests to differ between them.

- **GitHub Pages**: `.github/workflows/pages.yml` deploys `site/` on every push that
  touches it. Served at `https://markrusch.github.io/Compute-Index/`.
- **Vercel**: import the repo with **Root Directory set to `site`**. Served at the
  project root.

`site/api/refresh.js` is a Vercel-only serverless endpoint that can trigger `daily.yml`
on demand. **The v0.3.0 dashboard does not surface it** — deliberately, so the two hosts
behave identically rather than one carrying a button the other cannot honour. The
endpoint still functions if called directly; to use it, set two Vercel **Environment
Variables** (Project Settings → Environment Variables — never committed to the repo):
  - `GITHUB_DISPATCH_TOKEN` — a token scoped to just this repo's Actions
    (read/write), e.g. a fine-grained PAT limited to `markrusch/Compute-Index`
  - `GITHUB_REPO` — `markrusch/Compute-Index`

  The refresh endpoint refuses any date other than today (in UTC): these collectors
  report live market prices, not history, so a past date can never be honestly
  re-collected — see `GOVERNANCE.md` and `STYLE.md` on why a gap stays a gap.

## Changing the methodology

Not casually. Any change to `config/factors.yaml`, `config/sovereign.yaml`,
`src/eucri/index.py`, `src/eucri/normalise.py`, or `src/eucri/weights.py` fails CI
unless the version is bumped, the CHANGELOG has an entry, and the lock is regenerated —
and takes effect only after one publication's notice. Scheduled weight reviews execute
a fixed published formula and are data updates, not methodology changes. Procedure:
[GOVERNANCE.md](GOVERNANCE.md).

## Licence

Three kinds of material live here, under three different terms. A licence over source
code does not carry rights in the data a program produces, so they are stated separately.

| Material | Terms |
|---|---|
| **Software** — `src/`, `tests/`, build config | [Apache&nbsp;2.0](LICENSE) |
| **Documentation and research** — `METHODOLOGY.md`, `GOVERNANCE.md`, `SOURCES.md`, `DESIGN.md`, `STYLE.md`, `research/*.md` | [CC&nbsp;BY&nbsp;4.0](LICENSE-docs) |
| **Index data** — `site/data/`, `data/eucri.db` | [DATA-TERMS.md](DATA-TERMS.md) |

The methodology is openly licensed on purpose: a benchmark that cannot be checked is not
a benchmark, and this repo already claims every print is recomputable from public sources.
That claim is only real if you are actually permitted to do it.

**Name.** "EU-CRI" identifies this benchmark and the values published under it. Cite it,
critique it, build on it — but a fork must carry its own name, because a benchmark name
says who computed the value and under which published methodology. See [NOTICE](NOTICE).

**Status.** EU-CRI is a research publication: not investment advice, not administered by
an authorised benchmark administrator under Regulation (EU) 2016/1011, and not for use as
a reference price in a financial instrument. See [GOVERNANCE.md](GOVERNANCE.md).
