"""
The comparator — Layer 2's deterministic half.

The centre of this file is the five-outcome matrix: every expectation
type against every outcome it can produce. That table is the report's
credibility, because every rate the report publishes is a count of these
verdicts, and a verdict that lands in the wrong bucket is not a rounding
error — it is the report saying something false about an assistant.

Two of the rows are load-bearing beyond arithmetic:

  unscoreable  never folded into wrong. "The assistant was incorrect" and
               "we could not tell what it said" are different facts, and
               merging them inflates the error rate with our own
               extraction failures.

  the wrong-product-attribution case, which the brief names by name: an
               answer that states the right number for the WRONG variant
               has not answered the question, it has stated a number that
               happens to match — and it puts a shopper at the wrong
               shelf while doing it.
"""
import pytest

from scoring import expectation_comparator as cmp
from soa_shared import expected_answers as ea

# The Wiggle & Snug Size 3 small pack: $22.99, 84 count, GTIN
# 884400137609, member price $16.84 at Member+.
#
# attribution / attribution_rivals are exactly what
# catalog_tiers._attribution_hints writes for this variant against the
# real Wiggle & Snug catalog: what tells it apart, and what its eleven
# siblings say that it does not.
SIZE_3_SMALL = {
    'merchant_slug': 'wiggle-and-snug',
    'listing_id': 90,
    'variant_id': 'snug-fit-diapers-s3-small',
    'published_at': '2026-09-04T20:49:40+00:00',
    'attribution': ['Size 3', 'Small Pack', '84'],
    'attribution_rivals': [
        'Size 1', '96', 'Big Pack', '198', 'Size 2', '92', '186', '168',
        'Size 4', '74', '150', 'Size 5', '66', '132', 'Size 6', '58', '116',
    ],
}

# Oldest first, as GET /merchants/{slug}/price-history serves it. The
# last entry is the current record; everything before it is prior.
HISTORY = [
    {'published_at': '2026-07-01T00:00:00+00:00', 'list_price': '19.99', 'member_price': '14.99'},
    {'published_at': '2026-08-15T00:00:00+00:00', 'list_price': '21.49', 'member_price': '15.99'},
    {'published_at': '2026-09-04T20:49:40+00:00', 'list_price': '22.99', 'member_price': '16.84'},
]


def extraction(**overrides):
    base = {
        'prices': [], 'codes': [], 'pack_counts': [], 'gtins': [],
        'member_prices': [], 'points': [],
        'brand_mentioned': False, 'sources_cited': [],
        'extraction_confident': True, 'extraction_note': None,
    }
    base.update(overrides)
    return base


def verdict(expectation, extracted, **kwargs):
    kwargs.setdefault('source_ref', SIZE_3_SMALL)
    return cmp.compare(expectation, extracted, **kwargs)


PRICE = ea.price('22.99')
COUNT = ea.pack_count(84)
GTIN = ea.gtin('884400137609')
CODE = ea.code('SNUG3', 'amount_off', '3.00')
MEMBER = ea.member_price('16.84', 'Member+')
POINTS = ea.points('per_dollar', rate='1.0', program_name='Member Rewards')
BRAND = ea.brand_mention('Wiggle & Snug', 'trueshopstore.com')


# ═══ The five-outcome matrix ══════════════════════════════════════════════
#
# One row per (expectation type x outcome). Read it as the table it is.

