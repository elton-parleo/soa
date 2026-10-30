"""TEMPORARY (soa 2V-2): record parleo-supply-app's responses for Petco, an externally hosted seller, on the 2V-1
fixture (tests/fixtures/feeds/petco_2v1.csv and petco_2v1_incentives.csv: four SKUs, Autoship with Purina's ladder,
Perks Premier), priced as read on Oct 2 2026. Not committed to supply.

SOA_2V2_RECORD=<dir> pytest tests/test_zz_record_2v2.py
"""
import json
import os

import pytest

from test_seller_offer_2v1 import READ_DAY, _commit_petco, petco, ws  # noqa: F401  (fixtures)
from truesync import offer_path
from truesync.channels import mcp as mcp_channel

OUT = os.environ.get("SOA_2V2_RECORD")
#: Not a real address: the recording's stand-in for the mcp service's public URL.
MCP_URL = "https://mcp.parleo.example"
SLUG = "petco"
#: As the demo's retail mode shows them: s1-s5 on and approved; s6 off, waiting.
ON = ("s1", "s2", "s3", "s4", "s5")


def _save(name, response):
    os.makedirs(OUT, exist_ok=True)
    keep = {k: v for k, v in response.headers.items()
            if k.lower().startswith("x-truesync-") or k.lower() in ("content-type", "content-disposition")}
    try:
        body = response.json()
    except ValueError:
        body = {"bytes": len(response.content)}
    with open(os.path.join(OUT, f"{name}.json"), "w") as fh:
        json.dump({"status": response.status_code, "headers": keep, "body": body}, fh, indent=1, sort_keys=True)


@pytest.mark.skipif(not OUT, reason="recorder: set SOA_2V2_RECORD")
def test_record(client, db, petco, ws, monkeypatch):  # noqa: F811
    base = f"/api/truesync/merchants/{SLUG}"
    monkeypatch.setenv(mcp_channel.PUBLIC_URL_ENV, MCP_URL)
    monkeypatch.setattr(offer_path, "now", lambda: READ_DAY)
    _commit_petco(client, petco, ws)
    _save("rules-seed", client.get(f"{base}/rules"))
    _save("tenant-feed", client.get("/api/truesync/tenant"))
    for code in ON:
        r = client.put(f"{base}/rules/{code}", json={"on": True, "approval": "approved", "actor": "elton@parleo.io"})
        assert r.status_code == 200, r.text
    _save("rules", client.get(f"{base}/rules"))
    for name in ("feed", "catalog", "retailers", "incentives/owned", "price-paths"):
        _save(name.replace("/", "-"), client.get(f"{base}/{name}", params={"as_of": "2026-10-02"}
                                                 if name == "price-paths" else None))
    _save("publish", client.post(f"{base}/publish"))
    _save("tenant-held", client.get("/api/truesync/tenant"))
    _save("publications-held", client.get("/api/truesync/publications", params={"limit": 1000}))
    _save("channels", client.get("/api/truesync/channels"))
    _save("sent", client.post(f"{base}/publications/sent", json={
        "channel": "merchant_center", "sent_at": "2026-10-02T15:42:00Z", "stated_by": "Gabe L.",
        "actor": "elton@parleo.io"}))
    _save("tenant-sent", client.get("/api/truesync/tenant"))
    _save("publications-sent", client.get("/api/truesync/publications", params={"limit": 1000}))
    for channel in ("merchant_center", "deals_api", "deal_directory", "acp"):
        _save(f"artifact-{channel}", client.get(f"{base}/artifacts", params={"channel": channel}))
