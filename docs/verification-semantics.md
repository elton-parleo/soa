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
| `outcome` ∈ {`fetch_failed`, `failed`, `error`, `timeout`, `publish_failed`, `skipped`, `not_found`} | failed |
| `outcome` is `ok`, or absent (legacy records) | succeeded |
| `outcome` unrecognised, **and** the record carries a comparison result (findings, or a boolean `integrity`) | succeeded |
| `outcome` unrecognised with nothing to show for it | failed |

The last row keeps the principle: an unfamiliar outcome with no
comparison behind it is an absence, not a pass.

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
| `null` | `○` not yet verified |
| `0` | `✓` verified — no drift |
| `n > 0` | `⚠ n` |

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
| Verified | cells with `drift === 0` |
| Drifting | cells with `drift > 0` |
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
