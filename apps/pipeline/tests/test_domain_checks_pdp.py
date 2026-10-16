"""
2E-1: the domain checks read a product page, and a re-run replaces the record.

229's record (FL3-wiggle-and-snug-20261014) typed trueshopstore.com
brand_only from its store root alone, called Protocol & Feed "not
applicable" and skipped the signed probe, with 19 readable json_ld reads on
that domain in supply. The adapter read the reference rows under `rows`;
supply serves them under `prices` (truesync/fullloop/prices.py), so it saw
none. These tests run the 229-shaped cycle (rows exactly as supply serves
them, the reference read NOT cached on the cycle, as 229's was not) on
sqlite and Postgres, through the scan's real fetcher on recorded pages.
"""
import copy
import io
import json

import pytest

from scan.site_typing import SITE_TYPE_BRAND_ONLY, SITE_TYPE_COMMERCE
from scoring import domain_checks as dc
from tests.test_domain_checks import (FIX, FIXED_NOW, Supply, network, seed_cycle,  # noqa: F401 (fixtures)
                                      signing_on)

WS = 'trueshopstore.com'
WS_ORIGIN = f'https://{WS}'
BRAND = 'wiggleandsnug.com'
RETAILER = 'target.test'
NEWEST_JSON_LD = f'{WS_ORIGIN}/products/wiggle-snug-diapers-size-3'


def _row(i, url, *, method='json_ld', observed='2026-10-14T17:00:00+00:00', status='ok', domain=WS):
    """One row as supply /retailer-prices serves it (prices.FIELDS)."""
    return {'variant_ref': f'feed_sku:{i}', 'gtin': f'00850000000{i:03d}', 'sku': f'WS-{i}',
            'variant_label': f'Size {i % 7}', 'retailer_domain': domain, 'url': url, 'price': '39.99',
            'member_price': None, 'list_price': None, 'currency': 'USD', 'availability': 'InStock',
            'observed_at': observed if status else None, 'reference_source': 'direct' if status else None,
            'method': method if status else None, 'read_status': status, 'verifiable': status == 'ok',
            'unverifiable_reason': None if status == 'ok' else 'not read yet', 'reference_read_id': 1000 + i,
            'reference_run_id': 33 if status else None, 'offer_text': None, 'incentive_in_markup': None}


def ws_rows():
    """The 19 Oct 14 reads on trueshopstore.com, json_ld every one (the
    Catalog screen's "Retailers read": 19 pages, json_ld 19). One was read a
    little later than the others: that one is the page."""
    rows = [_row(i, f'{WS_ORIGIN}/products/ws-{i}', observed='2026-10-14T16:5%d:00+00:00' % (i % 10))
            for i in range(1, 19)]
    rows.insert(7, _row(19, NEWEST_JSON_LD, observed='2026-10-14T17:30:00+00:00'))
    return rows


def ws_payload():
    return {'merchant': 'wiggle-and-snug', 'kind': 'seller', 'as_of': '2026-10-16T06:43:00+00:00',
            'prices': ws_rows()}


def _ws_site(network):
    """trueshopstore.com as 229 read it: a store root with no commerce signal
    of its own, no llms.txt, no manifest; product pages with Offer markup."""
    pdp = (FIX / 'pdp.html').read_text()
    network['site'] = {f'{WS_ORIGIN}/robots.txt': (200, 'User-agent: *\nAllow: /\n', 'text/plain'),
                       WS_ORIGIN: (200, (FIX / 'store_home_plain.html').read_text(), 'text/html; charset=utf-8')}
    for row in ws_rows():
        network['site'][row['url']] = (200, pdp, 'text/html; charset=utf-8')
    return network


class WsSupply(Supply):
    def __init__(self, rows=None, own=(WS,), tenant=(WS, BRAND)):
        super().__init__(own=own, rows=ws_rows() if rows is None else rows, tenant=tenant)


def seed_229(engine):
    """The 229-shaped cycle: the W&S store's questions, reference_prices NULL
    (229 read supply's current one: reference_rows_from 'supply')."""
    seed_cycle(engine, reference=None)
    with engine.begin() as c:
        c.execute(dc.text("UPDATE soa_queries SET source_ref = :r"), {'r': json.dumps({'merchant_slug': 'wiggle-and-snug'})})
    return engine


# ─── the cause ─────────────────────────────────────────────────────────────

def test_supplys_rows_are_under_prices_and_2e_read_rows(any_engine):
    """The row shape that failed: supply's payload has no `rows`, so 2E's
    reader saw an empty reference read and fell to the store root alone."""
    payload = ws_payload()
    assert 'rows' not in payload and len(payload['prices']) == 19
    assert (payload.get('rows') or []) == []                       # what 2E read
    seed_229(any_engine)
    with any_engine.connect() as conn:
        rows, source = dc.reference_rows(conn, 229, WsSupply(), 'wiggle-and-snug')
    assert source == 'supply' and len(rows) == 19


