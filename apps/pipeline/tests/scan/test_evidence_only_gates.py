"""
Stage 25 (Part 2, P3): evidence-only upgrades for login-gated price and
popup/email-gated deals — score_price_truth_seen/score_deal_citability_seen
must produce IDENTICAL score/max whether a page has no signal at all or a
gated signal (the whole point: no scoring change), differing only in the
evidence list.
"""
from scan import scorer, site_typing
from scan.discovery import PageCandidate
from scan.engine import PageScanData
from scan.fetcher import FetchResult
from scan.structured_data import ExtractedData, OfferData, ProductData

COMMERCE_SITE = site_typing.SiteTypeResult(
    site_type=site_typing.SITE_TYPE_COMMERCE,
    reason="commerce signals present and product pages sampled",
    signals=["test"],
)


def _page(extracted):
    return PageScanData(
        candidate=PageCandidate(url="https://example.com/products/widget", kind="product"),
        fetch_result=FetchResult(url="https://example.com/products/widget", status="fetched"),
        extracted=extracted,
    )


# ─── Login-gated price: price_truth.seen ──────────────────────────────────

def test_login_gated_price_scores_identically_to_no_price_at_all():
    plain_no_price = _page(ExtractedData(
        products=[ProductData(name="Widget", offers=[OfferData(price=None)])],
    ))
    login_gated = _page(ExtractedData(
        products=[ProductData(name="Widget", offers=[OfferData(price=None)])],
        login_gated_price_text_hits=["sign in to see price"],
    ))

    plain_result = scorer.score_price_truth_seen([plain_no_price], COMMERCE_SITE)
    gated_result = scorer.score_price_truth_seen([login_gated], COMMERCE_SITE)

    assert gated_result.score == plain_result.score
    assert gated_result.max == plain_result.max


def test_login_gated_price_adds_evidence_the_plain_case_lacks():
    plain_no_price = _page(ExtractedData(
        products=[ProductData(name="Widget", offers=[OfferData(price=None)])],
    ))
    login_gated = _page(ExtractedData(
        products=[ProductData(name="Widget", offers=[OfferData(price=None)])],
        login_gated_price_text_hits=["sign in to see price"],
    ))

    plain_result = scorer.score_price_truth_seen([plain_no_price], COMMERCE_SITE)
    gated_result = scorer.score_price_truth_seen([login_gated], COMMERCE_SITE)

    assert not any("login-gated" in e for e in plain_result.evidence)
    assert any("login-gated" in e for e in gated_result.evidence)


def test_login_gated_hit_on_a_page_that_DOES_have_a_price_is_ignored():
    """The gate signal only matters when there's actually no crawlable
    price — a page that both has a structured price AND happens to
    mention "sign in to see price" elsewhere (e.g. for a different,
    unrelated variant) shouldn't get flagged as gated."""
    page = _page(ExtractedData(
        products=[ProductData(name="Widget", offers=[OfferData(price=29.99, price_currency="USD")])],
        visible_prices=[29.99],
        login_gated_price_text_hits=["sign in to see price"],
    ))
    result = scorer.score_price_truth_seen([page], COMMERCE_SITE)
    assert not any("login-gated" in e for e in result.evidence)


# ─── Popup/email-gated deal: deal_citability.seen ─────────────────────────

def test_email_gated_deal_scores_identically_to_no_deal_at_all():
    plain = _page(ExtractedData(products=[ProductData(name="Widget", offers=[OfferData(price=29.99)])]))
    gated = _page(ExtractedData(
        products=[ProductData(name="Widget", offers=[OfferData(price=29.99)])],
        email_gated_deal_text_hits=["enter your email to unlock"],
    ))

    plain_result = scorer.score_deal_citability_seen([plain], COMMERCE_SITE)
    gated_result = scorer.score_deal_citability_seen([gated], COMMERCE_SITE)

    assert gated_result.score == plain_result.score
    assert gated_result.max == plain_result.max


def test_email_gated_deal_adds_evidence_the_plain_case_lacks():
    plain = _page(ExtractedData(products=[ProductData(name="Widget", offers=[OfferData(price=29.99)])]))
    gated = _page(ExtractedData(
        products=[ProductData(name="Widget", offers=[OfferData(price=29.99)])],
        email_gated_deal_text_hits=["enter your email to unlock"],
    ))

    plain_result = scorer.score_deal_citability_seen([plain], COMMERCE_SITE)
    gated_result = scorer.score_deal_citability_seen([gated], COMMERCE_SITE)

    assert not any("email/signup popup" in e for e in plain_result.evidence)
    assert any("email/signup popup" in e for e in gated_result.evidence)
