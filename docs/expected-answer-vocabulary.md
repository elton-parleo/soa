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
signal — see *Secondary expectations*. Unlike `pack_count`, a GTIN never
appears in the question text, so a volunteered one is unambiguous
evidence.

### `pack_count`

```json
{ "type": "pack_count", "value": 84 }
```

An integer count of units. Only set where the record states a count.

**Compared:** exact integer.

**Secondary only, for now.** No question asks for a pack count. It rides
on the variant's price question as a secondary expectation, the same way
`gtin` does, and is scored only where the answer volunteered it.

It was briefly a question of its own — "How many come in the {brand}
{product} {variant}?" — and stopped being one for a reason worth writing
down, because it is the kind of reason that gets forgotten and reverted.
Two questions per variant put Wiggle & Snug's default study at 103
against the study's own 100-question cap: the feature's own defaults
opened on a red tally. One question per variant puts it at 87.

**Read the pack-count column carefully.** On a product with several
sizes, the price question names the variant *by* its count — "Size 3
small pack (84 ct)" — so an answer restating 84 is echoing the question
rather than demonstrating it knows. Only a single-variant product, whose
subject carries no count, produces a genuinely volunteered answer. The
tier report records the two populations separately
(`pack_count_volunteered` and `pack_count_restated` on `tier_config`) so
the report can say which is which.

The honest version of this measurement is a standalone probe that asks
without stating — a question naming the variant by size and pack format
only. That is a **future checkbox, not built**, and it should be built
before anyone quotes a pack-count accuracy number as evidence of
anything.

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
identity: the extracted product string is matched against the variant's
title, its size and its count, and a match needs the distinguishing parts
(size, count) not merely the product family.

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
