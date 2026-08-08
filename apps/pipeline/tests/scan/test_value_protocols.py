"""
Stage 25 (Part 3, V1-V4): Value Protocols fixture corpus. Built directly
against PageScanData/FetchResult (like test_price_consistency.py) for
precise control over the MCP well-known page's fetch status and manifest
body — the exact thing this dimension reads.
"""
import json
import re

from scan import scorer
from scan.discovery import PageCandidate
from scan.engine import PageScanData
from scan.fetcher import FetchResult


def _mcp_page(status="fetched", body=None):
    return PageScanData(
        candidate=PageCandidate(url="https://example.com/.well-known/mcp.json", kind="mcp_well_known"),
        fetch_result=FetchResult(url="https://example.com/.well-known/mcp.json", status=status, html=body),
        extracted=None,
    )


FULL_MANIFEST = json.dumps({
    "capabilities": [
        scorer.UCP_DISCOUNT_CAPABILITY, scorer.UCP_LOYALTY_CAPABILITY, scorer.ACP_PROMOTIONS_CAPABILITY,
    ],
    "specVersion": "2025-01",
})


# ─── V1: absent/unresolvable manifest never throws, always scores 0 ──────

def test_no_mcp_page_at_all_scores_zero_with_honest_evidence():
    result = scorer.score_value_protocols([])
    assert result.score == 0.0
    assert result.max == 14
    assert result.evidence == ["no protocol profile found"]


def test_mcp_well_known_not_found_scores_zero():
    result = scorer.score_value_protocols([_mcp_page(status="not_found", body=None)])
    assert result.score == 0.0
    assert result.evidence == ["no protocol profile found"]


def test_mcp_well_known_fetch_failed_scores_zero_never_raises():
    result = scorer.score_value_protocols([_mcp_page(status="failed", body=None)])
    assert result.score == 0.0


def test_empty_body_scores_zero():
    result = scorer.score_value_protocols([_mcp_page(status="fetched", body="   ")])
    assert result.score == 0.0


def test_unparseable_json_body_scores_zero_never_raises():
    """The 'unresolvable spec URL' case in practice: a manifest endpoint
    that resolves to garbage, not valid JSON."""
    result = scorer.score_value_protocols([_mcp_page(status="fetched", body="not json at all {{{")])
    assert result.score == 0.0
    assert result.evidence == ["no protocol profile found"]


def test_non_object_json_body_scores_zero():
    result = scorer.score_value_protocols([_mcp_page(status="fetched", body="[1, 2, 3]")])
    assert result.score == 0.0


# ─── V2/V3, re-weighting session (Part 1): five independent checks ───────
# schema_resolution (3) — capabilities is a list AND specVersion is a
# string, regardless of whether either is a REAL/current value.
# version_currency (3) — specVersion is a string AND in
# CURRENT_SPEC_VERSIONS. capability checks (ucp_discount 3, loyalty 3,
# acp_promotions 2) unchanged in what they test, rebalanced in points.

def test_full_manifest_scores_all_fourteen_points():
    result = scorer.score_value_protocols([_mcp_page(body=FULL_MANIFEST)])
    assert result.score == 14.0
    assert result.max == 14


def test_ucp_discount_alone_scores_resolution_plus_the_capability():
    # capabilities=[ucp] is a real list (+3 resolution); specVersion
    # "2024-01" is a string but not current (+0 currency); ucp matches (+3).
    body = json.dumps({"capabilities": [scorer.UCP_DISCOUNT_CAPABILITY], "specVersion": "2024-01"})
    result = scorer.score_value_protocols([_mcp_page(body=body)])
    assert result.score == 6.0  # 3 (resolution) + 3 (ucp_discount)


def test_loyalty_extension_alone_scores_resolution_plus_the_capability():
    body = json.dumps({"capabilities": [scorer.UCP_LOYALTY_CAPABILITY], "specVersion": "2024-01"})
    result = scorer.score_value_protocols([_mcp_page(body=body)])
    assert result.score == 6.0  # 3 (resolution) + 3 (loyalty_extension)


def test_acp_promotions_alone_scores_resolution_plus_the_capability():
    body = json.dumps({"capabilities": [scorer.ACP_PROMOTIONS_CAPABILITY], "specVersion": "2024-01"})
    result = scorer.score_value_protocols([_mcp_page(body=body)])
    assert result.score == 5.0  # 3 (resolution) + 2 (acp_promotions)