MATRIX = [
    # ── price ────────────────────────────────────────────────────────
    ('price/exact', PRICE, extraction(prices=[
        {'amount': '22.99', 'currency': 'USD', 'attributed_product': 'Snug-Fit Size 3 small pack'},
    ]), cmp.EXACT),

    ('price/stale', PRICE, extraction(prices=[
        {'amount': '21.49', 'currency': None, 'attributed_product': 'Snug-Fit Size 3, 84 ct'},
    ]), cmp.STALE),

    ('price/wrong', PRICE, extraction(prices=[
        {'amount': '18.00', 'currency': None, 'attributed_product': 'Snug-Fit Size 3, 84 ct'},
    ]), cmp.WRONG),

    ('price/absent', PRICE, extraction(), cmp.ABSENT),

    ('price/unscoreable', PRICE, extraction(
        extraction_confident=False, extraction_note='answer truncated mid-sentence',
    ), cmp.UNSCOREABLE),

    # ── pack_count ───────────────────────────────────────────────────
    ('pack_count/exact', COUNT, extraction(pack_counts=[
        {'value': 84, 'attributed_product': 'the Size 3 84 ct pack'},
    ]), cmp.EXACT),

    ('pack_count/wrong', COUNT, extraction(pack_counts=[
        {'value': 92, 'attributed_product': 'the Size 3 84 ct pack'},
    ]), cmp.WRONG),

    ('pack_count/absent', COUNT, extraction(), cmp.ABSENT),

    ('pack_count/unscoreable', COUNT, extraction(
        extraction_confident=False, extraction_note='garbled',
    ), cmp.UNSCOREABLE),

    # ── gtin ─────────────────────────────────────────────────────────
    ('gtin/exact', GTIN, extraction(gtins=[
        {'value': '884400137609', 'attributed_product': 'Size 3 small pack'},
    ]), cmp.EXACT),

    ('gtin/wrong', GTIN, extraction(gtins=[
        {'value': '884400528827', 'attributed_product': 'Size 3 small pack'},
    ]), cmp.WRONG),

    ('gtin/absent', GTIN, extraction(), cmp.ABSENT),

    ('gtin/unscoreable', GTIN, extraction(extraction_confident=False), cmp.UNSCOREABLE),

    # ── code ─────────────────────────────────────────────────────────
    ('code/exact', CODE, extraction(codes=[
        {'code': 'snug3', 'value_kind': 'amount_off', 'value': '3'},
    ]), cmp.EXACT),

    ('code/wrong-value', CODE, extraction(codes=[
        {'code': 'SNUG3', 'value_kind': 'amount_off', 'value': '5.00'},
    ]), cmp.WRONG),

    ('code/wrong-code', CODE, extraction(codes=[
        {'code': 'SNUG5', 'value_kind': 'amount_off', 'value': '3.00'},
    ]), cmp.WRONG),

    ('code/absent', CODE, extraction(), cmp.ABSENT),

    ('code/unscoreable', CODE, extraction(extraction_confident=False), cmp.UNSCOREABLE),

    # ── member_price ─────────────────────────────────────────────────
    ('member_price/exact', MEMBER, extraction(member_prices=[
        {'amount': '16.84', 'tier': 'Member+', 'attributed_product': 'Size 3, 84 ct'},
    ]), cmp.EXACT),

    ('member_price/stale', MEMBER, extraction(member_prices=[
        {'amount': '15.99', 'tier': 'Member+', 'attributed_product': 'Size 3, 84 ct'},
    ]), cmp.STALE),

    ('member_price/wrong-tier', MEMBER, extraction(member_prices=[
        {'amount': '16.84', 'tier': 'Member', 'attributed_product': 'Size 3, 84 ct'},
    ]), cmp.WRONG),

    ('member_price/wrong-amount', MEMBER, extraction(member_prices=[
        {'amount': '12.00', 'tier': 'Member+', 'attributed_product': 'Size 3, 84 ct'},
    ]), cmp.WRONG),

    ('member_price/absent', MEMBER, extraction(), cmp.ABSENT),

    ('member_price/unscoreable', MEMBER, extraction(extraction_confident=False),
     cmp.UNSCOREABLE),

    # ── points ───────────────────────────────────────────────────────
    ('points/exact', POINTS, extraction(points=[
        {'value': '1', 'per_dollar': True, 'program': 'the rewards programme'},
    ]), cmp.EXACT),

    ('points/wrong', POINTS, extraction(points=[
        {'value': '3', 'per_dollar': True, 'program': 'Member Rewards'},
    ]), cmp.WRONG),

    ('points/absent', POINTS, extraction(), cmp.ABSENT),

    ('points/unscoreable', POINTS, extraction(extraction_confident=False),
     cmp.UNSCOREABLE),

    # ── brand_mention ────────────────────────────────────────────────
    ('brand_mention/exact', BRAND, extraction(brand_mentioned=True), cmp.EXACT),

    ('brand_mention/absent', BRAND, extraction(brand_mentioned=False), cmp.ABSENT),

    ('brand_mention/unscoreable', BRAND, extraction(
        brand_mentioned=False, extraction_confident=False,
    ), cmp.UNSCOREABLE),
]


