Mirror. Canonical lives in `parleo-supply-app` at `docs/truesync/verification-semantics.md` — update both copies together.

# Verification semantics

How the Merchant Command Center decides what a cell is saying.

> **Canonical home.** This document describes behaviour of the supply
> app's TrueSync API as much as it does this page. It should be mirrored
> into the supply app's `docs/truesync/` and treated as canonical there;
> this copy exists because the consumer is here and drifted twice
> already for want of a written model.

**This document wins.** Where the implementation disagrees with what is
written here, the implementation is wrong. The table-driven tests in
`apps/api/web/src/components/merchant-command-center/__tests__/verificationModel.test.jsx`
are the executable form of this document; between the two there is no
third source of truth, and in particular no rule that lives only inside
a React component.

---

## Why this exists

Three bugs in this family shipped in three days, and all three were the
same mistake wearing different clothes: **one dimension's absence being
read as another dimension's evidence.**

1. A `gmc_diagnostics` record was fed through the field-comparison
   parser, produced a synthetic "unparsed" finding, and was counted as
   catalog drift. *A parse failure reported as a merchant data problem.*
2. A `fetch_probe` that could not fetch the page returned zero findings
   and was read as "verified, no drift". *A check that never ran
   reported as a passing check.*
3. Google reports `pending_initial_policy_review_free_listings` with
   `severity: "DISAPPROVED"`. Trusting that field paints an item that is
   simply awaiting review as a policy rejection. *A lifecycle state
   reported as a failure.*

The fix is not another special case. It is to say plainly what a cell
knows, and to keep those things from contaminating each other.

---

## The unit: a cell

A **cell** is one *(listing × channel)* pair — one row of the matrix,
one column.

Its inputs are exactly two:

- the **latest publication row** for that cell (the publication log)
- every **verification record** for that cell, newest first

Everything below is a pure function of those two.

---

## Verification surface — what a channel can be checked against

Before the dimensions, a property of the channel itself: **what independent
surface exists to check it against.** Every channel declares one.

| `verification_surface` | meaning | channels today |
|---|---|---|
| `fetch_probe` | something we can fetch and compare to what we published | `schema_org`, `acp` |
| `acceptance` | no comparable surface of our own, but a third party renders a verdict | `merchant_center` |
| `none` | nothing to fetch and nobody to ask | `deals_api`, `mcp`, `deal_directory`, `ucp_uip` |

This exists because the matrix was rendering `○ Unverified` on cells that
could never become anything else. `○` is supposed to mean "a probe could run
and none has" — a prompt to act. On a channel with no probe it meant "this
will be `○` forever", which is not a prompt, and a reader who learns to
ignore a glyph in one column stops reading it in the column where it matters.

**Dimension 2 applies only to `fetch_probe` channels.** For `acceptance` and
`none` channels the cell renders no drift glyph at all — a muted dash, with
the tooltip *"no independent verification surface for this channel yet"*. Not
`○`, not `✓`, and never `⚠`.

For `merchant_center` the distinction is worth stating plainly, because it
looks like a gap and is not: drift at our layer is not measurable against
Google's surface. We cannot fetch what Google renders; we can only ask what
Google decided. The acceptance dimension carries that cell, and asking it for
a drift number would be asking a question the surface cannot answer.

`ucp_uip` is `none` today because it publishes nothing. When it goes live it
becomes `fetch_probe`, on the same terms as ACP — the field moves with the
implementation, which is why it is derived from the code rather than stored
as editable data.

**The field is the truth.** No consumer may hardcode a channel list; a
channel that gains or loses a probe changes this one declaration and
everything follows. `ucp_uip` moving from `none` to `fetch_probe` must not
require touching a classifier, a legend, or a button.

---

## Four orthogonal dimensions

A cell is described by four dimensions. **No dimension may contribute to
another's count.** That sentence is the whole design.

### 1. Publish state — *what we did*

From the publication log. Independent of any verification.

| state | meaning |
|---|---|
| `published` | the artifact reached the surface |
| `compiled_not_published` | compiled and validated, not sent (carries a **reason**) |
| `failed` | a publish was attempted and failed (carries the upstream error) |
| `never` | no publication row exists for this cell |

`withdrawn` maps to `compiled_not_published` with the reason
`"withdrawn"`.

Absence of a publication row is `never` — never a blank, never an
optimistic green.

### 2. Drift — *our comparison*

**Only for channels whose `verification_surface` is `fetch_probe`.** On any
other channel this dimension does not apply, is not `null`, and renders no
glyph — see the verification-surface section above.

`number | null`. The count of master-vs-surface findings from the newest
**fresh, parseable `fetch_probe`** record.

