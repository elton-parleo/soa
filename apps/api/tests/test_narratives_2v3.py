"""
2V-3 Q2-Q4: what Petco's first cycle (FL17-petco-20261029) showed in the lines.

Q2  A line may not give the record or a page a size, count, price or program
    the record does not hold. FL17's four lines gave Petco's record the 40 lb
    an agent said (the record is 31.1 lb) and the 6 lb an agent said (Tidy
    Cats, no 6 lb in the record). The brief quoted the first with an ellipsis;
    the fixture fills it with the product's name. Each line passed the check
    before 2V-3 (asserted against the facts below) and drops now.
Q3  A read's date is its day in the workspace's timezone: an Oct 29 PDT read
    is "Oct 29", never the UTC "Oct 30".
Q4  A product row with no variant label is named by its question, never its
    key; a literal "<brand>", an empty name or a subject key is never written;
    "... but Petco is the store" reads "... but the record is Petco's".
No model is called: check() and the facts builders are pure.
"""
import pytest

from soa_shared import local_time
from soa_shared import narratives as n

PURINA = {
    'kind': 'product', 'product': '31.1 lb', 'store': 'Petco', 'gtin': '00017800149501', 'sku': '00017800149501',
    'agents_asked': 6,
    'retailer_prices_that_day': [{'retailer': 'Petco', 'price': '49.99', 'date': 'Oct 29'}],
    'quotes': [
        {'agent': 'Gemini', 'retailer': 'Walmart', 'price': '54.99', 'verdict': 'wrong price',
         'for_variant': 'Purina ONE Lamb & Rice 40 lb'},
        {'agent': 'Perplexity', 'retailer': 'Petco', 'price': '54.99', 'verdict': 'wrong price',
         'for_variant': 'Purina ONE Lamb & Rice 40 lb'},
        {'agent': 'Copilot', 'retailer': 'Petco', 'price': '54.99', 'verdict': 'wrong price',
         'for_variant': 'Purina ONE Lamb & Rice 40 lb'},
    ],
    'issue': '3 of 6 agents quoted the wrong price.', 'aliases': ['00017800149501'],
}
TIDY = {
    'kind': 'product', 'product': '17 lb', 'store': 'Petco', 'gtin': '00070230101015', 'sku': '00070230101015',
    'agents_asked': 6,
    'retailer_prices_that_day': [{'retailer': 'Petco', 'price': '19.99', 'date': 'Oct 29'}],
    'quotes': [{'agent': 'ChatGPT', 'retailer': 'Petco', 'price': '8.99', 'verdict': 'wrong price',
                'for_variant': 'Tidy Cats Free & Clean 6 lb'}],
    'issue': '1 of 6 agents quoted the wrong price.', 'aliases': ['00070230101015'],
}

FL17 = [
    (PURINA, "Gemini said Walmart offers Purina ONE Lamb & Rice in 40 lb bags. Petco's record pages show 40 lb.",
     '40 lb'),
    (TIDY, "ChatGPT quoted $8.99 for Tidy Cats Free & Clean, but Petco pages show 17 lb and 6 lb.", '6 lb'),
    (PURINA, "Perplexity quoted $54.99 for Purina ONE Lamb & Rice, and Petco's record lists a 40 lb bag.", '40 lb'),
    (PURINA, "Copilot quoted $54.99 for Purina ONE Lamb & Rice, but Petco's record lists a 40 lb bag.", '40 lb'),
]


# ── Q2 ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('facts,line,size', FL17)
def test_fl17_s_record_lines_drop(facts, line, size):
    assert n.check(line, facts) == f'record_fact_not_in_digest:{size}'


@pytest.mark.parametrize('facts,line,_size', FL17)
def test_fl17_s_lines_fail_only_the_new_check(facts, line, _size, monkeypatch):
    # what made them through: with the record check off, every other check passes
    monkeypatch.setattr(n, 'record_fact_check', lambda line, facts: None)
    assert n.check(line, facts) is None


def test_what_the_record_holds_may_be_given_to_it():
    line = "Gemini quoted $54.99 for a 40 lb bag. Petco's record lists 31.1 lb at $49.99."
    assert n.check(line, PURINA) is None


def test_a_price_or_program_the_record_does_not_hold_drops():
    assert n.record_fact_check("Petco's page shows $54.99.", PURINA) == 'record_fact_not_in_digest:$54.99'
    assert n.record_fact_check("Petco's record lists Petco Perks.", PURINA) == \
        'record_fact_not_in_digest:Petco Perks'
    held = {**PURINA, 'deals_live_that_day': [{'program': 'Petco Perks'}]}
    assert n.record_fact_check("Petco's record lists Petco Perks.", held) is None