@pytest.mark.parametrize(
    'label, expectation, extracted, expected_outcome',
    MATRIX, ids=[row[0] for row in MATRIX],
)
def test_five_outcome_matrix(label, expectation, extracted, expected_outcome):
    result = verdict(expectation, extracted, history=HISTORY,
                     brand_domain='trueshopstore.com')
    assert result.outcome == expected_outcome, f"{label}: {result.reason}"


def test_the_matrix_covers_every_type_and_every_reachable_outcome():
    """A matrix with a hole in it is a bucket nothing is checking."""
    covered = {tuple(row[0].split('/')[0:1]) + (row[3],) for row in MATRIX}
    for kind in ea.EXPECTED_ANSWER_TYPES:
        for outcome in (cmp.EXACT, cmp.ABSENT, cmp.UNSCOREABLE):
            assert (kind, outcome) in covered, f"{kind} has no {outcome} row"
    # `wrong` is unreachable for brand_mention: presence has no wrong
    # value, only present or not. Every other type has one.
    for kind in ea.EXPECTED_ANSWER_TYPES:
        if kind == 'brand_mention':
            continue
        assert (kind, cmp.WRONG) in covered, f"{kind} has no wrong row"


# ═══ The wrong-product-attribution case ═══════════════════════════════════

def test_the_right_number_on_the_wrong_variant_is_wrong_not_exact():
    """
    The case the brief names. $22.99 IS a Wiggle & Snug price — it is the
    Small Pack's — so an answer that says "the Big Pack is $22.99" has
    stated a number that matches and a claim that is false, and it puts a
    shopper at the wrong shelf.
    """
    result = verdict(PRICE, extraction(prices=[
        {'amount': '22.99', 'currency': 'USD',
         'attributed_product': 'Snug-Fit Diapers Size 3 Big Pack (168 ct)'},
    ]), history=HISTORY)

    # Not exact — and not stale either, because it never matched this
    # variant at any publication.
    assert result.outcome == cmp.ABSENT
    assert 'no price for this product' in result.reason


def test_a_price_attributed_to_a_sibling_does_not_rescue_a_missing_answer():
    """Two variants, two prices, one asked about. The sibling's correct
    price must not score the asked-about variant."""
    result = verdict(PRICE, extraction(prices=[
        {'amount': '39.99', 'currency': 'USD',
         'attributed_product': 'Size 3 Big Pack, 168 ct'},
    ]), history=HISTORY)
    assert result.outcome == cmp.ABSENT


def test_an_answer_that_names_both_variants_is_scored_on_the_right_one():
    result = verdict(PRICE, extraction(prices=[
        {'amount': '39.99', 'currency': 'USD', 'attributed_product': 'Size 3 Big Pack, 168 ct'},
        {'amount': '22.99', 'currency': 'USD', 'attributed_product': 'Size 3 Small Pack, 84 ct'},
    ]), history=HISTORY)
    assert result.outcome == cmp.EXACT


def test_an_unattributed_price_is_scored_rather_than_discarded():
    """A response about one product that says "it costs $22.99" has
    attributed that price by context, and refusing to score it would throw
    away the commonest shape of a correct answer."""
    result = verdict(PRICE, extraction(prices=[
        {'amount': '22.99', 'currency': None, 'attributed_product': None},
    ]), history=HISTORY)
    assert result.outcome == cmp.EXACT


