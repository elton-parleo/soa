"""TEMPORARY (soa 2U-5): record parleo-supply-app's responses on the Pampers feed as committed to production
(tests/fixtures/feeds/pampers_v3.csv: ten SKUs in seven lines) and the recorded reads of Oct 19 2026, as
tests/test_retail_prices_2u1.py's `pampers` fixture stores them, for soa's fixture. Not committed to supply.

SOA_2U5_RECORD=<dir> pytest tests/test_zz_record_2u5.py
"""
import json
import os

import pytest

from tests.test_retail_prices_2u1 import pampers  # noqa: F401  (fixture: the v3 feed and the recorded reads)
from truesync.channels import mcp as mcp_channel

OUT = os.environ.get("SOA_2U5_RECORD")
#: Not a real address: the recording's stand-in for the mcp service's public URL.
MCP_URL = "https://mcp.parleo.example"
SLUG = "pampers-2u1"
#: As on the live console after Oct 27's approvals: r1, r2, r5, r6 on and approved; r3 off; r4 waiting.
ON = ("r1", "r2", "r5", "r6")


def _save(name, response):
    os.makedirs(OUT, exist_ok=True)
    keep = {k: v for k, v in response.headers.items()
            if k.lower().startswith("x-truesync-") or k.lower() in ("content-type", "content-disposition")}
    with open(os.path.join(OUT, f"{name}.json"), "w") as fh:
        json.dump({"status": response.status_code, "headers": keep, "body": response.json()}, fh, indent=1,
                  sort_keys=True)


@pytest.mark.skipif(not OUT, reason="recorder: set SOA_2U5_RECORD")
def test_record(client, db, pampers, monkeypatch):  # noqa: F811
    base = f"/api/truesync/merchants/{SLUG}"
    monkeypatch.setenv(mcp_channel.PUBLIC_URL_ENV, MCP_URL)
    for code in ON:
        r = client.put(f"{base}/rules/{code}", json={"on": True, "approval": "approved", "actor": "elton@parleo.io"})
        assert r.status_code == 200, r.text
    _save("rules", client.get(f"{base}/rules"))
    for name in ("feed", "catalog", "retailers", "retailer-prices"):
        _save(name, client.get(f"{base}/{name}"))
    _save("publish", client.post(f"{base}/publish"))
    _save("tenant-held", client.get("/api/truesync/tenant"))
    _save("publications-held", client.get("/api/truesync/publications", params={"limit": 1000}))
    _save("channels", client.get("/api/truesync/channels"))
    # S1: a public URL without a scheme fails the mcp row, naming the variable
    monkeypatch.setenv(mcp_channel.PUBLIC_URL_ENV, "mcp.parleo.io")
    _save("publish-bare-host", client.post(f"{base}/publish", params={"channels": "mcp"}))
