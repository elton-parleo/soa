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
