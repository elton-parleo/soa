"""
2T-4 (1): a store named in prose is not a contradiction of its domain.

FL15's Answers (Oct 26, org 12) showed as High: "Gemini said 'Target' lists
Pampers Swaddlers Size 4 150 count but Pampers' record or pages show
target.com"; "Perplexity said 'You can buy Pampers Pure Protection from:
Amazon'. Pampers' record or pages show 'amazon.com'"; "Claude said 'Walmart -'
for Pampers Swaddlers, Newborn, 84 ct. Pampers' record or pages show
'walmart.com'". On the recorded index the brand-claim verdict already grounds
each sentence (its reason is the "on Pampers' record or pages: 'target.com'"
the lines quote). What made them High was the answer's
`fabricated_availability` flag: the flag read the question's own retailer list
and raised for any store off it, and a raised flag made the answer High
(console_read_models._severity) and a narrative subject beside a grounded
reason (2P-2's shape).

  * one retailer identity (soa_shared/retailers.retailer_key) for the index's
    domains and the claim's words: walmart.com, Walmart, Walmart.com and
    "Walmart -" are one store, and the brand's own site in words is its domain;
  * a store the brand's feed lists grounds; one it does not is unverified,
    never fabricated, and a brand's answer is never flagged
    fabricated_availability (a seller's list, its own site, still is);
  * the three live sentences on 2O-6's served index (supply's reader on its
    recorded pampers.com pages) with the feed's retailers (supply #33's
    recorded /retailers): grounded, and with no flag;
  * on 2Q-1's FL14-shaped where-to-buy fixture: how many answers lose the flag.

The three sentences are the live console's own quotes of the answers; nothing
here is a written model answer, read from production or a model call.
"""
import copy
import json
import os

import pytest

from scoring import answer_flags as af
from scoring import brand_fact_index as bfi
from soa_shared import expected_answers as ea
from soa_shared import retailers as rt
from tests import test_brand_claim_2o5 as t5
from tests import test_brand_claim_2o6 as t6

HERE = os.path.dirname(os.path.abspath(__file__))
WHERE_TO_BUY = json.load(open(os.path.join(HERE, 'fixtures', 'retailer_coding', 'fl14_where_to_buy.json')))
#: supply #33's recorded GET /merchants/pampers-2r1/retailers (apps/api/tests/fixtures/console/supply_2r1)
RETAILERS = json.load(open(os.path.join(HERE, '..', '..', 'api', 'tests', 'fixtures', 'console', 'supply_2r1',
                                        'retailers.json')))['body']
OWN = RETAILERS['own_domains']

#: (question, the sentence as the live console quoted it, the store it names)
FL15_LIVE = (
    ('Where can I buy Pampers Swaddlers Size 4, 150 ct?',
     'Target lists Pampers Swaddlers Size 4 150 count.', 'target.com'),
    ('Where can I buy Pampers Pure Protection?',
     'You can buy Pampers Pure Protection from: Amazon', 'amazon.com'),
    ('Where can I buy Pampers Swaddlers, Newborn, 84 ct?',
     '**Walmart** - Pampers Swaddlers, Newborn, 84 ct', 'walmart.com'),
)


def served_with_the_feeds_retailers():
    """2O-6's served index, with the merchant record's retailer list as supply serves it."""
    facts, reference = t5.pilot()
    facts = {**facts, 'retailer_list': RETAILERS['domains'], 'own_domains': OWN}
    rows = reference['prices'] + copy.deepcopy(t6.PAGES_2O6['prices'])
    return bfi.build(facts, {**reference, 'prices': rows, **{k: t6.PAGES_2O6[k] for k in t6.PAYLOAD}})


# ── one identity ──────────────────────────────────────────────────────────

@pytest.mark.parametrize('written', ['walmart.com', 'Walmart', 'Walmart.com', 'Walmart -', '**Walmart** -',
                                     'https://www.walmart.com/ip/123', 'at Walmart:', 'Walmart store', '1. Walmart'])
def test_every_way_a_store_is_written_is_one_key(written):
    assert rt.retailer_key(written) == 'walmart.com'
    assert rt.same_retailer(written, 'walmart.com')


