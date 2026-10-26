# Supply 2R-1 responses, recorded

Every `*.json` here is one response of parleo-supply-app PR #33 (branch `claude/optimistic-carson-2nihli`,
commit `4ec9a8a2526775d2094c66833087a36c8f78e397`, 2R-1 and 2R-1a), recorded on Oct 25, 2026 by running
`recorder.py` inside #33's own test harness (`tests/conftest.py`'s in-memory sqlite, its `pampers` fixture from
`tests/test_manufacturer_mode_2r1.py`: the committed `pampers_2l2.csv` feed plus the two Size 4 rows that
module builds from the recorded pampers.com pages). Nothing is hand-edited. Each file is
`{status, headers, body}` (`body_base64` for a file response); headers are `content-type`,
`content-disposition` and `X-TrueSync-*` only.

Run, from the supply checkout with `recorder.py` copied to `tests/test_zz_record_2r2.py`:

    SOA_2R2_RECORD=<dir> SOA_2R2_SENT_AT=2026-10-17T15:30:00Z pytest tests/test_zz_record_2r2.py
    SOA_2R2_RECORD=<dir> SOA_2R2_SENT_AT=2026-10-23T15:30:00Z pytest tests/test_zz_record_2r2.py

The first run is the top level here (`sent-20261017.json` is its sent POST); the second run's sent POST,
`/tenant` and `/publications` afterwards are in `sent-20261023/`. Its other responses differ from the first
run's only in wall-clock stamps (`compiled_at`, `at`, filenames' dates).

`brand-pages.json` is not a route's response: it is supply's own `brand_page.read` over the recorded pampers.com
pages, the value #33's harness stores on its reads. 2S-1: soa's tests no longer put it on the retailer-prices rows. Those
rows, as recorded, already carry the brand page the way 2O-6 serves it (`json_ld`, `size_chart` and `bullets` on the two
own-domain rows read Oct 20, beside their `observed_at`), and soa reads that. The earlier composition, under a
`brand_page` key no supply route serves, hid that soa looked for a key production never sent, which is why the live
site markup surface read "Not read yet". `brand-pages.json` stays for the tests that read the full read by hand.

Not from #33 (the soa side of the test, unchanged): 2P-1's two cycles, and their `/reference` attributes and
`/deals`, which are not 2R-1's routes.

Recorded with no production read or write and no network call: the harness is in memory.

2T-1: `deals-20261020.json` and `deals-20261021.json` are #33's `GET /merchants/pampers-2r1/deals?as_of=<day>` after its
compile, recorded on Oct 26, 2026 by `recorder_deals.py` in the same harness at the same commit (`4ec9a8a`), run as:

    SOA_2T1_RECORD=<dir> pytest tests/test_zz_record_2t1.py

#33's merchant has no live deal: its retailer rows were never read (`shelf_seen` 0 everywhere), so supply lists every
retailer under `walled` and `deals` is empty. The tests that need a live deal keep the pair's `/deals` (2P-1); one test
serves this recording and checks that nothing deal-shaped is invented from it.
