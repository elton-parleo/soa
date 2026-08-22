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
| `publications.json` | `GET /api/truesync/publications` | newest row per (listing, channel), plus a second older row per channel for listing 90 so the drawer's publish timeline has real history. Payloads kept intact — the drawer renders them |

Two properties of this data drive most of the tests:

- `merchant_center`, `acp` and `ucp_uip` have **only failed rows**, each
  carrying `error: "not implemented in Step 2"`. That is what the muted
  "stub" treatment keys off.
- **No verification fixture exists**, because the live API returns `[]`
  for every listing on every channel. Every badge is therefore ○, and
  the drift-badge tests build their own `VerificationResponse` objects
  to exercise the counting logic against a shape the API has never yet
  emitted.
