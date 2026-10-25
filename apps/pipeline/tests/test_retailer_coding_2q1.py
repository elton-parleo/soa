"""
2Q-1 (B1): a where-to-buy or cheapest-place answer's stores are coded by
rule over the whole answer (soa_shared/retailers.named_stores), stored on the
outcome's extraction as `named_stores`, never only from a unit with a buy
word.

After 2O-4 the brand-direct record's store pass (scoring/brand_claim_selector
.select) kept a store only from a unit that also carried a buy word, and
never the brand's own site. FL14's Retailer coverage read 49 of 60 before the
2O-4 rescore and 36 of 60 after, on the same answers; FL15 read 31 of 60.

  * a list with a price after each store, prose, and a table;
  * the brand's own site, as a domain and in words (2N-1's brand row);
  * a store the answer says does not carry it; an everyday word ("target");
    a cited domain that is no store;
  * through the scorer: stored on a where-to-buy run, on no other run, with
    no model call, twice identical;
  * the FL14-shaped fixture (fixtures/retailer_coding/fl14_where_to_buy.json,
    hand-written: see its builder): coverage 36 of 60 on the selector's
    coding, 49 of 60 on 2Q-1's.

NOTHING HERE IS RECORDED and there is no model call.
"""
import asyncio
import json
import os
from types import SimpleNamespace

from scoring import brand_claim_selector as sel
from scoring import expectation_scorer as scorer_module
from soa_shared import expected_answers as ea
from soa_shared import retailers as rt
from tests.test_expectation_scorer import FakeFacts, db, outcomes  # noqa: F401  (db is a fixture)
from tests.test_brand_claim_selector_2o4 import Explodes, NoHistory, NoTenant, Pages

HERE = os.path.dirname(os.path.abspath(__file__))
FL14 = json.load(open(os.path.join(HERE, 'fixtures', 'retailer_coding', 'fl14_where_to_buy.json')))
LISTED = FL14['retailers']
OWN = FL14['own_domains']


def coded(answer, retailers=LISTED, own=OWN, brand='Pampers'):
    return rt.named_stores(answer, retailers=retailers, own_domains=own, brand=brand)


def names(stores, role=None):
    return [s['name'] for s in stores if role is None or s['role'] == role]


# ── the coding ────────────────────────────────────────────────────────────

def test_a_list_with_a_price_after_each_store():
    answer = ("Here are the best places to buy Pampers Swaddlers Size 1:\n\n1. **Walmart**: $27.97, in stock\n"
              "2. **Target** - $28.49\n3. **Amazon** — $26.99 with Subscribe & Save\n\n"
              "Costco also has a bulk box for $44.99.")
    stores = coded(answer)
    assert names(stores) == ['Walmart', 'Target', 'Amazon', 'Costco']
    assert [s['position'] for s in stores] == [1, 2, 3, 4]
    assert [answer[s['at']:s['at'] + len(s['name'])] for s in stores] == ['Walmart', 'Target', 'Amazon', 'Costco']
    assert all(s['role'] == 'recommendation' and s['listed'] and not s['own'] for s in stores)
    # the selector's store pass kept the one line with a buy word ("in stock")
    vocab = sel.Vocabulary('Pampers', ['Pampers'], [], [])
    assert sel.select(answer, question='Where?', vocab=vocab, own_domains=OWN)['retailer_mentions'] == \
        [{'name': 'Walmart', 'role': 'recommendation'}]


def test_prose_and_a_table_in_the_order_written():
    prose = "Amazon usually has it cheapest, though Target runs Circle deals and Sam's Club sells the 168 count."
    assert names(coded(prose)) == ['Amazon', 'Target', "Sam's Club"]
    table = "| Store | Price |\n|---|---|\n| Walmart | $27.97 |\n| Sam's Club | $44.99 |\n| Amazon | $26.99 |"
    assert names(coded(table)) == ['Walmart', "Sam's Club", 'Amazon']


def test_the_brand_s_own_site_is_the_brand_row():
    for answer in ("Pampers.com sells it directly, and Walmart has it for $27.97.",
                   "Order it on the Pampers website, or at Walmart.",
                   "You can buy directly from Pampers, or at Walmart."):
        stores = coded(answer)
        assert [(s['name'], s['domain'], s['own'], s['listed']) for s in stores] == \
            [('pampers.com', 'pampers.com', True, False), ('Walmart', 'walmart.com', False, True)], answer
    # no own site to map to: the words are not a store
    assert names(coded("Order it on the Pampers website.", own=[])) == []


def test_a_store_that_does_not_carry_it_is_unavailable():
    stores = coded("Walmart and Target carry Size 1, but Costco doesn't carry it. Sam's Club is out of stock.")
    assert [(s['name'], s['role']) for s in stores] == [('Walmart', 'recommendation'), ('Target', 'recommendation'),
                                                       ('Costco', 'unavailable'), ("Sam's Club", 'unavailable')]
    # named again where it does have it: recommended
    assert names(coded("Costco is out of stock. Costco.com has it for $44.99."), 'recommendation') == ['Costco']


