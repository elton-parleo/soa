"""
2P-1 (B3): a week-over-week pair, FL14's shape as cycle 1 and cycle 2 of
the same study seven days later with controlled differences.

Cycle 1 is 229 (FL3-wiggle-and-snug-20261014) on 2N-1's FL14 shape: the
FL13 shape (2K-4's _fl13_shape, its earlier cycle 178 another study), 2L-2's
retired line (Pure, AMORE its successor), 2L-4's 20 intent questions,
2M-2's 12 cheapest-place and where-to-buy questions with supply's deals,
2M-1's 10 attribute questions judged against the cycle's truth. Cycle 2 is
230 (FL4-wiggle-and-snug-20261021): every row of 229 copied seven days on
(runs, outcomes, mentions, the cached reference, the study's comparison
set), then the differences in CHANGES applied, each to named rows.

Prices and product names are the fixtures', not production's.
"""
import copy
import json
from datetime import timedelta

from sqlalchemy import inspect, text

from tests import console_fixture_229 as f229

CYCLE_1, CYCLE_2 = f229.CYCLE_229, 'FL4-wiggle-and-snug-20261021'
ID_1, ID_2 = 229, 230
#: a copied run's id: the cycle-1 run's plus this
RUN_OFFSET = 1_000_000
DAYS = 7

#: tables keyed by run_id that a cycle's reads join through its runs
RUN_TABLES = ('soa_coded_mentions', 'soa_other_mentions', 'soa_citations', 'soa_expectation_outcomes')
#: tables keyed by cycle_id copied whole
CYCLE_TABLES = ('soa_cycle_entities',)


def _rows(c, sql, **params):
    return [dict(r) for r in c.execute(text(sql), params).mappings()]


def _columns(c, table):
    return [r for r in c.execute(text(f"SELECT * FROM {table} WHERE 1 = 0")).keys()]


def _insert(c, table, row, encode):
    row = {k: encode(v) if isinstance(v, (dict, list)) else v for k, v in row.items()}
    c.execute(text(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})"), row)


def _next_id(c, table):
    return (c.execute(text(f"SELECT MAX(id) FROM {table}")).scalar() or 0) + 1


def _shift(value):
    """A stored date or stamp, seven days on (sqlite hands text back)."""
    if value is None:
        return None
    if isinstance(value, str):
        from datetime import date, datetime
        try:
            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            return value
        moved = parsed + timedelta(days=DAYS)
        return moved.date().isoformat() if len(value) == 10 else moved.isoformat()
    return value + timedelta(days=DAYS)


def clone(db, encode):
    """Cycle 230: 229 copied seven days on, nothing else changed."""
    have = set(inspect(db).get_table_names())
    with db.begin() as c:
        [cycle] = _rows(c, "SELECT * FROM soa_cycles WHERE id = :i", i=ID_1)
        cycle.update(id=ID_2, cycle_code=CYCLE_2, start_date=_shift(cycle['start_date']))
        for key in ('created_at', 'completed_at', 'reference_as_of', 'end_date'):
            if key in cycle:
                cycle[key] = _shift(cycle[key])
        for key in ('share_of_algorithm', 'share_of_algorithm_version'):
            cycle.pop(key, None)
        ref = cycle.get('reference_prices')
        if ref:
            ref = json.loads(ref) if isinstance(ref, str) else copy.deepcopy(ref)
            if ref.get('as_of'):
                ref['as_of'] = _shift(ref['as_of'])
            for price in ref.get('prices') or []:
                if price.get('observed_at'):
                    price['observed_at'] = _shift(price['observed_at'])
            cycle['reference_prices'] = ref
        _insert(c, 'soa_cycles', cycle, encode)
        for table in (t for t in CYCLE_TABLES if t in have):
            for row in _rows(c, f"SELECT * FROM {table} WHERE cycle_id = :i", i=ID_1):
                row.update(id=_next_id(c, table), cycle_id=ID_2)
                _insert(c, table, row, encode)
        runs = _rows(c, "SELECT * FROM soa_runs WHERE cycle_id = :i ORDER BY id", i=ID_1)
        for run in runs:
            run = {**run, 'id': run['id'] + RUN_OFFSET, 'cycle_id': ID_2}
            for key in ('run_at', 'created_at'):
                if key in run:
                    run[key] = _shift(run[key])
            _insert(c, 'soa_runs', run, encode)
        for table in (t for t in RUN_TABLES if t in have):
            rows = _rows(c, f"SELECT t.* FROM {table} t JOIN soa_runs r ON r.id = t.run_id WHERE r.cycle_id = :i",
                         i=ID_1)
            for row in rows:
                row.update(id=_next_id(c, table), run_id=row['run_id'] + RUN_OFFSET)
                if 'cycle_id' in row:
                    row['cycle_id'] = ID_2
                if row.get('scored_at') is not None:
                    row['scored_at'] = _shift(row['scored_at'])
                _insert(c, table, row, encode)


