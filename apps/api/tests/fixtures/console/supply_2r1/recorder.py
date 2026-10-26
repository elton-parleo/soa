"""TEMPORARY (soa 2R-2a): record #33's responses for soa's fixture. Not committed to supply.

SOA_2R2_RECORD=<dir> SOA_2R2_SENT_AT=<iso> pytest tests/test_zz_record_2r2.py
"""
import base64
import json
import os

import pytest

from tests import test_manufacturer_mode_2r1 as t
from tests.test_manufacturer_mode_2r1 import pampers  # noqa: F401  (fixture)

OUT = os.environ.get("SOA_2R2_RECORD")
SENT_AT = os.environ.get("SOA_2R2_SENT_AT", "2026-10-17T15:30:00Z")
SLUG = t.SLUG


def _save(name, response, *, raw=False):
    os.makedirs(OUT, exist_ok=True)
    keep = {k: v for k, v in response.headers.items()
            if k.lower().startswith("x-truesync-") or k.lower() in ("content-type", "content-disposition")}
    entry = {"status": response.status_code, "headers": keep}
    if raw:
        entry["body_base64"] = base64.b64encode(response.content).decode()
    else:
        entry["body"] = response.json()
    with open(os.path.join(OUT, f"{name}.json"), "w") as fh:
        json.dump(entry, fh, indent=1, sort_keys=True)


@pytest.mark.skipif(not OUT, reason="recorder: set SOA_2R2_RECORD")
def test_record(client, db, pampers):  # noqa: F811
    base = f"/api/truesync/merchants/{SLUG}"
    _save("tenant-before", client.get("/api/truesync/tenant"))
    _save("publish-dry-run", client.post(f"{base}/publish", params={"dry_run": "true"}))
    _save("publish", client.post(f"{base}/publish"))
    _save("tenant-held", client.get("/api/truesync/tenant"))
    _save("publications-held", client.get("/api/truesync/publications", params={"limit": 1000}))
    _save("rules", client.get(f"{base}/rules"))
    _save("reference", client.get(f"{base}/reference"))
    _save("retailer-prices", client.get(f"{base}/retailer-prices"))
    _save("catalog", client.get(f"{base}/catalog"))
    _save("feed", client.get(f"{base}/feed"))
    _save("retailers", client.get(f"{base}/retailers"))
    _save("channels", client.get("/api/truesync/channels"))
    _save("artifact-manufacturer_center", client.get(f"{base}/artifacts", params={"channel": "manufacturer_center"}),
          raw=True)
    _save("artifact-acp", client.get(f"{base}/artifacts", params={"channel": "acp"}))
    first_mc = next(r for r in client.get("/api/truesync/publications", params={"limit": 1000}).json()
                    if r["record_ref"].startswith(f"feed:{SLUG}:") and r["channel_slug"] == "manufacturer_center")
    _save("artifact-publication", client.get(f"/api/truesync/publications/{first_mc['id']}/artifact"), raw=True)
    _save("rule-put-r4", client.put(f"{base}/rules/r4", json={"approval": "approved", "actor": "op@test",
                                                             "note": "Legal signed Oct 24"}))
    _save("rules-after-put", client.get(f"{base}/rules"))
    _save("sent-acp-409", client.post(f"{base}/publications/sent", json={
        "channel": "acp", "sent_at": SENT_AT, "stated_by": "P&G content team", "actor": "op@test"}))
    _save("sent", client.post(f"{base}/publications/sent", json={
        "channel": "manufacturer_center", "sent_at": SENT_AT, "stated_by": "P&G content team",
        "actor": "alice@test", "note": "uploaded in Manufacturer Center"}))
    _save("tenant-sent", client.get("/api/truesync/tenant"))
    _save("publications-sent", client.get("/api/truesync/publications", params={"limit": 1000}))
    # the brand pages #33's harness stores on its reads: supply's brand_page.read over the recorded pampers.com
    # pages (tests/fixtures/reads/pampers-2026-10-20); no route above serves them for this merchant
    with open(os.path.join(OUT, "brand-pages.json"), "w") as fh:
        json.dump({k: {"url": t._read_row(k)["url"], "observed_at": t._read_row(k)["observed_at"],
                       "brand_page": t._page(k)} for k in t.PAGES}, fh, indent=1, sort_keys=True)
    # put r4 back, as the test harness leaves it
    client.put(f"{base}/rules/r4", json={"approval": "needs_approval", "actor": "op@test"})