def test_a_cycle_caching_supplys_payload_reads_it_too(any_engine):
    """2B caches the payload as supply serves it (`prices`), and so reads it back."""
    seed_cycle(any_engine, reference=ws_payload())
    supply = WsSupply()
    with any_engine.connect() as conn:
        rows, source = dc.reference_rows(conn, 229, supply, 'wiggle-and-snug')
    assert source == 'cycle' and len(rows) == 19
    assert ('retailer_prices', 'wiggle-and-snug') not in supply.calls


# ─── the selection rule ────────────────────────────────────────────────────

def test_the_json_ld_read_on_the_own_domain_is_taken_newest_first():
    rows = [
        _row(1, f'https://{RETAILER}/p/1', domain=RETAILER, observed='2026-10-14T18:00:00+00:00'),   # a retailer
        _row(2, f'{WS_ORIGIN}/products/regex-newest', method='regex', observed='2026-10-14T19:00:00+00:00'),
        _row(3, f'{WS_ORIGIN}/products/json-ld-older', observed='2026-10-13T09:00:00+00:00'),
        _row(4, f'{WS_ORIGIN}/products/json-ld-newer', observed='2026-10-14T09:00:00Z'),
        _row(5, f'{WS_ORIGIN}/products/not-read', status=None),
        _row(6, f'{WS_ORIGIN}/products/failed', status='blocked'),
    ]
    sel = dc.select_product_page(rows, WS, [WS, BRAND])
    assert sel['url'] == f'{WS_ORIGIN}/products/json-ld-newer'
    assert sel['page']['method'] == 'json_ld' and sel['probe_from'] == dc.FROM_OWN
    assert 'rejected' not in sel                       # a page was found: no list kept
    # with no json_ld read, regex is next
    assert dc.product_page(rows[:2], WS) == f'{WS_ORIGIN}/products/regex-newest'


@pytest.mark.parametrize('host', [WS, f'www.{WS}', f'WWW.{WS.upper()}'])
@pytest.mark.parametrize('domain', [WS, f'www.{WS}', f'https://www.{WS}/'])
def test_www_and_bare_host_variants_both_match(host, domain):
    url = f'https://{host}/products/ws-1'
    rows = [_row(1, url, domain=host.lower())]
    assert dc.select_product_page(rows, domain, [WS])['url'] == url


def test_a_page_on_another_tenant_domain_is_not_this_sites_page():
    rows = [_row(1, f'{WS_ORIGIN}/products/ws-1')]
    sel = dc.select_product_page(rows, BRAND, [WS, BRAND])
    assert sel['url'] is None
    assert sel['probe_url'] == f'{WS_ORIGIN}/products/ws-1' and sel['probe_from'] == dc.FROM_TENANT
    assert sel['rejected'] == [{'url': f'{WS_ORIGIN}/products/ws-1', 'retailer_domain': WS, 'read_status': 'ok',
                                'method': 'json_ld', 'why': f'on {WS}, another own domain of the tenant, not {BRAND}'}]


def test_with_no_page_every_row_seen_is_listed_with_why():
    rows = [_row(1, f'https://{RETAILER}/p/1', domain=RETAILER), _row(2, f'{WS_ORIGIN}/products/a', status=None),
            _row(3, f'{WS_ORIGIN}/products/b', status='blocked'), {**_row(4, None), 'url': None}]
    sel = dc.select_product_page(rows, WS, [WS])
    assert sel['url'] is None and sel['rows_seen'] == 4 and sel['rejected_count'] == 4
    assert [r['why'] for r in sel['rejected']] == [
        f'on {RETAILER}, a retailer, not an own domain', 'not read yet', 'not readable (read_status blocked)',
        'no page URL']
    assert sel['probe_url'] == f'https://{RETAILER}/p/1' and sel['probe_from'] == dc.FROM_RETAILER


# ─── 229, end to end, on both databases ────────────────────────────────────

