"""
Tests for the challenge-page detection rewrite (hotfix 4): the incident
this fixes was a real ~150KB product page misclassified as a bot-
challenge interstitial because it embedded a grecaptcha script tag and
the old detector matched the bare substring "captcha" ANYWHERE in the
page body. _looks_like_challenge_page is now a conjunction of
independent signals (size gate, scoped signatures, real-content
override) — never a substring-anywhere match — and returns the reason
string directly (None when it's not a challenge) instead of a bare
bool, so FetchResult.error can name which rule fired.

Direct unit tests exercise _looks_like_challenge_page in isolation;
a few integration-level tests go through fetch() itself (httpx mocked)
to confirm the one call site wires the new return shape correctly and
that the untouched 403/429 status-code branches (hotfix 2 plumbing,
out of scope for this stage) still behave exactly as before. The
existing Allbirds root-rate-limited replay (test_scorer.py::
test_incident_replay_root_rate_limited_pdps_read_through_still_scores_
normally, hotfix 3) already covers the "still scores end to end, root
evidence intact" acceptance point — not duplicated here.
"""
import json

import httpx
import pytest

from scan import fetcher


def _fake_addrinfo(ip="93.184.216.34"):
    import socket
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


@pytest.fixture(autouse=True)
def reset_politeness_state(monkeypatch):
    import socket
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _fake_addrinfo())
    yield
    fetcher._last_fetch_at.clear()


def _real_pdp_html(target_bytes=150_000):
    """A real product page: schema.org Product/Offer JSON-LD, an og:type
    meta tag, a <nav>, AND a grecaptcha script tag (the incident's exact
    shape) — padded with plausible filler markup to real PDP size."""
    ld_json = json.dumps({
        "@context": "https://schema.org", "@type": "Product", "name": "Classic Runner",
        "offers": {"@type": "Offer", "price": "98.00", "priceCurrency": "USD", "availability": "https://schema.org/InStock"},
    })
    head = f"""
    <html><head>
      <title>Classic Runner - Acme Shoes</title>
      <meta property="og:type" content="product">
      <meta property="og:title" content="Classic Runner">
      <script type="application/ld+json">{ld_json}</script>
      <script src="https://www.google.com/recaptcha/api.js" async defer></script>
    </head><body>
      <nav><a href="/">Home</a><a href="/products">Shop</a></nav>
      <h1>Classic Runner</h1>
      <div class="g-recaptcha" data-sitekey="abc123"></div>
    """
    filler = "<p>Merino wool upper, recycled laces, machine washable. " * 400
    tail = "</body></html>"
    body = head + filler
    if len(body.encode("utf-8")) < target_bytes:
        body += "<!-- " + ("x" * (target_bytes - len(body.encode("utf-8")))) + " -->"
    return body + tail


def _cloudflare_interstitial_html():
    """A true Cloudflare bot-challenge interstitial — tiny, no product
    markup at all."""
    return """
    <html><head><title>Just a moment...</title></head>
    <body>
      <div class="cf-browser-verification cf-chl-verification">
        <h1>Checking your browser before accessing example.com</h1>
        <p>This process is automatic. Your browser will redirect shortly.</p>
      </div>
    </body></html>
    """


def _captcha_form_html():
    """A small page whose only signal is a scoped CAPTCHA phrase (not
    the dropped bare 'captcha' substring)."""
    return """
    <html><head><title>Verify you are human</title></head>
    <body><p>Please complete the captcha to continue.</p></body></html>
    """


# ─── C1.a: size gate ──────────────────────────────────────────────────

def test_real_pdp_with_recaptcha_and_ld_json_is_never_a_challenge_regardless_of_size():
    """The incident's exact shape: a real, large product page embedding
    a grecaptcha script tag must never be misread as a challenge page."""
    html = _real_pdp_html()
    assert len(html.encode("utf-8")) > fetcher.CHALLENGE_MAX_BYTES
    assert fetcher._looks_like_challenge_page(html) is None


def test_size_gate_wins_even_when_a_signature_is_present():
    """A body over CHALLENGE_MAX_BYTES is NEVER a challenge, even if a
    challenge phrase genuinely appears in the title."""
    big_body = "<html><head><title>Just a moment...</title></head><body>" + ("x" * (fetcher.CHALLENGE_MAX_BYTES + 1000)) + "</body></html>"
    assert fetcher._looks_like_challenge_page(big_body) is None


# ─── C1.c: real-content override ───────────────────────────────────────

def test_real_content_override_wins_even_with_a_signature_and_small_body():
    html = (
        '<html><head><title>Just a moment...</title>'
        '<script type="application/ld+json">{"@type": "Product"}</script>'
        "</head><body>checking your browser</body></html>"
    )
    assert fetcher._looks_like_challenge_page(html) is None


def test_og_type_alone_overrides_a_matching_signature():
    html = '<html><head><title>Just a moment...</title><meta property="og:type" content="website"></head><body></body></html>'
    assert fetcher._looks_like_challenge_page(html) is None


def test_nav_element_alone_overrides_a_matching_signature():
    html = "<html><head><title>Just a moment...</title></head><body><nav>Home</nav></body></html>"
    assert fetcher._looks_like_challenge_page(html) is None


# ─── C1.b: true interstitial detection + scoping ───────────────────────