- `null` — **unknown**. No fresh parseable probe exists. Renders `○`.
- `0` — a probe ran and found nothing. Renders `✓`.
- `n > 0` — renders `⚠ n`.

**`null` is not zero.** A cell with no probe has not been checked; it has
not passed. This is the only input to the Drift badge and to the
header's *Drifting* count.

A probe that did not succeed contributes **nothing** to drift — it goes
to dimension 4. Its zero findings are the absence of a measurement, not
a measurement of zero.

"Did not succeed" is deliberately narrower than "outcome is not `ok`". A
probe that completed and found drift may report `outcome: "drift"`, and
discarding those findings because the word was unfamiliar would be the
same mistake in the other direction. The rule:

| condition | verdict |
|---|---|
| `error` is set | failed |
| `outcome` ∈ {`fetch_failed`, `failed`, `error`, `timeout`, `publish_failed`, `skipped`, `not_found`, `blocked_for_agents`, `robots_disallowed`} | failed |
| `outcome` is `ok`, or absent (legacy records) | succeeded |
| `outcome` unrecognised, **and** the record carries a comparison result (findings, or a boolean `integrity`) | succeeded |
| `outcome` unrecognised with nothing to show for it | failed |

The last row keeps the principle: an unfamiliar outcome with no
comparison behind it is an absence, not a pass.

`blocked_for_agents` and `robots_disallowed` are named explicitly rather
than left to that catch-all. The verifier now fetches through the same
platform client the prospect ingest uses, so it can be turned away by our
own storefront's edge — a CDN rule, a rate limit — and that is a probe
that did not succeed, not a listing with zero drift. It belongs in
dimension 4, named, with the reason the fetcher gave.

#### 2b. Prospect drift — *surface versus surface*

A prospect is a brand we have no authorization to publish for. There is
no master: we never published their catalogue, so nothing authoritative
exists to measure a live page against. What exists instead is several
surfaces describing the same physical product, and the question worth
asking is how far they disagree with **each other**.

That is a different measurement, so it wears a different method:
`prospect_fetch`, added to `truesync_verifications.method` by migration
`e4c9a17b3d52`. **It must never be `fetch_probe`.** Dimension 2 above is
defined as the findings of the newest fresh parseable `fetch_probe`
record; a surface-vs-surface observation carrying that method name would
become eligible to answer a question about one of our own listings, which
is the cross-contamination this whole document exists to prevent.

Prospect rows therefore contribute to **no** dimension of a cell. They
carry `listing_id = NULL` — a prospect is not one of our listings — and
`record_ref` of the form `prospect:<brand>:<product>`. They are read by
`GET /api/truesync/prospects/{slug}/drift`, never by the cell grid.

Findings mirror dimension 2's schema field-for-field, with the
expected/observed pair replaced by two named surfaces, because nothing
here knows which side is right:

| fetch_probe finding | prospect_fetch finding |
|---|---|
| `variant_key` | `variant_key` |
| `field` | `field` |
| `expected` | `surface_a` + `value_a` |
| `observed` | `surface_b` + `value_b` |

`field` is one of `title`, `gtin`, `gtin_missing`, `price`, `currency`,
`availability`, `member_price`. `price` reports the **spread** — the
cheapest surface against the dearest — rather than a pairwise walk.
`gtin_missing` is a first-class finding rather than an alignment problem
worked around: a surface that omits the identifier is the one an agent
trips over first.

The comparison's own `outcome` is `ok`, `drift_detected`, or
`insufficient_surfaces`. That third value carries the same weight as
`null` does in dimension 2: **fewer than two readable surfaces is not
agreement.** One surface cannot disagree with itself, and a run that
fetched one page and found nothing to report has measured nothing.

##### Per-surface outcomes

A prospect's surfaces belong to other people, and they answer a declared
crawler very differently from a bare HTTP client. Fetching goes through
the vendored Agent Scan fetcher (`truesync/vendored/fetcher.py`), which
declares itself, honours robots, waits between requests, retries a
429/403/5xx ladder, and recognises a challenge interstitial. Each surface
records one of:

| outcome | meaning | readable? |
|---|---|---|
| `fetched` | a real page came back; extraction decides what is in it | yes |
| `no_structured_data` | **we fetched a real page and it carried no JSON-LD** | no |
| `blocked_for_agents` | the surface is up and declined to serve us — challenge interstitial, 403/429, or a 2xx body too short to be a page | no |
| `robots_disallowed` | robots.txt disallows this path; we did not fetch it | no |
| `parse_failed` | JSON-LD was present but described no product | no |
| `fetch_failed` | the page did not load — DNS, timeout, 404/410, 5xx, SSRF guard, redirect loop | no |

