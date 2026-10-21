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

No network and no production database: the engine is sqlite in memory and
DATABASE_URL is never read.
"""
import os
import sys

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'narratives')
CYCLE_ID = 229
NAME = 'fl13'


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
    return e
