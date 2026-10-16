# Console fixtures

Recorded supply payloads and the W&S fixture cycle the console read-model
tests and `docs/console-read-models.md` samples read. Each JSON file's `_note`
says where its shape comes from.

## 2E: domain checks

`domain_checks_ws_none.json` and `domain_checks_ws_full.json` are
`soa_cycles.domain_checks` records as the worker writes them
(`apps/pipeline/scoring/domain_checks.py`), for the W&S store's own domain,
trueshopstore.com:

- **none**: the store publishes no `/llms.txt`, no `/.well-known/mcp.json` and
  no protocol markup. Protocol & Feed 0 of 5 (four verifiable sub-checks, none
  present), Value Protocols 0 of 14 ("no protocol profile found").
- **full**: the Audit's own `LLMS_TXT`, a manifest declaring all three
  capabilities with a current `specVersion`, and UCP `<link>` markup.
  Protocol & Feed 3.8 of 5 (three of four), Value Protocols 14 of 14.

They are not hand-written. The pages are the recorded Acme Baby store
(`apps/pipeline/tests/fixtures/domain_checks/`) served at the W&S domain, and
`apps/pipeline/tests/test_domain_checks.py::test_the_console_fixtures_are_this_modules_output`
rebuilds both through the real fetcher and the Audit's functions and fails if
either file differs. Regenerate from `apps/pipeline` with

    WRITE_CONSOLE_FIXTURES=1 pytest tests/test_domain_checks.py -k console_fixtures

`checked_at` is fixed (2026-10-16T09:00Z) and the signing key id is
`test-key`; the signed probe ran with a throwaway key and both requests read.
No real site's markup is in them.

## 2E-2: supply's served flags on 229's shape

`supply_retailer_prices_229_bar.json` is supply `/retailer-prices` in #114's
shape (`prices`), its 19 rows from #114's own builder
(`apps/pipeline/tests/test_domain_checks_pdp.py` `ws_payload`). Each row's
`offer_text` and `incentive_in_markup` were computed by supply's own
`truesync/fullloop/parse.offer_text` and `incentive.incentive_in_markup`
(parleo-supply-app `ef3c267`). The input was the store's announcement bar
("Free shipping on orders of $35 or more · 30-day returns · Members earn 1 pt
/ $1", truesync-demo-store `components/SiteChrome.tsx`), with a JSON-LD half
of `member_price` only. Supply serves `promo: true` from the bar's text on
every row. That is the 2E-2 Deal Citability case (`tests/test_console_2e2.py`).

## 2G: availability on the read

`supply_retailer_prices_ws_availability.json` is `supply_retailer_prices_ws.json`
(supply #20's history shape, `prices`) with each readable row's `availability`
set the way supply's reader stores it: parleo-supply-app `ef3c267`
`truesync/fullloop/parse._availability`, applied to the store's Offer
availability, `https://schema.org/InStock`, gives `in_stock`. The Oct 14
recording predates the field, so every row there is null. The 2G record test
(`tests/test_console_2g.py`) reads this file for Availability and the original
for the case where no read carries one.

## 2H: a tenant with two merchants

`supply_tenant_ws_2h.json` is supply `/tenant` for the Wiggle & Snug tenant
after 2F, in the shape `api/truesync_tenant_router.py` `_merchant_view`
serves (parleo-supply-app `ef3c267`): merchants ordered by slug, the store
(seller, Parleo-hosted, trueshopstore.com) then the brand (customer-hosted,
wiggleandsnug.com, the 2F feed). `supply_retailers_ws_2h.json` is each
merchant's `/retailers` in the shape `api/truesync_feed_router.py` serves.
Values come from supply's repo (the brand's feed and its tests), not from
production. The brand's display name, "Wiggle & Snug Brand", is this
fixture's.

## 2I: the brand's catalog, feed and page reads

`supply_ws_brand_2i.json` is the Wiggle & Snug brand (`wiggle-and-snug-brand`,
customer-hosted, wiggleandsnug.com, retailer trueshopstore.com) in supply's
shapes at parleo-supply-app `868e8cf`:

- `catalog`: `/catalog` for an external merchant (`truesync/feed/serve.py`
  `catalog`).
- `feed`: `/feed` rows (`truesync/feed/store.py` `sku_view`).
- `retailer_prices`: `/retailer-prices` rows (`truesync/fullloop/prices.py`
  `_row`), one `own` and one `retailer` row per variant.

The 19 SKUs are supply's committed 2F feed,
`truesync/demo/feeds/wiggle-and-snug-brand.csv`. It has no GTIN and no
price, so each variant is `sku:<sku>` and has no list price. Each
trueshopstore.com row carries the store page's recorded Oct 14 read, the
newest per variant in `supply_retailer_prices_ws.json`, matched on the
variant's title. The own-site rows are not read yet. Rebuild it with:

    python tests/fixtures/console/build_ws_brand_2i.py <parleo-supply-app>/truesync/demo/feeds/wiggle-and-snug-brand.csv

The B2 tests (`tests/test_brand_prices_2i.py`, and the pipeline's file of the
same name) make the partial and no-reads cases by blanking rows into the
not-read-yet shape that `_row` serves.
