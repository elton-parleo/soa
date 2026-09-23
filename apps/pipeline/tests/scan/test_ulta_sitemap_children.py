"""
Ulta follow-up (request 141): Ulta's sitemap index lists 23 children
and its product child is just "p.xml" — named after its /p/ PDP path,
with nothing _PRODUCT_FILENAME_HINTS could match. The sampler spent its
child-probe allowance on discover, company, shop and guestservices and
stopped; only the homepage tier rescued the run.

A child whose filename stem is exactly a PDP path prefix is now a
product hint for ORDERING. The fixture below is Ulta's real child list
(www.ulta.com/sitemap/index.xml, 2026-09-23), in its declared order —
and, as the live smoke showed, p.xml is itself a <sitemapindex> of
p-0.xml … p-27.xml, so a product-hinted nested index now has its own
children probed next.
"""
import socket

import httpx
import pytest

from scan import engine, fetcher
from scan.discovery import _product_hinted_for_ordering, _reorder_children_by_product_hint

ORIGIN = "https://www.ulta.com"

ULTA_CHILDREN = [
    f"{ORIGIN}/sitemap/{name}.xml" for name in (
        "discover", "company", "shop", "guestservices", "beautyservices", "p", "brand",
        "stores", "promotion", "search", "rewards", "account",
        "discover/wellness", "discover/makeup", "discover/skin", "discover/hair",
        "discover/lifestyle", "discover/beauty-education", "discover/body", "discover/fragrance",
        "home", "community", "store-events",
    )
]

PDP_HTML = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@type": "Product", "name": "Lipstick",
 "offers": {"@type": "Offer", "price": "24.00", "priceCurrency": "USD", "availability": "https://schema.org/InStock"}}
</script></head><body><nav><a href="/">Home</a></nav><h1>Lipstick</h1></body></html>"""

HOMEPAGE_HTML = (
    "<html><body><nav><a href='/bag'>Bag</a></nav><p>Beauty for every routine — "
    "plenty of real homepage copy here, well past the short-body heuristic.</p></body></html>"
)


def _sitemapindex(*locs):
    return (
        '<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in locs) + "</sitemapindex>"
    )


def _urlset(*locs):
    return (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{u}</loc></url>" for u in locs) + "</urlset>"
    )


@pytest.fixture(autouse=True)
def reset_fetch_state(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    fetcher._domain_seen.clear()
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    yield
    fetcher._last_fetch_at.clear()


def test_ulta_p_xml_is_ordered_first():
    ordered = _reorder_children_by_product_hint(ULTA_CHILDREN)
    assert ordered[0] == f"{ORIGIN}/sitemap/p.xml"
    # Everything else keeps its declared order behind it.
    assert ordered[1:] == [u for u in ULTA_CHILDREN if not u.endswith("/p.xml")]


@pytest.mark.parametrize("name, hinted", [
    ("p.xml", True), ("t.xml", True), ("ip.xml", True), ("dp.xml", True), ("pd.xml", True),
    ("pdp.xml", True), ("products.xml", True), ("product.xml.gz", True), ("p.xml.gz", True),
    # A stem only counts when it IS the prefix — never a word that starts with one.
    ("promotion.xml", False), ("pages.xml", False), ("sitemap-p1.xml", False),
    ("tips.xml", False), ("shop.xml", False), ("discover.xml", False),
])
def test_pdp_stem_hint_is_exact(name, hinted):
    assert _product_hinted_for_ordering(f"{ORIGIN}/sitemap/{name}") is hinted


def test_the_hotfix_5_decoy_is_still_never_promoted():
    children = [
        f"{ORIGIN}/sitemap-c.xml",
        f"{ORIGIN}/sitemap-product-questions.xml",
    ]
    assert _reorder_children_by_product_hint(children) == children


def _ulta_server(requested, p_xml_is_index=True, p_name="p"):
    def fake_get(self, url, headers=None):
        requested.append(url)
        if url.endswith("/robots.txt"):
            body = f"User-agent: *\nSitemap: {ORIGIN}/sitemap/index.xml\n"
        elif url.endswith("/sitemap/index.xml"):
            children = [u.replace("/sitemap/p.xml", f"/sitemap/{p_name}.xml") for u in ULTA_CHILDREN]
            body = _sitemapindex(*children)
        elif url.endswith(f"/sitemap/{p_name}.xml"):
            body = (
                _sitemapindex(*(f"{ORIGIN}/sitemap/{p_name}-{i}.xml" for i in range(28)))
                if p_xml_is_index
                else _urlset(f"{ORIGIN}/p/lipstick-pimprod1", f"{ORIGIN}/p/mascara-pimprod2")
            )
        elif url.endswith(f"/sitemap/{p_name}-0.xml"):
            body = _urlset(f"{ORIGIN}/p/lipstick-pimprod1", f"{ORIGIN}/p/mascara-pimprod2")
        elif url.startswith(f"{ORIGIN}/sitemap/"):
            body = _urlset(f"{ORIGIN}/discover/article-{len(requested)}")
        elif "/p/" in url:
            body = PDP_HTML
        elif url == ORIGIN:
            body = HOMEPAGE_HTML
        else:
            return httpx.Response(404, text="", request=httpx.Request("GET", url))
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))
    return fake_get


def _children_probed(result):
    return [
        c["url"] for c in result.dimensions["sitemap_sampling"]["children_probed"]
        if c["url"] != f"{ORIGIN}/sitemap/index.xml"
    ]


def test_ulta_scan_probes_p_xml_first_then_its_own_children(monkeypatch):
    requested = []
    monkeypatch.setattr(httpx.Client, "get", _ulta_server(requested))

    result = engine.run_scan(ORIGIN)

    assert _children_probed(result)[:2] == [f"{ORIGIN}/sitemap/p.xml", f"{ORIGIN}/sitemap/p-0.xml"]
    assert result.dimensions["discovery_path"] == "sitemap"
    assert result.dimensions["sitemap_sampling"]["child_chosen"] == f"{ORIGIN}/sitemap/p-0.xml"
    assert result.dimensions["discovery_outcome"]["code"] == "product_pages_read"


def test_a_flat_p_xml_is_chosen_directly(monkeypatch):
    requested = []
    monkeypatch.setattr(httpx.Client, "get", _ulta_server(requested, p_xml_is_index=False))

    result = engine.run_scan(ORIGIN)

    assert _children_probed(result)[0] == f"{ORIGIN}/sitemap/p.xml"
    assert result.dimensions["sitemap_sampling"]["child_chosen"] == f"{ORIGIN}/sitemap/p.xml"


def test_an_unhinted_nested_index_is_still_not_descended(monkeypatch):
    """The descent is for a product-hinted nested index only. Renamed
    to "q", the same nested index is skipped like any other — its
    children are never probed."""
    requested = []
    monkeypatch.setattr(httpx.Client, "get", _ulta_server(requested, p_name="q"))

    result = engine.run_scan(ORIGIN)

    assert f"{ORIGIN}/sitemap/q-0.xml" not in _children_probed(result)
