# Supply responses for Petco, an externally hosted seller, re-recorded for 2V-4

Every `.json` here is a parleo-supply-app response from `main` at **13c9c80** (the merge of #40, 2V-2, on top
of #39, 2V-1), recorded on Oct 30, 2026 by running `recorder.py` inside supply's own test harness:
`tests/conftest.py`'s in-memory sqlite and the `petco` fixture of `tests/test_seller_offer_2v1.py`
(`tests/fixtures/feeds/petco_2v1.csv` and `petco_2v1_incentives.csv` as committed): four SKUs (Pro Plan 30 lb,
Tidy Cats 17 lb, Greenies 36 ct, NexGard PLUS Rx), Autoship 35% capped at $20 then 5% with Rx excluded from the
first order, Purina's 40/20/10 ladder on the two Purina SKUs (ends Oct 31), Perks Premier 10% off dog and cat
food, Petco Perks formerly Vital Care and Repeat Delivery. Prices are as of Oct 2 2026 (the recorder pins
supply's clock to the read day). Nothing is hand-edited. Each file is `{status, headers, body}`.

Run from a detached checkout of supply `main` at 13c9c80, with `recorder.py` copied to
`tests/test_zz_record_2v4.py` (and removed after):

    SOA_2V4_RECORD=<dir> pytest tests/test_zz_record_2v4.py

It replaces `supply_2v2/` (recorded from the 2V-2 branch before its merge). Normalised for wall-clock stamps
(`2026-10-30T…`) and the random `upload_id` / `token_id`, every file is identical to the 2V-2 recording: supply's
answers did not move in the merge. The stamps did: the compile is at 15:10:37 UTC, so a send stated before it
is refused (soa's `test_mark_as_sent_records_the_sellers_statement` states one after it).

`rules-seed` and `tenant-feed` are before any rule is touched (all six off, needs_approval). Then the recorder
switches s1 to s5 on and approved (`actor` elton@parleo.io), as the demo's retail mode shows them; s6 waits. With
s2 on, the held files carry no member price; with s3 on, NexGard PLUS compiles at list price only.

`publish` is the compile and hold: schema_org, merchant_center, acp, ucp_uip, deals_api and deal_directory held
for Petco's team, mcp published, readback approved 4/4. `sent` is Petco's statement that it sent the Merchant
Center file (Oct 2, 15:42 UTC, stated by Gabe L.); `tenant-sent` and `publications-sent` are after it.

`PARLEO_MCP_PUBLIC_URL` is `https://mcp.parleo.example`, a stand-in; supply's `tests/fake_mcp.py` answers in its
place.

The merchant is `petco`; soa's tests serve it as the harness's `pampers-2r1` (`tests/test_console_2v2_seller.py`,
`_rename`), so 2P-1's pair and its cycles read it.

Recorded with no production read or write and no network call: the harness is in memory.
