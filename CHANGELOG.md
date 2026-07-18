# Changelog

All methodology-affecting changes require an entry here **before** the lock regenerates
(see GOVERNANCE.md §1). Format: version, date, what changed, why.

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