def test_words_that_are_not_stores():
    stores = coded("Aim for your target weight range, a chewy wipe texture is normal; see consumerreports.org. "
                   "Instacart delivers from Kroger.")
    assert names(stores) == ['Instacart', 'Kroger']
    assert [s['listed'] for s in stores] == [False, False]


def test_a_retailer_on_the_merchant_s_list_the_lexicon_lacks():
    stores = coded("Bellababy has it, and so does bellababy.com's outlet.", retailers=LISTED + ['bellababy.com'])
    assert [(s['name'], s['listed']) for s in stores] == [('bellababy.com', True)]
    assert coded("a bellababy blanket", retailers=['bellababy.com']) == []


def test_the_same_answer_gives_the_same_list():
    for r in FL14['answers']:
        assert coded(r['answer']) == coded(r['answer'])


# ── through the scorer ────────────────────────────────────────────────────

FACTS = {'brand': 'Pampers', 'domain': 'pampers.com', 'own_domains': OWN, 'retailer_list': LISTED,
         'product_titles': ['Pampers Swaddlers Diapers Size 1, 96 Count'], 'variants': [], 'tier_names': []}
LIST_ANSWER = "Pampers Swaddlers Size 1:\n- Amazon: $26.99\n- Target: $28.49\n- Walmart: $27.97"


class Terms:
    def for_cycle(self, *_a, **_k):
        return {'terms': ['Pampers'], 'product_names': [], 'rivals': ['Huggies']}


def make_scorer():
    return scorer_module.ExpectationScorer(Explodes(), NoHistory(), FakeFacts(FACTS), labeler=Explodes(),
                                           references=Pages(), tenant_domains=NoTenant(), brand_terms=Terms())


def seed(db, intents=('where_to_buy', 'cheapest_place', None)):
    from sqlalchemy import text
    with db.begin() as conn:
        for i, intent in enumerate(intents, 1):
            ref = {'merchant_slug': 'pampers', **({'intent': intent} if intent else {})}
            conn.execute(text("""
                INSERT INTO soa_queries (id, query_text, tier, expected_answer, provenance, source_ref)
                VALUES (:id, 'Where can I buy Pampers Swaddlers Size 1?', 'brand_direct', :e, 'catalog', :r)
            """), {'id': i, 'e': json.dumps(ea.brand_mention('Pampers', 'pampers.com')), 'r': json.dumps(ref)})
            conn.execute(text("""
                INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, raw_response, status)
                VALUES (:id, 3, :id, 'gemini', 1, :a, 'success')
            """), {'id': i, 'a': LIST_ANSWER})


def stored(db):
    return {r['run_id']: json.loads(r['extraction']) for r in outcomes(db)}


def test_the_scorer_stores_the_stores_on_a_where_to_buy_run_with_no_model_call(db):
    seed(db)
    scorer = make_scorer()
    assert {asyncio.run(scorer.score_run(i)).status for i in (1, 2, 3)} == {'success'}
    rows = stored(db)
    for run_id in (1, 2):
        assert names(rows[run_id]['named_stores']) == ['Amazon', 'Target', 'Walmart']
        assert rows[run_id]['coder']['version'] == ea.BRAND_CODER_VERSION == 7
        assert rows[run_id]['coder']['calls'] == []
    # an AI-written question's answer is the brand-claim rule's: no store coding
    assert 'named_stores' not in rows[3]
    first = stored(db)
    scorer = make_scorer()
    for i in (1, 2, 3):
        asyncio.run(scorer.score_run(i))
    assert stored(db) == first


def test_code_stores_keeps_a_stored_coding_with_no_answer_text():
    ref = {'intent': 'where_to_buy'}
    kept = {'named_stores': [{'name': 'Walmart'}]}
    assert scorer_module.code_stores(ref, kept, None, facts=FACTS) is kept
    assert scorer_module.code_stores({'intent': 'attribute'}, {'x': 1}, LIST_ANSWER, facts=FACTS) == {'x': 1}
    # the catalog unread: the question's own list
    got = scorer_module.code_stores({**ref, 'retailer_list': ['amazon.com'], 'own_domain': 'pampers.com'}, {},
                                    LIST_ANSWER, facts={})
    assert [(s['name'], s['listed']) for s in got['named_stores']] == \
        [('Amazon', True), ('Target', False), ('Walmart', False)]


# ── the FL14-shaped fixture ───────────────────────────────────────────────

def _covered(domains) -> bool:
    return len(set(domains) & set(LISTED)) >= 2


