# EU-CRI Design System

**European Compute Reference Index — visual specification, v1.0**

| File | What it is |
|---|---|
| `tokens.css` | The system. Every colour, size, and duration, heavily commented. |
| `components.html` | Component gallery — every pattern, both themes, working toggle. |
| `homepage.html` | Full homepage mockup with realistic data. |
| `DESIGN.md` | This document. |

All three pages are self-contained: system font stacks, inline SVG, no images,
no `@import`, no `url()`, no external scripts. They render correctly under a
CSP that permits nothing off-origin.

---

## 1. Rationale

### What we are trying to look like

A benchmark **publisher** — an exchange or an index administrator — not a data
vendor's sales site and not a trading app. The distinction is concrete and
observable in the comparables: real markets (Nord Pool, EEX, ENTSO-E, Bloomberg)
run a narrow cool low-saturation base, increase density as you approach the
actual price, and spend colour almost exclusively on meaning. Vendors *selling
access* to markets (Argus, S&P) run ordinary enterprise B2B marketing — more
whitespace, stock photography, softer tone. EU-CRI must read as the former.

The single most useful data point in the research: Ornn's shipped stylesheet is
~95% cool greyscale — ten grey/black/white values — plus **exactly one saturated
hex, used once**. That is what "cool, not screamy" means in hex terms. It means
picking one accent and then almost never using it.

### Three decisions, and why

**1. Cool-slate neutrals with no hue cast.** The research recommended a
green-tinted neutral ramp to pair with the teal. Rejected: teal accent + lime
secondary + a green-cast base reads as an eco/sustainability brand, not a trading
venue. Every strong comparable gets its institutional signal from a *neutral*
base with the accent carrying all the hue. Tinting the base spends the hue budget
on chrome — the exact anti-pattern the research itself flags.

**2. Teal as the single accent, rationed to "live / current".** Every comparable
in the category defaults to blue — Ornn, Deribit, Linear's link colour, generic
fintech. Teal has a genuine Nord Pool / power-market lineage, is rarer, and — the
practical argument — blue is already spoken for as categorical slot 1 in charts,
so a blue brand accent would collide with chart identity. The hex here is an
original adaptation deepened for contrast, not a copy of anyone's brand colour.

**3. The basis ribbon as the signature device.** The research proposed a
decorative 50 Hz sine trace. Rejected: ornament pretending to be meaning, and it
will date. The brief asks for complexity, and complexity should come from
information density, not graphics. The ribbon instead is:

- **the literal product** — EU-CRI's differentiated object is the *basis*, not
  the level; two US venues already contest the level;
- **substantively** electricity-native — diverging zonal-spread visualisations
  (nodal price maps, EPAD spreads) are the actual visual signature of power
  trading, so the reference is earned rather than illustrated;
- **unique** — no compute index publishes a basis;
- **information**, so it survives a trading desk reading it closely.

### Type: three stacks, three jobs

| Stack | Job | Never |
|---|---|---|
| **Sans** (`system-ui` → Segoe UI / -apple-system) | All UI, all prose | — |
| **Mono** (`ui-monospace` → Cascadia / SF Mono / Consolas) | Every numeral a reader might compare: prices, deltas, weights, timestamps, hashes, versions, axis ticks, symbols | Body prose |
| **Serif** (`Iowan Old Style` → Palatino → Georgia) | Research and methodology **display type only** | A price, a chart, any UI |

The sans + mono + serif triad is Ornn's system reduced to system fonts. It is
what makes a data product feel *written* rather than merely rendered.

**A deliberate deviation from the house dataviz rules, stated openly.** Those
rules say a hero figure uses proportional figures in the UI sans, because
`tabular-nums` makes a number like `121` look loose at display sizes. The hero
price here is **mono and tabular** instead. Reasons: (a) the brief makes
fixed-decimal tabular numerals a hard constraint; (b) a live fix must never
reflow its own width on update, and a proportional hero would jitter every time
the last digit changed; (c) the rule's actual target is a *serif or display*
face reading as decoration — mono is neither, and is the documented institutional
convention for a price. Everything else in the rule holds: no serif on any figure.

---

## 2. Token usage rules

The component sheet contains no raw hex, no raw font sizes, and no second
box-shadow. If you find one, it is a bug.

