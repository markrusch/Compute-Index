# Changelog

All methodology-affecting changes require an entry here **before** the lock regenerates
(see GOVERNANCE.md §1). Format: version, date, what changed, why.

## 0.3.0-dev — 2026-08-16

A structural rebuild. Validation against the stored observations showed the v0.2.0 index
was measuring its own sampling rather than the market: over 14 collection days the
published headline moved +10.03% while the matched-pair market move was **+0.00%**, and
a +10% shock to four of six constituents moved the print by **exactly 0.00%**. The root
cause was not the estimator but the unit definition. Changes, in order of impact:

- **Node-size floor 8 → 2 GPUs** (`filters.min_gpu_count`). The 8-GPU floor admitted
  marketplace inventory on **1 collection day in 10** and discarded essentially all price
  discovery: vast.ai posted 9 distinct EU H100 prices spanning +12.3% (~179% annualised
  vol) and almost none of it reached a print. Marketplace supply is 1/2/4-GPU. Measured
  within one venue on one day, the per-GPU discount **saturates at 2 GPUs** (1×=1.000,
  2×=0.951, 4×=0.916, 8×=0.916), so 2/4/8-GPU offers are comparable within ~4% and need
  no adjustment, while the ~9% 1-GPU small-order premium stays excluded rather than
  normalised away. **Effect on the level**: the headline now responds to marketplace
  price moves at all.
- **Aggregation unit: offer, not provider.** A weighted median over ~6 providers has
  ∂I/∂p = 1 for one name and 0 for every other, and steps discontinuously when the 50%
  crossing point moves. A capacity-weighted median over many offers is the SOFR
  construction — locally smooth, and it always lands on a price someone actually quoted.
- **Market-segment segregation.** The constituent distribution is bimodal (measured
  separation **5.4 sd** between the neocloud/marketplace cluster and the hyperscaler
  catalog cluster); a mean across that gap falls in an empty interval and prices nothing.
  The headline population is marketplace + neocloud; hyperscaler catalog rates move to
  `EU-CRI-H100-HS`, where they are the correct object of measurement. New series
  `EU-CRI-H100-NC` and `EU-CRI-H100-HS`; `EU-CRI-H100-CLOUD` is retired.
  **Effect on the level**: removes AWS/GCP catalog rates from the headline.
- **Count-based trim replaces percentile winsorising.** `winsorise_pct: [5, 95]` was a
  **no-op for the entire history of the index** — at n=6, nearest-rank p5/p95 *and*
  p10/p90 both resolve to (min, max) and clamp nothing; percentiles only begin binding
  at n≥10, and even there only on the upper tail. Replaced with clamping the k highest
  and k lowest, k by panel size.
- **Provider weighting is tier-only.** Capacity is unobservable for every list source, so
  `default_capacity: 8` made AWS and Seeweb identical while giving vast.ai — which
  honestly discloses a real 2-GPU offer — a *lower* weight than either, inverting the
  hierarchy the executable multiplier exists to express. Capacity still weights offers
  *within* a provider, where it is genuinely observed. Scheduled weight reviews and the
  `bootstrap_weights` / `no_weight_history` flags are retired from the calculation path.
- **No assumed variant factors.** `H100_NVL_94GB: 1.0 # default until measured` is
  removed; H100 PCIe becomes its own class rather than being folded into SXM. A factor
  may enter only when measured from same-venue, same-day, same-SKU pairs. Measured
  candidates are published under `measured_factors` and are *not* in the calculation path.
- **FX look-ahead fixed.** `latest_rate()` returned the globally latest ECB rate with no
  date bound, so backfilled prints for 2026-07-18/19 were computed with a rate published
  on 2026-07-21. Replaced with `rate_for(conn, date)` (`fx_date <= date`), regression
  tested. The EUR leg is now stated as **T-1**: the ECB publishes ~14:00 UTC, after the
  11:00 UTC cut-off, so same-day FX was never achievable. Providers quoting natively in
  EUR are converted from the native amount at print time rather than at collection.
- **New classes and series**: H200, B300, H100-PCIe. New sources: Scaleway (public
  Instance API, French/sovereign, also carries B300 in the EEA) and Azure Retail Prices
  (10 EEA regions). Switzerland is **not** in the EEA and is excluded from both.
- **Scope statement corrected.** Regulation (EU) 2025/914 (applying 1 Jan 2026) removes
  non-significant benchmarks from BMR Titles II–VI, but new Article 2(1c) separately
  applies Article 19 to *any commodity benchmark based on contributed input data*, exempt
  only below EUR 200m average notional over 12 months. The research-publication
  disclaimer is retained, and the settlement-grade preconditions are now published and
  falsifiable rather than implied.
