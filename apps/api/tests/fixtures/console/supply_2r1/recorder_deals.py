"""TEMPORARY (soa 2T-1): record #33's /deals for soa's fixture. Not committed to supply.

Copied to supply's tests/test_zz_record_2t1.py at 4ec9a8a: SOA_2T1_RECORD=<dir> pytest tests/test_zz_record_2t1.py
"""
import json
import os

import pytest

from tests import test_manufacturer_mode_2r1 as t
from tests.test_manufacturer_mode_2r1 import pampers  # noqa: F401  (fixture)

OUT = os.environ.get("SOA_2T1_RECORD")


@pytest.mark.skipif(not OUT, reason="recorder: set SOA_2T1_RECORD")
def test_record(client, db, pampers):  # noqa: F811
    base = f"/api/truesync/merchants/{t.SLUG}"
    client.post(f"{base}/publish")
    for day in ("2026-10-20", "2026-10-21"):
        r = client.get(f"{base}/deals", params={"as_of": day})
        keep = {k: v for k, v in r.headers.items() if k.lower() in ("content-type",)}
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, f"deals-{day.replace('-', '')}.json"), "w") as fh:
            json.dump({"status": r.status_code, "headers": keep, "body": r.json()}, fh, indent=1, sort_keys=True)
