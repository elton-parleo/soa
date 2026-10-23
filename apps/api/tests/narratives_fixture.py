"""
2L-3: the FL13-shaped cycle the narratives are recorded and replayed on.

console_fixture_2j2 (Pampers at Walmart and Amazon, six agents, 10 variants),
in a throwaway sqlite database with the console schema (soa_narratives
included). Its flagged answers: the catalog tier's wrong prices (ChatGPT's
Walmart price at Amazon, Gemini's and Perplexity's Amazon price at Walmart),
Copilot's other-brand answers, and console_fixture_2i8's brand-direct and
category rows (a fabricated or misattributed verdict, a rival first pick),
whose question text and reasons are filler ("question 1083", "r"). Its 10
products are the 10 variants.

2L-3a adds three shapes the FL13 dry run (Oct 22) showed (fl13_shapes()),
each by changing rows the 2J-2 fixture already has:
  unread     Easy Ups S5 66's Amazon page could not be read (verifiable
             false, no price); ChatGPT's wrong quote there stays wrong, as
             run-14727's did.
  range      Gemini at Walmart on Baby Dry S3 136 quotes $19.97 and $32.97,
             either side of Walmart's $29.97 (run-14539, 14858).
  per unit   Perplexity at Walmart on Cruisers 360 S4 104 quotes "$0.38 per
             diaper" against a $39.97 pack (run-14815).

No network and no production database: the engine is sqlite in memory and
DATABASE_URL is never read.
"""
import json
import os
import sys

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'narratives')
CYCLE_ID = 229
NAME = 'fl13'


UNREAD = ('00037000863489', 'amazon.com')
RANGE = ('00037000863465', 'walmart.com', 'gemini_grounded', ['19.97', '32.97'])
PER_UNIT = ('00037000863472', 'walmart.com', 'perplexity', '0.38', 'Pampers Cruisers 360 run about $0.38 per diaper.')


def _run(conn, gtin: str, retailer: str, platform: str) -> int:
    from sqlalchemy import text
    for rid, ref, expected in conn.execute(text(
            "SELECT r.id, q.source_ref, q.expected_answer FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id "
            "WHERE r.cycle_id = :c AND r.platform = :p AND q.tier = 'catalog_accuracy'"),
            {'c': CYCLE_ID, 'p': platform}):
        ref = json.loads(ref) if isinstance(ref, str) else ref
        expected = json.loads(expected) if isinstance(expected, str) else expected
        if (ref or {}).get('gtin') == gtin and (expected or {}).get('attributed_to') == retailer:
            return rid
    raise LookupError((gtin, retailer, platform))


def fl13_shapes(e) -> None:
    """The three FL13 shapes above, on a loaded 2J-2 fixture."""
    from sqlalchemy import text
    with e.begin() as c:
        cached = c.execute(text("SELECT reference_prices FROM soa_cycles WHERE id = :c"), {'c': CYCLE_ID}).scalar()
        cached = json.loads(cached) if isinstance(cached, str) else cached
        for row in cached['prices']:
            if row.get('gtin') == UNREAD[0] and row.get('retailer_domain') == UNREAD[1]:
                row.update({'price': None, 'verifiable': False, 'read_status': 'blocked',
                            'unverifiable_reason': 'the page could not be read'})
        c.execute(text("UPDATE soa_cycles SET reference_prices = :p WHERE id = :c"),
                  {'p': json.dumps(cached), 'c': CYCLE_ID})

        gtin, retailer, platform, stated = RANGE
        rid = _run(c, gtin, retailer, platform)
        claims = [{'target': 'asked', 'stated': s, 'outcome': 'wrong', 'variant_id': gtin} for s in stated]
        c.execute(text("UPDATE soa_expectation_outcomes SET claim_results = :c WHERE run_id = :r"),
                  {'c': json.dumps(claims), 'r': rid})

        gtin, retailer, platform, stated, span = PER_UNIT
        rid = _run(c, gtin, retailer, platform)
        claims = [{'target': 'asked', 'stated': stated, 'outcome': 'wrong', 'variant_id': gtin}]
        extraction = {'prices': [{'amount': stated, 'currency': 'USD'}], 'spans': [{'text': span}]}
        c.execute(text("UPDATE soa_expectation_outcomes SET claim_results = :c, extraction = :x WHERE run_id = :r"),
                  {'c': json.dumps(claims), 'x': json.dumps(extraction), 'r': rid})


def engine():
    """A fresh sqlite engine holding the console schema and the 2J-2 fixture."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
    testing = os.path.join(root, 'packages', 'testing')
    if testing not in sys.path:
        sys.path.insert(0, testing)
    from cryptography.fernet import Fernet
    from soa_pg_harness import sqlite_engine

    from soa_shared import config
    from tests import console_fixture_2j2 as f2j2
    from tests.test_console_read_models import _encode, seed_console_db

    if not config.SOA_SECRET_KEY:
        config.SOA_SECRET_KEY = Fernet.generate_key().decode()   # seed_console_db seals two test tokens
    e = sqlite_engine()
    seed_console_db(e)
    f2j2.load(e, _encode)
    fl13_shapes(e)
    return e
