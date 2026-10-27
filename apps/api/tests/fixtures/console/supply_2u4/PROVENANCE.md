# Supply 2U-4 responses, recorded

Every `.json` here is a parleo-supply-app 2U-4 response (PR #37, branch `claude/2u4-variant-facts`), recorded on
Oct 27, 2026 by running `recorder.py` inside that branch's own test harness: `tests/conftest.py`'s in-memory
sqlite and the `pampers` fixture of `tests/test_manufacturer_mode_2r1.py`. That is the same merchant
(`pampers-2r1`), feed and brand pages as `../supply_2u2/` and `../supply_2r1/`. Nothing is hand-edited. Each
file is `{status, headers, body}`.

Run, from the supply checkout with `recorder.py` copied to `tests/test_zz_record_2u4.py`:

    SOA_2U4_RECORD=<dir> pytest tests/test_zz_record_2u4.py

The recorder sets `PARLEO_MCP_PUBLIC_URL=https://mcp.parleo.example`, a stand-in, not a real address. In
2U-4, supply's readback is a client of that URL. In supply's harness, `tests/fake_mcp.py` answers in its
place: an in-memory MCP server with the real tools, reading the harness's database through its own session.
Three readbacks are recorded:

* `publish`, `tenant-held`, `publications-held`, `channels`: served. Acceptance `approved`, 6/6.
* `publish-not-served`, `tenant-held-not-served`: a server that answers MCP but does not list
  `get_product_facts` (`fake_mcp.not_serving`). Acceptance `disapproved`, reason
  `tool not served at https://mcp.parleo.example`.
* `publish-unreachable`, `tenant-held-unreachable`: the real streamable-http transport against a loopback port
  nothing listens on. Acceptance `unavailable`, reason `server not reachable at http://127.0.0.1:<port>: ...`.

`publish-dry-run` is the dry run's answer, with supply's `counts`. The harness leaves the six rules as seeded
(off), so ACP and UCP are blocked by r1 and r2; their `blocked` journal entries name both (`rules`).

Recorded with no production read or write and no network call beyond that loopback port: the harness is in
memory.
