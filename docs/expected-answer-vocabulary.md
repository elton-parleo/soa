# The expected-answer vocabulary

What a study question may claim the right answer *is*, and how a claim is
written down.

**This document wins.** Where the implementation disagrees with what is
written here, the implementation is wrong. The executable form of this
document is `soa_shared/expected_answers.py` and its test suite
(`apps/pipeline/tests/test_expected_answers.py`); between the three there
is no fourth source of truth.

---

## Why a vocabulary at all

`soa_queries.expected_answer` holds what a correct answer to that
question must contain. It is JSON, and JSON will hold anything, so the
first decision is what it is *not* allowed to hold: free text.

A free-text expectation ("about twenty-three dollars", "the SNUG3 code")
can only be scored by asking a model whether an answer matches it, which
means the scorer is a second opinion rather than a comparison. Two
models disagreeing about whether `$22.99` matches "about twenty-three
dollars" is not a measurement — and worse, it fails in the direction that
flatters us, because a generous judge scores a wrong answer as right.

So every expectation is one of seven typed shapes. Each shape names
exactly which fields carry meaning, and each has a **deterministic**
comparison rule written beside it. The only model in the scoring loop
transcribes what an answer said (see *Extraction* below); it never
decides whether that was correct.

## The shape

```json
{ "type": "<one of the seven>", ... type-specific fields ... }
```

`type` is required and is one of:

| `type`          | Means                                                     |
| --------------- | --------------------------------------------------------- |
| `price`         | The variant's published list price                        |
| `gtin`          | The variant's GTIN                                        |
| `pack_count`    | How many units are in the pack                            |
| `code`          | A promotion code and what it is worth                     |
| `member_price`  | What a named loyalty tier pays                            |
| `points`        | The points-earning rule                                   |
| `brand_mention` | The brand is named, and (separately) its domain is cited   |

Unknown `type` values are rejected at write time, not tolerated and
ignored. A question carrying an expectation nothing can score is worse
than a question carrying none: the first is counted in an accuracy
denominator it can never contribute to.

### Money is a string, never a float

Every amount is the decimal string the published record spells —
`"22.99"`, not `22.99`. Canonical records serialise `Decimal` to a
string, the comparison is string-exact after normalisation to two
decimal places, and a round trip through binary floating point is a
silent way to make two identical published prices differ. The supply
side made the same call for the same reason; see the
`GET /merchants/{slug}/catalog` docstring in the supply app.

`currency` is an ISO-4217 code, uppercase, and is compared. `$22.99` and
`CA$22.99` are not the same answer.

---

## The seven types

### `price`

```json
{ "type": "price", "amount": "22.99", "currency": "USD" }
```

The list price of one variant, as published.

**Compared:** exact to the cent, *for the attributed product*. An answer
that states `$22.99` while attributing it to a different product has not
answered the question — it has stated a number that happens to match. See
*Attribution* below.

### `gtin`

```json
{ "type": "gtin", "value": "884400137609" }
```

**Compared:** exact string, after stripping spaces and hyphens. A GTIN is
an identifier; a near-miss is a different product.

GTIN is never the primary expectation of a question. It rides along on a
price question as a secondary expectation and is scored as a bonus
signal — see *Secondary expectations*. A GTIN never appears in a question,
so a stated one is always volunteered.

### `pack_count`

```json
{ "type": "pack_count", "value": 84 }
```

An integer count of units. Only set where the record states a count.

**Compared:** exact integer.

**Secondary only, for now.** No question asks for a pack count. It rides
on the variant's price question as a secondary expectation, the same way
`gtin` does, and is scored where the answer states it.

It was briefly a question of its own — "How many come in the {brand}
{product} {variant}?" — and stopped being one for a reason worth writing
down, because it is the kind of reason that gets forgotten and reverted.
Two questions per variant put Wiggle & Snug's default study at 103
against the study's own 100-question cap: the feature's own defaults
opened on a red tally. One question per variant puts it at 87.

### The count stays out of the question wherever it can

A question that names a variant *by* its count and then scores whether
the answer knows the count is scoring an echo. So the price question
names the variant by whatever actually tells it apart, and states the
count **only when nothing else does**:

* `Size 3 small pack` — unambiguous against `Size 3 big pack`, so no
  count.
* `Size 3` for the overnight range — four sizes, no two alike, so no
  count.
* `Standard (100 ct)` for a product whose variants share a size and
  differ only in how many are in the box. Here the count *is* the handle
  and has to be said.

On Wiggle & Snug the count is never needed: all **18** pack-count
secondaries are volunteered, none restated.

Where the count does appear in the wording, that variant is recorded
under `pack_count_restated` on `tier_config` (against
`pack_count_volunteered` for the rest), so nobody reads its "right" as
knowledge. The honest measurement for those is a standalone probe that
asks without stating — a **future checkbox, not built**.