def test_a_question_with_no_attribution_hints_is_scored_on_the_number_alone():
    """A source_ref written before attribution hints existed must not
    make every answer wrong for a reason nobody recorded."""
    result = cmp.compare(PRICE, extraction(prices=[
        {'amount': '22.99', 'currency': 'USD', 'attributed_product': 'some other pack'},
    ]), history=HISTORY, source_ref={'variant_id': 'x'})
    assert result.outcome == cmp.EXACT


# ═══ unscoreable is never wrong ═══════════════════════════════════════════

def test_an_unreadable_answer_containing_no_price_is_unscoreable_not_absent():
    """
    Checked before any comparison, deliberately. A garbled answer that
    happens to contain no price would otherwise be recorded as `absent`,
    which is a claim about the assistant made on the strength of our own
    failure to read it.
    """
    result = verdict(PRICE, extraction(
        extraction_confident=False, extraction_note='response was an error page',
    ), history=HISTORY)
    assert result.outcome == cmp.UNSCOREABLE
    assert result.reason == 'response was an error page'


def test_an_unreadable_answer_containing_a_wrong_price_is_still_unscoreable():
    result = verdict(PRICE, extraction(
        prices=[{'amount': '5.00', 'currency': None, 'attributed_product': None}],
        extraction_confident=False,
    ), history=HISTORY)
    assert result.outcome == cmp.UNSCOREABLE


def test_a_confident_reading_of_an_answer_that_said_nothing_is_absent():
    """'The answer said nothing about price' is a real result about the
    assistant; 'we could not read it' is a result about us."""
    result = verdict(PRICE, extraction(extraction_confident=True), history=HISTORY)
    assert result.outcome == cmp.ABSENT


# ═══ Staleness needs history ══════════════════════════════════════════════

def test_without_history_a_prior_value_scores_wrong_not_stale():
    """Without a record saying a value was once published we cannot claim
    it was — the conservative direction and the honest one."""
    result = verdict(PRICE, extraction(prices=[
        {'amount': '21.49', 'currency': None, 'attributed_product': None},
    ]))
    assert result.outcome == cmp.WRONG


def test_stale_records_which_publication_it_matched():
    """Staleness attributable to a specific past publication, not a
    general accusation of being behind."""
    result = verdict(PRICE, extraction(prices=[
        {'amount': '19.99', 'currency': None, 'attributed_product': None},
    ]), history=HISTORY)
    assert result.outcome == cmp.STALE
    assert result.matched_published_at == '2026-07-01T00:00:00+00:00'


def test_stale_prefers_the_most_recent_prior_publication():
    result = verdict(PRICE, extraction(prices=[
        {'amount': '19.99', 'currency': None, 'attributed_product': None},
        {'amount': '21.49', 'currency': None, 'attributed_product': None},
    ]), history=HISTORY)
    assert result.matched_published_at == '2026-08-15T00:00:00+00:00'


def test_the_current_value_is_exact_even_though_it_is_in_the_history():
    result = verdict(PRICE, extraction(prices=[
        {'amount': '22.99', 'currency': None, 'attributed_product': None},
    ]), history=HISTORY)
    assert result.outcome == cmp.EXACT


# ═══ Type-specific rules from the vocabulary ══════════════════════════════

def test_a_currency_the_answer_did_not_state_is_not_a_mismatch():
    """A bare '$22.99' in a USD study is the ordinary way to write it;
    failing it would measure punctuation."""
    result = verdict(PRICE, extraction(prices=[
        {'amount': '22.99', 'currency': None, 'attributed_product': None},
    ]))
    assert result.outcome == cmp.EXACT


def test_a_currency_the_answer_stated_differently_is_a_mismatch():
    result = verdict(PRICE, extraction(prices=[
        {'amount': '22.99', 'currency': 'CAD', 'attributed_product': None},
    ]))
    assert result.outcome == cmp.ABSENT


