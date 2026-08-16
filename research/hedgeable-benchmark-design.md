# What makes a compute benchmark hedgeable

**Design rules from oil, power, freight and repo — and which of them compute can actually satisfy**

EU-CRI Research Note 2026-02 · 16 August 2026 · Mark Rusch

---

## Abstract

Compute is being financialised on the assumption that a price index is enough to support a
derivatives market. It is not. A benchmark becomes hedgeable through specific structural
properties, each of which has been learned expensively by an older commodity complex. This
note extracts those properties, applies them to compute, and is explicit about which ones
compute currently fails — including for our own index.

The short version: the tradeable object in every mature complex is an **average over a
delivery period**, not a spot fix; the estimator must have a **non-degenerate delta
vector**; the panel must be **dense enough that the estimator is locally smooth**; and the
settlement value must become **final**. Compute today satisfies the first, is being built
to satisfy the second, and largely fails the third and fourth.

---

## 1. The state of play

| Venue | Index | Contract | Status |
|---|---|---|---|
| CME / NYMEX | Silicon Data H100 & B200 Rental | one month's rental cost, cash-settled | lists 5 Oct 2026 |
| ICE | Ornn Compute Price Index (OCPI) | USD cash-settled suite | announced, pending approval |
| — | EU-CRI | — | research publication, not for contracts |

Both listed contracts settle on a **monthly aggregation of a daily $/GPU-hour index**. That
convention is not an accident, and §3 explains why it is the single most important design
decision in the whole complex.

---

## 2. Five design rules, and where they come from

### 2.1 The delta vector must be non-degenerate

For a weighted median, ∂I/∂pₖ = 1 for exactly one constituent and 0 for all others. Three
consequences follow: providers who are not the median have no index beta, so the natural
short has no reason to sell it; the response is a jump function; and replication requires
switching 100% of notional at the crossing point, which is unwarehouseable.

This is why SOFR works and a six-name median does not. SOFR is a volume-weighted median
over thousands of daily repo transactions — its constituent is an observation, not an
institution. Density, not the choice of statistic, is what makes a median safe.

**Compute verdict:** achievable, but only by aggregating over *offers* rather than
providers, which in turn requires a unit definition that admits marketplace inventory
(see Research Note 2026-01).

### 2.2 Composition changes must not move the level

Every mature index separates the price effect from the composition effect with a divisor or
multiplier reset. The Baltic Exchange dropped Handysize from the BDI on 1 March 2018 and
changed the multiplier from 0.10907849 to 0.1 to hold the level continuous; the
C5TC(180)→C5TC(182) transition in January 2026 used a fixed differential, a new multiplier
of 0.11026, and legacy publication through 24 December 2026. Platts announced WTI Midland's
entry into Dated Brent twelve months in advance.

The pattern is consistent: **fixed cardinality, pre-announced reconstitution, a published
divisor, and parallel publication of old and new definitions.**

**Compute verdict:** necessary, but with a caveat most treatments miss. A Laspeyres link
with a same-day divisor reset contributes exactly zero return on entry and exit. Where
panel churn is high and correlated with price moves — a venue leaving *because* it cut
price — the link ratchets: rises made in-panel are permanent, falls taken while absent are
laundered out. We measured this at roughly +7.8% per cycle for a constituent at a 25% cap.
Chain-linking is the right tool for scheduled reconstitution and the wrong tool for daily
churn.

### 2.3 Assessed prices carry a bias that widens exactly when you need the hedge

Catalog rates are step functions with an unobservable, time-varying discount to transacted
levels. The bias widens in a glut and collapses in a squeeze, so tracking error against the
real market is **largest precisely in the tail being hedged**. That is what makes list-price
indices unhedgeable rather than merely imprecise, and it is the structural lesson of LIBOR.

**Compute verdict:** the binding constraint. Hyperscaler catalog rates for EU H100 have not
moved in a month while marketplace prices moved 12.3%. Ornn markets OCPI to ICE explicitly
on being built only from printed transactions. Any index without a transaction feed —
including ours — must say so on its face rather than implying otherwise.

### 2.4 Settlement must be final

Append-only revision is excellent audit practice and incompatible with clearing. Platts
corrects only for technical error or an upstream source correction, and explicitly **never**
for information arriving after publication. SOFR revises same-day only, at 14:30 ET, and
only for changes above one basis point.

The cost of breaking finality is not theoretical: after the LME cancelled nickel trades in
March 2022, open interest fell from roughly 236,000 to 126,000 lots, and volumes fell
across *unrelated* metals. Finality is a property of the whole venue's credibility, not of
one contract.

**Compute verdict:** unsolved, and mostly unaddressed. Note that finality is a *publication*
property, not a storage property — an immutable database and a final settlement value are
complementary, not in tension.

### 2.5 A gap is an undefined settlement

A minimum-source gate that publishes nothing is correct for a research series and fatal for
a cleared one: a CCP needs a number on every settlement date. Real contracts define a
fallback waterfall. CFTC Part 38 Appendix C names low participant counts as a
manipulation-susceptibility factor in terms that are uncomfortably direct: *"situations
susceptible to manipulation include those in which the volume of cash market transactions
and/or the number of participants... are very low."*

**Compute verdict:** the honest answer for a thin panel is to keep gapping and not claim
settlement suitability. A fallback waterfall that readmits the hyperscaler tier a
methodology has just excluded — at a 32–43% level difference — is worse than a gap, because
it is a gap wearing a number.

---

## 3. The one rule that matters most: settle on an average, never a fix

Across every mature complex, the object a contract settles against is an **arithmetic mean
over the delivery period**:

- EEX and Nasdaq power futures settle on the mean of hourly prices across the delivery
  period (~2,880 market time units in a month) — baseload and peakload.