### The attribution guard follows the wording

The phrases the wrong-product-attribution guard checks are *exactly* the
phrases the question used to name the variant — one function behind both,
so a guard can never test a phrase the question never said.

This is why the count leaves the guard wherever it leaves the wording,
and it is load-bearing rather than tidy. Where the question does not
state the count, an answer's count is a **claim being scored**, not an
identifier we handed over. Leave it among the rival phrases and an answer
that names the right variant while volunteering the *wrong* count —
"Size 3 small pack, 92 ct", where 92 is Size 2's — reads as a claim about
a sibling, voids its own attribution, and takes the price measurement
down with it. The thing being measured must not be able to erase the
measurement. That wrong count is still scored; it is scored as a
`pack_count` secondary, beside the price rather than instead of it.

### `code`

```json
{ "type": "code", "code": "SNUG3", "value_kind": "amount_off", "value": "3.00" }
```

A promotion code the shopper types, and what it is worth.

`value_kind` is one of `amount_off`, `percent_off`, `member_price`.
`value` is the decimal string for that kind — dollars for `amount_off`
and `member_price`, percent for `percent_off` (`"10.0"`, not `"0.10"`).

**Compared:** the code string exact and case-insensitive (codes are typed
by humans and every checkout upper-cases them), *and* the value exact for
its kind. A right code with a wrong discount is `wrong`, not partially
right — an answer that sends a shopper to checkout expecting the wrong
saving has failed in the way that costs the merchant.

### `member_price`

```json
{ "type": "member_price", "amount": "16.84", "currency": "USD", "tier_name": "Member+" }
```

What a member of one named tier pays for one variant.

**Compared:** amount exact to the cent **and** `tier_name` exact
(case-insensitive). A correct price attributed to the wrong tier is
`wrong`: a shopper told that the entry tier gets the top tier's price has
been misinformed about the thing the tier exists to signal.

### `points`

```json
{ "type": "points", "rule": { "kind": "per_dollar", "rate": "1.0", "program_name": "Member Rewards" } }
```

or

```json
{ "type": "points", "rule": { "kind": "fixed", "points": 16, "program_name": "Member Rewards" } }
```

The points-earning rule as published. `kind` is `per_dollar` (the record
carried a multiplier) or `fixed` (the record carried a computed total for
this variant).

**Compared:** `kind` must match, then `rate` exact as a decimal string
(`per_dollar`) or `points` exact as an integer (`fixed`). `program_name`
is carried for display and is **not** compared — programs are renamed and
paraphrased in answers far more freely than tiers are, and failing an
otherwise correct rate over "Member Rewards" versus "the rewards
programme" would measure paraphrase, not accuracy.

### `brand_mention`

```json
{ "type": "brand_mention", "brand": "Wiggle & Snug", "domain": "trueshopstore.com" }
```

The weakest expectation, and the only one with no number in it: the
answer names the brand.

**Compared:** presence of the brand, case-insensitive, on the extracted
`brand_mentioned` flag. Whether the brand's own domain was cited is kept
as a **separate bit** on the outcome row (`domain_cited`) and is *not*
part of the exact/wrong decision. The two are different questions — "did
the assistant know the brand" and "did it send the shopper to the brand's
own store rather than a retailer" — and folding the second into the first
loses the source-attribution measure the report reports.

#### The question has to name the brand

A `brand_mention` expectation is the only one a question can make
**unmeetable by its own wording**. Every other type asks for a published
value and an answer either states it or does not. This one asks whether
the brand came up — and if the question never said the brand, a correct,
helpful, complete answer has no reason to say it either. The row then
scores `absent` against an assistant that did nothing wrong, and the
tier's visibility rate measures the questions rather than the assistant.

This is not hypothetical. The first brand-mode study generated twelve
brand-direct questions and not one of them named the brand: the tier
reached the generator through the prompt's *unbranded* mode, which tells
the model not to name a brand at any stage, and the model complied. All
twelve were unscoreable from the moment they were written.

So the rule, enforced in `generation/brand_direct_guard.py` and not only
requested in the prompt:

> Every `brand_direct` question must contain the brand name. A question
> that does not is rejected and regenerated; if the retries run out, the
> tier reports a **shortfall**. It never pads its count with a question
> it cannot score.

Matching tolerates typography and nothing else — `Wiggle & Snug`,
`wiggle and snug` and `WIGGLE & SNUG` are the same brand typed three
ways; `Wiggle` on its own is not the brand.

#### Naming the brand is not a result

A `brand_mention` expectation was scored on presence: `exact` if the
answer named the brand, `absent` if not. Cycle
20260915-113207-wiggle-snug-full is what that produces — 63 of 66 runs
`exact`, on a brand that two of those answers had actually read:

