# Fixtures

Captured verbatim from the live TrueSync API (`https://api.parleo.io`)
on **2026-08-22**, with `curl`. They are real responses, not
hand-written examples — the point of committing them is that the
matrix's derivation is tested against shapes the API actually emits,
including the awkward ones:

| file | endpoint | why it is interesting |
|---|---|---|
| `active-brand.json` | `GET /api/truesync/demo/active-brand` | supplies the brand name and the accent colour the page themes itself with |
| `channels.json` | `GET /api/truesync/channels` | 7 channels; note there is **no** `is_stub` / tier field, which is why implementation state is derived from publication rows |
| `merchant-schema-org.json` | `GET /api/truesync/merchants/{slug}/schema-org` | the catalog spine. Payloads trimmed to the three fields the page reads (`@type`, `name`, `image`) — the originals are ~35 KB of JSON-LD |
| `listings.json` | `GET /api/truesync/listings/{id}` (90–94), keyed by id | canonical records. `offers` (51 entries on listing 90) stripped; nothing on the page reads it. Mixed GTIN coverage is real: 4 of 12 variants on listing 90, 0 of 4 on 91 |
| `verifications-envelope.json` | `GET /api/truesync/listings/90/verifications` | captured **2026-08-24**, after the endpoint changed shape. It used to return a bare `VerificationResponse[]`; it now returns `{listing_id, lineage, verifications}`. `verifications` is still `[]` in production |
| `verifications-gmc.json` | `GET /api/truesync/listings/90/verifications?channel=merchant_center` | captured **2026-08-24**. Four of the twelve real rows (one per variant upstream), `observed.body.raw` truncated — it is a ~2 KB Google 404 page on every row and the drawer only shows it inside a collapsed block. This is the exact payload that used to mis-parse as catalog drift |
| `verifications-fetch-probe.json` | `GET /api/truesync/listings/90/verifications?channel=schema_org` | captured **2026-08-24** immediately after triggering a real `POST /listings/90/verify` — a live read of the demo store's own PDP. `observed.jsonld` replaced with a marker (it is the whole PDP JSON-LD, ~24 KB; `merchant-schema-org.json` has the same content) |
| `publications.json` | `GET /api/truesync/publications` | newest row per (listing, channel), plus a second older row per channel for listing 90 so the drawer's publish timeline has real history. Payloads kept intact — the drawer renders them |

Two properties of this data drive most of the tests:

- `merchant_center`, `acp` and `ucp_uip` have **only failed rows**, each
  carrying `error: "not implemented in Step 2"`. That is what the muted
  "stub" treatment keys off.
- Both methods are now represented by **real** records:
  `gmc_diagnostics` (`{approved, issues, httpStatus}`) and `fetch_probe`
  (`{url, error, outcome, findings, integrity, bytes_identical}`). The
  `fetch_probe` capture is the one that mattered most — the inferred
  shape had `findings` right but omitted `outcome`/`error`, so a probe
  that failed to fetch the page would have been read as "verified, no
  drift". Both fixtures are clean runs; a *drifting* record of either
  kind is still synthesised in the tests.


## A note on dates

`verifications-envelope.json` is from **2026-08-24**; everything else is
from **2026-08-22**. That two-day gap is itself the point: the
verifications endpoint changed shape between the two captures, with no
version bump, and the page's original `Array.isArray(rows) ? rows : []`
guard turned every response into an empty list rather than failing
loudly. Re-capture these before trusting them.


## Re-capture before trusting these

The supply app has changed shape twice in three days with no version
bump — the verifications envelope on the 24th, and `created_at` /
`outcome` appearing on `VerificationResponse` in the same window. The
`merchant_center` channel also went from failing every publish with
`"not implemented in Step 2"` to publishing successfully, which the
matrix's channel treatment picks up on its own (it derives
implementation state from publication rows rather than a hardcoded
list). Assume anything here older than a few days is stale.
