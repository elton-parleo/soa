# Domain-check fixtures (2E)

An invented store, Acme Baby, on `acmebaby.test`, recorded as the worker's
domain checks (`scoring/domain_checks.py`) fetch it: `robots.txt`, the store
root (`home.html`), and a product page (`pdp.html`). The store root declares a
UCP profile in `<link>` markup (the Audit's `AGENTIC_PROTOCOL_LINK_HINTS`) and
has a cart link (a commerce signal for `classify_site`); the product page has
Product JSON-LD with a price and a GTIN.

`/llms.txt` and `/.well-known/mcp.json` are not files here: the tests serve the
Audit's own fixtures for them (`tests/scan/test_soft_200_protocol_files.py`:
`LLMS_TXT`, `MANIFEST`, and the Church & Dwight soft 404), so the adapter is
checked against the same bodies the Audit's checks are.

No real site's markup is reproduced. `.test` never resolves; the tests patch
`socket.getaddrinfo` and `httpx.Client.get`, so every request goes through the
scan's real fetcher (headers, robots, SSRF guard) without reaching a network.