| What the answer said | Old outcome |
| --- | --- |
| "not a real or widely recognized brand of diapers" | `exact` |
| "a private label brand sold exclusively at Kohl's", tiers "Snuggle Friend, Pal, Bestie" | `exact` |
| "the closest match I found is Beezpro's Snug Fit Padded underwear" | `exact` |
| cited trueshopstore.com/loyalty, named Member and Member+ | `exact` |

So brand-direct questions are no longer scored on the value axis at all.
They are classified on their own, by what the answer did with the brand —
`grounded`, `echoed`, `misattributed`, `fabricated`,
`acknowledged_unknown`, plus `absent` and `unscoreable`, which mean here
what they mean everywhere. The rules and their precedence live in
`scoring/brand_direct_classifier.py`; the classifier reads only
transcribed fields and the published record, and asks no model whether an
answer was good.

Two consequences worth stating:

**Visibility is retired for this tier**, not renamed. It was the pass-1
mention rate over these runs — "was the brand named" — which is precisely
what `echoed` counts. Two numbers for one fact, one of them called
visibility, is how 63 of 66 came to look like a score.

**`misattributed` outranks `acknowledged_unknown`** when both apply, and
both usually do. An answer that says "I cannot verify Wiggle & Snug, but
here is Huggies Snug & Dry" leaves the reader holding Huggies. The
admission is a mitigation, not the result.

#### What the extractor transcribes, and what it does not

Forty stored answers from cycle 20260915 were read by hand against their
extractions. Ten disagreed, and the corrections are these:

| Rule | Why |
| --- | --- |
| A **size** is not a pack count. `4 oz`, `3.4 fl oz`, `100 ml` go in `sizes` with their unit. | Four of the ten. A size read as a count is a wrong number attached to a real product — worse than a missing one, because it scores an assistant against a quantity nobody asked about. |
| A **recommendation** is not a citation. "Check Amazon, Walmart or Target" goes in `recommended_retailers`; `sources_cited` stays empty. | A citation says where the answer got something. A recommendation says where to go. An answer that names three shops and links to none has cited nothing. |
| A **hedge** is not a claim. "It's possible", "likely", "might be" never reach `brand_claims`. | A possibility is not an assertion, and one row was classified `fabricated` on three hedged sentences alone. |
| `brand_unknown_statement` means **can't-find**, not a freshness disclaimer. | "I don't have real-time access to the latest ingredient list" says your knowledge has a date on it. The same answer went on to describe the brand as real. |
| A bare **`$` is USD**, every time, including inside a range. | The extractor read it as USD in some rows and null in others. |
| `presented_as` is one of **four words** — `closest_match`, `comparison`, `recommendation`, `source`. | It was free text and came back holding sentence fragments. |

**`brand_mentioned` is no longer asked of the model.** It is
`ea.names_brand(answer, brand)` — a case-insensitive substring on the
normalized forms, computed after the call returns. The model got it wrong
in both directions on one cycle: `false` on an answer reading "on
eligible Wiggle & Snug products", `true` on one that only ever said
"Wonder" and "The Wiggles". Both changed an outcome. A string is in a
string or it is not.

That function is the **same object** the generator's guard uses to reject
a brand-direct question that does not name the brand. If the two drifted,
a question could pass the guard and then be scored against a different
idea of naming.

`recommended_retailers` is not only a correction — it is a signal. An
answer that tells a shopper to buy this brand at three retailers, cites
nothing, and does **not** say it could not find the brand has made an
unsourced claim about where the brand is sold, and is classified
`fabricated`. The two exemptions are deliberate: a cited answer is
sourced, and "I could not find this brand — you could try Amazon" is a
suggestion to go looking, not an assertion that it is there.

#### Guessable expectations

`points` at **one per dollar** is the category default. An answer that
gets it right has not shown it read the record, so `is_low_information`
marks it and the **value-survival headline excludes it** — reported
separately, with its own count, because silently dropping rows from a
published rate is its own kind of lie. Judged on the expectation, never
on the answer, so which rows are excluded is fixed before anything is
scored.

A `code` answered with the **right code and the wrong terms** is still
`wrong` — the shopper is told they will save an amount they will not
save. It carries a `near_miss` flag beside the outcome, counted apart
and never moved out of the denominator.

The same guard rejects a brand-direct question that **restates a catalog
question**: same ask (price, code, member price, points) about the same
product, in different words. Left in, it would measure one published
number twice and score the second copy against a brand mention, which is
not what it measured. A question that asks something the catalog tiers
never ask — where to buy, whether the brand makes a thing, whether it
suits a need — is never a duplicate, however many product words it
shares.

---

## Secondary expectations

A question may carry one primary expectation and, in
`expected_answer.secondary`, a list of further typed expectations that
the question does **not** ask about.