@pytest.mark.parametrize('written,key', [
    ("BJ's Wholesale Club", 'bjs.com'), ("Sam's Club", 'samsclub.com'), ('Kirkland Signature', 'costco.com'),
    ('Pampers Official Store', 'pampers.com'), ('the Pampers website', 'pampers.com'),
    ('Pampers Swaddlers', None), ('Huggies', None), ('target weight', None),
])
def test_the_lexicon_the_labels_and_the_brands_own_site(written, key):
    assert rt.retailer_key(written, own_domains=OWN, brand='Pampers') == key


def test_the_sync_copies_are_identical():
    import filecmp
    root = os.path.join(HERE, '..', '..', '..')
    assert filecmp.cmp(os.path.join(root, 'apps/api/soa_shared/retailers.py'),
                       os.path.join(root, 'apps/pipeline/soa_shared/retailers.py'), shallow=False)


# ── the fact index ────────────────────────────────────────────────────────

def test_the_index_holds_stores_by_the_one_key():
    idx = served_with_the_feeds_retailers()
    assert {'amazon.com', 'samsclub.com', 'target.com', 'walmart.com', 'pampers.com'} <= idx.retailers
    for written in ('Walmart', 'walmart.com', 'Walmart -'):
        assert bfi.check({'type': 'retailer', 'text': written, 'value': written}, idx)['status'] == bfi.FOUND
    off = bfi.check({'type': 'retailer', 'text': 'kroger.com', 'value': 'kroger.com'}, idx)
    assert off['status'] == bfi.UNVERIFIED and off['slot'] == 'retailers'


@pytest.mark.parametrize('question,sentence,store', FL15_LIVE)
def test_the_live_sentences_are_grounded_on_the_feeds_retailers(question, sentence, store):
    decided = t5.judge(sentence, question, idx=served_with_the_feeds_retailers())
    assert decided['outcome'] == 'grounded', decided['reason']
    span = decided['brand_claim']['spans'][decided['brand_claim']['decided_by']]
    assert {'type': 'retailer', 'text': store} in span['facts_found'] and span['facts_missing'] == []


@pytest.mark.parametrize('question,sentence,store', FL15_LIVE)
def test_a_store_off_the_brands_list_is_unverified_never_fabricated(question, sentence, store):
    """2O-6's index as served (no merchant record list): Target is on no row of it."""
    decided = t5.judge(sentence, question, idx=t6.served())
    assert decided['outcome'] != 'fabricated'
    span = decided['brand_claim']['spans'][decided['brand_claim']['decided_by']]
    assert span['facts_missing'] == []
    if store not in t6.served().retailers:
        assert t5.read(decided) == ea.UNVERIFIED


# ── the flag ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('question,sentence,store', FL15_LIVE)
def test_a_brands_answer_is_never_flagged_for_a_store(question, sentence, store):
    mentions = [{'name': s['name'], 'role': s['role']}
                for s in rt.named_stores(sentence, retailers=[], own_domains=OWN, brand='Pampers')]
    out = af.fabricated_availability(mentions, retailer_list=[], own_domain=OWN[0], merchant_kind='brand')
    assert out['fabricated'] == [] and [e['domain'] for e in out['unverified']] == [store]
    on_list = af.fabricated_availability(mentions, retailer_list=RETAILERS['domains'], own_domain=OWN[0],
                                         merchant_kind='brand')
    assert on_list['fabricated'] == [] and [e['domain'] for e in on_list['listed']] == [store]


def test_a_sellers_list_is_still_closed():
    out = af.fabricated_availability([{'name': 'Walmart -', 'role': 'recommendation'}],
                                     retailer_list=['shop.example'], own_domain='shop.example', merchant_kind='seller')
    assert [e['domain'] for e in out['fabricated']] == ['walmart.com']


def _flagged(kind_rule):
    d = WHERE_TO_BUY
    n = 0
    for a in d['answers']:
        stores = rt.named_stores(a['answer'], retailers=d['retailers'], own_domains=d['own_domains'], brand=d['brand'])
        out = af.fabricated_availability([{'name': s['name'], 'role': s['role']} for s in stores],
                                         retailer_list=d['retailers'], own_domain=d['own_domains'][0],
                                         merchant_kind='brand')
        n += bool(kind_rule(out))
    return n


def test_on_the_fl14_shaped_where_to_buy_fixture_four_answers_lose_the_flag():
    """Before 2T-4 a store off the list was `fabricated` (now `unverified`): 4 of 60 flagged, now none."""
    assert len(WHERE_TO_BUY['answers']) == 60
    assert _flagged(lambda out: out['fabricated'] or out['unverified']) == 4
    assert _flagged(lambda out: out['fabricated']) == 0
