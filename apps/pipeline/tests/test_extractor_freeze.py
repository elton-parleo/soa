"""
The freeze changes, on the rows from seed 5.

Two code changes and then a stop. Both are the same principle the
pipeline has been converging on for four rounds: where the evidence is
disputed or the shape is wrong, take the reading that cannot manufacture
a finding.

  * a span the lexicon and the labeller read differently counts as
    hedged. It is still surfaced, so a human sees it; what it cannot do
    is produce a fabricated verdict while nobody is looking.
  * a codes entry has to look like a code. "10% off" was being compared
    against a published promotion code it could never match.
"""
import json
import pathlib

import pytest

from parser import extraction_postprocess as pp
from parser.span_segmenter import segment
from scoring import brand_direct_classifier as c

BRAND = "Wiggle & Snug"


def record(**kw):
    base = {
        "prices": [], "codes": [], "pack_counts": [], "sizes": [], "gtins": [],
        "member_prices": [], "points": [], "brand_unknown_statement": None,
        "other_brands_named": [], "loyalty_tiers_named": [], "brand_claims": [],
        "sources_cited": [], "recommended_retailers": [],
        "extraction_confident": True, "extraction_note": None,
    }
    base.update(kw)
    return base


def label_all(answer, **kinds):
    out = []
    for span in segment(answer):
        kind, modality = 'none', 'asserted'
        for needle, value in kinds.items():
            if needle.replace('_', ' ') in span['text'].lower():
                kind, modality = value if isinstance(value, tuple) else (value, 'asserted')
                break
        out.append({'span_id': span['id'], 'kind': kind, 'modality': modality})
    return {'spans': out}


def run(answer, labels=None, **kw):
    return pp.apply_labels(
        pp.normalize(record(**kw), answer_text=answer, brand=BRAND,
                     brand_domain="trueshopstore.com"),
        labels if labels is not None else label_all(answer),
        answer_text=answer, brand=BRAND,
    )


# ── (1) a disputed span is hedged ─────────────────────────────────────────

ROW_31 = "It appears that Wiggle & Snug Bum Balm 4 oz has been **discontinued**."
ROW_38 = ("Size 2 generally fits babies from around 12 to 18 lbs, making it a "
          "good fit for a 15 lb baby.")


@pytest.mark.parametrize("answer", [ROW_31, ROW_38])
def test_a_disputed_span_never_reaches_fabricated(answer):
    """Both were scored fabricated. In both the lexicon read a hedge —
    "appears", "generally" — and the labeller read a flat assertion."""
    out = run(answer, labels=label_all(answer, **{answer.split()[1].lower(): ("assertion", "asserted")}))
    (claim,) = out["brand_claims"]
    assert claim["lexicon_hedged"] is True
    assert claim["modality"] == "asserted"
    assert claim["effective_modality"] == "hedged"
    assert pp.asserted_claims(out) == []
    assert c.classify(out, {"type": "brand_mention", "brand": BRAND})[0] != c.FABRICATED


@pytest.mark.parametrize("answer", [ROW_31, ROW_38])
def test_a_disputed_span_is_still_surfaced(answer):
    """Defaulting to hedged decides what the classifier does while it
    waits. It does not decide the question."""
    out = run(answer, labels=label_all(answer, **{answer.split()[1].lower(): ("assertion", "asserted")}))
    (flag,) = [f for f in out["needs_review"] if f.get("lexicon")]
    assert flag["lexicon"] == "hedged"
    assert flag["label"] == "asserted"


def test_a_disputed_unsourced_claim_lands_in_its_own_bucket():
    """Not fabricated, and not nothing. The answer said something
    specific about the brand, did not commit to it, and cited nobody."""
    out = run(ROW_31, labels=label_all(ROW_31, appears=("assertion", "asserted")))
    assert [c["claim"] for c in out["hedged_unsourced"]] == [ROW_31]


def test_a_hedged_claim_with_a_source_is_not_in_that_bucket():
    out = run(ROW_31,
              labels=label_all(ROW_31, appears=("assertion", "asserted")),
              sources_cited=["trueshopstore.com"])
    assert out["hedged_unsourced"] == []


def test_agreement_on_asserted_still_reaches_fabricated():
    """The fail-safe must not disarm the mechanism. Where both readings
    agree the answer committed to something, it still counts."""
    answer = "Wiggle & Snug is a private label brand sold exclusively at Kohl's."
    out = run(answer, labels=label_all(answer, kohl=("assertion", "asserted")))
    (claim,) = out["brand_claims"]
    assert claim["lexicon_hedged"] is False
    assert claim["effective_modality"] == "asserted"
    assert pp.asserted_claims(out) == [claim]
    assert c.classify(out, {"type": "brand_mention", "brand": BRAND})[0] == c.FABRICATED