- ICE JKM settles on a half-month assessment window.
- CME's own compute futures represent *"one month's worth of rental costs."*

Two reasons. First, averaging over ~30 daily prints is dramatically harder to manipulate
than a single fix — the lesson of the WM/Reuters 4pm scandal, after which the fixing window
was widened from one minute to five, following £1.1bn in FCA and $1.4bn in CFTC penalties.
Second, an average matches the economic exposure: nobody consumes a GPU-hour at 11:00 UTC
on a Tuesday; they consume a month of capacity.

**This is the design rule compute has already adopted**, and it is why a daily index with
moderate single-day noise can still support a sound monthly contract. It also means daily
precision is worth less than daily *consistency* — a point that argues against clever
estimators and for boring, reproducible ones.

---

## 4. What compute has that oil does not: generational obsolescence

Brent in 2026 is Brent in 1996. An H100 is not.

Azure's own EEA pricing on 2026-08-15 shows H200 SXM at **$13.78/GPU-hr against H100 SXM at
$16.53** — newer, strictly better silicon priced **17% below** the older generation. Silicon
Data's published statistics show the same asymmetry in volatility: H100 neocloud
coefficient of variation 2.6%, against B200 at 11.4% with an 18.9% maximum daily move.

Two implications:

1. **Never normalise across generations.** H100→H200 is a pure memory upgrade at identical
   FLOPS: per BF16 PFLOP-hour the H200 is 31% *dearer*; per HBM-TB/s-hour it is 9%
   *cheaper*. Two defensible normalisers disagree in **sign**. "Effective compute" is not
   salvageable as a settlement basis. Both CME and ICE reached the same conclusion
   independently — their contracts are per-GPU-type.
2. **The headline should not be anchored to the dead end of the curve.** An index whose
   flagship is H100 is indexing the generation with the least volatility and the least
   hedging demand.

---

## 5. Is there a correlated hedge?

A benchmark with no deliverable and no storage gets liquidity only if some *other* traded
instrument correlates with it. For compute the obvious candidate is power.

The decomposition does not support it. Per-GPU facility load for an H100 is about 1.59 kW
(700 W × 1.82 node overhead × 1.25 PUE). At European industrial rates that is roughly €0.11
per GPU-hour in the Nordics, €0.25 in Germany, €0.35 in Ireland — against a ~€2.75 price.
So electricity is **4–13% of the price**, and the elasticity of compute price to power is
0.04–0.13. German baseload at ~30% volatility contributes about 2.7% of compute volatility.

Power futures therefore hedge the **seller's residual cost**, not the index. Once capex is
sunk and revenue is contracted, power is 50–65% of a neocloud's remaining controllable
cost — which is a real exposure, but it is a spark-spread trade, not an index hedge. A
published "compute minus power" series would be 91–99% one leg and should not be presented
as a spread.

The honest conclusion is that compute currently has **no correlated hedge instrument**, and
liquidity will have to come from natural two-sided interest instead. There is academic
support that such interest exists: Bandi and Su (2026) construct the first compute futures
return panel sorted by GPU generation and maturity, and find evidence of a positive compute
risk premium attributable to **hedging pressure from compute providers** — i.e. structurally
long sellers paying to lay off risk.

---

## 6. The regulatory position, stated carefully

Regulation (EU) 2025/914, applying from 1 January 2026, narrows the EU Benchmarks
Regulation considerably: Titles II–VI now apply only to critical benchmarks, significant
benchmarks, and EU Climate Transition / Paris-aligned benchmarks. Non-significant
benchmarks fall outside them.

That is frequently over-read, and we over-read it ourselves before checking the text. New
**Article 2(1c)** separately provides that *"Article 19 applies to any commodity benchmark
based on contributed input data"*, unless it is a regulated-data benchmark, has a majority
of supervised contributors, or is a gold/silver/platinum critical benchmark. Article 2(2)(g)
exempts commodity benchmarks only where total average notional referencing them stays below
**EUR 200 million over 12 months** — a threshold a cleared contract would cross quickly.

Whether scraped public rate cards constitute "contributed input data" is an open question
on which we express no view. The practical point stands regardless: exchanges and clearing
members will require BMR-grade governance contractually long before the law compels it, so
the sensible course is to build to Annex II shape now and take advice before any contractual
use. *(Not legal advice.)*

---

## 7. Scorecard

| Rule | Mature complexes | Compute complex, 2026 | EU-CRI |
|---|---|---|---|
| Settle on a period average | universal | **adopted** | monthly series specified |
| Non-degenerate delta | required | index-dependent | addressed via offer-level aggregation |
| Composition-stable level | divisors, announced reconstitution | not published by any index | raw headline + labelled chained companion |
| Transaction-anchored | post-LIBOR default | OCPI claims it; others opaque | **fails — no transaction feed, stated openly** |
| Settlement finality | strict | undisclosed | **not claimed** |
| Defined disruption fallback | mandatory | undisclosed | **gaps honestly instead** |
| Published, reproducible methodology | PRA standard | **no incumbent publishes one** | full method + code + database public |

The last row is the only one where a small, transparent, regional index has a structural
advantage over well-funded incumbents — and it is the one we intend to compete on.

---

## Sources

Primary: CME Group press release, 11 Aug 2026; ICE investor-relations release on OCPI;
Regulation (EU) 2025/914 (EUR-Lex); CFTC Part 38 Appendix C; Baltic Exchange index change
notices (2018, 2026); Azure Retail Prices API (queried 2026-08-15); Scaleway public Instance
API (queried 2026-08-15); Bandi & Su, *(Early) AI Compute Asset Pricing*, arXiv 2607.12156.

---

*EU-CRI is a research publication. It is not investment advice and may not be used as a
reference price in financial instruments. Nothing in §6 is legal advice.*
