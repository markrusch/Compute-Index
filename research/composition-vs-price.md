# When an index measures its own sampling

**How a 10% move in a compute benchmark turned out to be entirely composition noise — and what the unit definition had to do with it**

EU-CRI Research Note 2026-01 · 16 August 2026 · Mark Rusch

---

## Abstract

Between 18 July and 15 August 2026, the EU-CRI-H100 headline moved from $2.99 to $3.29,
a rise of 10.03%. Decomposing that move against the underlying constituent set shows the
matched-pair market move over the same window was **+0.00%**. Every basis point of the
published change came from constituents entering and leaving the panel.

The proximate cause was the estimator: a weighted median over roughly six providers has a
partial derivative of 1.0 with respect to exactly one constituent and 0.0 with respect to
every other. The *root* cause was the unit definition. A minimum-node-size filter of eight
GPUs admitted marketplace inventory on one collection day in ten, discarding a source that
had posted nine distinct prices spanning 12.3% — while retaining catalog rate cards that
had not moved once in a month.

The index was not measuring the compute market. It was measuring which of its sources
happened to answer.

---

## 1. Why this note exists

Compute became a listed commodity this year. CME Group lists Silicon Data H100 and B200
Rental Index Futures on NYMEX on 5 October 2026, cash-settled on a monthly average of a
daily $/GPU-hour index. ICE has announced competing contracts on the Ornn Compute Price
Index. Both are US venues, both USD, both global in scope.

That makes the construction of compute benchmarks a question with money attached, and it
makes the failure modes worth publishing rather than quietly patching. What follows is a
post-mortem of our own index, using our own data, with the code and the database public.

---

## 2. Data

All figures derive from `data/eucri.db` in the public repository, covering 14 collection
days between 2026-07-18 and 2026-08-15. Seven providers were ever observed: two executable
marketplaces (Vast.ai, RunPod), three neocloud rate cards (Nebius, DataCrunch, Seeweb) and
two hyperscaler catalogs (AWS, GCP via the `gpuhunt` package).

Every query below is reproducible from the committed database.

---

## 3. Finding 1 — the published series had almost no price content

Distinct prices per provider across all 14 days:

| Provider | Tier | Distinct prices observed |
|---|---|---|
| aws | list | 7.3616 |
| datacrunch | list | 3.2500 |
| gcp | list | 5.4424 |
| nebius | list | 3.8500 |
| seeweb | list | 2.1600 |
| vast.ai | executable | 2.2003 |
| **runpod** | executable | **2.99 → 3.29** |

Six of seven providers show exactly one price for the entire history. The whole dataset
contains one price move, at one provider.

At the time this looked like a fact about the market — that EU H100 rental prices are
sticky. Section 6 shows it was a fact about our filter.

## 4. Finding 2 — the move was composition, not price

Chain-linking on matched pairs (providers present on both days) isolates the price effect
from the composition effect:

| Date | n | Matched | Matched return | Chained $ | Published $ | Panel change |
|---|---|---|---|---|---|---|
| 07-18 | 7 | base | — | 2.9900 | 2.9900 | |
| 07-19 | 6 | 6 | +0.000% | 2.9900 | 3.2500 | −vast.ai |
| 07-21 | 6 | 6 | +0.000% | 2.9900 | 3.2500 | |
| 08-05 | 5 | 5 | +0.000% | 2.9900 | 3.8500 | −runpod |
| 08-06 | 5 | 5 | +0.000% | 2.9900 | 3.8500 | |
| 08-07 | 6 | 5 | +0.000% | 2.9900 | 3.2900 | +runpod |
| 08-08 → 08-15 | 6 | 6 | +0.000% | 2.9900 | 3.2900 | |

**Published: +10.03%. Matched-pair: +0.00%.**

Realised volatility of the published series over the window was 107.5%, annualised — of
which 100% is composition and 0.00% is price. Anyone who had sold options on this series
would have been short a pure jump process with no diffusion to hedge.

