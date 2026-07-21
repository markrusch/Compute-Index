# Changelog

All methodology-affecting changes require an entry here **before** the lock regenerates
(see GOVERNANCE.md §1). Format: version, date, what changed, why.

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
