"""
Block evidence (fetcher hardening): the facts that answer "who refused
us?" on a blocked fetch. The export of every status='blocked' scan row
showed a Cloudflare block, an Akamai "Access Denied" page and a
client-rendered app shell all looking identical after the fact — the
fetcher computed a reason string for each and then dropped it, and no
response headers were captured anywhere.

Same mocking pattern as test_fetcher.py's A3 section: socket.getaddrinfo
and httpx.Client.get are monkeypatched, real httpx.Response objects are
built, and tests/conftest.py's autouse fixture has already zeroed the
retry-ladder sleeps.
"""
import socket

import httpx
import pytest

from scan import engine, fetcher

_AKAMAI_BODY = (
    "<html><head><title>Access Denied</title></head>"
    "<body>You don't have permission... Reference #18.abc</body></html>"
)


def _fake_addrinfo(ip="93.184.216.34"):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


@pytest.fixture(autouse=True)
def reset_politeness_state(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    monkeypatch.setattr(fetcher, "SCAN_FETCH_RETRIES", 1)
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo())
    yield
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()


def _mock_response(monkeypatch, status_code, *, text="", headers=None):
    def fake_get(self, url, headers=None, **kw):
        return httpx.Response(status_code, text=text, headers=_mock_response.headers,
                              request=httpx.Request("GET", url))

    _mock_response.headers = headers or {}
    monkeypatch.setattr(httpx.Client, "get", fake_get)


# ─── per-response evidence ───────────────────────────────────────────────

def test_akamai_403_records_vendor_title_excerpt_and_cookie_names_only(monkeypatch):
    _mock_response(
        monkeypatch, 403, text=_AKAMAI_BODY,
        headers={"Server": "AkamaiGHost", "Set-Cookie": "_abck=secret; Path=/"},
    )

    result = fetcher.fetch("https://walled.example.com/products/thing")

    assert result.status == fetcher.BLOCKED
    assert result.error == "HTTP 403"
    assert result.response_headers["server"] == "AkamaiGHost"
    assert result.set_cookie_names == ["_abck"]
    assert result.title == "Access Denied"
    assert "Reference #18.abc" in result.body_excerpt
    assert result.edge_vendor_hint == "akamai"


def test_a_cookie_value_never_survives_anywhere_on_the_result(monkeypatch):
    """A Set-Cookie value is a bearer token by construction — names only,
    and nothing else on the result may smuggle the value through either."""
    _mock_response(
        monkeypatch, 403, text=_AKAMAI_BODY,
        headers={"Server": "AkamaiGHost", "Set-Cookie": "_abck=secret; Path=/"},
    )

    result = fetcher.fetch("https://walled.example.com/products/thing")

    assert "secret" not in repr(result)


def test_cloudflare_403_is_hinted_from_server_header_and_cf_ray(monkeypatch):
    _mock_response(
        monkeypatch, 403, text="<html><body>blocked</body></html>",
        headers={"Server": "cloudflare", "cf-ray": "8abc123def456-LHR"},
    )

    result = fetcher.fetch("https://cf.example.com/")

    assert result.edge_vendor_hint == "cloudflare"
    assert result.response_headers["cf-ray"] == "8abc123def456-LHR"


def test_a_plain_429_gets_a_body_excerpt_but_no_vendor_hint(monkeypatch):
    """No vendor fingerprint is not a vendor named on a guess — an
    unattributed refusal stays unattributed."""
    _mock_response(monkeypatch, 429, text="Too Many Requests")

    result = fetcher.fetch("https://plain.example.com/")

    assert result.status == fetcher.BLOCKED
    assert result.body_excerpt == "Too Many Requests"
    assert result.edge_vendor_hint is None


def test_a_fetched_page_records_its_title_but_never_its_body(monkeypatch):
    """include_excerpt is False on the 'fetched' path: a real product
    page's own content is never stored in a scan row."""
    body = (
        "<html><head><title>Blue Widget — Acme</title></head>"
        "<body><h1>Blue Widget</h1><p>" + ("a real product page " * 20) + "</p></body></html>"
    )
    _mock_response(monkeypatch, 200, text=body)

    result = fetcher.fetch("https://shop.example.com/products/blue-widget")

    assert result.status == fetcher.FETCHED
    assert result.title == "Blue Widget — Acme"
    assert result.body_excerpt is None