### The three rules that make the system work

**1. The accent is rationed.** `--accent` means one thing: *this is the live /
current value*. Budget: **≈3 accent marks per viewport**, which in practice is
the rule on the print card, the live dot, and the chart's current-value marker.
It is not a default link colour, not a default button colour, not a section
header colour. If every chip and button is the brand colour, none of it signals
importance.

**2. The base carries no hue.** All hue comes from the accent, the status scale,
and the chart palettes.

**3. Colour is never the only channel.** Every status ships an icon **and** a
label. Every delta ships a `+`/`−` sign and a hairline arrow glyph. Every
diverging value carries direction and height as well as hue. Every chart ships a
table view.

### Which ink, where

| Token | Use for | Floor |
|---|---|---|
| `--ink-1` | Headings, prices, values, the number the row is about | — |
| `--ink-2` | Body prose, table cells | — |
| `--ink-3` | Labels, captions, units, timestamps, **axis tick text** | **The floor for text.** Nothing lighter is text. |
| `--ink-faint` | Disabled controls, decorative glyphs | Never text (2.80:1 light) |

Three text levels is the whole scale. A fourth means a hierarchy problem, not a
token problem.

### Status tokens come in threes

`--status-x` is the **mark** (dot, icon, chart fill — non-text).
`--status-x-ink` is the **text** (AA-safe on both the surface and the wash).
`--status-x-bg` is the **wash** (chip backgrounds only).

Using the mark hex as text is the most likely misuse: `--status-good` `#0ca30c`
is 3.35:1 on white and fails AA as text. `--status-good-ink` `#006300` is 7.54:1.

### Do / don't

| Don't | Do |
|---|---|
| `color: var(--status-critical)` on a price | `color: var(--delta-down)` — the text-safe step |
| A red or green **background wash** on a changed table cell | A signed number + arrow glyph in `--delta-*`, and a 180 ms **opacity** flash on that cell only |
| Emoji or dingbat triangles for deltas | Inline SVG hairline arrows, `currentColor` |
| Teal on links, buttons, headers, and chips | Teal on the live value; `--ink-1` links with a `--rule-heavy` underline |
| `--ink-faint` for a caption | `--ink-3` |
| Zebra-striped tables | Hairline row rules; stripes read as a spreadsheet export |
| A second `box-shadow` for card depth | Surface + hairline. The one shadow token is for floating layers |
| `border-radius: 12px` | `--radius-md` (6px) is the ceiling |
| A gradient on a CTA | A flat `--accent` fill |
| Hiding nav behind a hamburger on desktop | A broad flat top nav |
| A page with no visible `as of` stamp | Data vintage is non-optional chrome |

---

## 3. Chart rules

### The house rule: charts are greyscale by default

`--chart-line` (a slate) is the default single-series stroke. The categorical
palette comes out **only when two or more series genuinely need identity**. The
accent marks the current value and nothing else. This is the Economist/FT
rationing rule applied to a benchmark: the one number that matters is the one
that gets colour.

### Fixed mark specs

| Mark | Spec |
|---|---|
| Line | 2px, round join and cap |
| Bar / column | ≤ 24px thick, **4px rounded data-end, square at the baseline** |
| Marker / end-dot | ≥ 8px diameter, with a **2px surface ring** so it stays legible where it crosses a line |
| Gridlines / axes | 1px **solid** hairline, one step off the surface, recessive. Never dashed — dashing reads as "projection" |
| Gap between touching fills | **2px of surface colour**, never a stroke around the mark |

### Encoding

- **Categorical** = identity. Eight slots, fixed order, assigned in sequence,
  **never cycled**. Colour follows the entity, never its rank — filtering a
  series out must not repaint the survivors. There is no slot 9: a ninth series
  folds into "Other" or facets into small multiples.
- **Sequential** = magnitude. One hue, light → dark. Never a rainbow.
- **Diverging** = polarity. Two hues that read as opposite + a **neutral grey**
  midpoint. Blue↔orange here; blue↔aqua would fail because both are cool and the
  midpoint would not read as "nothing".
- **Ordinal** = position in a sequence. One hue, monotone lightness steps. Tier
  badges (L1/L2/L3) are ordinal and are encoded by ink weight and wash lightness,
  not by three unrelated hues.