def test_229_reads_its_product_page_and_is_a_store(any_engine, network, signing_on):
    _ws_site(network)
    seed_229(any_engine)
    record = dc.run_for_cycle(229, engine=any_engine, client=WsSupply(), now=FIXED_NOW)
    entry = record['domains'][0]
    assert record['reference_rows_from'] == 'supply' and record['reference_rows'] == 19
    assert record['tenant_own_domains'] == [WS, BRAND]
    assert entry['pdp_url'] == NEWEST_JSON_LD
    # classify_site saw the store root AND the product page
    assert entry['site_type']['site_type'] == SITE_TYPE_COMMERCE
    assert 'Offer markup found on at least one fetched page' in entry['site_type']['signals']
    # Protocol & Feed measured: a value (0: nothing published), never 'na'. A
    # measured F3 is always the Audit's coverage 'partial' (its two deferred
    # items, feed and ACP participation, are not crawl-observable), which the
    # console counts as measured.
    pf = record['protocol_feed']
    assert pf['coverage'] == 'partial' and pf['score'] == 0.0 and pf['deferred_items']
    assert not any('not applicable' in e for e in pf['evidence'])
    # Value Protocols unchanged: the store publishes no profile on its domain
    assert (record['value_protocols']['score'], record['value_protocols']['coverage']) == (0.0, 'full')
    assert record['value_protocols']['evidence'] == ['no protocol profile found']
    # the probe ran on that page, signed once and unsigned once
    pdp = [h for u, h in network['requests'] if u == NEWEST_JSON_LD]
    assert len(pdp) == 2 and 'Signature' in pdp[0] and 'Signature' not in pdp[1]
    assert record['signed_probe']['outcome'] == dc.BOTH_IN and record['signed_probe']['page_from'] == dc.FROM_OWN
    # nothing but the one product page among the 19 was fetched
    assert sum(1 for u, _ in network['requests'] if '/products/' in u) == 2


def test_the_store_root_alone_still_says_brand_only(network):
    """What 229's record said, kept as the reason the page matters."""
    _ws_site(network)
    entry = dc.fetch_domain(WS, pdp_url=None)
    assert entry['site_type']['store_root_only']['site_type'] == SITE_TYPE_BRAND_ONLY
    assert entry['site_type']['site_type'] is None
    assert entry['protocol_feed']['evidence'] == [dc.NO_PDP] and entry['protocol_feed']['coverage'] == 'not_measured'


@pytest.mark.parametrize('tenant, page_from', [((WS, BRAND), dc.FROM_TENANT), ((BRAND,), dc.FROM_RETAILER)])
def test_a_brand_with_reads_only_on_the_retailer(any_engine, network, signing_on, tenant, page_from):
    """The W&S brand: its own site is wiggleandsnug.com, every read is on the
    store. The probe falls back to the store's page and says so; the brand
    site is not typed from it, and Protocol & Feed is not measured."""
    _ws_site(network)
    network['site'][f'https://{BRAND}'] = (200, (FIX / 'store_home_plain.html').read_text(), 'text/html')
    seed_229(any_engine)
    record = dc.run_for_cycle(229, engine=any_engine, client=WsSupply(own=(BRAND,), tenant=tenant), now=FIXED_NOW)
    entry = record['domains'][0]
    assert entry['domain'] == BRAND and entry['pdp_url'] is None
    assert entry['site_type']['site_type'] is None
    assert record['protocol_feed']['evidence'] == ['not measured: no product page']
    assert record['protocol_feed']['score'] is None
    assert record['value_protocols']['coverage'] == 'full'           # its own site's files, as before
    probe = record['signed_probe']
    assert probe['url'] == NEWEST_JSON_LD and probe['page_from'] == page_from
    assert probe['outcome'] == dc.BOTH_IN and 'the probe only, the site is not typed from it' in probe['note']
    assert [u for u, _ in network['requests']].count(NEWEST_JSON_LD) == 2
    assert f'{WS_ORIGIN}/robots.txt' in [u for u, _ in network['requests']]   # the fallback's own robots.txt


# ─── the script ────────────────────────────────────────────────────────────

def _script(argv, engine, journal, client):
    from scripts import run_domain_checks
    out = io.StringIO()
    code = run_domain_checks.main(argv + ['--journal', str(journal)], engine=engine, client=client, out=out)
    return code, out.getvalue()


def test_the_no_page_path_lists_the_rejected_rows(any_engine, network, tmp_path):
    _ws_site(network)
    seed_229(any_engine)
    rows = [_row(1, f'https://{RETAILER}/p/1', domain=RETAILER), _row(2, f'{WS_ORIGIN}/products/a', status=None)]
    code, out = _script(['--cycle', '229', '--dry-run'], any_engine, tmp_path / 'j.jsonl', WsSupply(rows=rows))
    assert code == 0
    assert f'product page      NONE on {WS}: 2 reference rows seen' in out
    assert f'rejected  https://{RETAILER}/p/1   on {RETAILER}, a retailer, not an own domain' in out
    assert f'rejected  {WS_ORIGIN}/products/a   not read yet' in out
    assert '(the store root alone would say brand_only' in out
    assert 'protocol_feed     not measured  coverage not_measured' in out
    assert 'not applicable' not in out