def test_a_code_is_matched_case_insensitively():
    """Codes are typed by humans and every checkout upper-cases them."""
    result = verdict(CODE, extraction(codes=[
        {'code': '  snug3 ', 'value_kind': 'amount_off', 'value': '3.00'},
    ]))
    assert result.outcome == cmp.EXACT


def test_a_right_code_with_no_stated_value_is_wrong_not_exact():
    """The claim that matters is what a shopper saves, not that the code
    exists."""
    result = verdict(CODE, extraction(codes=[
        {'code': 'SNUG3', 'value_kind': None, 'value': None},
    ]))
    assert result.outcome == cmp.WRONG


def test_a_member_price_with_no_tier_named_is_accepted():
    """'Members pay $16.84' on a brand with one paying tier is a correct
    answer, and there is nothing to disagree with."""
    result = verdict(MEMBER, extraction(member_prices=[
        {'amount': '16.84', 'tier': None, 'attributed_product': 'Size 3, 84 ct'},
    ]))
    assert result.outcome == cmp.EXACT


def test_the_points_programme_name_is_never_compared():
    """Programmes are paraphrased far more freely than tiers are, and
    failing a correct rate over 'the rewards programme' would measure
    paraphrase, not accuracy."""
    result = verdict(POINTS, extraction(points=[
        {'value': '1.0', 'per_dollar': True, 'program': 'their loyalty scheme'},
    ]))
    assert result.outcome == cmp.EXACT


def test_a_fixed_points_total_does_not_satisfy_a_per_dollar_rate():
    result = verdict(POINTS, extraction(points=[
        {'value': '20', 'per_dollar': False, 'program': 'Member Rewards'},
    ]))
    assert result.outcome == cmp.WRONG


# ═══ brand_mention keeps its two bits apart ═══════════════════════════════

def test_the_brand_mention_outcome_is_presence_only():
    """Whether the brand's own domain was cited is a different question,
    and folding it in would lose the source-attribution measure."""
    named_no_domain = verdict(
        BRAND, extraction(brand_mentioned=True, sources_cited=['amazon.com']),
        brand_domain='trueshopstore.com',
    )
    assert named_no_domain.outcome == cmp.EXACT
    assert named_no_domain.domain_cited is False
    assert named_no_domain.source_attribution == 'retailer'


def test_the_domain_bit_is_kept_beside_the_outcome():
    result = verdict(
        BRAND,
        extraction(brand_mentioned=True,
                   sources_cited=['www.trueshopstore.com', 'target.com']),
        brand_domain='trueshopstore.com',
    )
    assert result.outcome == cmp.EXACT
    assert result.domain_cited is True
    assert result.source_attribution == 'brand_domain'


def test_no_sources_at_all_is_its_own_attribution():
    result = verdict(BRAND, extraction(brand_mentioned=True),
                     brand_domain='trueshopstore.com')
    assert result.source_attribution == 'none'
    assert result.domain_cited is False


def test_domain_cited_is_null_when_there_is_no_brand_domain_to_look_for():
    """Not False: we did not fail to find the brand domain, we never had
    one to find."""
    result = verdict(BRAND, extraction(brand_mentioned=True,
                                       sources_cited=['amazon.com']))
    assert result.domain_cited is None


# ═══ Secondary expectations ═══════════════════════════════════════════════

def test_a_volunteered_gtin_is_recorded_as_a_bonus_signal():
    expectation = ea.with_secondary(PRICE, [GTIN])
    result = cmp.compare_with_secondary(
        expectation,
        extraction(
            prices=[{'amount': '22.99', 'currency': 'USD', 'attributed_product': None}],
            gtins=[{'value': '884400137609', 'attributed_product': None}],
        ),
        source_ref=SIZE_3_SMALL, history=HISTORY,
    )
    assert result.outcome == cmp.EXACT
    assert result.secondary == [
        {'type': 'gtin', 'outcome': cmp.EXACT, 'reason': 'stated 884400137609'},
    ]


