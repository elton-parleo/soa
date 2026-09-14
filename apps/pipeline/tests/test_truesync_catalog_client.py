"""
TrueSyncCatalogClient — the read that grounds a study.

The contract worth testing here is the degradation, not the happy path:
each of the four endpoints can fail on its own, and each failure must
cost exactly one thing rather than the snapshot. A TrueSync outage has to
degrade a study to its ungrounded form, never fail the generation job —
fifty good AI-written questions are worth more than a failed job.
"""
import json
import os

import pytest

from clients import truesync_catalog as tc

FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures", "wiggle_and_snug_catalog.json",
)


@pytest.fixture
def payloads():
    with open(FIXTURE_PATH) as fh:
        return json.load(fh)


class FakeClient(tc.TrueSyncCatalogClient):
    """A client whose transport answers from a dict of path -> payload.
    Anything not in the dict answers with the error it was seeded with."""

    def __init__(self, responses, errors=None):
        super().__init__(base_url="https://example.invalid")
        self.responses = responses
        self.errors = errors or {}
        self.calls = []

    def _get(self, path, params=None):
        # Exact paths, not substrings. '/api/truesync/merchants' is a
        # prefix of every other path here, so substring dispatch would
        # answer the catalog read with the merchant list — a fake that
        # lies in exactly the direction the tests are checking.
        self.calls.append(path)
        if path in self.responses:
            return self.responses[path], None
        if path in self.errors:
            return None, self.errors[path]
        return None, f"unstubbed path {path}"


MERCHANTS = "/api/truesync/merchants"
CATALOG = "/api/truesync/merchants/wiggle-and-snug/catalog"
INCENTIVES = "/api/truesync/merchants/wiggle-and-snug/incentives"
HISTORY = "/api/truesync/merchants/wiggle-and-snug/price-history"


def _all(payloads):
    return {
        CATALOG: payloads["catalog"],
        INCENTIVES: payloads["incentives"],
        HISTORY: payloads["price_history"],
        MERCHANTS: payloads["merchants"],
    }


def _without(payloads, path, error):
    """Every endpoint answering except one, which is down."""
    responses = _all(payloads)
    responses.pop(path)
    return FakeClient(responses, errors={path: error})


# ── the happy path ────────────────────────────────────────────────────────

def test_a_full_read_merges_all_four_payloads(payloads):
    client = FakeClient(_all(payloads))
    snapshot = client.snapshot("wiggle-and-snug")

    assert snapshot.available is True
    assert snapshot.brand == "Wiggle & Snug"
    assert snapshot.domain == "trueshopstore.com"
    assert snapshot.variant_count == 19
    assert snapshot.code_count == 2
    assert snapshot.price_history["snug-fit-diapers-s3-small"]


def test_history_is_skipped_when_the_caller_does_not_want_it(payloads):
    """The generation path writes expectations against the CURRENT record
    and has no use for prior values; the scorer reads history at scoring
    time instead."""
    client = FakeClient(_all(payloads))
    snapshot = client.snapshot("wiggle-and-snug", with_history=False)

    assert snapshot.available is True
    assert snapshot.price_history == {}
    assert not any("price-history" in path for path in client.calls)


# ── degradation, one endpoint at a time ───────────────────────────────────

def test_a_missing_catalog_is_the_only_failure_that_fails_the_snapshot(payloads):
    client = FakeClient(
        {}, errors={"/api/truesync/merchants/nobody/catalog": "no TrueSync merchant"},
    )
    snapshot = client.snapshot("nobody")

    assert snapshot.available is False
    assert snapshot.error == "no TrueSync merchant"
    assert snapshot.products == []


def test_a_missing_merchant_list_costs_the_domain_and_nothing_else(payloads):
    """The domain is what a brand_mention expectation cites. The
    vocabulary keeps 'brand named' and 'domain cited' as separate bits
    precisely so one can be absent without taking the other down."""
    client = _without(payloads, MERCHANTS, "502")

    snapshot = client.snapshot("wiggle-and-snug")
    assert snapshot.available is True
    assert snapshot.domain is None
    assert snapshot.variant_count == 19
    assert snapshot.code_count == 2


def test_missing_incentives_leave_the_value_tier_with_nothing_to_build(payloads):
    client = _without(payloads, INCENTIVES, "504")

    snapshot = client.snapshot("wiggle-and-snug")
    assert snapshot.available is True
    assert snapshot.incentives == []
    assert snapshot.code_count == 0
    # The catalog tier is untouched — it does not read incentives.
    assert snapshot.variant_count == 19


def test_missing_history_leaves_staleness_unprovable(payloads):
    """Without a record saying a value was once published we cannot claim
    it was, so a mismatch scores wrong rather than stale — the
    conservative direction and the honest one."""
    client = _without(payloads, HISTORY, "500")

    snapshot = client.snapshot("wiggle-and-snug")
    assert snapshot.available is True
    assert snapshot.price_history == {}


# ── the transport never raises ────────────────────────────────────────────

def test_a_transport_exception_becomes_an_error_string(monkeypatch):
    def boom(*_args, **_kwargs):
        raise OSError("connection reset")

    monkeypatch.setattr(tc.httpx, "get", boom)
    client = tc.TrueSyncCatalogClient(base_url="https://example.invalid")

    payload, error = client._get("/api/truesync/merchants")
    assert payload is None
    assert "connection reset" in error


def test_a_404_says_the_merchant_is_not_there_rather_than_returning_empty(monkeypatch):
    class Response:
        status_code = 404
        text = "Not Found"

    monkeypatch.setattr(tc.httpx, "get", lambda *a, **k: Response())
    client = tc.TrueSyncCatalogClient(base_url="https://example.invalid")

    payload, error = client._get("/api/truesync/merchants/ghost/catalog")
    assert payload is None
    assert "no TrueSync merchant" in error


def test_the_read_carries_no_admin_key(monkeypatch):
    """These are unauthenticated reads on purpose: a generator holding the
    key that gates publishing could also publish."""
    seen = {}

    class Response:
        status_code = 200
        text = "[]"

        @staticmethod
        def json():
            return []

    def capture(url, params=None, timeout=None, **kwargs):
        seen["kwargs"] = kwargs
        return Response()

    monkeypatch.setattr(tc.httpx, "get", capture)
    tc.TrueSyncCatalogClient(base_url="https://example.invalid")._get(
        "/api/truesync/merchants"
    )
    assert "headers" not in seen["kwargs"]
