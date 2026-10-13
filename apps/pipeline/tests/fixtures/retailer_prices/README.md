# retailer-prices fixtures (2B)

Recorded in the shape supply serves at
`GET /api/truesync/merchants/{slug}/retailer-prices?as_of=` (parleo-supply-app
`docs/truesync/verification-semantics.md`, "retailer_price (2A)"). The merchant
is fictional ("acme-baby", a brand with two retailers); no customer data.

- `acme_baby_as_of_cycle2.json` — the cycle being scored. One row per variant x
  retailer page. `target.com` blocked both reference sources for the 120 ct
  pack (`verifiable: false`).
- `acme_baby_as_of_cycle1.json` — the previous cycle's cached rows, which is
  what `stale` is computed from (supply serves no history).