# ─── Cycle 1's priced catalog block (both cycles carry it) ─────────────────

AGENTS = (('chatgpt', 'grounded_api', 'openai'), ('gemini_grounded', 'grounded_api', 'google_genai'),
          ('aimode', 'consumer_ui', 'serpapi'), ('perplexity', 'grounded_api', 'perplexity'),
          ('copilot', 'consumer_ui', 'serpapi'), ('claude', 'grounded_api', 'anthropic'))
RETAILERS = ('walmart.com', 'amazon.com')
#: (variant, label, Walmart's price, Amazon's): the reference's own variants v0 to v2
PRICED = (('v0', 'Newborn, 84 ct', '24.97', '27.97'), ('v1', 'Size 1, 96 ct', '27.97', '30.97'),
          ('v2', 'Size 4, 120 ct', '39.97', '42.97'))
PRICE_QUESTION, PRICE_RUN = 3400, 99000
#: cycle 1: every agent quotes the asked retailer's price, Copilot none, and
#: Gemini Walmart's price at Amazon on v0 (wrong)
CYCLE_1_QUOTES = {('v0', 'amazon.com', 'gemini_grounded'): '24.97'}


def _price(vid, retailer, prices=None):
    row = next(p for p in PRICED if p[0] == vid)
    return (prices or {}).get((vid, retailer)) or (row[2] if retailer == 'walmart.com' else row[3])


def _retailer_rows(prices=None, observed='2026-10-14T14:00:00+00:00'):
    return [{'variant_ref': f'feed_sku:{vid}', 'gtin': None, 'sku': vid, 'variant_label': label,
             'retailer_domain': r, 'url': f'https://www.{r}/ip/{vid}', 'role': 'retailer',
             'price': _price(vid, r, prices), 'currency': 'USD', 'observed_at': observed,
             'reference_source': 'honest_fetch', 'method': 'json_ld', 'read_status': 'ok', 'verifiable': True}
            for vid, label, _w, _a in PRICED for r in RETAILERS]


def _claim(vid, stated, outcome):
    return [{'target': 'asked', 'stated': stated, 'outcome': outcome, 'variant_id': f'feed_sku:{vid}'}] if stated else []


def _extraction(stated):
    return {'prices': [{'amount': stated, 'currency': 'USD'}] if stated else [], 'codes': [], 'pack_counts': [],
            'gtins': [], 'member_prices': [], 'points': [], 'brand_mentioned': True, 'sources_cited': [],
            'extraction_confident': True, 'extraction_note': None}