def stored_229_record(record):
    """The record 229 holds: 2E's, typed brand_only from the store root, no
    revision."""
    old = copy.deepcopy(record)
    old.pop('revision')
    old['version']['adapter_revision'] = 1
    old['checked_at'] = '2026-10-16T06:43:21.140094+00:00'
    na = {'score': 0.0, 'max': 5, 'evidence': ['protocol & feed presence is not applicable — no cart, commerce paths, '
                                               'platform markers, or Offer markup found'],
          'fix': None, 'fix_human': None, 'coverage': 'na', 'deferred_items': [], 'cap_basis': []}
    probe = {'url': None, 'signed': None, 'unsigned': None, 'key_id': None, 'outcome': dc.NOT_CHECKED,
             'reason': "no product page on the merchant's own domain in the reference read"}
    for holder in (old, old['domains'][0]):
        holder.update(protocol_feed=na, signed_probe=probe)
    old['domains'][0].update(pdp_url=None, site_type={'site_type': 'brand_only', 'signals': [],
                                                      'reason': 'no cart, commerce paths, platform markers, or Offer markup found'})
    return old


def test_a_rerun_shows_old_beside_new_then_replaces_the_record(any_engine, network, tmp_path, signing_on):
    _ws_site(network)
    seed_229(any_engine)
    new = dc.run_for_cycle(229, engine=any_engine, client=WsSupply(), now=FIXED_NOW)
    with any_engine.begin() as c:   # what run_domain_checks.py stored on 229 (2E)
        c.execute(dc.text("UPDATE soa_cycles SET domain_checks = :j WHERE id = 229"),
                  {'j': json.dumps(stored_229_record(new))})
    journal = tmp_path / 'j.jsonl'

    code, out = _script(['--cycle', 'FL3-acme-baby-20261014', '--dry-run'], any_engine, journal, WsSupply())
    assert code == 0 and 'dry run — nothing written.' in out
    assert 'the stored record (revision 1) beside this one (revision 2 if written); * = changed:' in out
    lines = out.splitlines()

    def line(label):
        return next(x for x in lines if x.strip().startswith(label + ' '))
    assert line(f'{WS} site_type').split(None, 2)[2] == '* brand_only  →  commerce_normal'
    assert line(f'{WS} protocol_feed.coverage').split(None, 2)[2] == '* na  →  partial'
    assert line(f'{WS} pdp_url').split(None, 2)[2] == f'* -  →  {NEWEST_JSON_LD}'
    assert line(f'{WS} signed_probe.outcome').split(None, 2)[2] == '* not_checked  →  both_in'
    assert line(f'{WS} value_protocols.score').split(None, 2)[2] == '0.0  →  0.0'   # unchanged: no mark
    assert line('revision').split(None, 1)[1] == '* 1  →  2'
    assert dc.stored(any_engine, 229)['domains'][0]['site_type']['site_type'] == 'brand_only'   # untouched

    code, out = _script(['--cycle', '229'], any_engine, journal, WsSupply())
    assert code == 2 and '--replace to replace it' in out
    code, out = _script(['--cycle', '229', '--replace'], any_engine, journal, WsSupply())
    assert code == 0 and 'replaced on soa_cycles.domain_checks, revision 2.' in out
    back = dc.stored(any_engine, 229)
    assert back['revision'] == 2 and back['domains'][0]['site_type']['site_type'] == SITE_TYPE_COMMERCE
    assert back['protocol_feed']['coverage'] == 'partial'
    # one record per cycle, replaced, never appended
    with any_engine.connect() as c:
        assert c.execute(dc.text("SELECT COUNT(*) FROM soa_cycles WHERE id = 229")).scalar() == 1
    assert isinstance(back, dict) and 'domains' in back
    events = [json.loads(x)['event'] for x in journal.read_text().splitlines()]
    assert events.count('replaced') == 1
    replaced = next(json.loads(x) for x in journal.read_text().splitlines() if json.loads(x)['event'] == 'replaced')
    assert replaced['record']['domains'][0]['site_type']['site_type'] == 'brand_only'   # the old one, kept

    code, out = _script(['--cycle', '229', '--replace'], any_engine, journal, WsSupply())
    assert 'revision 3.' in out and dc.stored(any_engine, 229)['revision'] == 3


def test_the_first_store_is_revision_1(any_engine, network):
    _ws_site(network)
    seed_229(any_engine)
    record = dc.run_for_cycle(229, engine=any_engine, client=WsSupply(), now=FIXED_NOW)
    assert record['revision'] is None
    assert dc.store(any_engine, 229, record) and record['revision'] == 1
    assert dc.stored(any_engine, 229)['revision'] == 1
