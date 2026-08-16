# EU-CRI Governance

Administrator and author: **Mark Rusch** (rusch.mh@gmail.com), Amsterdam.
This document implements the IOSCO Principles for Financial Benchmarks (2013) as
voluntary best practice. EU-CRI is a research publication: it is not licensed for use in
financial instruments and any request to hard-wire it into a financial contract will be
refused.

### Regulatory scope — stated precisely

**Regulation (EU) 2025/914** (in force 8 June 2025, applying from **1 January 2026**)
narrowed the EU Benchmarks Regulation: Titles II–VI now apply only to critical
benchmarks, significant benchmarks, and EU Climate Transition / Paris-aligned benchmarks.
A non-significant benchmark falls outside them.

That is easy to over-read, and an earlier draft of this document did over-read it. New
**Article 2(1c)** separately provides that *"Article 19 applies to any commodity benchmark
based on contributed input data"* — unless it is a regulated-data benchmark, has a
majority of supervised contributors, or is a gold/silver/platinum critical benchmark. And
Article 2(2)(g) exempts a commodity benchmark only while the total average notional of
instruments referencing it stays below **EUR 200 million over 12 months**.

Whether prices scraped from public rate cards and public APIs constitute "contributed
input data" within the meaning of the Regulation is an open question on which the
administrator expresses no view. The disclaimer is therefore retained as a deliberate
choice rather than a legal necessity, and **legal advice will be obtained before any
contractual use.** Nothing in this document is legal advice.

### Settlement-grade preconditions (published and falsifiable)

EU-CRI is a **price-transparency benchmark, not a settlement benchmark**, and will not be
represented as one until *all* of the following hold. Progress is published on the
dashboard so the claim can be checked rather than trusted:

1. ≥15 independent constituents in the headline population, of which ≥5 executable.
2. ≥180 consecutive collection days at ≥95% coverage.
3. Realised index volatility demonstrably driven by price rather than composition.
4. Executable share ≥50% by weight.
5. An independent oversight committee (Baltic Index Council model). Governance by one
   person is not a defect that code can fix.
6. External methodology assurance review.
7. A legal opinion on the Article 2(1c) question above.

As of methodology v0.3.0 none of 1, 2, 4, 5, 6 or 7 is met.

## 1. Methodology change procedure (IOSCO P12)

The methodology is everything that can change a published print: `config/factors.yaml`,
`config/sovereign.yaml`, `src/eucri/index.py`, `src/eucri/normalise.py`,
`src/eucri/weights.py`. A sha256 over these files is recorded in `METHODOLOGY.lock`;
CI fails whenever the working tree no longer matches the lock, and the lock generator
refuses to record a changed hash under an unchanged released version. A methodology
change therefore requires, in one commit:

1. The change itself.
2. A `methodology_version` bump in `config/factors.yaml`
   (patch = editorial/no numeric effect; minor = parameter or constituent change;
   major = unit definition or aggregation change).
3. A CHANGELOG.md entry describing the change and its motivation.
4. `python -m eucri.run docs` to regenerate METHODOLOGY.md and the lock.
5. **One publication's notice**: the change is announced in a published post before the
   first print computed under the new version. Prints record the version they were
   computed under (`daily_index.methodology_version`), so the transition is auditable.

Versions with a `-dev` suffix (pre-launch construction) are exempt from the refusal
rule; the exemption ends at launch when the suffix is dropped.

**Scheduled weight reviews are not methodology changes.** Constituent weights and the
composite's class basket shares are recomputed on a fixed schedule by a fixed published
formula (METHODOLOGY.md §3.1–3.2) with no discretion; each review is stored append-only
in `weight_sets` and reproducible via `python -m eucri.run weights --date`. Changing the
formula, the schedule, or any of their parameters **is** a methodology change and
follows the procedure above.

## 2. Correction policy (IOSCO P13)

Published prints are never edited or deleted (database triggers forbid it). An erroneous
print is superseded by a **new revision** for the same date, flagged `correction`, no
later than the next publication, with the error described in the accompanying post.
Prior revisions remain queryable forever.

## 3. Audit trail (IOSCO P16)

Raw observations are append-only. Every print stores its full constituent set — every
candidate provider, its price, its weight, whether it was included, and the exclusion
reason if not. Any reader can request it; it is reproduced with:

    python -m eucri.run constituents --date YYYY-MM-DD [--series NAME]

## 4. Conflicts of interest (IOSCO P4–P5)

The author may trade on venues whose prices the index observes (see the companion
trading memo). Mitigations: the calculation path contains no expert judgement — every
parameter is a published config value and the code is public at launch; observations are
immutable; any position on an observed venue held by the author is disclosed in the
publication where relevant. The index is produced by one person; readers should weigh
that against the full transparency of inputs and code.

## 5. Data sufficiency and publication gate (IOSCO P6–P7)

A print requires at least the configured minimum of qualifying providers
(`aggregation.min_providers`). Below that, the value is null and flagged
`insufficient_sources` — a gap is published, a number is never fabricated.

## 6. Complaints

Complaints or challenges to any print: rusch.mh@gmail.com. Acknowledged within 7 days;
outcome (correction or rationale for no change) published with the next print.

## 7. Review

The methodology is reviewed annually (first review due July 2027) or upon a structural
market change (e.g. professional market makers entering the observed venues), whichever
comes first. Reviews are logged in CHANGELOG.md even when nothing changes.

## 8. Cessation

If the index can no longer be produced credibly (source loss, market structure change),
a final post will announce cessation with at least 30 days' notice; the repository,
data, and methodology history remain public.