def test_a_response_with_nothing_to_record_yields_empty_containers_not_none(monkeypatch):
    _mock_response(monkeypatch, 403, text="nope")

    result = fetcher.fetch("https://bare.example.com/")

    # httpx synthesizes a content-type for a text= response, and
    # content-type is legitimately allowlisted — everything else here
    # is genuinely absent, and comes back as empty containers rather
    # than None so a reader never has to handle both.
    assert set(result.response_headers) == {"content-type"}
    assert result.set_cookie_names == []
    assert result.title is None


def test_header_values_are_truncated_and_keys_lowercased(monkeypatch):
    _mock_response(monkeypatch, 403, text="nope", headers={"Server": "x" * 500})

    result = fetcher.fetch("https://long.example.com/")

    assert result.response_headers["server"] == "x" * fetcher.RESPONSE_HEADER_VALUE_MAX_CHARS
    assert all(k == k.lower() for k in result.response_headers)


def test_non_allowlisted_headers_are_never_copied(monkeypatch):
    _mock_response(
        monkeypatch, 403, text="nope",
        headers={"Server": "nginx", "Authorization": "Bearer nope", "X-Internal-Route": "abc"},
    )

    result = fetcher.fetch("https://allowlist.example.com/")

    assert "authorization" not in result.response_headers
    assert "x-internal-route" not in result.response_headers
    assert result.response_headers["server"] == "nginx"


# ─── _edge_vendor_hint: pure, ordered, and never raises ──────────────────

@pytest.mark.parametrize("headers,cookies,title,body,expected", [
    ({"server": "cloudflare"}, [], None, None, "cloudflare"),
    ({}, ["cf_clearance"], None, None, "cloudflare"),
    ({}, [], "Just a moment...", None, "cloudflare"),
    ({"server": "akamaighost"}, [], None, None, "akamai"),
    ({}, ["bm_sz"], None, None, "akamai"),
    ({}, [], "Access Denied", "Reference #18.abc", "akamai"),
    ({"x-datadome": "protected"}, [], None, None, "datadome"),
    ({}, ["datadome"], None, None, "datadome"),
    ({"x-px-block": "1"}, [], None, None, "human_px"),
    ({}, ["_pxhd"], None, None, "human_px"),
    ({}, [], "Are you a robot or human?", None, "human_px"),
    ({"x-iinfo": "9-123"}, [], None, None, "imperva"),
    ({}, ["incap_ses_123_456"], None, None, "imperva"),
    ({"x-shopify-stage": "production"}, [], None, None, "shopify"),
    ({}, ["_shopify_y"], None, None, "shopify"),
    ({"server": "nginx"}, ["session"], "Blue Widget", "just a product", None),
])
def test_edge_vendor_hint_markers(headers, cookies, title, body, expected):
    assert fetcher._edge_vendor_hint(headers, cookies, title, body) == expected


def test_edge_vendor_hint_precedence_is_cloudflare_first():
    """Several vendors can fingerprint the same response (a Shopify store
    behind Cloudflare). EDGE_VENDOR_MARKERS' order is the tiebreak."""
    hint = fetcher._edge_vendor_hint(
        {"server": "cloudflare", "x-shopify-stage": "production"}, ["_abck"], None, None,
    )
    assert hint == "cloudflare"
    assert [v for v, _ in fetcher.EDGE_VENDOR_MARKERS] == [
        "cloudflare", "akamai", "datadome", "human_px", "imperva", "shopify",
    ]


def test_edge_vendor_hint_never_raises_on_garbage():
    assert fetcher._edge_vendor_hint(None, None, None, None) is None
    assert fetcher._edge_vendor_hint({}, ["", "=", "no-equals-sign"], 12345, object()) is None
    assert fetcher._edge_vendor_hint({None: None}, [None], None, None) is None


def test_body_excerpt_strips_scripts_styles_and_tags():
    html = (
        "<html><head><style>body{color:red}</style>"
        "<script>var x = 'Access Denied';</script></head>"
        "<body>  <p>Access\n  Denied</p>  </body></html>"
    )
    assert fetcher._body_excerpt(html) == "Access Denied"