- **Status** = state. Reserved. Never "series 5", and a series colour is never
  used for status.
- **Never a value-ramp on nominal categories** — colouring each bar
  darker-where-bigger double-encodes what bar length already shows.

### Hard prohibitions

- **No dual-axis charts.** Two y-scales on one plot invent a correlation that is
  not in the data. Two measures of different scale → two charts, small multiples,
  or index both to a common base on one axis.
- **No area fill under a truncated baseline.** The 30-day chart's y-axis starts
  at $3.00, so it is a *line*. An area implies magnitude measured from zero;
  filling under a truncated axis overstates the level. (This is why the headline
  chart has no wash.)
- **No number on every data point.** Direct-label selectively — the endpoint, the
  extreme, the one series that is the story. The chart here labels exactly two
  things: the 30-day low and the current value.
- **A legend is always present for ≥ 2 series; a single series gets none** — the
  title already says what is plotted, and a one-swatch box just restates it.
- **Text never wears the data colour.** Values, labels, and legends use ink
  tokens; a coloured mark sits *beside* them. The one exception is a label set
  inside a filled shape, where ink is chosen by the fill's luminance.

### Interaction

Every chart ships a hover layer and a table-view twin.

- **Line charts: crosshair finds the X.** A vertical hairline snaps to the
  nearest data position, so readers aim at a date, not at a 2px line. Hit bands
  are the full plot height and one band wide (≈28px).
- **Bars and cells: the mark is the hit target**, no crosshair, and the hovered
  mark lifts (here, the others recede to 45%).
- **Values lead, labels follow** in the tooltip — the reader already has the
  series and wants the number.
- **Line keys, not boxes**, in tooltip rows.
- **Tooltips enhance, never gate.** Every value is also in the table view.

Both hover layers here are **CSS-only** and work with scripting disabled. Hit
targets are `tabindex="0"` with `aria-label`, so keyboard focus shows the same
readout as hover.

> **Known limitation to fix in production:** 30 focusable points per chart is 30
> tab stops. Production should implement a roving tabindex — one tab stop for the
> chart, arrow keys between points — which needs JS. The table view is the
> keyboard path in the interim.

### Filters

One row, above everything they scope. Never inside a chart card, never per-chart.
Date range first, presets before a custom range. On refetch, hold the previous
render at reduced opacity — no skeleton, no layout jump.

---

## 4. Density rules

Density is what separates a benchmark from a dashboard. It is also the thing most
easily overdone, so it is rationed by content type.

| Content type | Row height | Type size | Rhythm |
|---|---|---|---|
| Ticker strip | `--strip-h` 34px | `--text-2xs`/`--text-sm` | 4px |
| Constituents grid | `--row-h-dense` 28px | `--text-xs`, heads `--text-3xs` caps | 4px |
| Standard table | `--row-h` 36px | `--text-xs` | 8px |
| Ledger rows | auto | `--text-sm` / `--text-xs` | 8px |
| Prose | auto | `--text-base`, `--leading-prose` | 8px, max `--measure-prose` 68ch |

**The nesting rule:** the outer rhythm is 8px; inside a dense grid or the ticker
it halves to 4px. That nesting is what produces terminal density without the page
itself feeling cramped.

**Numerals.** All of them: `tabular-nums`, `lining-nums`, fixed decimal places,
right-aligned in columns, mono. A currency or unit suffix is a smaller, muted
sibling — hierarchy comes from size and desaturation, never from decoration.
Fixed decimal width means a live cell never reflows on update.

**Wide content scrolls itself.** Tables and charts live inside
`overflow-x: auto` containers; the page body never scrolls horizontally. This
requires `min-inline-size: 0` on every grid/flex item that can contain one —
grid items default to `min-width: auto`, which is *min-content*, so a card
holding a 660px-min chart will otherwise refuse to shrink and push the whole page
sideways on a phone. Verified: `documentElement.scrollWidth === clientWidth` on
both pages at 485px and 1409px.

**Editorial breaks out.** Prose is capped at 68ch; charts and tables break to
full width. Two layout systems sharing one colour system — which is how FT and
Bloomberg actually operate.

---

## 5. Accessibility

### Verified contrast ratios