def priced(db, encode):
    """Cycle 1's six price questions (3 variants at Walmart and Amazon), one run per agent."""
    with db.begin() as c:
        ref = c.execute(text("SELECT reference_prices FROM soa_cycles WHERE id = :c"), {'c': ID_1}).scalar()
        ref = json.loads(ref) if isinstance(ref, str) else dict(ref or {})
        ref['prices'] = list(ref.get('prices') or []) + _retailer_rows()
        c.execute(text("UPDATE soa_cycles SET reference_prices = :p WHERE id = :c"), {'p': encode(ref), 'c': ID_1})
        qid, rid = PRICE_QUESTION, PRICE_RUN
        for vid, label, _w, _a in PRICED:
            for retailer in RETAILERS:
                qid += 1
                expected = {'type': 'price', 'amount': _price(vid, retailer), 'currency': 'USD',
                            'attributed_to': retailer}
                source = {'merchant_slug': 'wiggle-and-snug', 'variant_id': f'feed_sku:{vid}', 'sku': vid,
                          'own_domain': 'pampers.com', 'merchant_kind': 'brand', 'retailer_list': list(RETAILERS)}
                c.execute(text("INSERT INTO soa_queries (id, query_code, query_text, stage, status, study_type, "
                               "study_pattern, organization_id, tier, expected_answer, provenance, source_ref) VALUES "
                               "(:i, :c, :t, 'Ready to Buy', 'Active', :st, 'brand_at_retail', 1, 'catalog_accuracy', "
                               ":e, 'catalog', :r)"),
                          {'i': qid, 'c': f'WSP_{qid}', 't': f'What does Pampers Swaddlers {label} cost at {retailer}?',
                           'st': f229.STUDY, 'e': encode(expected), 'r': encode(source)})
                for platform, surface, collector in AGENTS:
                    rid += 1
                    stated = None if platform == 'copilot' else \
                        CYCLE_1_QUOTES.get((vid, retailer, platform), expected['amount'])
                    outcome = 'absent' if stated is None else 'exact' if stated == expected['amount'] else 'wrong'
                    c.execute(text("INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, run_at, "
                                   "raw_response, status, surface, collector, answer_status) VALUES (:r, :cy, :q, :p, 1, "
                                   "'2026-10-14T15:00:00+00:00', :t, 'success', :s, :col, 'answered')"),
                              {'r': rid, 'cy': ID_1, 'q': qid, 'p': platform, 's': surface, 'col': collector,
                               't': f'It costs ${stated} at {retailer}.' if stated else 'Check the store.'})
                    c.execute(text("INSERT INTO soa_expectation_outcomes (run_id, query_id, cycle_id, platform, tier, "
                                   "expected_answer, outcome, outcome_reason, flags, surface, claim_results, extraction) "
                                   "VALUES (:r, :q, :cy, :p, 'catalog_accuracy', :e, :o, 'r', '[]', :s, :cl, :x)"),
                              {'r': rid, 'q': qid, 'cy': ID_1, 'p': platform, 'e': encode(expected), 'o': outcome,
                               's': surface, 'cl': encode(_claim(vid, stated, outcome)), 'x': encode(_extraction(stated))})


# ─── Cycle 2's differences ──────────────────────────────────────────────────
#
#   price cells     v0 at Amazon wrong -> exact (Gemini now quotes $27.97);
#                   v1 at Walmart exact -> wrong (ChatGPT quotes $25.97);
#                   v2 at Walmart: Walmart's price moved $39.97 -> $37.97 and
#                   Perplexity quoted last week's: stale (the others quote $37.97)
#   deals           the Walmart Rollback ended (Walmart read, no deal); Sam's Club
#                   walled (its Sam's Cash not read); a new Amazon coupon on v9,
#                   named in one cheapest-place answer
#   retired         three answers that named Pure name Swaddlers: 10 -> 7 of 102
#   attribute       one Size 4 answer gives the brand's 15-34 lb: 8 -> 9 of 15
#   coverage        two where-to-buy answers that named Amazon and Costco name
#                   Amazon and Walmart: 38 -> 40 of 49
#   first picks     on brand-choice answers, Pampers +3 (two from Huggies, one
#                   that named no tracked brand first), Huggies -2. The fixture's
#                   comparison set is Pampers, Huggies and Pull-Ups: Coterie,
#                   FL14's, is not in it.
#   the score       up 4, two pillars moving: Visibility (ours coded as the pick,
#                   strength Primary, in PICKS of our unprompted mentions per
#                   surface: Recommendation Strength 5 -> 6) and True Value
#                   (supply's newest page read, which the score reads at
#                   scoring time, gained six pages, three with a member price
#                   in markup: Member Value's seen half 0 of 2 -> 3 of 8). Per
#                   surface 42 -> 44.9 of 69: 61 -> 65.