- 2026-09-04 (still 0.3.0-dev, pre-launch): **methodology lock rehashed for an editorial
  change — no numeric effect.** The project was licensed (Apache-2.0 for the software,
  CC BY 4.0 for the documentation, separate terms for the index data), which added a
  two-line SPDX/copyright header to every source file including three hash-locked ones:
  `index.py`, `normalise.py`, `weights.py`. The diff is 6 inserted comment lines and zero
  deletions; the golden print, weighting, normalisation, trim and estimator tests all
  reproduce their pinned values unchanged. `methodology_version` is deliberately **not**
  bumped: this is editorial under §1's patch definition, and a bump would discard the
  stored weight review (`_load_review` drops a review whose methodology version differs)
  and force a recomputation for a licence header. Recorded here because the lock hash
  moving without a version change is exactly the kind of thing an audit trail exists to
  explain.

## 0.2.0-dev — 2026-07-19

Adaptive, data-driven weighting — standard index procedure (scheduled reviews,
concentration caps, chain linking) adapted to a young, fast-moving market:

- **Scheduled weight reviews** (new `src/eucri/weights.py`, hash-locked): constituent
  weights are recomputed each Monday from the trailing 28-day observation window —
  provider weight = median daily (qualifying capacity × tier multiplier) × presence
  ratio — and held fixed between reviews. Rationale: same-day capacity weighting let a
  single day's listings swing constituent influence; review weights make the weighting
  data-driven yet stable, and each review is stored append-only (`weight_sets`) and
  auditable via the new `weights` CLI command. Bootstrap rule below 5 collection days:
  same-day capacity weighting, prints flagged `bootstrap_weights`.
- **Concentration cap**: no constituent above 25% of a print's weight; excess
  redistributed pro-rata; included weights published as shares summing to 100.
  Rationale: dropout sensitivity showed a single marketplace (vast.ai, 53% of headline
  weight) could set the median alone; the memo's own rule ("if any single source moves
  the index >5%, cap its weight") is now structural, as in mainstream commodity
  benchmarks. **Effect on the level**: the headline no longer prints the dominant
  marketplace's ask when that venue alone crosses 50% of weight.
- **Model classes**: the unit definition generalises to classes (H100, A100, B200),
  each with a reference variant and published per-variant factors (replaces the flat
  `adjustment_factors` map). New class series `EU-CRI-A100` / `EU-CRI-B200`, published
  once they clear the same ≥5-provider gate.
- **EU-CRI-COMPUTE**: chain-linked composite of class series (base 100). Class basket
  shares = observed qualifying capacity share at each review (floor 5% / cap 75% when
  ≥2 classes are eligible). Chaining means reweights never jump the level, and the
  basket migrates across hardware generations without methodology changes.
- Governance clarification: a scheduled weight review executes a fixed published
  formula with no discretion — it is a data update, not a methodology change; the
  formula and its parameters remain hash-locked.

## 0.1.0-dev — 2026-07-18

Initial construction. Unit definition, filters, weights, and aggregation per the EU-CRI
methodology memo (17 Jul 2026):

- Unit: H100 SXM 80GB GPU-hour, on-demand, 8-GPU NVLink node, EU/EEA datacenter,
  excl. storage/egress; USD primary, EUR at ECB reference rate.
- Aggregation: per-provider representative price (min executable ask, else list price),
  winsorised 5/95 (nearest-rank, clamp), capacity-capped weighted median
  (cap 64, default 8, executable ×2), minimum 5 providers.
- Deviations from the memo, deliberate: static entries excluded (not just warned) when
  `last_verified` > 90 days; junk-listing guards (price band $0.25–$25.00, ≥8 GPUs,
  datacenter-verified only); >30% day-over-day constituent moves flagged for review.
- Governance: append-only observations and prints (trigger-enforced), constituent-level
  audit table, METHODOLOGY.lock hash guard in CI.
- 2026-07-18 (still 0.1.0-dev, pre-launch): capacity weighting tightened after the
  first live print — capacity counts as observable only for executable marketplace
  listings; list-price catalog rows always carry the default weight. Rationale: a
  hyperscaler catalog enumerating one instance type across N regions is not N units
  of available capacity, and the sum rule let aws/azure/gcp each hit the 64-GPU
  weight cap and set the median. Also: known sub-node configurations (e.g. 1x H100
  instances) are excluded at any tier, not only for executable asks.