def test_agreement_on_hedged_is_not_a_disagreement():
    answer = "Wiggle & Snug is possibly a private label brand."
    out = run(answer, labels=label_all(answer, possibly=("assertion", "hedged")))
    assert [f for f in out["needs_review"] if f.get("lexicon")] == []
    assert pp.asserted_claims(out) == []


# ── (1b) list items inherit a hedged lead-in ──────────────────────────────

ROW_40 = ("It's possible that:\n"
          "*   It was a limited-time offer that has since ended.\n"
          "*   The name might have changed.")


def test_list_items_under_a_hedged_lead_in_inherit_it():
    """Each item reads as a flat assertion on its own. The lead-in is
    what makes them possibilities, and it is a line away."""
    spans = segment(ROW_40)
    assert [s["inherits_hedge"] for s in spans] == [False, True, True]


def test_an_inherited_hedge_keeps_an_item_out_of_fabricated():
    out = run(ROW_40, labels=label_all(
        ROW_40, **{"limited-time": ("assertion", "asserted")}))
    (claim,) = out["brand_claims"]
    assert claim["inherits_hedge"] is True
    assert claim["effective_modality"] == "hedged"
    assert pp.asserted_claims(out) == []


def test_a_list_under_a_flat_lead_in_inherits_nothing():
    answer = "Popular alternatives include:\n*   Desitin\n*   Aquaphor"
    assert [s["inherits_hedge"] for s in segment(answer)] == [False, False, False]


def test_the_list_ends_at_the_next_ordinary_line():
    answer = ("It's possible that:\n*   It ended.\n"
              "Wiggle & Snug is sold at Kohl's.\n*   Desitin")
    assert [s["inherits_hedge"] for s in segment(answer)] == [False, True, False, False]


# ── (2) codes must be code-shaped ─────────────────────────────────────────

@pytest.mark.parametrize("code,ok", [
    ("SAVE5", True), ("WELCOME10", True), ("SNUG3", True), ("bc-10", True),
    ("10% off", False), ("10 percent off", False), ("Free shipping", False),
    ("", False), ("A", False), ("x" * 40, False),
])
def test_what_a_code_looks_like(code, ok):
    assert pp.is_code_shaped(code) is ok


def test_row_28_a_discount_description_is_not_a_code():
    """It was in the codes list, compared against a published promotion
    code it could never match, and produced a wrong verdict about a code
    the answer never named."""
    answer = "It generally offers **10% off** your first order."
    out = run(answer, codes=[{"code": "10% off", "value_kind": "percent_off",
                              "value": "10"}])
    assert out["codes"] == []
    assert any("not codes: 10% off" in n for n in out["postprocess"])


def test_a_real_code_survives():
    out = run("Use WELCOME10 at checkout.",
              codes=[{"code": "WELCOME10", "value_kind": "percent_off", "value": "10"}])
    assert [c["code"] for c in out["codes"]] == ["WELCOME10"]


def test_duplicate_codes_collapse():
    out = run("Use SNUG3.", codes=[
        {"code": "SNUG3", "value_kind": "percent_off", "value": "15"},
        {"code": "snug3", "value_kind": "percent_off", "value": "15"},
    ])
    assert len(out["codes"]) == 1


# ── the transcription mismatch is a boundary, not a disagreement ──────────

def test_a_statement_read_to_a_different_boundary_is_not_a_finding():
    """Row 40's needs_review held a "disagreement" between two readings
    of one sentence, one of which was a substring of the other."""
    answer = ('Based on my most recent check, I cannot find a product named '
              'the "Wiggle & Snug Snug-Fit Trial Pack" on their website.')
    out = run(answer,
              brand_unknown_statement='I cannot find a product named the '
                                      '"Wiggle & Snug Snug-Fit Trial Pack" on their website.',
              labels=label_all(answer, **{"cannot find": "unknown_statement"}))
    assert [f for f in out["needs_review"] if f.get("reason", "").startswith("the transcription")] == []


def test_two_genuinely_different_statements_still_disagree():
    answer = ("I cannot verify the Wiggle & Snug trial pack. "
              "Wiggle & Snug sells swaddles and sleepwear.")
    out = run(answer,
              brand_unknown_statement="Wiggle & Snug sells swaddles and sleepwear.",
              labels=label_all(answer, **{"cannot verify": "unknown_statement"}))
    assert [f for f in out["needs_review"] if f.get("reason", "").startswith("the transcription")]