The catalog-accuracy tier uses two: a price question attaches `gtin`
where the record carries one, and `pack_count` where the variant has a
count above one. So the tier is **one question per sampled variant**,
carrying up to three expectations.

Secondary expectations:

* are **not** asked for in the question text,
* do **not** contribute to the tier's headline accuracy — a wrong GTIN
  or a wrong count on a right price is still a right price,
* are reported in their own column, with their own sample count, under
  the same rate rules as everything else.

The reason they exist at all is that an assistant that volunteers the
right GTIN or the right count is demonstrating catalog-level grounding
that a price alone does not prove.

**Every secondary outcome is recorded, `absent` included.** It used to be
dropped, on the argument that an assistant is not wrong for failing to
recite an identifier nobody asked for — but that was an argument about
how to *report* it, answered in the wrong place. The report now gives
each secondary its own column, and a column without a denominator cannot
tell "right nine times out of ten" from "volunteered nine times in a
thousand".

---

## Attribution

Every extracted quantity carries the product the answer attributed it to.
A `price` expectation is `exact` only when the matching amount was
attributed to the product the question asked about.

An answer that says

> Snug-Fit Diapers Size 3 Big Pack is $22.99

when $22.99 is the **Small Pack** price is `wrong`, not `exact`. The
number is in the answer; the claim it makes is false, and it is false in
the direction that puts a shopper at the wrong shelf. This case is in the
comparator's test matrix by name.

Attribution matching is deliberately loose on wording and strict on
identity. The extracted product string must contain at least one of the
phrases the question used to name the variant, and none of the phrases
its siblings use and it does not. Those phrases are the question's own —
see *The attribution guard follows the wording* above — so on Wiggle &
Snug that is the size and the pack format, and never the count.

---

## The five outcomes

Every scored (question × surface × sample) lands in exactly one bucket.

| Outcome       | Means                                                              |
| ------------- | ------------------------------------------------------------------ |
| `exact`       | Matches the **currently published** record                          |
| `stale`       | Matches a **prior published** value, per publication history        |
| `wrong`       | Matches **no** published value, ever                               |
| `absent`      | The answer did not address the quantity at all                     |
| `unscoreable` | Extraction could not confidently parse the answer                  |

`unscoreable` is its own bucket and is **never** folded into `wrong`.
They are different facts — "the assistant was incorrect" and "we could
not tell what the assistant said" — and merging them inflates the error
rate with our own extraction failures. It is also the bucket that the
validation harness (below) exists to keep honest: an extractor quietly
degrading shows up as `unscoreable` climbing, which is visible, rather
than as accuracy falling, which is not attributable.

`stale` requires publication history. Where no history is available for a
variant, a non-matching value is `wrong` — we cannot claim it was once
true without a record saying so.

### The rates

* **accuracy** = `exact ÷ (exact + stale + wrong)` — `absent` and
  `unscoreable` are outside the denominator, because neither is a claim.
* **staleness** = `stale ÷ scored`, where `scored = exact + stale + wrong`.
* **value survival** = the `exact` rate on the value & incentives tier.

Every rate is published with its sample count. A rate over four samples
and a rate over four hundred are not the same claim, and a report that
renders them identically invites them to be read as if they were.

---

## Extraction

The extraction pass transcribes; it never judges.

Its JSON schema is fixed:

```json
{
  "prices":        [{"amount": "22.99", "currency": "USD", "attributed_product": "Snug-Fit Diapers Size 3 Small Pack"}],
  "codes":         [{"code": "SNUG3", "value_kind": "amount_off", "value": "3.00"}],
  "pack_counts":   [{"value": 84, "attributed_product": "..."}],
  "member_prices": [{"amount": "16.84", "tier": "Member+", "attributed_product": "..."}],
  "brand_mentioned": true,
  "sources_cited":   ["trueshopstore.com", "amazon.com"]
}
```

Nothing in that schema is a verdict. There is no `correct`, no
`matches_expectation`, no confidence in the *answer* — only confidence
that the transcription itself succeeded, which is what produces
`unscoreable`.

The comparison that follows is ordinary Python: string and integer
equality on normalised values. It is deterministic, it is testable
without a network, and it produces the same verdict today and in six
months for the same stored answer — which is what makes a stored outcome
re-checkable rather than merely re-runnable.

## Validating the extractor

Because the extractor is the one model in the loop, its agreement with a
human is a number the report must be able to state.

`apps/pipeline/scripts/validate_extractions.py` samples N stored answers
and writes a side-by-side of the answer text and the extraction record
for hand-checking. The agreement rate a human arrives at is recorded on
the cycle (`soa_cycles.extraction_validation`) and rendered in the report
header.

Until someone records it, the field is **blank** and the report says so.
It is never estimated, never defaulted to a plausible number, and never
inferred from the extractor's own confidence. A validated agreement rate
that nobody validated is the single most damaging number this system
could print.
