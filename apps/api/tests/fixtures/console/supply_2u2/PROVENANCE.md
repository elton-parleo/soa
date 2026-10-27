# Supply 2U-2 responses, recorded

`tenant-held.json`, `publications-held.json`, `publish.json` and `channels.json` are parleo-supply-app 2U-2's
responses (PR #35, branch `claude/2u2-mcp-brand-facts`, commit `633e14e`), recorded on Oct 27, 2026 by running
`recorder.py` inside that branch's own test harness: `tests/conftest.py`'s in-memory sqlite and the `pampers`
fixture of `tests/test_manufacturer_mode_2r1.py` — the same merchant (`pampers-2r1`), feed and brand pages as
`../supply_2r1/` (#33's), so every other #33 recording still describes it. Nothing is hand-edited. Each file is
`{status, headers, body}`.

Run, from the supply checkout with `recorder.py` copied to `tests/test_zz_record_2u2.py`:

    SOA_2U2_RECORD=<dir> pytest tests/test_zz_record_2u2.py

The recorder sets `PARLEO_MCP_PUBLIC_URL=https://mcp.parleo.example`, a stand-in, not a real address, so the mcp
rows are `published` with `external_ref` `https://mcp.parleo.example#get_product_facts`. The harness leaves the
six rules as seeded (off), so the ACP rows are blocked by ACP's price clause with no rule named; the tests derive
the rule-named case from these rows.

Recorded with no production read or write and no network call: the harness is in memory.