**`no_structured_data` and `blocked_for_agents` are the distinction this
vocabulary exists for.** The first is the most valuable finding a prospect
ingest can make: a storefront that serves agents nothing. The second is a
fact about how we asked, not about their markup. Before the platform
fetcher both arrived as "no structured data", and a demo row could not
tell you which one it was looking at.

`robots_disallowed` is a policy finding rather than a failure — the
surface published a rule and we followed it — and it is likewise not
evidence about their markup.

Every unreadable outcome, `blocked_for_agents` and `robots_disallowed`
included, counts toward `insufficient_surfaces`. They are more
informative than an unreachable page, but they carry no opinion about the
product, and a comparison with nothing to compare has measured nothing.

Each surface also records what the fetcher saw — `http_status`,
`final_url`, `bytes`, `attempts`, `redirect_chain`, `user_agent` — under
`observed.surfaces[].transport`. "403 after 3 attempts" is the evidence
behind a blocked row, and without it the row is an assertion.

##### Agent access policy

Each surface also carries `observed.surfaces[].robots_policy`: what that
domain's robots.txt says to the six named AI agents — GPTBot,
OAI-SearchBot, ChatGPT-User, ClaudeBot, PerplexityBot, Google-Extended —
for the site root and for that surface's own path, plus any divergence
between an agent's named group and the `*` default.

It costs no extra request: robots.txt is already fetched for our own
politeness check, and this re-reads the same parsed rules through the
vendored Agent Access Matrix.

**It is an independent question from every other outcome on the row.** A
surface can serve us a perfect page and still be closed to every agent a
shopper would actually use; it can turn us away while welcoming them. A
retailer blocking GPTBot and ClaudeBot on its product paths will not be
found by a shopping agent however good its markup is, which makes this
the finding most likely to explain the rest of the row.

States are `allowed`, `blocked`, `partial`, or `unknown`. `unknown` means
robots.txt could not be read — never a guess in either direction.

#### 2c. Self-hosted surfaces

`acp` joins dimension 2 on the same terms as `schema_org`: a `fetch_probe`
record, integrity plus per-variant findings, drift counted the same way.

The difference is whose surface it is. A schema.org probe fetches a page
built by a storefront we do not control, so drift there is a real
possibility with a real cause. An ACP probe fetches our own endpoint,
where both ends are ours, and it can only catch a serving layer that
reformats, truncates or serves a stale artifact.

That is a weaker check, and the column should not be read as equally
strong evidence. What it does buy is that `published` stops being a claim
the database makes about itself: the artifact is fetchable, and the fetch
is compared to what the publication row says was published.

Findings are keyed by `item_id` and cover `title`, `price`, `sale_price`,
`availability` and `gtin`. An item on one side only is its own finding —
`field: "item"`, expected/observed `present`/`absent` — because a feed
that quietly drops a variant is not a feed that agrees.

### 3. Surface acceptance — *their opinion*

Only meaningful for channels that have an **acceptance authority** — a
third party who can accept or reject what we sent. Today that is
`merchant_center` alone. For every other channel this dimension is
permanently `unknown` and renders nothing.

From the newest **fresh, parseable `gmc_diagnostics`** record.

| state | derived from | renders |
|---|---|---|
| `approved` | `approved: true` | green |
| `pending` | not approved, and every issue is **lifecycle-shaped** | **amber — "pending review"** |
| `disapproved` | not approved, with at least one genuine policy/data rejection | red |
| `not_found` | `httpStatus: 404` — the item is not in the account | grey "not in feed" |
| `unavailable` | the record explains why no opinion could be obtained (e.g. `outcome: publish_failed`) | grey, with the reason |
| `unknown` | no fresh parseable acceptance record | renders nothing |

Issues aggregate into a separate **Issues** indicator. They never touch
Drift.

#### Lifecycle codes override Google's severity field

Google reports `pending_initial_policy_review_free_listings` with
`severity: "DISAPPROVED"`. It is not a disapproval; it is the normal
first step of the publish → pending → approved lifecycle.

**A lifecycle-shaped code renders amber "pending review" regardless of
the severity field.** Recognised as lifecycle:

- `pending_initial_policy_review*` (any suffix)
- `image_link_pending_crawl`
- any code matching `/(^|_)pending(_|$)/`, `/_crawl(_|$)/`, or
  `/_processing(_|$)/`

Anything else that is not approved is a genuine rejection and renders
red. When in doubt the code is treated as genuine — under-reporting a
real disapproval is worse than over-reporting one.

A cell whose issues are *all* lifecycle is `pending`. One genuine
rejection among them makes the cell `disapproved`; the lifecycle issues
in it still render amber individually.