def test_current_version_with_no_capabilities_scores_resolution_and_currency():
    # An empty-but-well-typed capabilities list still resolves (it IS a
    # list) — resolution and currency are both real, distinct facts
    # about this manifest, independent of whether anything is declared.
    body = json.dumps({"capabilities": [], "specVersion": "2025-01"})
    result = scorer.score_value_protocols([_mcp_page(body=body)])
    assert result.score == 6.0  # 3 (resolution) + 3 (currency)


def test_wrong_version_profile_scores_resolution_and_the_capability_not_currency():
    """A manifest that's otherwise well-formed but declares an out-of-date
    or unrecognized specVersion doesn't earn the currency point, even
    though resolution and capabilities themselves still score."""
    body = json.dumps({"capabilities": [scorer.UCP_DISCOUNT_CAPABILITY], "specVersion": "1999-01"})
    result = scorer.score_value_protocols([_mcp_page(body=body)])
    assert result.score == 6.0  # 3 (resolution) + 3 (ucp_discount), not +3 currency
    assert any("out of date" in e or "unrecognized" in e for e in result.evidence)


def test_missing_spec_version_fails_both_resolution_and_currency():
    # specVersion absent entirely -> not a string -> resolution requires
    # BOTH a list AND a string, so it fails too, not just currency.
    body = json.dumps({"capabilities": [scorer.ACP_PROMOTIONS_CAPABILITY]})
    result = scorer.score_value_protocols([_mcp_page(body=body)])
    assert result.score == 2.0  # acp_promotions only


# ─── V2: conservative exact-namespace match, never a substring/prefix ────

def test_a_similar_but_not_exact_capability_string_never_counts():
    body = json.dumps({
        "capabilities": [
            "dev.ucp.shopping.discount.v2", "dev.ucp.shopping.discounts", "dev.ucp.shoppingdiscount",
        ],
        "specVersion": "2025-01",
    })
    result = scorer.score_value_protocols([_mcp_page(body=body)])
    # Resolution and currency both clear (a well-typed, current
    # manifest) — none of the near-miss strings are an exact match for
    # the real capability namespace, so no capability check fires.
    assert result.score == 6.0  # 3 (resolution) + 3 (currency)


def test_capabilities_field_of_the_wrong_type_fails_resolution_not_currency():
    # A bare string isn't a capabilities list -> resolution fails (it
    # needs a real list) -> currency is independent of resolution and
    # still clears on its own.
    body = json.dumps({"capabilities": "dev.ucp.shopping.discount", "specVersion": "2025-01"})
    result = scorer.score_value_protocols([_mcp_page(body=body)])
    assert result.score == 3.0  # currency only


# ─── F3/VP dedup: profile present but no capabilities declared ───────────

def test_f3_scores_presence_while_vp_scores_zero_when_manifest_is_empty():
    """The exact dedup scenario: an MCP well-known endpoint that resolves
    and is genuinely fetchable (F3/protocol_feed sees this as 'MCP
    endpoint declaration discoverable') but declares no capabilities at
    all and no specVersion — value_protocols correctly scores 0 even
    though the underlying page is the same one F3 gave credit for."""
    body = json.dumps({})
    pages = [_mcp_page(body=body)]

    from scan import site_typing
    site_type_result = site_typing.SiteTypeResult(
        site_type=site_typing.SITE_TYPE_COMMERCE, reason="commerce", signals=[],
    )
    f3_result = scorer.score_protocol_feed(pages, site_type_result)
    vp_result = scorer.score_value_protocols(pages)

    assert f3_result.score > 0  # F3 credits MCP endpoint discoverability
    assert vp_result.score == 0.0  # VP credits nothing — no capabilities declared


# ─── Wording discipline: "declares", never "supports" ────────────────────

def test_evidence_and_fix_text_never_says_supports():
    scenarios = [
        None,
        json.dumps({}),
        json.dumps({"capabilities": [scorer.UCP_DISCOUNT_CAPABILITY]}),
        FULL_MANIFEST,
        "not json {{{",
    ]
    for body in scenarios:
        pages = [] if body is None else [_mcp_page(body=body)]
        result = scorer.score_value_protocols(pages)
        haystack = " ".join(result.evidence + [result.fix or "", result.fix_human or ""]).lower()
        assert not re.search(r"\bsupports?\b", haystack), f"'supports' leaked into: {haystack!r}"


def test_source_never_uses_supports_wording_in_the_value_protocols_section():
    """Static grep over the Value Protocols section of scorer.py itself —
    a stronger guard than just checking rendered evidence strings, since
    it also catches the wording rule drifting in a docstring or a future
    edit before it ever reaches a test fixture."""
    import inspect
    source = inspect.getsource(scorer.score_value_protocols)
    assert not re.search(r"\bsupports?\b", source.lower())
