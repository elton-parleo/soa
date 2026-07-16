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