### 4. Observability health — *our own honesty*

The count of records this page could not turn into either of the two
readings above:

- unparseable payloads (no recognised shape)
- probes that failed to run (`outcome != "ok"`, `error` set,
  `fetch_failed`)
- records whose `method` we have no parser for

Renders as the `?` **unreadable** indicator.

This is a statement about *this page*, not about the merchant. It never
counts as Drift and never counts as Issues. A cell whose only record is
unreadable has drift `null` (`○`) — unknown, because we genuinely do not
know.

`unavailable` acceptance (dimension 3) is deliberately **not** counted
here: we read that record correctly and it told us plainly that no
opinion exists. Nothing is wrong with our reading.

---

## Freshness — the cross-cutting rule

> A verification record whose `created_at` predates the cell's latest
> `published_at` verified a **superseded artifact**.

Such a record is **stale**. Stale records:

- contribute to **no** count, in any dimension
- render greyed, with the note *"pre-dates latest publish — re-verify"*
- leave the cell's badge at `○` until a fresh run exists

This matters because publishing invalidates evidence. A probe that
passed against yesterday's artifact says nothing about the one we sent
this morning, and a green tick sourced from it is a lie with a
timestamp on it.

**Comparison rule:** `record.created_at < publication.published_at`,
compared as ISO-8601 instants.

Edge cases, decided once:

- **No `published_at`** (never published, or a failed publish): nothing
  supersedes anything, so **every record is fresh**. A cell that never
  published cannot have stale evidence.
- **Missing `created_at`** on the record: treated as **stale**. We
  cannot show it is current, and the safe direction is to withhold a
  green tick rather than grant one. (Every record the API has produced
  since 2026-08-24 carries `created_at`.)
- **Equal timestamps**: fresh. The comparison is strictly "predates".

---

## Reading order within a cell

For each dimension, take the **newest fresh parseable record of the
matching kind**. Not the newest record overall — a cell can hold both a
`fetch_probe` and a `gmc_diagnostics` history, and they answer different
questions. The newest record of one kind never speaks for the other.

---

## Badge glyphs

The cell's primary badge is the **Drift** badge, and only Drift:

| drift | glyph |
|---|---|
| not applicable — `verification_surface` is not `fetch_probe` | `–` muted, tooltip "no independent verification surface for this channel yet" |
| `null` | `○` not yet verified |
| `0` | `✓` verified — no drift |
| `n > 0` | `⚠ n` |

The first row is the one that keeps the other three honest. `○` means a probe
surface exists and no fresh record does; it is a prompt to press Verify. A
channel with no probe surface must never wear it, or `○` degrades into
"unknown for reasons unknown" and stops being actionable anywhere.

Alongside it, and never merged into it:

- an **acceptance** marker, for channels with an acceptance authority
- a `?` marker when `unreadableCount > 0`

The publish state colours the cell's segment, as it always has.

---

## Header counts

All derived by `summarize(cells)`; no component counts anything.

| indicator | definition |
|---|---|
| Published | cells whose publish state is `published` |
| Verified | cells with `drift === 0` — `fetch_probe` channels only |
| Drifting | cells with `drift > 0` — `fetch_probe` channels only |
| Issues | total issues across cells with acceptance `pending` or `disapproved` |
| Unreadable | total `unreadableCount` across cells |
| Stale | records excluded by the freshness rule |
| Last verified | newest `created_at` across **fresh** records |

Indicators for which the count is zero and which have nothing to say are
hidden rather than shown as `0`.

---

## Real payloads this system has produced

Every shape below is committed as a fixture and enumerated in the test
table. They are the reason each rule above exists.

```jsonc
// fetch_probe, clean run (2026-08-24, verification_id 41)
{ "url": "…", "error": null, "outcome": "ok",
  "findings": [], "integrity": true, "bytes_identical": false }

// gmc_diagnostics, pending initial review — note the severity field
{ "issues": [ { "code": "pending_initial_policy_review_free_listings",
                "severity": "DISAPPROVED",
                "description": "Pending initial review" } ],
  "approved": false }

// gmc_diagnostics, the "ghost": accepted nowhere, itemised nowhere
{ "issues": [], "approved": false, "httpStatus": 404 }

// gmc_diagnostics, no opinion obtainable — the publish never landed
{ "issues": [], "reason": "not implemented in Step 2",
  "outcome": "publish_failed", "approved": false }
```

---

## Method names

The API's values are `fetch_probe` and `gmc_diagnostics`. `live_fetch`
appears in older specs and is accepted as an alias for `fetch_probe`, so
a rename on either side cannot silently route records to the wrong
parser. Any other method is dimension 4 — unreadable, named in the UI.