## 5. Finding 3 — two-thirds of the panel had no influence at all

Shocking each constituent by +10% on the 2026-08-15 panel (lower weighted median, $3.29):

| Shock | Index after | ∂ |
|---|---|---|
| +10% seeweb | 3.2900 | **0.00%** |
| +10% datacrunch | 3.5750 | +8.66% |
| +10% runpod | 3.6190 | +10.00% |
| +10% nebius | 3.2900 | **0.00%** |
| +10% gcp | 3.2900 | **0.00%** |
| +10% aws | 3.2900 | **0.00%** |

AWS and GCP — between them a large share of global compute capacity — had exactly zero
influence on the print. A hedger short EU-CRI-H100 was, in delta terms, short RunPod's rate
card and a little DataCrunch.

This is not an argument that medians are bad. SOFR is a volume-weighted median and is
among the most robust benchmarks in existence — because its constituent is *an observation
out of thousands*, not *a provider out of six*. A median is locally smooth over a dense
distribution and a step function over a sparse one. Panel density is the variable that
matters, and we did not have it.

## 6. Finding 4 — the root cause was the unit definition, not the estimator

The reference unit required a minimum of **eight GPUs** per offer, intended to pin the
contract to a standard 8-way SXM training node. Marketplace inventory is not shaped like
that. Checking Vast.ai's raw EU H100 SXM observations *before* the filter:

| Metric | Value |
|---|---|
| Distinct EU H100 prices posted | **9** |
| Price range | **+12.3%** |
| Implied annualised volatility | **~179%** |
| Observations passing the ≥8-GPU filter | **1** |
| Collection days with any passing offer | **1 of 10** |

The price discovery was in the data the whole time. The unit definition removed it and
left the rate cards behind.

This is the general lesson, and it is not specific to compute: **a specification filter
that correlates with the source of variance will silently convert a price index into a
catalog index.** The filter looked conservative. It was the single most destructive
parameter in the methodology.

### 6.1 What the market itself says about node size

Because Vast.ai posts several node sizes simultaneously, the node-size effect is directly
measurable within one venue on one day — no cross-provider or cross-time confounding:

| Node | USD/GPU-hr (2026-07-18) | Ratio vs 1× |
|---|---|---|
| 1× | 2.4027 | 1.000 |
| 2× | 2.2007 | 0.951 |
| 4× | 2.2006 | 0.916 |
| 8× | 2.2003 | 0.916 |

The per-GPU discount **saturates at two GPUs**. A 2-GPU offer and an 8-GPU offer differ by
under 4% per GPU; the meaningful premium is on the single-GPU order (~9%), which is a
small-order effect rather than a fabric effect.

So the eight-GPU floor was not buying comparability. It was buying almost nothing, at the
cost of nearly all the data.

## 7. Finding 5 — the robustness control did not exist

The methodology winsorised the constituent set at the nearest-rank 5th and 95th
percentiles. At n = 6, nearest-rank p5 resolves to the minimum and p95 to the maximum:

| n | p5/p95 | p10/p90 | p20/p80 |
|---|---|---|---|
| 6 | no-op | no-op | clamps |
| 8 | no-op | no-op | clamps |
| 10 | clamps (upper only) | clamps (upper only) | clamps |

The clamp performed no work on any print in the index's history, and even at n = 10 it
protects only the upper tail. A percentile control is inert at small n; small panels need
count-based trimming, which binds deterministically at every n.

We had shipped a robustness parameter that was decorative, and it was visible in config as
though it were doing something.

## 8. Finding 6 — the panel is bimodal, so the average is a fiction

The 2026-08-15 constituent set:

```
neocloud/marketplace [2.16  3.25  3.29  3.85] │ gap │ hyperscaler [5.44  7.36]
```

Cluster separation is **5.4 standard deviations**. A weighted mean across the full panel
returns $4.03–4.23, which falls inside the empty interval between the two clusters — a
number no participant in this market quotes or could transact at.