MOVED = {('v2', 'walmart.com'): '37.97'}
PICKS = {'grounded_api': 5, 'consumer_ui': 3}
CYCLE_2_QUOTES = {('v0', 'amazon.com', 'gemini_grounded'): '27.97',
                  ('v1', 'walmart.com', 'chatgpt'): '25.97',
                  ('v2', 'walmart.com', 'perplexity'): '39.97'}
STALE = {('v2', 'walmart.com', 'perplexity')}
COUPON = {'retailer_domain': 'amazon.com', 'kind': 'coupon', 'text': '$3 off coupon', 'value': '3.00',
          'value_unit': 'usd', 'terms': None, 'program': None,
          'variants': [{'variant_ref': 'feed_sku:v9', 'gtin': None, 'sku': 'v9', 'variant_label': 'v9, 84 ct',
                        'product_name': 'Pampers Swaddlers v9', 'url': 'https://example.com/v9',
                        'reference_read_id': 1, 'observed_at': '2026-10-21T14:00:00+00:00', 'shelf_price': '27.97',
                        'price': '24.97', 'was_price': None, 'evidence': '$3 off coupon'}]}
COUPON_ANSWER = 'Amazon has a $3 off coupon that brings it to $24.97.'
RETIRED_FROM, RETIRED_TO = 'Pampers Pure is a good pick.', 'Pampers Swaddlers is a good pick.'
SIZE_4_FROM, SIZE_4_TO = 'Size 4 fits 22–37 lbs.', 'Size 4 fits 15–34 lbs.'


def reference_2(reference_1: dict) -> dict:
    """supply's /reference when cycle 2 is scored: six more pages read, three with a member price."""
    rows = [{'retailer_domain': r, 'read_status': 'ok', 'price': '29.97', 'variant_ref': v,
             'member_price': '27.97' if n < 3 else None}
            for n, (v, r) in enumerate((v, r) for v in ('v3', 'v4', 'v5') for r in RETAILERS)]
    return {**reference_1, 'rows': list(reference_1.get('rows') or []) + rows}


def deals_2(deals_1: dict) -> dict:
    """supply's /deals on cycle 2's read date."""
    keep = [d for d in deals_1['deals'] if d['retailer_domain'] not in ('walmart.com', 'samsclub.com')]
    retailers = [r for r in deals_1.get('retailers') or []] + [
        {'retailer_domain': 'walmart.com', 'rows': 10, 'shelf_seen': 10, 'asked': 10, 'with_deals': 0},
        {'retailer_domain': 'samsclub.com', 'rows': 10, 'shelf_seen': 0, 'asked': 0, 'with_deals': 0}]
    return {**deals_1, 'as_of': '2026-10-21T23:59:59.999999+00:00', 'read_date': '2026-10-21',
            'deals': keep + [COUPON], 'retailers': retailers,
            'walled': sorted(set(deals_1.get('walled') or []) | {'samsclub.com'})}


def _run(c, cycle_id, query_id, platform):
    return c.execute(text("SELECT id FROM soa_runs WHERE cycle_id = :c AND query_id = :q AND platform = :p"),
                     {'c': cycle_id, 'q': query_id, 'p': platform}).scalar()


def _json(value):
    return json.loads(value) if isinstance(value, str) else (dict(value) if value else {})