def test_body_excerpt_and_title_are_capped():
    long_title = "t" * 400
    html = f"<html><head><title>{long_title}</title></head><body>{'b' * 1000}</body></html>"
    assert len(fetcher._extract_title(html)) == fetcher.TITLE_MAX_CHARS
    assert len(fetcher._body_excerpt(html)) == fetcher.BODY_EXCERPT_MAX_CHARS


def test_title_and_body_excerpt_never_raise_on_empty_input():
    assert fetcher._extract_title(None) is None
    assert fetcher._extract_title("") is None
    assert fetcher._body_excerpt(None) is None
    assert fetcher._body_excerpt("<html></html>") is None


# ─── engine serialization ────────────────────────────────────────────────

def test_fetch_entry_carries_every_block_evidence_key():
    fr = fetcher.FetchResult(
        url="https://walled.example.com/", status="blocked", http_status=403,
        error="HTTP 403", redirect_chain=["https://walled.example.com"],
        response_headers={"server": "AkamaiGHost"}, set_cookie_names=["_abck"],
        title="Access Denied", body_excerpt="Reference #18.abc", edge_vendor_hint="akamai",
        bytes=370,
    )

    entry = engine._fetch_entry(fr)

    assert entry["error"] == "HTTP 403"
    assert entry["redirect_chain"] == ["https://walled.example.com"]
    assert entry["response_headers"] == {"server": "AkamaiGHost"}
    assert entry["set_cookie_names"] == ["_abck"]
    assert entry["title"] == "Access Denied"
    assert entry["body_excerpt"] == "Reference #18.abc"
    assert entry["edge_vendor_hint"] == "akamai"
    # A4's existing keys are untouched.
    assert entry["url"] == "https://walled.example.com/"
    assert entry["http_status"] == 403
    assert entry["bytes"] == 370


def test_fetch_entry_defaults_are_containers_not_none():
    entry = engine._fetch_entry(fetcher.FetchResult(url="https://x.example.com/", status="failed"))
    assert entry["response_headers"] == {}
    assert entry["set_cookie_names"] == []
    assert entry["redirect_chain"] == []
    assert entry["title"] is None


def test_block_evidence_summary_counts_vendors_and_dedupes_titles():
    entries = [
        {"status": "blocked", "edge_vendor_hint": "akamai", "title": "Access Denied", "bytes": 370},
        {"status": "blocked", "edge_vendor_hint": "akamai", "title": "Access Denied", "bytes": 370},
        {"status": "blocked", "edge_vendor_hint": "akamai", "title": "Access Denied", "bytes": 412},
        {"status": "fetched", "edge_vendor_hint": "cloudflare", "title": "Blue Widget", "bytes": 120000},
        {"status": "failed", "edge_vendor_hint": None, "title": None, "bytes": None},
    ]

    summary = engine._block_evidence_summary(entries)

    assert summary["vendor_hints"] == {"akamai": 3, "cloudflare": 1}
    assert summary["blocked_titles"] == ["Access Denied"]
    assert summary["blocked_body_sizes"] == [370, 412]


def test_block_evidence_summary_caps_its_lists():
    entries = [
        {"status": "blocked", "title": f"Denied {i}", "bytes": i} for i in range(20)
    ]
    summary = engine._block_evidence_summary(entries)
    assert len(summary["blocked_titles"]) == engine.BLOCK_EVIDENCE_MAX_TITLES
    assert len(summary["blocked_body_sizes"]) == engine.BLOCK_EVIDENCE_MAX_BODY_SIZES


def test_block_evidence_summary_never_raises_on_garbage():
    empty = {
        "vendor_hints": {}, "blocked_titles": [], "blocked_body_sizes": [],
        # Vendor attribution: always present, never absent — a reader
        # must never have to tell "no vendor recognized" apart from
        # "written before this key existed".
        "dominant_vendor": None,
        # Unreachable-host follow-up: same always-present rule for the
        # DNS fallback, which only ever runs on a blocked/unreachable run.
        "dns_vendor_hint": None, "dns_vendor_record": None,
    }
    assert engine._block_evidence_summary(None) == empty
    assert engine._block_evidence_summary([]) == empty
