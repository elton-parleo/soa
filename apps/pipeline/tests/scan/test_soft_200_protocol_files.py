"""
Soft-200 follow-up (Church & Dwight, request 149): /llms.txt and
/.well-known/mcp.json both answered HTTP 200 with the site's own 14 KB
text/html "404 Something Went Wrong" page. It was harmless there only
because protocol_feed is N/A on a brand-only site; on a commerce site it
scored "/llms.txt present and non-empty" and "MCP endpoint declaration
discoverable".

That page is the SITE's soft-404, not an Imperva challenge (it was
served by IIS behind Imperva, and says so in its own <title>) — so the
fetcher rightly leaves it 'fetched', and the scorer is what decides it
isn't the file. A real challenge interstitial on the same probe still
flips to 'blocked' in the fetcher; both are covered here.
"""
import socket

import httpx
import pytest

from scan import fetcher, scorer
from scan.discovery import PageCandidate
from scan.engine import PageScanData
from scan.fetcher import FetchResult
from scan.site_typing import SITE_TYPE_COMMERCE, SiteTypeResult

COMMERCE = SiteTypeResult(site_type=SITE_TYPE_COMMERCE, reason="x")

# The leading slice of what churchdwight.com actually served, verbatim.
CHURCH_DWIGHT_SOFT_404 = """<!DOCTYPE html>
<html>
  <head>
    <base href="/" />
    <meta name="viewport" content="width=device-width, initial-scale=1" /><meta charset="UTF-8" />
  <meta name="robots" content="noindex" />
  <title>404 Something Went Wrong | Church and Dwight</title>
</head><body>""" + ("<p>corporate page body</p>" * 400) + "</body></html>"

LLMS_TXT = "# Acme\n\n> Acme sells widgets.\n\n## Products\n- [Widgets](https://acme.example.com/widgets)\n"
MANIFEST = '{"capabilities": ["dev.ucp.shopping.discount"], "specVersion": "2025-01"}'


def _probe(kind, body, content_type=None, status="fetched"):
    headers = {"content-type": content_type} if content_type else {}
    fr = FetchResult(url=f"https://acme.example.com/{kind}", status=status, html=body, http_status=200, response_headers=headers)
    return PageScanData(candidate=PageCandidate(url=fr.url, kind=kind), fetch_result=fr, extracted=None)


def _protocol_feed(llms, mcp):
    return scorer.score_f3_protocol_feed_presence([llms, mcp], COMMERCE)


# ─── llms.txt ───────────────────────────────────────────────────────────

def test_html_soft_404_is_not_llms_txt():
    result = _protocol_feed(
        _probe("llms_txt", CHURCH_DWIGHT_SOFT_404, "text/html; charset=utf-8"),
        _probe("mcp_well_known", MANIFEST, "application/json"),
    )
    assert "/llms.txt present and non-empty" not in result.evidence
    assert any(
        line.startswith("could not verify /llms.txt — the path answered with an HTML page") for line in result.evidence
    )


def test_soft_200_is_unverifiable_not_absent():
    """Neither present nor absent: excluded from the scored basis
    exactly like a network failure, so it can neither earn nor lose."""
    soft = _protocol_feed(
        _probe("llms_txt", CHURCH_DWIGHT_SOFT_404, "text/html"),
        _probe("mcp_well_known", MANIFEST, "application/json"),
    )
    network = _protocol_feed(
        _probe("llms_txt", None, status="failed"),
        _probe("mcp_well_known", MANIFEST, "application/json"),
    )
    assert soft.score == network.score
    assert "1 sub-check(s) excluded from scoring — the path didn't serve the file, not counted as absent" in soft.evidence


@pytest.mark.parametrize("content_type", [None, "text/plain", "text/plain; charset=utf-8", "text/markdown"])
def test_a_real_llms_txt_is_present(content_type):
    result = _protocol_feed(_probe("llms_txt", LLMS_TXT, content_type), _probe("mcp_well_known", MANIFEST))
    assert "/llms.txt present and non-empty" in result.evidence