def apply_changes(db, encode):
    """Cycle 2's differences, each on named rows of the copy."""
    with db.begin() as c:
        # the cached reference: v2's Walmart price moved
        ref = _json(c.execute(text("SELECT reference_prices FROM soa_cycles WHERE id = :c"), {'c': ID_2}).scalar())
        for row in ref['prices']:
            key = (row.get('sku'), row.get('retailer_domain'))
            if key in MOVED and row.get('role') == 'retailer':
                row['price'] = MOVED[key]
                row['observed_at'] = '2026-10-21T14:00:00+00:00'
        c.execute(text("UPDATE soa_cycles SET reference_prices = :p WHERE id = :c"), {'p': encode(ref), 'c': ID_2})

        # the price questions: expectations at cycle 2's prices, the moved quotes
        qid = PRICE_QUESTION
        for vid, _label, _w, _a in PRICED:
            for retailer in RETAILERS:
                qid += 1
                amount = _price(vid, retailer, MOVED)
                expected = {'type': 'price', 'amount': amount, 'currency': 'USD', 'attributed_to': retailer}
                for platform, _surface, _collector in AGENTS:
                    if platform == 'copilot':
                        continue
                    stated = CYCLE_2_QUOTES.get((vid, retailer, platform), amount)
                    outcome = 'stale' if (vid, retailer, platform) in STALE else \
                        'exact' if stated == amount else 'wrong'
                    rid = _run(c, ID_2, qid, platform)
                    c.execute(text("UPDATE soa_runs SET raw_response = :t WHERE id = :r"),
                              {'t': f'It costs ${stated} at {retailer}.', 'r': rid})
                    c.execute(text("UPDATE soa_expectation_outcomes SET outcome = :o, expected_answer = :e, "
                                   "claim_results = :cl, extraction = :x, outcome_reason = :why WHERE run_id = :r"),
                              {'o': outcome, 'e': encode(expected), 'cl': encode(_claim(vid, stated, outcome)),
                               'x': encode(_extraction(stated)), 'r': rid,
                               'why': f"quoted ${stated}, the price in the previous cycle; ${amount} now"
                               if outcome == 'stale' else 'r'})

        # retired: three answers that named Pure name Swaddlers
        runs = c.execute(text("SELECT id FROM soa_runs WHERE cycle_id = :c AND raw_response = :t ORDER BY id"),
                         {'c': ID_2, 't': RETIRED_FROM}).scalars().all()
        assert len(runs) == 3, runs
        for rid in runs:
            c.execute(text("UPDATE soa_runs SET raw_response = :t WHERE id = :r"), {'t': RETIRED_TO, 'r': rid})

        # attribute: one Size 4 answer (Swaddlers, v2) gives the brand's range
        rid = c.execute(text("SELECT r.id FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id WHERE r.cycle_id = :c "
                             "AND q.query_code LIKE 'WSA_%' AND r.raw_response = :t ORDER BY r.id"),
                        {'c': ID_2, 't': SIZE_4_FROM}).scalars().first()
        c.execute(text("UPDATE soa_runs SET raw_response = :t WHERE id = :r"), {'t': SIZE_4_TO, 'r': rid})
        x = _json(c.execute(text("SELECT extraction FROM soa_expectation_outcomes WHERE run_id = :r"), {'r': rid}).scalar())
        x['spans'] = [{'id': 1, 'text': SIZE_4_TO}]
        x.pop('weight_range', None)
        c.execute(text("UPDATE soa_expectation_outcomes SET extraction = :x WHERE run_id = :r"), {'x': encode(x), 'r': rid})

        # coverage: two where-to-buy answers that named Amazon and Costco name Amazon and Walmart
        moved = 0
        for rid, x in c.execute(text("SELECT o.run_id, o.extraction FROM soa_expectation_outcomes o JOIN soa_queries q "
                                     "ON q.id = o.query_id WHERE o.cycle_id = :c AND q.query_code LIKE 'WSF_31%' "
                                     "ORDER BY o.run_id"), {'c': ID_2}).fetchall():
            x = _json(x)
            names = [m.get('name') for m in x.get('retailer_mentions') or []]
            if names == ['Amazon', 'Costco'] and moved < 2:
                x['retailer_mentions'] = [{'name': 'Amazon', 'role': 'recommendation'},
                                          {'name': 'Walmart', 'role': 'recommendation'}]
                x['spans'] = [{'id': 1, 'text': 'You can find it at Amazon.'}, {'id': 2, 'text': 'You can find it at Walmart.'}]
                c.execute(text("UPDATE soa_expectation_outcomes SET extraction = :x WHERE run_id = :r"),
                          {'x': encode(x), 'r': rid})
                moved += 1
        assert moved == 2

        # promo: the new coupon named in one cheapest-place answer on v9 (2M-2's questions)
        rid = c.execute(text("SELECT r.id FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id WHERE r.cycle_id = :c "
                             "AND q.query_text = 'Cheapest place to buy Pampers Swaddlers v9?' AND r.platform = 'chatgpt'"),
                        {'c': ID_2}).scalar()
        c.execute(text("UPDATE soa_runs SET raw_response = :t WHERE id = :r"), {'t': COUPON_ANSWER, 'r': rid})

        # first picks: Pampers +3, Huggies -2, on brand-choice (category-control) answers
        def firsts(entity):
            return c.execute(text("SELECT cm.run_id FROM soa_coded_mentions cm JOIN soa_runs r ON r.id = cm.run_id "
                                  "JOIN soa_queries q ON q.id = r.query_id WHERE r.cycle_id = :c AND "
                                  "q.tier = 'category_control' AND cm.entity_id = :e AND cm.position = 1 "
                                  "ORDER BY cm.run_id"), {'c': ID_2, 'e': entity}).scalars().all()
        huggies = firsts(f229.HUGGIES)[:2]
        for rid in huggies:
            c.execute(text("UPDATE soa_coded_mentions SET position = 2 WHERE run_id = :r AND entity_id = :e"),
                      {'r': rid, 'e': f229.HUGGIES})
            _pampers_first(c, rid)
        firsted = set(c.execute(text("SELECT cm.run_id FROM soa_coded_mentions cm JOIN soa_runs r ON r.id = cm.run_id "
                                     "WHERE r.cycle_id = :c AND cm.position = 1"), {'c': ID_2}).scalars().all())
        nobody = c.execute(text("SELECT r.id FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id WHERE "
                                "r.cycle_id = :c AND q.tier = 'category_control' AND r.answer_status = 'answered' "
                                "AND q.query_text NOT LIKE 'Is Wiggle & Snug right%' ORDER BY r.id"),
                           {'c': ID_2}).scalars().all()
        rid = next(r for r in nobody if r not in firsted)
        _pampers_first(c, rid)

        _score(c, encode)