Computed with the dataviz validator's WCAG `contrast()` function against the
system's own surfaces, not the reference defaults. **Every text token clears AA
4.5:1 on every surface it is permitted on, in both themes.** The lowest text
ratio anywhere in the system is 4.89:1.

**Light theme** — surfaces: card `#ffffff`, page `#f3f3f3`, inset `#f7f8f9`,
strip `#eceef1`

| Token | Card | Page | Inset | Strip |
|---|---|---|---|---|
| `--ink-1` `#111214` | 18.74 | 16.89 | 17.63 | 16.12 |
| `--ink-2` `#454b54` | 8.80 | 7.93 | 8.27 | 7.57 |
| `--ink-3` `#5f6570` | 5.86 | 5.28 | 5.51 | 5.04 |
| `--accent-ink` `#00655c` | 6.96 | 6.27 | 6.55 | 5.99 |
| `--delta-up` `#006300` | 7.54 | 6.80 | 7.09 | 6.49 |
| `--delta-down` `#a32222` | 7.48 | 6.74 | 7.03 | 6.43 |
| `--ink-faint` `#949ba5` (non-text) | 2.80 | 2.53 | 2.64 | 2.41 |

**Dark theme** — surfaces: card `#17191c`, page `#101113`, inset `#1c1f24`,
chrome `#0b0c0e`

| Token | Card | Page | Inset | Chrome |
|---|---|---|---|---|
| `--ink-1` `#f5f6f7` | 16.28 | 17.46 | 15.27 | 18.08 |
| `--ink-2` `#c3c8d0` | 10.48 | 11.24 | 9.83 | 11.64 |
| `--ink-3` `#a2a9b3` | 7.43 | 7.97 | 6.97 | 8.26 |
| `--accent-ink` `#2fd6c3` | 9.67 | 10.37 | 9.07 | 10.74 |
| `--delta-up` `#0ca30c` | 5.25 | 5.63 | 4.93 | 5.83 |
| `--delta-down` `#ef7a7a` | 6.49 | 6.96 | 6.09 | 7.21 |

**Chip ink on its own wash** (light / dark): good 6.52 / 4.89 · warning 6.12 /
8.67 · serious 5.96 / 6.34 · critical 6.25 / 6.31 · neutral 7.57 / 9.04 ·
tier-L1 5.91 / 8.27.

**UI and marks, 3:1 target** (light / dark): accent mark 5.38 / 9.67 · text on
accent fill 5.38 / 9.89 · chart line 8.80 / 10.48 · chart de-emphasis 3.14 / 4.54
· axis tick text 5.86 / 7.43.

### Palette validation — run, not eyeballed

`scripts/validate_palette.js`, against this system's surfaces:

```
light, surface #FFFFFF     dark, surface #17191C
[PASS] Lightness band      [PASS] Lightness band
[PASS] Chroma floor        [PASS] Chroma floor
[PASS] CVD separation      [PASS] CVD separation
       worst adjacent             worst adjacent
       #eda100↔#1baf7a            #c98500↔#199e70
       ΔE 9.1 (protan)            ΔE 8.4 (protan)
[PASS] Normal-vision 19.6  [PASS] Normal-vision 19.3
[WARN] Contrast vs surface [PASS] Contrast vs surface
       3 slots below 3:1          all 8 ≥ 3:1
```

ΔE is Euclidean distance in OKLab ×100, under protanopia and deuteranopia
simulated with Machado–Oliveira–Fernandes 2009 at severity 1.0.

**The light-mode contrast WARN is not dismissable.** Slots 3 (`#1baf7a`, 2.82:1),
4 (`#eda100`, 2.17:1) and 5 (`#e87ba4`, 2.69:1) sit below 3:1 on white. Wherever
they appear, ship visible direct labels or the table view. Dark mode does not
have this problem, but ship the labels there too so both themes read identically.

**Diverging arms** pass the ordinal check in all four combinations (monotone
lightness, adjacent ΔL ≥ 0.06, near-surface end ≥ 2:1, single hue): light cool
end 2.11:1, light warm end 2.19:1, dark cool end 2.17:1, dark warm end 2.07:1.

### Other guarantees

- **Never colour alone.** Status = icon + label. Delta = sign + arrow + colour.
  Diverging = direction + height + hue + legend + table.
- **Every chart has a table-view twin** in a `<details>`, which is both the
  WCAG-clean equivalent and the relief channel for sub-3:1 marks.
