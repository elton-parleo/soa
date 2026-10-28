# Supply responses on the Pampers feed as committed to production, recorded

Every `.json` here is a parleo-supply-app response (`main` after PR #37, with 2U-5's S1 on branch
`claude/2u5-public-url`), recorded on Oct 27, 2026 by running `recorder.py` inside supply's own test harness:
`tests/conftest.py`'s in-memory sqlite and the `pampers` fixture of `tests/test_retail_prices_2u1.py`. That is
`tests/fixtures/feeds/pampers_v3.csv` as committed to production (ten SKUs in seven lines, Pure Protection
retired to AMORE) and the 53 recorded reads of Oct 19, 2026 (UTC Oct 20), reparsed with the model's answers
replayed: no model call, no fetch. Nothing is hand-edited. Each file is `{status, headers, body}`.

Run, from the supply checkout with `recorder.py` copied to `tests/test_zz_record_2u5.py`:

    SOA_2U5_RECORD=<dir> pytest tests/test_zz_record_2u5.py

Before recording, the recorder switches r1, r2, r5 and r6 on and approved (`actor` elton@parleo.io), as on the
live console after Oct 27's approvals; r3 stays off and r4 waits. With r1 and r2 on, ACP and UCP carry the
reads' dated retailer prices where a read priced the SKU, and block the SKUs no read priced.

`PARLEO_MCP_PUBLIC_URL` is `https://mcp.parleo.example`, a stand-in; supply's `tests/fake_mcp.py` answers in its
place. `publish-bare-host` is the mcp-only republish with the variable set to `mcp.parleo.io` (S1): every mcp row
`failed`, its error naming the variable and the expected shape, and no readback.

The merchant is `pampers-2u1`; soa's tests serve it as the harness's `pampers-2r1`
(`tests/test_console_2u5.py`, `_rename`), so 2P-1's pair and its cycles read it.

Recorded with no production read or write and no network call: the harness is in memory.
