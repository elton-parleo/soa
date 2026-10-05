"""
TrueSyncCatalogClient — the read that grounds a study.

The contract worth testing here is the degradation, not the happy path:
each of the four endpoints can fail on its own, and each failure must
cost exactly one thing rather than the snapshot. A TrueSync outage has to
degrade a study to its ungrounded form, never fail the generation job —
fifty good AI-written questions are worth more than a failed job.

The one exception is a refused token (401/403), which raises: see the
module docstring of clients/truesync_catalog.py.
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


class _Response:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = [] if body is None else body
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


def test_every_read_carries_the_tenant_token(monkeypatch):
    """
    Since supply's tenancy step these routes are scoped to one customer and
    refuse a request without its token. Every read sends it.
    """
    seen = []

    def capture(url, params=None, timeout=None, headers=None, **kwargs):
        seen.append((url, headers or {}))
        return _Response(200, [] if url.endswith("/merchants") else {"listings": []})

    monkeypatch.setattr(tc.httpx, "get", capture)
    client = tc.TrueSyncCatalogClient(base_url="https://example.invalid", token="tst_abc_secret")
    client.snapshot("wiggle-and-snug", with_history=True)

    assert {url.rsplit("/", 1)[-1] for url, _ in seen} == {
        "catalog", "merchants", "incentives", "price-history",
    }
    for url, headers in seen:
        assert headers.get("X-TrueSync-Key") == "tst_abc_secret", url


def test_the_token_comes_from_config_by_default(monkeypatch):
    monkeypatch.setattr(tc.config, "TRUESYNC_TENANT_TOKEN", "tst_from_env")
    assert tc.TrueSyncCatalogClient(base_url="https://x.invalid").token == "tst_from_env"


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_token_raises_rather_than_degrading(monkeypatch, status):
    """
    An outage degrades a study to ungrounded; a refusal must not. It is
    true on every retry, and degrading around it would make every study
    ungrounded while reporting success.
    """
    monkeypatch.setattr(tc.httpx, "get", lambda *a, **k: _Response(status, {"detail": "no"}))
    client = tc.TrueSyncCatalogClient(base_url="https://example.invalid", token="tst_abc_secret")

    with pytest.raises(tc.TrueSyncNotAuthorized) as exc:
        client.snapshot("wiggle-and-snug", with_history=False)

    message = str(exc.value)
    assert "Not authorized for this customer" in message
    assert "TrueSync refused TRUESYNC_TENANT_TOKEN" in message
    assert "tst_abc_secret" not in message


def test_a_missing_token_is_named_as_the_cause(monkeypatch):
    seen = {}

    def capture(url, params=None, timeout=None, headers=None, **kwargs):
        seen["headers"] = headers
        return _Response(403, {"detail": "missing or invalid X-TrueSync-Key"})

    monkeypatch.setattr(tc.httpx, "get", capture)
    client = tc.TrueSyncCatalogClient(base_url="https://example.invalid", token="")

    with pytest.raises(tc.TrueSyncNotAuthorized, match="TRUESYNC_TENANT_TOKEN is not set"):
        client.list_merchants()
    assert seen["headers"] == {}


def test_an_outage_still_degrades_rather_than_raising(monkeypatch):
    monkeypatch.setattr(tc.httpx, "get", lambda *a, **k: _Response(503, {"detail": "down"}))
    client = tc.TrueSyncCatalogClient(base_url="https://example.invalid", token="tst_abc_secret")

    snapshot = client.snapshot("wiggle-and-snug", with_history=False)

    assert snapshot.available is False


def test_the_scorer_no_longer_degrades_on_a_refusal():
    """
    Step 1C reverses the earlier choice. Scoring without the catalog does
    not cost nuance, it changes outcomes: no history means a `stale` answer
    scores `wrong`. So the refusal propagates (and fails the cycle; see
    test_customer_tokens_pipeline.py).
    """
    from scoring.expectation_scorer import BrandFactsCache, HistoryCache

    class Refusing:
        def snapshot(self, *_a, **_k):
            raise tc.TrueSyncNotAuthorized("Not authorized for this customer: refused")

    with pytest.raises(tc.TrueSyncNotAuthorized):
        HistoryCache(Refusing()).for_variant("wiggle-and-snug", "v1", study_type="s")
    with pytest.raises(tc.TrueSyncNotAuthorized):
        BrandFactsCache(Refusing()).for_merchant("wiggle-and-snug", study_type="s")


def test_an_outage_still_degrades_in_the_scorer(monkeypatch):
    from scoring.expectation_scorer import HistoryCache

    monkeypatch.setattr(tc.httpx, "get", lambda *a, **k: _Response(503, {"detail": "down"}))
    client = tc.TrueSyncCatalogClient(base_url="https://example.invalid", token="tst_abc_secret")

    assert HistoryCache(client).for_variant("wiggle-and-snug", "v1") is None
