# The Compute Index — house style

`The Compute Index` (computeindex.substack.com) is the newsletter. `EU-CRI` is the index
it publishes. Keep that distinction in your own head even if readers never notice it:
the newsletter can have opinions, a voice, and bad days; the index can't. This document
is about the newsletter's voice. It exists because the single fastest way to lose the
credibility the methodology is built to earn is to sound like everyone's LLM-generated
finance blog. Read this before every post, not just the first one.

## The one-sentence version

Write like you're explaining today's print to Arjan across the desk, not like you're
narrating it for an audience. Everything below is just that instinct, itemised.

## What "sounds like AI" actually means, specifically

Not "good grammar" — bad grammar isn't the fix. It's these concrete patterns, all of
which are easy to write by accident and easy to cut once you're looking for them:

- **The rule-of-three reflex.** "Faster, cheaper, and more reliable." Three examples,
  three reasons, three takeaways — every single time, symmetrical, no item longer or
  shorter than the others. Real thinking is lumpy: sometimes there's one reason, or five,
  or two and the second one gets three sentences and the first gets one.
- **"It's not just X, it's Y."** And its cousins: "This isn't about X — it's about Y."
  Ban this construction outright. If the second half is true, just say it.
- **Throat-clearing openers.** "In today's rapidly evolving compute landscape..." /
  "As AI continues to reshape..." Start with the number, the observation, or the thing
  that happened. Cut the first paragraph of every draft and check whether anyone
  notices it's gone. Usually they won't.
- **The neat bow.** Every section resolving into a tidy, reassuring conclusion. Real
  updates sometimes end on an open question, an unresolved number, or "I don't know yet
  — next print will tell us more."
- **Hedging as a reflex, not a judgment.** "This could potentially suggest..." stacked
  on "may indicate..." stacked on "it's possible that..." Say what you think. Flag
  *specific* uncertainty ("n=6 is thin, this could move on one provider dropping out")
  rather than *generic* uncertainty ("of course, markets can be unpredictable").
  Confident and calibrated beats vague and hedged.
- **Em-dash overuse as a substitute for a real sentence break.** One or two a post is
  fine. Five in a paragraph reads like a template.
- **Perfectly even paragraph lengths.** If every paragraph in a post is 3–4 sentences,
  it was probably built that way rather than written that way. Let some be one line.
- **False balance on things you actually have a view on.** "Some argue compute will
  never commoditise, while others believe it will" is a cop-out when you've spent a
  methodology doc explaining exactly where you land. State your read; note the strongest
  counterargument once, specifically, then move on.
- **Banned stock phrases** (non-exhaustive, add to this list when you catch a new one):
  "it's worth noting that," "at the end of the day," "let's dive in," "needless to say,"
  "in conclusion," "the landscape of...," "unlock/leverage/harness" as verbs, "game-
  changer," "paradigm shift," "in today's world."

## What to do instead

- **Lead with the specific.** A number, a price, a thing you actually did this week
  ("I pulled today's print Saturday morning and one provider had vanished"). The
  context and the "why this matters" comes after, not before.
- **Vary sentence length on purpose.** Follow a long, clause-heavy sentence with a
  three-word one. That's not a trick, it's just how people who care about a sentence
  actually write it.
- **Use "I," not "we."** This is one person's project, running on one person's laptop
  and one person's GitHub Action. Pretending otherwise is itself a tell.
- **Show the work, including the mess.** A methodology bug you found and fixed, a
  provider whose page changed format and broke a collector, a print you almost got
  wrong — these are the most human material available and they cost nothing to include
  honestly, because they're true. See "Behind the print," below.
- **Commit to a specific number over a vague qualifier.** Not "prices vary quite a bit
  across providers" — "seeweb prints $2.16, AWS prints $7.36, same hour, same continent."
- **Let a post end without resolving everything.** If the honest ending is "I don't know
  whether this is noise or a pattern yet," write that. It reads as more credible, not
  less, precisely because it's the opposite of an AI system's compulsion to close every
  loop.
- **One recurring structural device: "Behind the print."** Most posts should include a
  short section — three to six sentences, no heading required if it flows, or a small
  `###` if it doesn't — describing something concrete about that week's actual data run:
  what changed in the constituent set, what a collector logged, what the weight review
  did, what you're keeping an eye on. This is the section a generic AI finance blog
  cannot write, because it requires an actual pipeline actually running. Use it every
  time there's something real to say (there almost always is).

## Structure and formatting

- **Title:** plain and specific. A number, a claim, or a named thing — not a question,
  not a listicle, not "5 things you need to know about...". Examples that fit this
  newsletter: "A 3.4x spread, for the same GPU-hour" (good), "Is Europe's Compute Market
  Ready to Explode?" (not this).
- **Dek (subtitle):** one sentence, states the finding, doesn't tease it.
- **Length:** 500–900 words for a regular post. A "print note" (something broke, a
  number moved oddly, a quick methodology point) can be 150–300 words — post it as a
  short one rather than padding it to match the usual length.
- **Prose over bullets.** Reach for a bulleted list only for genuinely enumerable things
  (a list of data sources, a checklist). Analysis and argument go in paragraphs. A post
  that's 60% bullet points reads like a slide deck, not a newsletter.
- **Numbers:** two decimals with the unit every time ($3.25/GPU-hr, not "around $3");
  say what changed in absolute and relative terms when both are informative ("+8.7%,
  $2.99 to $3.25").
- **Links:** inline, in the sentence they support, not dumped in a list at the bottom
  except the one standing exception below.
- **One blockquote maximum per post** (if any) — for an actual quoted source, not for
  emphasis.
- **Sign-off:** "— Mark" (or "— MR, Amsterdam" for a slightly more formal post). Not
  "The Compute Index Team" — there is no team.
- **Standing footer**, verbatim, every post, no exceptions: the EU-CRI disclaimer
  ("research publication... not investment advice... not administered as a benchmark
  under EU Regulation 2016/1011...") plus one line on corrections policy. This is the one
  piece of boilerplate allowed to look like boilerplate, because it's a legal/governance
  statement, not a piece of writing.

## Cadence

One full post every 2–3 weeks. A short print note whenever something breaks, changes, or
moves enough to be worth a paragraph — these can run weekly and keep the publication
feeling alive between the longer pieces without straining for content.

## Before you hit publish

Read it out loud once. Any sentence you wouldn't actually say to a colleague at your
desk, cut or rewrite. Any paragraph that could run unchanged in a different newsletter
about a different topic, cut. Any claim hedged more than once, pick a side or cut the
claim. Check that the post contains at least one number, date, or detail that only
exists because you actually ran the pipeline this week.
