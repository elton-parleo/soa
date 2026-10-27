"""TEMPORARY (soa 2U-2): record parleo-supply-app 2U-2's responses for soa's fixture. Not committed to supply.

SOA_2U2_RECORD=<dir> pytest tests/test_zz_record_2u2.py
"""
import json
import os

import pytest

from tests import test_manufacturer_mode_2r1 as t
from tests.test_manufacturer_mode_2r1 import pampers  # noqa: F401  (fixture)
from truesync.channels import mcp as mcp_channel

OUT = os.environ.get("SOA_2U2_RECORD")
#: Not a real address: the recording's stand-in for the mcp service's public URL.
MCP_URL = "https://mcp.parleo.example"
SLUG = t.SLUG


def _save(name, response):
    os.makedirs(OUT, exist_ok=True)
    keep = {k: v for k, v in response.headers.items()
            if k.lower().startswith("x-truesync-") or k.lower() in ("content-type", "content-disposition")}
    with open(os.path.join(OUT, f"{name}.json"), "w") as fh:
        json.dump({"status": response.status_code, "headers": keep, "body": response.json()}, fh, indent=1,
                  sort_keys=True)


@pytest.mark.skipif(not OUT, reason="recorder: set SOA_2U2_RECORD")
def test_record(client, db, pampers, monkeypatch):  # noqa: F811
    base = f"/api/truesync/merchants/{SLUG}"
    monkeypatch.setenv(mcp_channel.PUBLIC_URL_ENV, MCP_URL)
    _save("publish", client.post(f"{base}/publish"))
    _save("tenant-held", client.get("/api/truesync/tenant"))
    _save("publications-held", client.get("/api/truesync/publications", params={"limit": 1000}))
    _save("channels", client.get("/api/truesync/channels"))
