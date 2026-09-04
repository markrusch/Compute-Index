# EU-CRI Index Data — Terms of Use

**Version 0.1 (draft, pre-launch) · 4 September 2026 · Mark Rusch, administrator**

> **Status.** These terms are published so that the data is usable *now* rather than
> sitting under default "all rights reserved". The non-commercial grant in §2 is
> deliberate and you may rely on it. The commercial position in §3 is **not yet settled**
> — see §5 — and will be completed before launch. Nothing here is legal advice.

---

## 1. What these terms cover

| Covered by these terms | Covered elsewhere |
|---|---|
| `site/data/index_history.csv` | Software — [Apache 2.0](LICENSE) |
| `site/data/latest.json`, including the constituent audit set | Documentation and methodology — [CC BY 4.0](LICENSE-docs) |
| `data/eucri.db` (observations, prints, constituents, weight sets) | The name "EU-CRI" — [NOTICE](NOTICE) |
| Index values reproduced on the project website | |

A licence over source code does not carry rights in the data that code produces, which is
why the index data is stated separately rather than folded into the Apache licence.

**Legal basis.** Individual prices are facts and not copyrightable. What is protected is
the *database*: the substantial investment in obtaining, verifying and presenting these
observations, under the EU sui generis database right (Directive 96/9/EC), the
administrator being established in the EU.

## 2. What you may do — free, no permission needed

For **research, teaching, journalism, and other non-commercial purposes**, you may access,
copy, analyse, redistribute and publish extracts of the index data, including in academic
papers, articles, theses, blog posts, talks and open-source software, provided you
attribute it as in §6.

This expressly includes:

- reproducing published values to **check or falsify them** — the whole point of an index
  whose methodology and code are public;
- publishing a **critique** that quotes the data at length;
- redistributing the CSV or JSON as part of a reproducibility package for a paper;
- building non-commercial tools that consume `latest.json`.

Verification is never restricted. If you believe a print is wrong, you may publish
everything needed to demonstrate it, commercially or not.

## 3. What requires permission

**Commercial use** — including redistribution as part of a paid product or data feed, use
in a commercial terminal or dashboard, resale, or use in or in connection with a financial
instrument or contract.

Contact **rusch.mh@gmail.com**. Commercial terms are being finalised (§5); enquiries are
welcome now, and reasonable requests are unlikely to be refused.

Separately, and regardless of these terms: EU-CRI **must not be used as a reference price
in a financial instrument or contract**. That is a governance restriction, not a
commercial one, and it is not for sale. See [GOVERNANCE.md](GOVERNANCE.md).

## 4. Limits on what is granted

**These terms grant nothing in respect of upstream sources' own data.** Index values are
derived from public price surfaces operated by third parties; [SOURCES.md](SOURCES.md)
records, per source, the endpoint and the robots/ToS basis relied on. Two sources are
themselves redistributors (ECB reference rates via frankfurter.dev; hyperscaler catalog
prices via the `gpuhunt` package). Your use of the derived index data does not give you
any right in those sources' data, and their terms continue to apply to them.

**No warranty.** The data is provided "as is". Values are derived from third-party
surfaces believed reliable but are **not independently verified**; observed prices may
differ materially from prices actually obtainable. Past values do not indicate future
values. No liability is accepted for any loss arising from use of the data.

**Corrections and gaps.** Prints are append-only and corrected by new revisions, never
edited. A session below the provider gate is published as a gap and is never back-filled
or carried forward. If you cache the data, honour revisions; do not present a stale value
as current.

## 5. Why §3 is not yet complete

Before commercial terms can be offered honestly, one question has to be answered: how far
the upstream sources' terms permit commercial redistribution of *derived* output. The
headline value is a weighted median — a new work produced by an original, published
method, and comfortably the administrator's own. The **constituent audit set** published
in `latest.json` sits closer to the sources themselves, and it cannot simply be withheld,
because publishing every candidate the index saw (including the rejected ones and why) is
an audit-trail obligation under IOSCO P16.

That review is under way and will be resolved before launch, if necessary by publishing
the audit set under narrower terms than the headline values. It is recorded here rather
than quietly deferred, because a benchmark that is careful about its numbers should be
equally careful about what it claims to own.

## 6. Attribution

> Source: EU-CRI (European Compute Reference Index), Mark Rusch.
> https://markrusch.github.io/Compute-Index/

When citing a specific value, cite the **print date, methodology version and lock hash**
so the claim is checkable — for example *"EU-CRI-H100, 2026-08-30: $3.25/GPU-hr
(EU-CRI-M v0.3.0-dev, lock sha256:64d7f6cd88fc…)"*. Machine-readable equivalents are in
`latest.json`. See `CITATION.cff` for a formal citation.

## 7. Changes

These terms may change before launch; §2 will not be narrowed retrospectively for data
already published under it. Material changes will be recorded in
[CHANGELOG.md](CHANGELOG.md).