def test_markdown_body_served_as_text_html_is_not_counted():
    result = _protocol_feed(_probe("llms_txt", LLMS_TXT, "text/html"), _probe("mcp_well_known", MANIFEST))
    assert "/llms.txt present and non-empty" not in result.evidence


def test_empty_llms_txt_is_still_checked_and_absent():
    result = _protocol_feed(_probe("llms_txt", "  ", "text/plain"), _probe("mcp_well_known", MANIFEST))
    assert "/llms.txt fetched but empty" in result.evidence


# ─── MCP manifest ───────────────────────────────────────────────────────

def test_html_soft_404_is_not_an_mcp_manifest():
    result = _protocol_feed(
        _probe("llms_txt", LLMS_TXT, "text/plain"),
        _probe("mcp_well_known", CHURCH_DWIGHT_SOFT_404, "text/html; charset=utf-8"),
    )
    assert "MCP endpoint declaration discoverable (well-known path)" not in result.evidence
    assert any(
        line.startswith("could not verify MCP endpoint — the well-known path answered with an HTML page")
        for line in result.evidence
    )


@pytest.mark.parametrize("body", ['["a", "list"]', '"a string"', "not json {{{"])
def test_json_that_is_not_an_object_is_not_a_manifest(body):
    result = _protocol_feed(_probe("llms_txt", LLMS_TXT), _probe("mcp_well_known", body, "application/json"))
    assert "MCP endpoint declaration discoverable (well-known path)" not in result.evidence


def test_a_real_manifest_is_present():
    result = _protocol_feed(_probe("llms_txt", LLMS_TXT), _probe("mcp_well_known", MANIFEST, "application/json"))
    assert "MCP endpoint declaration discoverable (well-known path)" in result.evidence


def test_value_protocols_names_the_soft_200_instead_of_asserting_absence():
    result = scorer.score_value_protocols([_probe("mcp_well_known", CHURCH_DWIGHT_SOFT_404, "text/html")])
    assert result.score == 0.0
    assert result.evidence == [
        "could not verify a protocol profile — the MCP well-known path answered with an HTML page, not a manifest"
    ]


def test_value_protocols_still_scores_a_real_manifest():
    result = scorer.score_value_protocols([_probe("mcp_well_known", MANIFEST, "application/json")])
    assert result.score > 0


def test_value_protocols_absent_manifest_wording_is_unchanged():
    result = scorer.score_value_protocols([_probe("mcp_well_known", None, status="not_found")])
    assert result.evidence == ["no protocol profile found"]


# ─── the fetcher side ───────────────────────────────────────────────────

@pytest.fixture
def served(monkeypatch):
    monkeypatch.setattr(fetcher, "POLITENESS_DELAY_SECONDS", 0)
    fetcher._last_fetch_at.clear()
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )

    def serve(body, content_type="text/html"):
        def fake_get(self, url, headers=None):
            return httpx.Response(
                200, text=body, headers={"content-type": content_type}, request=httpx.Request("GET", url),
            )
        monkeypatch.setattr(httpx.Client, "get", fake_get)
    return serve


def test_a_challenge_interstitial_on_the_llms_probe_is_blocked(served):
    served("<html><head><title>Just a moment...</title></head><body>Checking your browser</body></html>")
    result = fetcher.fetch("https://acme.example.com/llms.txt", max_403_attempts=1)
    assert result.status == "blocked"
    assert result.error.startswith("challenge-page")


def test_a_challenge_interstitial_on_the_mcp_probe_is_blocked(served):
    served("<html><head><title>Attention Required! | Cloudflare</title></head><body></body></html>")
    result = fetcher.fetch("https://acme.example.com/.well-known/mcp.json", max_403_attempts=1)
    assert result.status == "blocked"


def test_a_site_soft_404_is_not_treated_as_a_block(served):
    """Flipping it to 'blocked' would be wrong twice over: nothing
    refused us, and agent_access counts blocked pages against the site."""
    served(CHURCH_DWIGHT_SOFT_404)
    result = fetcher.fetch("https://acme.example.com/llms.txt", max_403_attempts=1)
    assert result.status == "fetched"
    assert result.response_headers.get("content-type") == "text/html"