def test_an_agent_s_own_clause_is_not_the_record_s():
    assert n.record_fact_check("Gemini said Walmart's page shows 40 lb.", PURINA) is None


# ── Q3 ─────────────────────────────────────────────────────────────────────

def test_a_read_date_is_the_workspace_s_day():
    stamp = '2026-10-30T02:15:00+00:00'      # Oct 29, 19:15 PDT
    assert n._day(stamp, 'America/Los_Angeles') == 'Oct 29'
    assert n._day(stamp, 'UTC') == 'Oct 30'
    assert n._day('2026-10-29') == 'Oct 29'  # a bare date reads as it is
    row = {'retailer_domain': 'petco.com', 'price': '28.99', 'observed_at': stamp}
    assert n._reference_fact(row, zone='America/Los_Angeles')['date'] == 'Oct 29'


def test_the_console_and_the_lines_share_one_day_rule():
    from app.services import console_days
    console_days.use_zone('America/Los_Angeles')
    stamp = '2026-10-30T02:15:00+00:00'
    assert console_days.short_day(stamp) == local_time.short_day(stamp, 'America/Los_Angeles') == 'Oct 29'


# ── Q4 ─────────────────────────────────────────────────────────────────────

def test_a_labelless_row_is_named_by_its_question_never_its_key():
    assert n.question_product('What does the NexGard Chewables for Dogs cost at Petco?') == 'NexGard Chewables for Dogs'
    assert n.question_product('What does the Wiggle & Snug Cloud Wipes 3-Pack cost?') == \
        'Wiggle & Snug Cloud Wipes 3-Pack'
    assert n.product_label('NexGard Chewables for Dogs', None) == 'NexGard Chewables for Dogs'
    assert n.product_label('NexGard Chewables for Dogs', '31.1 lb') == '31.1 lb'   # unchanged: its digest stays
    assert n.product_label(None, None) is None
    reference = {'prices': [{'variant_ref': 'feed_sku:78', 'retailer_domain': 'petco.com', 'price': '69.99',
                             'observed_at': '2026-10-29T18:00:00+00:00'}]}
    runs = [{'query_text': 'What does the NexGard Chewables for Dogs cost at Petco?', 'platform': 'gemini',
             'source_ref': {'variant_ref': 'feed_sku:78'}, 'outcome': 'wrong',
             'expected_answer': {'type': 'price', 'attributed_to': 'petco.com'},
             'claim_results': [{'target': 'asked', 'stated': '59.99'}]}]
    out = n.product_facts(reference, runs, n.Merchant(name='Petco', kind='seller', terms=('Petco',)))
    assert out['feed_sku:78']['product'] == 'NexGard Chewables for Dogs'


@pytest.mark.parametrize('line,reason', [
    ("Perplexity first picked Costco, then <brand>.", 'placeholder:<brand>'),
    ("Perplexity first picked Costco, then .", 'empty_name:then .'),
    ("Perplexity named \"\" first.", 'empty_name:""'),
    ("Gemini quoted $59.99 for feed_sku:78.", 'subject_key:feed_sku:78.'),
])
def test_a_slot_an_empty_name_or_a_key_is_never_written(line, reason):
    assert n.placeholder_check(line) == reason
    assert n.check(line, PURINA) == reason


def test_an_entity_with_no_name_is_not_a_pick():
    from soa_shared import surfaces
    run = {'answer_status': surfaces.ANSWERED, 'tier': 'category_control', 'platform': 'perplexity',
           'query_text': 'Best dog food for a puppy?', 'source_ref': {}}
    mentions = [{'name': 'Costco', 'position': 1}, {'name': '', 'position': 2}, {'name': None, 'position': 3}]
    petco = n.Merchant(name='Petco', kind='seller', terms=('Petco',))
    facts = n.answer_facts(run, None, mentions, petco, {})
    assert (facts['first pick'], facts['named in order']) == ('Costco', ['Costco'])
    # a nameless first pick is no rival's pick: nothing to write
    assert n.answer_facts(run, None, [{'name': '', 'position': 1}], petco, {}) is None


def test_the_store_is_not_the_store_it_is_the_record_s():
    line = "Copilot quoted $54.99, but Petco is the store."
    assert n.normalise(line, PURINA) == "Copilot quoted $54.99, but the record is Petco's."
