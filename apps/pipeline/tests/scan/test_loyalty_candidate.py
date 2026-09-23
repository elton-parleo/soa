"""
Loyalty-candidate fix (Loreal, request 139): "member" matched the href
/en/groupe/governance-and-ethics/comex-members/ — a corporate board page
whose visible text is "Executive Committee" — and member value then
scored 5/5 on a site with no program at all.

"member", "plus" and "circle" now count only in a link's visible text,
as whole words; "reward", "loyalty", "perk" and "insider" still match
text or href. And no loyalty page is sampled at all without at least
one of site_typing's commerce signals — a brand-only site has no
program to score.
"""
from scan import discovery
from scan.discovery import (
    LOYALTY_LINK_KEYWORDS,
    LOYALTY_TEXT_WORD_KEYWORDS,
    _find_links_by_keyword,
    _has_commerce_signal,
)
from scan.fetcher import FetchResult

BASE = "https://www.example.com"

# The real Loreal homepage link, as served (text and href).
LOREAL_HOMEPAGE = (
    "<html><body><nav>"
    "<a href='/en/groupe/governance-and-ethics/comex-members/'>Executive Committee</a>"
    "<a href='/en/articles/science-and-technology/'>Science</a>"
    "</nav></body></html>"
)
ULTA_HOMEPAGE = (
    "<html><body><nav>"
    "<a href='/bag'>Bag</a>"
    "<a href='/brand/plusone'>Plus One</a>"
    "</nav></body></html>"
)


def _loyalty_links(html):
    return _find_links_by_keyword(html, BASE, LOYALTY_LINK_KEYWORDS, text_word_keywords=LOYALTY_TEXT_WORD_KEYWORDS)


def _robots(html="User-agent: *\n"):
    return FetchResult(url=f"{BASE}/robots.txt", status="fetched", html=html)


# ─── keyword matching ───────────────────────────────────────────────────

def test_loreal_board_page_is_not_a_loyalty_link():
    assert _loyalty_links(LOREAL_HOMEPAGE) == []


def test_ulta_plus_one_link_still_is():
    assert _loyalty_links(ULTA_HOMEPAGE) == [f"{BASE}/brand/plusone"]


def test_member_plus_circle_only_as_whole_words_in_visible_text():
    html = (
        "<a href='/join'>Become a Member</a>"            # whole word in text -> yes
        "<a href='/plusone-offers'>Offers</a>"           # only in href -> no
        "<a href='/about'>Encircled by nature</a>"       # substring, not a word -> no
        "<a href='/club'>Beauty Circle</a>"              # whole word -> yes
    )
    assert _loyalty_links(html) == [f"{BASE}/join", f"{BASE}/club"]


def test_unambiguous_keywords_still_match_the_href():
    html = "<a href='/rewards'>Earn with us</a><a href='/x'>Our Insider program</a>"
    assert _loyalty_links(html) == [f"{BASE}/rewards", f"{BASE}/x"]


def test_shipping_link_matching_is_unchanged():
    html = "<a href='/help/shipping-policy'>Help</a>"
    assert _find_links_by_keyword(html, BASE, discovery.SHIPPING_LINK_KEYWORDS) == [f"{BASE}/help/shipping-policy"]


# ─── the commerce-signal gate ───────────────────────────────────────────

def test_brand_only_homepage_has_no_commerce_signal():
    assert _has_commerce_signal(LOREAL_HOMEPAGE, _robots(), [], []) is False


def test_cart_link_is_a_commerce_signal():
    assert _has_commerce_signal(ULTA_HOMEPAGE, _robots(), [], []) is True


def test_homepage_offer_markup_is_a_commerce_signal():
    html = (
        "<html><head><script type='application/ld+json'>"
        '{"@context":"https://schema.org","@type":"Product","name":"Kit",'
        '"offers":{"@type":"Offer","price":"20.00","priceCurrency":"USD"}}'
        "</script></head><body></body></html>"
    )
    assert _has_commerce_signal(html, _robots(), [], []) is True


def test_sitemap_product_paths_are_a_commerce_signal():
    assert _has_commerce_signal(LOREAL_HOMEPAGE, _robots(), [f"{BASE}/products/kit"], []) is True


# ─── end to end through discover_pages ──────────────────────────────────

def _discover_with(monkeypatch, homepage_html):
    import socket

    import httpx

    from scan import fetcher

    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    def fake_get(self, url, headers=None):
        if url.endswith("/robots.txt"):
            return httpx.Response(200, text="User-agent: *\n", request=httpx.Request("GET", url))
        return httpx.Response(404, text="", request=httpx.Request("GET", url))
    monkeypatch.setattr(httpx.Client, "get", fake_get)

    homepage = FetchResult(url=BASE, status="fetched", html=homepage_html, http_status=200, final_url=BASE)
    return discovery.discover_pages(BASE, fetcher.FetchBudget(), homepage_fetch=homepage)


def test_loreal_shaped_homepage_yields_no_loyalty_candidate(monkeypatch):
    result = _discover_with(monkeypatch, LOREAL_HOMEPAGE)
    assert not [c for c in result.candidates if c.kind == "loyalty"]


def test_ulta_shaped_homepage_yields_its_plus_one_link(monkeypatch):
    result = _discover_with(monkeypatch, ULTA_HOMEPAGE)
    loyalty = [c.url for c in result.candidates if c.kind == "loyalty"]
    assert loyalty == [f"{BASE}/brand/plusone"]
