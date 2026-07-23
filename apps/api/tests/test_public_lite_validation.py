"""
Tests for PublicLiteSubmitRequest and PublicLiteEmailRequest validation —
length bounds, URL/email/injection-shaped rejection, and cross-field
distinctness. Pure Pydantic construction, no DB.
"""
import pytest
from pydantic import ValidationError

from app.schemas import PublicLiteEmailRequest, PublicLiteSubmitRequest


def _submit(**overrides):
    data = dict(brand_name="Acme Co", competitor_names=[], captcha_token="tok")
    data.update(overrides)
    return PublicLiteSubmitRequest(**data)


def test_valid_submission_passes():
    req = _submit(brand_name="Drunk Elephant", competitor_names=["Glossier", "The Ordinary"])
    assert req.brand_name == "Drunk Elephant"
    assert req.competitor_names == ["Glossier", "The Ordinary"]


def test_ampersand_and_apostrophe_and_accents_allowed():
    req = _submit(brand_name="L'Oréal", competitor_names=["Procter & Gamble"])
    assert req.brand_name == "L'Oréal"


def test_brand_name_too_short_rejected():
    with pytest.raises(ValidationError):
        _submit(brand_name="A")


def test_brand_name_too_long_rejected():
    with pytest.raises(ValidationError):
        _submit(brand_name="A" * 81)


def test_brand_name_min_length_boundary_passes():
    req = _submit(brand_name="Ab")
    assert req.brand_name == "Ab"


def test_brand_name_max_length_boundary_passes():
    req = _submit(brand_name="A" * 80)
    assert len(req.brand_name) == 80


def test_brand_name_whitespace_is_trimmed():
    req = _submit(brand_name="  Acme Co  ")
    assert req.brand_name == "Acme Co"


@pytest.mark.parametrize("bad_name", [
    "rival.com",
    "https://rival.com",
    "www.rival.com",
    "check this out example.org today",
])
def test_url_shaped_brand_name_rejected(bad_name):
    with pytest.raises(ValidationError):
        _submit(brand_name=bad_name)


def test_email_shaped_brand_name_rejected():
    with pytest.raises(ValidationError):
        _submit(brand_name="someone@example.com")


@pytest.mark.parametrize("bad_name", [
    "<script>alert(1)</script>",
    "'; DROP TABLE users; --",
    "brand`whoami`",
    "brand{{7*7}}",
    "brand;rm -rf",
])
def test_injection_shaped_brand_name_rejected(bad_name):
    with pytest.raises(ValidationError):
        _submit(brand_name=bad_name)


def test_more_than_two_competitors_rejected():
    with pytest.raises(ValidationError):
        _submit(competitor_names=["A Co", "B Co", "C Co"])


def test_two_competitors_allowed():
    req = _submit(competitor_names=["Riva Co", "Other Co"])
    assert len(req.competitor_names) == 2


def test_zero_competitors_allowed():
    req = _submit(competitor_names=[])
    assert req.competitor_names == []


def test_competitor_matching_brand_case_insensitive_rejected():
    with pytest.raises(ValidationError):
        _submit(brand_name="Acme Co", competitor_names=["ACME CO"])


def test_duplicate_competitors_case_insensitive_rejected():
    with pytest.raises(ValidationError):
        _submit(competitor_names=["Rival Co", "rival co"])


def test_invalid_competitor_name_rejected():
    with pytest.raises(ValidationError):
        _submit(competitor_names=["http://evil.com"])


def test_email_request_accepts_valid_email():
    req = PublicLiteEmailRequest(email="visitor@example.com")
    assert req.email == "visitor@example.com"


@pytest.mark.parametrize("bad_email", ["not-an-email", "missing@tld", "@nodomain.com", ""])
def test_email_request_rejects_invalid_format(bad_email):
    with pytest.raises(ValidationError):
        PublicLiteEmailRequest(email=bad_email)


# ─── store_url ────────────────────────────────────────────────────────────

def test_store_url_omitted_defaults_to_none():
    req = _submit()
    assert req.store_url is None


def test_store_url_blank_string_becomes_none():
    req = _submit(store_url="   ")
    assert req.store_url is None


def test_store_url_accepts_bare_domain_and_adds_scheme():
    req = _submit(store_url="acme.com")
    assert req.store_url == "https://acme.com"


def test_store_url_accepts_https_and_preserves_scheme():
    req = _submit(store_url="http://shop.acme.com")
    assert req.store_url == "http://shop.acme.com"


def test_store_url_strips_path_and_query():
    req = _submit(store_url="https://acme.com/products/widget?ref=ad")
    assert req.store_url == "https://acme.com"


def test_store_url_strips_credentials():
    req = _submit(store_url="https://user:pass@acme.com/")
    assert req.store_url == "https://acme.com"


def test_store_url_preserves_non_default_port():
    req = _submit(store_url="https://acme.com:8443/")
    assert req.store_url == "https://acme.com:8443"


@pytest.mark.parametrize("bad_scheme", ["ftp://acme.com", "javascript://acme.com"])
def test_store_url_rejects_disallowed_scheme(bad_scheme):
    with pytest.raises(ValidationError):
        _submit(store_url=bad_scheme)


@pytest.mark.parametrize("ip_url", [
    "http://10.0.0.5",
    "http://172.16.5.5",
    "http://192.168.1.1",
    "http://127.0.0.1",
    "http://169.254.169.254",       # cloud metadata endpoint
    "http://93.184.216.34",         # a public IP is still rejected — must be a domain
    "http://[::1]",
    "http://[fc00::1]",
])
def test_store_url_rejects_ip_literal_hosts(ip_url):
    with pytest.raises(ValidationError):
        _submit(store_url=ip_url)


@pytest.mark.parametrize("bad_domain", [
    "https://localhost",
    "https://not-a-real-tld-single-label",
    "https://bad_domain!.com",
])
def test_store_url_rejects_non_domain_shaped_hosts(bad_domain):
    with pytest.raises(ValidationError):
        _submit(store_url=bad_domain)


def test_store_url_too_long_rejected():
    with pytest.raises(ValidationError):
        _submit(store_url="https://acme.com/" + "a" * 500)
