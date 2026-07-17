# EU-CRI Governance

Administrator and author: **Mark Rusch** (rusch.mh@gmail.com), Amsterdam.
This document implements the IOSCO Principles for Financial Benchmarks (2013) as
voluntary best practice. EU-CRI is a research publication outside the scope of EU
Regulation 2016/1011 (it is not licensed for use in financial instruments and any
request to hard-wire it into a financial contract will be refused).

## 1. Methodology change procedure (IOSCO P12)

The methodology is everything that can change a published print: `config/factors.yaml`,
`config/sovereign.yaml`, `src/eucri/index.py`, `src/eucri/normalise.py`. A sha256 over
these files is recorded in `METHODOLOGY.lock`; CI fails whenever the working tree no
longer matches the lock, and the lock generator refuses to record a changed hash under
an unchanged released version. A methodology change therefore requires, in one commit:

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