def _score(c, encode):
    """Visibility's pillar: ours the pick in PICKS of our unprompted mentions per
    surface. True Value's moves on supply's page read (reference_2)."""
    for surface, n in PICKS.items():
        ids = c.execute(text("SELECT cm.id FROM soa_coded_mentions cm JOIN soa_runs r ON r.id = cm.run_id JOIN "
                             "soa_queries q ON q.id = r.query_id WHERE r.cycle_id = :c AND r.surface = :s AND "
                             "q.tier = 'category_control' AND cm.entity_id = :e AND cm.mentioned = :t ORDER BY cm.id"),
                        {'c': ID_2, 's': surface, 'e': f229.WS, 't': True}).scalars().all()[:n]
        assert len(ids) == n, (surface, ids)
        for i in ids:
            c.execute(text("UPDATE soa_coded_mentions SET strength = 'Primary' WHERE id = :i"), {'i': i})


def _pampers_first(c, run_id):
    found = c.execute(text("SELECT id FROM soa_coded_mentions WHERE run_id = :r AND entity_id = :e"),
                      {'r': run_id, 'e': f229.PAMPERS}).scalar()
    if found:
        c.execute(text("UPDATE soa_coded_mentions SET position = 1, mentioned = :t WHERE id = :i"),
                  {'i': found, 't': True})
    else:
        c.execute(text("INSERT INTO soa_coded_mentions (id, run_id, entity_id, mentioned, position) "
                       "VALUES (:i, :r, :e, :t, 1)"),
                  {'i': _next_id(c, 'soa_coded_mentions'), 'r': run_id, 'e': f229.PAMPERS, 't': True})