- **Focus is never removed**, only restyled: 2px accent outline, 2px offset.
- **`prefers-reduced-motion`** collapses all animation to 1 ms. The only ambient
  motion in the product is the live-dot pulse.
- **`forced-colors`** drops the shadow and lets the OS palette through. Texture
  (a 45°/135° hatch) is the identity backup channel there — opt-in, never
  decorative, never on by default.
- **Semantics**: one `<h1>` per page, `<th scope>` on every table header,
  `aria-current="page"` on nav, `<fieldset>`/`<legend>` on segmented controls,
  visually-hidden `<caption>` on data tables, `aria-label` summaries on charts.
- **No emoji anywhere.** All glyphs are inline SVG with `currentColor`.

---

## 6. Theming contract

```css
:root { /* the COMPLETE light palette + every untheme-able token */ }

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { /* ONLY the tokens that change */ }
}

:root[data-theme="dark"] { /* identical body, declared AFTER the media block */ }
```

Why this exact shape:

- The `:not([data-theme="light"])` guard means an explicit **light** stamp beats
  an OS set to dark, without needing a fourth block.
- `:root[data-theme="dark"]` is declared **after** the media block; both have
  specificity (0,2,0), so source order makes the explicit **dark** stamp beat an
  OS set to light.
- Type, space, radii, motion, and layout are declared once and never themed.
- `body` has an **explicit token background**. A transparent body borrows the
  host's theme and the palette comes apart.
- `color-scheme` is set in each block so form controls and scrollbars follow.

The two dark blocks are byte-identical in body. **Keep them in lockstep** — that
duplication is the cost of the contract, and it is cheaper than the alternative.

Dark is **selected, not flipped.** The eight categorical hues are re-stepped for
the dark surface; the diverging arms invert their anchor so the step nearest zero
is the *darkest* and "nearly flat" still recedes; the accent converges to one
step because it clears both the 3:1 mark floor and the 4.5:1 text floor.

The toggle is a small inline script (not an external request) that stamps
`data-theme` on `<html>`. If a deploying CSP forbids inline script, the page
still themes correctly from the OS preference — it only loses the manual
override.

---

## 7. How to extend

**Adding a colour.** Don't, if a semantic token already exists. If you must, mint
it from an existing ramp step in `tokens.css` §1, give it a semantic name in
§2–§7, and add its measured contrast to the table in §5 of this document. Never
put a raw hex in a component.

**Adding a chart type.** Work the order: pick the form first (is it even a
chart?), assign colour by the job it does, **run the validator**, apply the mark
specs, add the hover layer, then the accessibility pass, then render it and look
at it. Use the FT Visual Vocabulary's job taxonomy — deviation, correlation,
ranking, distribution, change-over-time, part-to-whole, magnitude, spatial — to
pick the form.

**Adding a series to an existing chart.** Take the next categorical slot. Do not
reorder existing slots — colour follows the entity, and a reader who learned
"runpod is blue" is misled by a repaint. Past eight, fold the tail into "Other"
or facet. In scatter, bubble, choropleth, or small multiples the all-pairs test
applies and the cap is **three** slots, not eight.

**Adding a page type.** There are two layout registers, and mixing them is the
mistake: the **grid register** (dense, terminal, mono numerals) for price
surfaces, and the **editorial register** (68ch measure, serif display, ledger
rows, marginalia footnotes) for methodology and research. They share the colour
system and the type stacks; they do not share the layout system.

**Changing the accent.** Check the new hue against (a) 4.5:1 as text on both the
card and page planes, (b) 3:1 as a mark, (c) ΔE ≥ 15 from categorical slot 1 and
from status-good, since it appears near both. Then re-run the categorical
validator, because the accent must not read as a ninth series.

**Before shipping any chart**, check it against the anti-pattern list: dual axis,
recolour-on-filter, cycled hues, eyeballed CVD safety, a value ramp on nominal
categories, a rainbow sequential, a hue at the diverging midpoint, status colour
as a series, a number on every point, dashed gridlines, borders around marks to
separate them, a clipped in-mark label, a fixed container height that excludes
the axis band, a serif hero figure, per-chart filters, a skeleton flash on
refetch, or a tooltip as the only route to a value.