def test_fl14_shaped_coverage_before_and_after():
    vocab = sel.Vocabulary('Pampers', ['Pampers'], [], ['Huggies'])
    before = after = 0
    by_shape = {}
    for r in FL14['answers']:
        old = sel.select(r['answer'], question=r['question'], vocab=vocab, own_domains=OWN)['retailer_mentions']
        was = _covered(d for m in old for d in rt.retailers_named(m['name']))
        now = _covered(s['domain'] for s in coded(r['answer']) if s['role'] != 'unavailable')
        before, after = before + was, after + now
        by_shape.setdefault(r['shape'], [0, 0, 0])
        by_shape[r['shape']][0] += 1
        by_shape[r['shape']][1] += was
        by_shape[r['shape']][2] += now
    assert len(FL14['answers']) == 60
    assert (before, after) == (36, 49)
    # [answers, covered before, covered after] per shape (the builder's mix)
    assert by_shape == {'prose': [34, 34, 34], 'list': [15, 0, 15], 'gone': [2, 2, 0], 'one': [5, 0, 0],
                        'other': [4, 0, 0]}


def test_the_fixture_rebuilds_byte_identical():
    from tests.fixtures import build_where_to_buy_2q1 as build
    assert json.loads(json.dumps(build.build(), sort_keys=True)) == FL14


# ── the printout ──────────────────────────────────────────────────────────

def _seed_fl14(db):
    """The fixture's 60 answers as FL14's where-to-buy runs, each with its
    outcome as the post-2O-4 rescore stored it (the selector's record, coder 6:
    retailer_mentions, no named_stores)."""
    from sqlalchemy import text
    vocab = sel.Vocabulary('Pampers', ['Pampers'], [], ['Huggies'])
    expectation = ea.brand_mention('Pampers', 'pampers.com')
    with db.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS soa_cycles (id INTEGER PRIMARY KEY, cycle_code TEXT)")
        conn.exec_driver_sql("INSERT INTO soa_cycles (id, cycle_code) VALUES (3, 'FL14-pampers-20261023')")
        conn.exec_driver_sql("ALTER TABLE soa_queries ADD COLUMN query_code TEXT")
        for i, r in enumerate(FL14['answers'], 1):
            conn.execute(text("""
                INSERT INTO soa_queries (id, query_text, tier, expected_answer, provenance, source_ref, query_code)
                VALUES (:id, :q, 'brand_direct', :e, 'catalog', :r, :code)
            """), {'id': i, 'q': r['question'], 'e': json.dumps(expectation), 'code': r['query_code'],
                   'r': json.dumps({'merchant_slug': 'pampers', 'intent': 'where_to_buy'})})
            conn.execute(text("""
                INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, raw_response, status)
                VALUES (:id, 3, :id, :agent, 1, :a, 'success')
            """), {'id': i, 'agent': r['agent'], 'a': r['answer']})
            old = sel.select(r['answer'], question=r['question'], vocab=vocab, own_domains=OWN)
            old['coder']['version'] = 6
            conn.execute(text("""
                INSERT INTO soa_expectation_outcomes (run_id, query_id, cycle_id, platform, tier, expected_answer,
                                                      extraction, outcome, scored_at)
                VALUES (:id, :id, 3, :agent, 'brand_direct', :e, :x, 'grounded', '2026-10-24T00:00:00+00:00')
            """), {'id': i, 'agent': r['agent'], 'e': json.dumps(expectation), 'x': json.dumps(old)})


def test_rescore_prints_coverage_before_and_after(db, capsys, monkeypatch):
    """rescore_cycle --tier brand_direct on the FL14-shaped cycle: the stored
    coding's coverage, 2Q-1's, and routing's base; a dry run prints the same."""
    from scripts import rescore_cycle
    _seed_fl14(db)
    monkeypatch.setattr(rescore_cycle, 'engine', db)
    monkeypatch.setattr(rescore_cycle, '_brand_direct_scorer', lambda **_kw: make_scorer())
    monkeypatch.delenv('OPEN_AI_API_KEY', raising=False)

    def run(*args):
        code = rescore_cycle.main(['--cycle', 'FL14-pampers-20261023', '--tier', 'brand_direct', *args])
        return code, capsys.readouterr().out

    code, dry = run('--dry-run')
    assert code == 0 and all('named_stores' not in x for x in stored(db).values())
    lines = [
        "where-to-buy stores (2Q-1: coded over the whole answer, named_stores; before is the stored coding):",
        "    retailer coverage    36 of 60 -> 49 of 60  (where-to-buy answers naming 2 or more of amazon.com, "
        "costco.com, samsclub.com, target.com, walmart.com)",
        "    routing base         41 -> 60  (where-to-buy and cheapest-place answers naming a store)",
    ]
    assert '\n'.join(lines) in dry
    code, real = run()
    assert code == 0 and '\n'.join(lines) in real
    assert all(isinstance(x.get('named_stores'), list) for x in stored(db).values())
    # the second run reads 2Q-1's coding as stored: nothing moves
    code, again = run()
    assert "    retailer coverage    49 of 60 -> 49 of 60" in again and "    routing base         60 -> 60" in again
