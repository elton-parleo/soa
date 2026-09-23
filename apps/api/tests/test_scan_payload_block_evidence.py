"""
Block evidence (fetcher hardening): the pipeline now records a lot more
per fetch — the fetcher's own reason string, an allowlisted slice of the
response headers, the names of any cookies the response set, the page
title, a body excerpt and an edge-vendor hint. That is OUR diagnostic
record for reading a blocked run after the fact. None of it is report
content, so build_scan_payload filters pages_fetched back down to the
keys it has always carried publicly before the payload is built.

Direct build_scan_payload tests over a synthetic scan_row tuple — no
database needed; this is about the payload's shape, not persistence.
"""
import json

from app.services.cycle_scoring import (
    PUBLIC_PAGES_FETCHED_KEYS,
    _public_pages_fetched,
    build_scan_payload,
)

_DIAGNOSTIC_ROW = {
    "url": "https://walled.example.com/robots.txt",
    "final_url": "https://walled.example.com/robots.txt",
    "status": "blocked",
    "http_status": 403,
    "attempts": 2,
    "retry_after_seen": None,
    "bytes": 370,
    # Everything below is diagnostic and must never reach the browser.
    "error": "HTTP 403",
    "redirect_chain": ["https://walled.example.com"],
    "response_headers": {"server": "AkamaiGHost", "x-reference-error": "18.abc"},
    "set_cookie_names": ["_abck"],
    "title": "Access Denied",
    "body_excerpt": "You don't have permission... Reference #18.abc",
    "edge_vendor_hint": "akamai",
}

_DIAGNOSTIC_KEYS = (
    "error", "redirect_chain", "response_headers", "set_cookie_names",
    "title", "body_excerpt", "edge_vendor_hint",
)


def _scan_row(status, *, dimensions=None, pages_fetched=None):
    return (
        status, None, False,
        json.dumps(dimensions or {}),
        json.dumps(pages_fetched if pages_fetched is not None else [_DIAGNOSTIC_ROW]),
        None, None, None, "https://walled.example.com",
    )


def test_blocked_row_is_served_without_any_block_evidence_keys():
    payload = build_scan_payload(_scan_row("blocked", dimensions={"degraded_reason": "blocked"}), {})

    served = payload["pages_fetched"][0]
    assert set(served) == set(PUBLIC_PAGES_FETCHED_KEYS)
    for key in _DIAGNOSTIC_KEYS:
        assert key not in served


def test_complete_row_is_filtered_the_same_way():
    """The filter runs before the status branch — a complete run's
    successful fetches carry a title too, and it is just as much ours."""
    payload = build_scan_payload(
        _scan_row("complete", dimensions={"scorer_version": "4"}), {},
    )

    served = payload["pages_fetched"][0]
    assert set(served) == set(PUBLIC_PAGES_FETCHED_KEYS)


def test_the_public_keys_themselves_survive_untouched():
    payload = build_scan_payload(_scan_row("blocked"), {})

    served = payload["pages_fetched"][0]
    assert served["url"] == "https://walled.example.com/robots.txt"
    assert served["status"] == "blocked"
    assert served["http_status"] == 403
    assert served["attempts"] == 2
    assert served["bytes"] == 370
    assert served["retry_after_seen"] is None


def test_no_cookie_name_or_body_excerpt_survives_serialization():
    """Belt-and-braces: the whole serialized payload, not just the row
    dict — nothing may smuggle a refusal page's body through."""
    payload = build_scan_payload(_scan_row("blocked"), {})

    serialized = json.dumps(payload)
    assert "_abck" not in serialized
    assert "AkamaiGHost" not in serialized
    assert "Reference #18.abc" not in serialized


def test_an_old_row_without_the_new_keys_renders_unchanged():
    """Additive-JSON discipline: a pre-block-evidence row has only the
    public keys and must come back exactly as it always has."""
    old_row = {k: _DIAGNOSTIC_ROW[k] for k in PUBLIC_PAGES_FETCHED_KEYS}
    payload = build_scan_payload(_scan_row("blocked", pages_fetched=[old_row]), {})

    assert payload["pages_fetched"] == [old_row]


def test_the_array_length_the_frontend_reads_is_preserved():
    """The three readers (fullAnalysisDerive.js, DiscoveryFinding.jsx,
    AuditsPage.jsx) use pages_fetched for its LENGTH only — filtering
    keys must never drop a row."""
    payload = build_scan_payload(
        _scan_row("blocked", pages_fetched=[_DIAGNOSTIC_ROW] * 4), {},
    )
    assert len(payload["pages_fetched"]) == 4


def test_the_filter_itself_never_raises_on_an_unexpected_shape():
    """Rule 7: the filter degrades rather than raising. (PublicLiteScan
    itself has always required dict rows, so a non-dict row still fails
    validation downstream exactly as it did before this filter existed —
    the filter just never becomes the thing that breaks first.)"""
    assert _public_pages_fetched(None) == []
    assert _public_pages_fetched("not a list") == []
    assert _public_pages_fetched([]) == []
    assert _public_pages_fetched(["legacy", None]) == ["legacy", None]
    assert _public_pages_fetched([{}]) == [{}]


# ─── unreachable-host follow-up: the DNS vendor fallback ────────────────

_UNREACHABLE_ROW = {
    "url": "https://lululemon.example.com/robots.txt", "final_url": "https://lululemon.example.com/robots.txt",
    "status": "failed", "http_status": None, "attempts": 1, "retry_after_seen": None, "bytes": None,
    "error": "timeout: timed out", "retry_http_status": None,
}

_UNREACHABLE_DIMENSIONS = {
    "degraded_reason": "unreachable",
    "discovery_outcome": {
        "code": "unreachable",
        "summary": "your site did not respond to our reader at all — every request timed out before any answer came back",
    },
    "block_evidence": {
        "vendor_hints": {}, "blocked_titles": [], "blocked_body_sizes": [],
        "dominant_vendor": None,
        "dns_vendor_hint": "akamai",
        "dns_vendor_record": "a23-67-33-24.deploy.static.akamaitechnologies.com",
    },
}


def test_unreachable_row_names_the_dns_vendor_and_its_outcome():
    """Lululemon (request 138): nothing answered, so no response carried
    a fingerprint — edge_vendor falls back to the DNS hint."""
    payload = build_scan_payload(
        _scan_row("failed", dimensions=_UNREACHABLE_DIMENSIONS, pages_fetched=[_UNREACHABLE_ROW]), {},
    )
    assert payload["degraded_reason"] == "unreachable"
    assert payload["discovery_outcome"]["code"] == "unreachable"
    assert payload["edge_vendor"] == "akamai"
    # The matched DNS record, like the rest of block_evidence, is ours.
    assert "dns_vendor_record" not in json.dumps(payload)
    assert "retry_http_status" not in payload["pages_fetched"][0]


def test_a_response_fingerprint_outranks_the_dns_hint():
    dimensions = dict(_UNREACHABLE_DIMENSIONS)
    dimensions["degraded_reason"] = "blocked"
    dimensions["block_evidence"] = {**_UNREACHABLE_DIMENSIONS["block_evidence"], "dominant_vendor": "imperva"}
    payload = build_scan_payload(_scan_row("blocked", dimensions=dimensions), {})
    assert payload["edge_vendor"] == "imperva"


def test_a_row_without_the_dns_keys_still_names_nothing():
    """Written before the DNS fallback existed."""
    dimensions = {"degraded_reason": "blocked", "block_evidence": {"dominant_vendor": None}}
    payload = build_scan_payload(_scan_row("blocked", dimensions=dimensions), {})
    assert payload["edge_vendor"] is None