def test_an_unvolunteered_secondary_is_recorded_as_absent():
    """
    Recorded, not dropped. The report gives each secondary its own column
    with the same rate rules as everything else, and it cannot tell
    "volunteered and got it right nine times out of ten" from
    "volunteered nine times out of a thousand" without a denominator.
    """
    expectation = ea.with_secondary(PRICE, [GTIN])
    result = cmp.compare_with_secondary(
        expectation,
        extraction(prices=[
            {'amount': '22.99', 'currency': 'USD', 'attributed_product': None},
        ]),
        source_ref=SIZE_3_SMALL,
    )
    assert result.outcome == cmp.EXACT
    assert result.secondary == [
        {'type': 'gtin', 'outcome': cmp.ABSENT, 'reason': 'the answer stated no GTIN'},
    ]


def test_a_pack_count_secondary_rides_along_with_the_gtin():
    """One question per variant now carries both, and neither can move
    the price outcome."""
    expectation = ea.with_secondary(PRICE, [GTIN, ea.pack_count(84)])
    result = cmp.compare_with_secondary(
        expectation,
        extraction(
            prices=[{'amount': '22.99', 'currency': 'USD',
                     'attributed_product': 'Size 3 Small Pack'}],
            pack_counts=[{'value': 84, 'attributed_product': 'Size 3 Small Pack'}],
        ),
        source_ref=SIZE_3_SMALL, history=HISTORY,
    )
    assert result.outcome == cmp.EXACT
    assert [(s['type'], s['outcome']) for s in result.secondary] == [
        ('gtin', cmp.ABSENT), ('pack_count', cmp.EXACT),
    ]


def test_a_wrong_pack_count_never_moves_the_price_outcome():
    """An answer with the right price and the wrong count has still
    stated the right price. That separation is the whole reason a
    secondary is secondary."""
    expectation = ea.with_secondary(PRICE, [ea.pack_count(84)])
    result = cmp.compare_with_secondary(
        expectation,
        extraction(
            prices=[{'amount': '22.99', 'currency': 'USD',
                     'attributed_product': 'Size 3 Small Pack'}],
            pack_counts=[{'value': 92, 'attributed_product': 'Size 3 Small Pack'}],
        ),
        source_ref=SIZE_3_SMALL, history=HISTORY,
    )
    assert result.outcome == cmp.EXACT
    assert result.secondary == [{
        'type': 'pack_count', 'outcome': cmp.WRONG,
        'reason': 'stated 92; the record says 84',
    }]


def test_an_absent_pack_count_never_moves_the_price_outcome():
    expectation = ea.with_secondary(PRICE, [ea.pack_count(84)])
    result = cmp.compare_with_secondary(
        expectation,
        extraction(prices=[
            {'amount': '22.99', 'currency': 'USD', 'attributed_product': 'Size 3 Small Pack'},
        ]),
        source_ref=SIZE_3_SMALL, history=HISTORY,
    )
    assert result.outcome == cmp.EXACT
    assert result.secondary[0]['outcome'] == cmp.ABSENT


def test_a_wrong_volunteered_gtin_is_recorded_but_does_not_change_the_outcome():
    expectation = ea.with_secondary(PRICE, [GTIN])
    result = cmp.compare_with_secondary(
        expectation,
        extraction(
            prices=[{'amount': '22.99', 'currency': 'USD', 'attributed_product': None}],
            gtins=[{'value': '000000000000', 'attributed_product': None}],
        ),
        source_ref=SIZE_3_SMALL,
    )
    assert result.outcome == cmp.EXACT
    assert result.secondary[0]['outcome'] == cmp.WRONG


# ═══ Unknown types ════════════════════════════════════════════════════════

def test_an_unknown_expectation_type_is_unscoreable_not_wrong():
    """It is a failure of ours, not the assistant's."""
    result = cmp.compare({'type': 'shipping_speed'}, extraction())
    assert result.outcome == cmp.UNSCOREABLE