This is why the fix is not "use a mean instead of a median". Across a bimodal population
both estimators are wrong in different ways: the mean invents a price, and the median
picks a real price but responds to only one name. The fix is to stop averaging across the
gap: hyperscaler catalog rates belong in a hyperscaler series where they are the object of
measurement, not a drag on someone else's print.

## 9. What changed

Methodology v0.3.0, in order of measured impact:

1. **Node-size floor 8 → 2 GPUs.** Recovers marketplace price discovery at a measured
   comparability cost under 4%; the ~9% single-GPU small-order premium stays excluded.
2. **Aggregation over offers, not providers.** Restores a non-degenerate delta vector by
   making the panel dense — the SOFR construction, applied at the level where it works.
3. **Market-segment segregation.** Headline population is marketplace + neocloud;
   hyperscaler catalogs move to their own series.
4. **Count-based trim replaces percentile winsorising.** A control that binds.
5. **Tier-only provider weighting.** Capacity is unobservable for list sources; weighting
   by a default made a rate card that discloses nothing outrank a marketplace disclosing a
   real 2-GPU offer.
6. **No assumed variant factors.** Removed an unmeasured `H100_NVL_94GB: 1.0`; H100 PCIe
   became its own class. Factors must be measured from same-venue, same-day pairs.
7. **FX look-ahead fixed.** Two backfilled prints had used a rate published after their own
   print date.

## 10. What did not change, and what we are not claiming

We considered and **rejected** a chain-linked level as the headline. Chain-linking cures
composition instability, but a Laspeyres link with a same-day divisor reset contributes
exactly zero return on panel entry and exit — which makes in-panel rises permanent while
falls taken via exit and re-entry are laundered away. On this panel's churn that ratchet is
worth roughly +7.8% per cycle for a constituent at the concentration cap. The chained level
is published as a labelled companion; the headline is the raw cross-section, which is the
number a third party can most easily verify.

We also **rejected** three series we had specified:

- an **EU-vs-US basis**, because the neocloud tier is globally arbitraged and the spread is
  approximately zero;
- a **Nordic-vs-Continental basis**, because our own data refutes it — Azure's H100 price in
  Sweden equals West Europe exactly, and the 22.5% dispersion we had cited was Poland
  against Germany, both Continental;
- a **compute–power spark spread**, because power is 0.9–8.8% of the price, so the spread
  would be 91–99% one leg.

And the headline claim is deliberately narrow. EU-CRI has **no transaction feed**. It is a
reproducible, spec-locked, publicly auditable *price-transparency* benchmark, not a
settlement benchmark, and it should not be referenced in a financial contract. The
conditions that would have to be met before that changed are published, falsifiable, and
currently unmet — chiefly ≥15 constituents with ≥50% executable share, against today's five
constituents and roughly 17%.

## 11. Reproducibility

Everything above recomputes from the public repository:

```bash
git clone https://github.com/markrusch/Compute-Index
cd Compute-Index && pip install -e .[dev]
python -m eucri.run constituents --date 2026-08-16
python -m eucri.run backfill --from 2026-07-18 --to 2026-08-15
pytest
```

Raw observations and published prints are append-only, enforced by database triggers.
Every print records the methodology version it was computed under, so the v0.2.0 series
discussed here remains queryable alongside its v0.3.0 recomputation.

## 12. Limitations

The window is 14 collection days and seven providers. The node-size ratios in §6.1 rest on
three venue-days for the 2× step and one each for 4× and 8×; they are published as
provisional and are deliberately *not* used as adjustment factors in the calculation path.
The bimodality result is a single-day cluster separation, not a formal mixture test. None
of these weaken the two central findings — the composition decomposition in §4 and the
filter effect in §6 — which are arithmetic rather than inferential.

---

*EU-CRI is a research publication. It is not investment advice and may not be used as a
reference price in financial instruments. Author and administrator: Mark Rusch
(rusch.mh@gmail.com). Conflicts: the author may hold positions on venues whose prices the
index observes; see GOVERNANCE.md.*