def test_true_cloudflare_interstitial_is_detected():
    html = _cloudflare_interstitial_html()
    assert len(html.encode("utf-8")) < 4000  # genuinely tiny
    reason = fetcher._looks_like_challenge_page(html)
    assert reason is not None
    assert reason.startswith("challenge-page:")


def test_captcha_phrase_form_is_detected_but_bare_captcha_word_is_not():
    """Dropped bare 'captcha' entirely; 'complete the captcha' is a
    scoped phrase signature instead."""
    assert fetcher._looks_like_challenge_page(_captcha_form_html()) is not None

    bare_captcha_html = (
        "<html><head><title>Sign in</title></head>"
        '<body><img src="captcha.png" alt="captcha"></body></html>'
    )
    assert fetcher._looks_like_challenge_page(bare_captcha_html) is None


def test_signature_beyond_the_scan_window_is_not_detected():
    """A signature appearing after the title and past the first 2KB of
    the body — even in an otherwise-small page — is out of scope and
    must not fire."""
    filler = "<p>Real store copy, nothing suspicious here. " * 100  # pushes past 2KB
    assert len(filler.encode("utf-8")) > fetcher.CHALLENGE_SCAN_BYTES
    html = f"<html><head><title>Store</title></head><body>{filler}checking your browser</body></html>"
    assert len(html.encode("utf-8")) < fetcher.CHALLENGE_MAX_BYTES
    assert fetcher._looks_like_challenge_page(html) is None


def test_thin_but_real_200_with_no_signatures_is_not_a_challenge():
    """A short, genuine page (e.g. a redirect stub) with none of the
    scoped signatures stays fetch-evaluated — the separate, untouched
    MIN_BODY_LENGTH short-body check is what governs pages this thin,
    not the challenge detector."""
    html = "<html><head><title>Redirecting…</title></head><body>One moment.</body></html>"
    assert fetcher._looks_like_challenge_page(html) is None


def test_reason_names_which_rule_fired():
    title_reason = fetcher._looks_like_challenge_page(_cloudflare_interstitial_html())
    assert "title signature" in title_reason

    body_signature_html = "<html><head><title>Store</title></head><body>checking your browser</body></html>"
    body_reason = fetcher._looks_like_challenge_page(body_signature_html)
    assert "body signature" in body_reason


# ─── Integration: through fetch() itself ───────────────────────────────

def test_fetch_returns_fetched_for_the_real_pdp_shape(monkeypatch):
    html = _real_pdp_html()

    def fake_get(self, url, headers=None):
        return httpx.Response(200, text=html, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://example.com/products/classic-runner", check_short_body=True)
    assert result.status == fetcher.FETCHED


def test_fetch_returns_blocked_for_a_true_interstitial_with_the_new_reason(monkeypatch):
    html = _cloudflare_interstitial_html()

    def fake_get(self, url, headers=None):
        return httpx.Response(200, text=html, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://example.com/")
    assert result.status == fetcher.BLOCKED
    assert result.error.startswith("challenge-page:")


def test_fetch_still_blocks_a_403_with_a_captcha_form_body_unchanged(monkeypatch):
    """hotfix 2 plumbing, out of scope and unchanged: a 403 response
    status alone is blocked outright by the existing, untouched status-
    code branch — it never even reaches the challenge-page detector.
    This fixture's shape (403 + small body + a captcha-phrase form)
    still ends up blocked, same as any other 403."""
    html = _captcha_form_html()

    def fake_get(self, url, headers=None):
        return httpx.Response(403, text=html, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = fetcher.fetch("https://example.com/")
    assert result.status == fetcher.BLOCKED
    assert result.http_status == 403


# ─── End-to-end: "request 47" shape (real bodies with recaptcha assets) ─

def test_request_47_shape_scores_normally_end_to_end(monkeypatch):
    """All 200s, large real bodies with recaptcha assets on product
    pages — the run must complete and score normally, not degrade to
    blocked over a false challenge-page match."""
    from scan import engine

    robots_txt = "User-agent: *\nSitemap: https://request47.example.com/sitemap.xml\n"
    sitemap_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://request47.example.com/products/widget-a</loc></url>"
        "<url><loc>https://request47.example.com/products/widget-b</loc></url>"
        "</urlset>"
    )
    homepage_html = _real_pdp_html(target_bytes=120_000)
    product_a_html = _real_pdp_html(target_bytes=140_000)
    product_b_html = _real_pdp_html(target_bytes=130_000)

    def fake_get(self, url, headers=None):
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text=robots_txt, request=httpx.Request("GET", url))
        if url.endswith("/sitemap.xml"):
            return httpx.Response(200, text=sitemap_xml, request=httpx.Request("GET", url))
        if url.endswith("/products/widget-a"):
            return httpx.Response(200, text=product_a_html, request=httpx.Request("GET", url))
        if url.endswith("/products/widget-b"):
            return httpx.Response(200, text=product_b_html, request=httpx.Request("GET", url))
        if "request47.example.com" in url:
            return httpx.Response(200, text=homepage_html, request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    result = engine.run_scan("https://request47.example.com")

    assert result.status == "complete"
    assert result.total_score is not None
    blocked_pages = [p for p in result.pages_fetched if p["status"] == "blocked"]
    assert blocked_pages == []
