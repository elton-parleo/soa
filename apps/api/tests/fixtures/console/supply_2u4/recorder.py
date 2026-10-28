"""TEMPORARY (soa 2U-4): record parleo-supply-app 2U-4's responses for soa's fixture. Not committed to supply.

SOA_2U4_RECORD=<dir> pytest tests/test_zz_record_2u4.py
"""
import json
import os
import socket

import pytest

import fake_mcp
from tests import test_manufacturer_mode_2r1 as t
from tests.test_manufacturer_mode_2r1 import pampers  # noqa: F401  (fixture)
from truesync.channels import mcp as mcp_channel

OUT = os.environ.get("SOA_2U4_RECORD")
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


@pytest.mark.skipif(not OUT, reason="recorder: set SOA_2U4_RECORD")
def test_record(client, db, pampers, monkeypatch):  # noqa: F811
    base = f"/api/truesync/merchants/{SLUG}"
    monkeypatch.setenv(mcp_channel.PUBLIC_URL_ENV, MCP_URL)
    # The public server stand-in serves the tool (tests/fake_mcp.serving, conftest's default).
    _save("publish-dry-run", client.post(f"{base}/publish", params={"dry_run": "true"}))
    _save("publish", client.post(f"{base}/publish"))
    _save("tenant-held", client.get("/api/truesync/tenant"))
    _save("publications-held", client.get("/api/truesync/publications", params={"limit": 1000}))
    _save("channels", client.get("/api/truesync/channels"))
    # A server that answers MCP and does not serve get_product_facts (a stale deploy).
    monkeypatch.setattr(mcp_channel, "client_for", fake_mcp.client_for(fake_mcp.not_serving()))
    _save("publish-not-served", client.post(f"{base}/publish", params={"channels": "mcp"}))
    _save("tenant-held-not-served", client.get("/api/truesync/tenant"))
    # The real transport against a loopback port nothing listens on.
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setattr(mcp_channel, "READBACK_TIMEOUT_SECONDS", 3)
    monkeypatch.setattr(mcp_channel, "client_for", fake_mcp.REAL_CLIENT_FOR)
    monkeypatch.setenv(mcp_channel.PUBLIC_URL_ENV, f"http://127.0.0.1:{port}")
    _save("publish-unreachable", client.post(f"{base}/publish", params={"channels": "mcp"}))
    _save("tenant-held-unreachable", client.get("/api/truesync/tenant"))
