"""
2E: the Audit's domain checks, run from the worker (scoring/domain_checks.py).

Every check is the Audit's (scan/scorer.py), called through the adapter on
recorded fixtures: the Audit's own protocol-file fixtures
(tests/scan/test_soft_200_protocol_files.py) and an invented store on
acmebaby.test (tests/fixtures/domain_checks/). Requests go through the
scan's real fetcher with httpx.Client.get and getaddrinfo patched, so the
honest UA, robots.txt and the signing headers are what is asserted, and
nothing reaches a network. The cycle-level tests run on sqlite and Postgres
(any_engine).
"""
import io
import json
import pathlib
import socket
from datetime import date, datetime, timezone

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import text

from scan import fetcher, scorer, signing
from scan.discovery import PageCandidate
from scan.engine import PageScanData, _serialize_dim_score
from scan.fetcher import FetchResult
from scan.site_typing import SITE_TYPE_BRAND_ONLY, SITE_TYPE_COMMERCE, SiteTypeResult
from scoring import domain_checks as dc
from soa_pg_harness import model_schema
from soa_shared.models.soa_models import Base
from tests.scan.test_soft_200_protocol_files import CHURCH_DWIGHT_SOFT_404, LLMS_TXT, MANIFEST

FIX = pathlib.Path(__file__).parent / 'fixtures' / 'domain_checks'
ORIGIN = 'https://acmebaby.test'
PDP = f'{ORIGIN}/products/overnight-diapers-size-3'
FULL_MANIFEST = json.dumps({'capabilities': ['dev.ucp.shopping.discount', 'dev.ucp.shopping.loyalty',
                                             'dev.acp.promotions'], 'specVersion': '2025-01'})


def _site(**override):
    """url -> (status, body, content type): the recorded store."""
    site = {
        f'{ORIGIN}/robots.txt': (200, (FIX / 'robots.txt').read_text(), 'text/plain'),
        ORIGIN: (200, (FIX / 'home.html').read_text(), 'text/html; charset=utf-8'),
        f'{ORIGIN}/llms.txt': (200, LLMS_TXT, 'text/plain'),
        f'{ORIGIN}/.well-known/mcp.json': (200, MANIFEST, 'application/json'),
        PDP: (200, (FIX / 'pdp.html').read_text(), 'text/html; charset=utf-8'),
    }
    site.update(override)
    return site


@pytest.fixture
def network(monkeypatch):
    """The recorded store behind the real fetcher. `requests` records every
    request's URL and headers; `refuse_unsigned` makes the product page a 403
    to a request without a Web Bot Auth signature."""
    monkeypatch.setattr(fetcher, 'POLITENESS_DELAY_SECONDS', 0)
    fetcher._last_fetch_at.clear()
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    state = {'site': _site(), 'requests': [], 'refuse_unsigned': False, 'refuse_signed': False}

    def fake_get(self, url, headers=None, **kw):
        state['requests'].append((url, dict(headers or {})))
        key = url.rstrip('/') if url.rstrip('/') == ORIGIN else url
        signed = 'Signature' in (headers or {})
        if key == PDP and ((state['refuse_unsigned'] and not signed) or (state['refuse_signed'] and signed)):
            return httpx.Response(403, text='<html><title>Access denied</title>denied</html>',
                                  headers={'content-type': 'text/html'}, request=httpx.Request('GET', url))
        if key not in state['site']:
            return httpx.Response(404, text='not found', request=httpx.Request('GET', url))
        status, body, ctype = state['site'][key]
        return httpx.Response(status, text=body, headers={'content-type': ctype}, request=httpx.Request('GET', url))

    monkeypatch.setattr(httpx.Client, 'get', fake_get)
    yield state
    fetcher._last_fetch_at.clear()


@pytest.fixture
def signing_on(monkeypatch):
    monkeypatch.setattr(signing, '_PRIVATE_KEY', Ed25519PrivateKey.generate())
    monkeypatch.setattr(signing, 'WEB_BOT_AUTH', 'on')


def _probe(kind, body, content_type=None, status='fetched'):
    """The Audit test's own page builder (test_soft_200_protocol_files._probe)."""
    headers = {'content-type': content_type} if content_type else {}
    fr = FetchResult(url=f'https://acme.example.com/{kind}', status=status, html=body, http_status=200,
                     response_headers=headers)
    return PageScanData(candidate=PageCandidate(url=fr.url, kind=kind), fetch_result=fr, extracted=None)


# ─── one domain, through the real fetcher ──────────────────────────────────

def test_a_domain_is_fetched_through_the_scan_fetcher_with_the_honest_ua(network):
    entry = dc.fetch_domain('acmebaby.test', pdp_url=PDP)
    urls = [u for u, _ in network['requests']]
    assert urls == [f'{ORIGIN}/robots.txt', ORIGIN, f'{ORIGIN}/llms.txt', f'{ORIGIN}/.well-known/mcp.json', PDP]
    for _, headers in network['requests']:
        assert headers['User-Agent'] == fetcher.USER_AGENT
        assert headers['Accept'] == fetcher.ACCEPT_HEADER
    assert [f['kind'] for f in entry['fetches']] == ['robots', 'homepage', 'llms_txt', 'mcp_well_known', 'product']
    assert entry['site_type']['site_type'] == SITE_TYPE_COMMERCE
    assert entry['agentic_protocol_hints'] == ["<link> markup mentions: ['ucp']"]


def test_both_dimensions_are_the_audits_functions_on_those_pages(network):
    entry = dc.fetch_domain('acmebaby.test', pdp_url=PDP)
    # llms.txt present, MCP manifest present, UCP link markup present, no
    # agentic-commerce JSON hint: 3 of 4 checks, the Audit's F3 on weight 5
    assert entry['protocol_feed']['score'] == 3.8
    assert entry['protocol_feed']['max'] == 5
    assert entry['protocol_feed']['evidence'][:3] == [
        '/llms.txt present and non-empty', 'MCP endpoint declaration discoverable (well-known path)',
        'UCP/UIP capability markup present']
    # the Audit's own MANIFEST: one capability, a current version: 3 + 3 + 3 of 14
    assert entry['value_protocols']['score'] == 9.0
    assert entry['value_protocols']['max'] == 14
    direct = scorer.score_value_protocols([_probe('mcp_well_known', MANIFEST, 'application/json')])
    assert entry['value_protocols'] == _serialize_dim_score(direct)


def test_robots_txt_is_honoured(network):
    network['site'][f'{ORIGIN}/robots.txt'] = (200, 'User-agent: *\nDisallow: /products/\n', 'text/plain')
    entry = dc.fetch_domain('acmebaby.test', pdp_url=PDP)
    assert PDP not in [u for u, _ in network['requests']]
    assert dc._fetch_of(entry, 'product')['status'] == 'robots_disallowed'
    assert entry['signed_probe']['outcome'] == dc.NOT_CHECKED
    assert entry['signed_probe']['reason'] == 'robots.txt disallows the product page to our reader'


def test_robots_and_store_root_both_refusing_stops_there(network):
    network['site'][f'{ORIGIN}/robots.txt'] = (403, 'denied', 'text/html')
    network['site'][ORIGIN] = (403, 'denied', 'text/html')
    entry = dc.fetch_domain('acmebaby.test', pdp_url=PDP)
    assert entry['short_circuited'] is True
    assert {u for u, _ in network['requests']} == {f'{ORIGIN}/robots.txt', ORIGIN}
    assert entry['value_protocols']['evidence'] == [
        f'could not verify a protocol profile — not attempted; {scorer.SHORT_CIRCUIT_EVIDENCE_CLAUSE}']
    assert entry['signed_probe']['outcome'] == dc.NOT_CHECKED


# ─── the signed-agent probe ────────────────────────────────────────────────

def test_without_a_key_the_probe_is_not_checked_and_one_request_is_sent(network):
    entry = dc.fetch_domain('acmebaby.test', pdp_url=PDP)
    assert [u for u, _ in network['requests']].count(PDP) == 1
    assert entry['signed_probe']['outcome'] == dc.NOT_CHECKED
    assert entry['signed_probe']['reason'] == 'no Web Bot Auth key on the worker, so no signed request was sent'


def test_signed_and_unsigned_the_same_ua(network, signing_on):
    network['refuse_unsigned'] = True
    entry = dc.fetch_domain('acmebaby.test', pdp_url=PDP)
    pdp = [h for u, h in network['requests'] if u == PDP]
    assert len(pdp) == 2
    assert 'Signature' in pdp[0] and 'Signature-Agent' in pdp[0]
    assert 'Signature' not in pdp[1]
    assert pdp[0]['User-Agent'] == pdp[1]['User-Agent'] == fetcher.USER_AGENT
    assert signing.WEB_BOT_AUTH == 'on'          # restored after the unsigned request
    probe = entry['signed_probe']
    assert probe['outcome'] == dc.SIGNED_ONLY
    assert probe['signed']['status'] == 'fetched' and probe['unsigned']['http_status'] == 403
    assert probe['key_id'] == signing.key_id()


@pytest.mark.parametrize('refuse_unsigned, refuse_signed, outcome', [
    (False, False, dc.BOTH_IN), (True, False, dc.SIGNED_ONLY), (False, True, dc.UNSIGNED_ONLY), (True, True, dc.NEITHER)])
def test_every_probe_outcome(network, signing_on, refuse_unsigned, refuse_signed, outcome):
    network['refuse_unsigned'], network['refuse_signed'] = refuse_unsigned, refuse_signed
    assert dc.fetch_domain('acmebaby.test', pdp_url=PDP)['signed_probe']['outcome'] == outcome


def test_the_probe_never_enters_either_score(network, signing_on):
    network['refuse_unsigned'] = True
    a = dc.fetch_domain('acmebaby.test', pdp_url=PDP)
    network['refuse_unsigned'] = False
    b = dc.fetch_domain('acmebaby.test', pdp_url=PDP)
    assert a['signed_probe']['outcome'] != b['signed_probe']['outcome']
    assert (a['protocol_feed'], a['value_protocols']) == (b['protocol_feed'], b['value_protocols'])


def test_no_product_page_on_the_domain(network):
    entry = dc.fetch_domain('acmebaby.test', pdp_url=None)
    assert entry['signed_probe']['reason'] == 'no readable product page in the reference read'
    # 2E-1: no product page, the site is not typed from the store root alone
    # (what the store root alone says is kept beside it), and Protocol & Feed
    # is not measured, never the Audit's 'na'
    assert entry['site_type']['site_type'] is None
    assert entry['site_type']['store_root_only']['site_type'] != SITE_TYPE_BRAND_ONLY
    assert entry['protocol_feed']['coverage'] == 'not_measured' and entry['protocol_feed']['score'] is None
    assert entry['protocol_feed']['evidence'] == ['not measured: no product page']


# ─── each check through the adapter, on the Audit's own fixtures ──────────

AUDIT_CASES = {
    # name: (llms.txt (body, type, http), manifest (body, type, http))
    'real files': ((LLMS_TXT, 'text/plain', 200), (MANIFEST, 'application/json', 200)),
    'church & dwight soft 404 on both': ((CHURCH_DWIGHT_SOFT_404, 'text/html; charset=utf-8', 200),
                                        (CHURCH_DWIGHT_SOFT_404, 'text/html; charset=utf-8', 200)),
    'markdown served as html': ((LLMS_TXT, 'text/html', 200), (MANIFEST, 'application/json', 200)),
    'empty llms.txt': (('  ', 'text/plain', 200), (MANIFEST, 'application/json', 200)),
    'json that is not an object': ((LLMS_TXT, 'text/plain', 200), ('["a", "list"]', 'application/json', 200)),
    'both missing': (('not found', 'text/plain', 404), ('not found', 'text/plain', 404)),
    'every capability': ((LLMS_TXT, 'text/plain', 200), (FULL_MANIFEST, 'application/json', 200)),
}


@pytest.mark.parametrize('case', sorted(AUDIT_CASES))
def test_the_adapter_scores_exactly_as_the_audit_does(network, case):
    (lb, lt, lh), (mb, mt, mh) = AUDIT_CASES[case]
    network['site'][f'{ORIGIN}/llms.txt'] = (lh, lb, lt)
    network['site'][f'{ORIGIN}/.well-known/mcp.json'] = (mh, mb, mt)
    entry = dc.fetch_domain('acmebaby.test', pdp_url=PDP)

    def page(kind, body, ctype, http):
        status = 'fetched' if http == 200 else 'not_found'
        return _probe(kind, body if http == 200 else None, ctype if http == 200 else None, status=status)
    hints = PageScanData(candidate=PageCandidate(url=ORIGIN, kind='homepage'),
                         fetch_result=FetchResult(url=ORIGIN, status='fetched'),
                         extracted=__import__('scan.structured_data', fromlist=['extract']).extract((FIX / 'home.html').read_text()))
    pages = [page('llms_txt', lb, lt, lh), page('mcp_well_known', mb, mt, mh), hints]
    site = SiteTypeResult(site_type=SITE_TYPE_COMMERCE, reason='x')
    assert entry['protocol_feed']['score'] == scorer.score_protocol_feed(pages, site).score
    assert entry['protocol_feed']['evidence'] == scorer.score_protocol_feed(pages, site).evidence
    assert entry['value_protocols'] == _serialize_dim_score(scorer.score_value_protocols(pages))


def test_a_stored_record_rescores_to_the_same_numbers(network):
    """The score of record is reproducible: the record, through JSON as the
    column stores it, re-scores through the Audit's functions to what was stored."""
    for case in sorted(AUDIT_CASES):
        (lb, lt, lh), (mb, mt, mh) = AUDIT_CASES[case]
        network['site'][f'{ORIGIN}/llms.txt'] = (lh, lb, lt)
        network['site'][f'{ORIGIN}/.well-known/mcp.json'] = (mh, mb, mt)
        entry = json.loads(json.dumps(dc.fetch_domain('acmebaby.test', pdp_url=PDP)))
        assert dc.score_entry(entry) == {'protocol_feed': entry['protocol_feed'],
                                         'value_protocols': entry['value_protocols']}, case


def test_a_long_llms_txt_is_kept_to_what_its_check_reads(network):
    long_file = LLMS_TXT + ('- [More](https://acme.example.com/more)\n' * 400)
    network['site'][f'{ORIGIN}/llms.txt'] = (200, long_file, 'text/plain')
    entry = dc.fetch_domain('acmebaby.test', pdp_url=PDP)
    assert len(dc._fetch_of(entry, 'llms_txt')['body']) == dc.LLMS_BODY_KEEP
    assert dc.score_entry(json.loads(json.dumps(entry)))['protocol_feed'] == entry['protocol_feed']


def test_a_product_page_body_is_never_stored(network):
    entry = dc.fetch_domain('acmebaby.test', pdp_url=PDP)
    assert dc._fetch_of(entry, 'product')['body'] is None
    assert dc._fetch_of(entry, 'homepage')['body'] is None


# ─── a cycle, on both databases ────────────────────────────────────────────

class Supply:
    """supply /retailers (#20's own_domains), /tenant and /retailer-prices."""

    def __init__(self, own=('acmebaby.test',), rows=None, tenant=None):
        self.own, self.rows, self.tenant, self.calls = list(own), rows, tenant, []

    def retailers(self, slug):
        self.calls.append(('retailers', slug))
        return {'own_domains': self.own, 'domains': ['target.test']}, None

    def merchant_record(self, slug):
        return {'slug': slug, 'domain': self.own[0] if self.own else None}, None

    def retailer_prices(self, slug, as_of=None):
        self.calls.append(('retailer_prices', slug))
        # as supply serves it (truesync/fullloop/prices.py): the rows are `prices`
        return {'merchant': slug, 'kind': 'seller', 'as_of': '2026-10-14T17:00:00+00:00', 'prices': self.rows or []}, None

    def tenant_own_domains(self):
        self.calls.append(('tenant_own_domains',))
        return list(self.tenant if self.tenant is not None else self.own), None


REFERENCE = {'as_of': '2026-10-14T17:00:00+00:00', 'prices': [
    {'retailer_domain': 'target.test', 'url': 'https://target.test/p/1', 'read_status': 'ok'},
    {'retailer_domain': 'acmebaby.test', 'url': PDP, 'read_status': 'ok'},
]}


def seed_cycle(engine, *, column=True, reference=REFERENCE):
    model_schema(engine)
    t = Base.metadata.tables
    with engine.begin() as c:
        if column:
            kind = 'JSON' if engine.dialect.name == 'postgresql' else 'TEXT'
            c.exec_driver_sql(f'ALTER TABLE soa_cycles ADD COLUMN domain_checks {kind}')   # b4e8f1c3a9d2
        c.execute(t['organizations'].insert(), [{'id': 10, 'name': 'Acme Baby'}])
        c.execute(t['soa_cycles'].insert(), [{
            'id': 229, 'cycle_code': 'FL3-acme-baby-20261014', 'start_date': date(2026, 10, 14), 'status': 'complete',
            'study_type': 'acme', 'study_pattern': 'retailer', 'cycle_mode': 'query', 'organization_id': 10,
            'platforms': ['chatgpt'], 'reference_prices': reference}])
        c.execute(t['soa_queries'].insert(), [{
            'id': 1, 'query_code': 'ACM_1', 'query_text': 'What does the Acme Overnight cost?', 'category': 'Cross-Category',
            'stage': 'Research', 'specificity': 'Narrow', 'persona': 'New / First-Time Parent', 'status': 'Active', 'study_type': 'acme',
            'study_pattern': 'retailer', 'organization_id': 10, 'tier': 'catalog_accuracy',
            'source_ref': {'merchant_slug': 'acme-baby'}}])
        c.execute(t['soa_runs'].insert(), [{'id': 1, 'cycle_id': 229, 'query_id': 1, 'platform': 'chatgpt', 'run_number': 1,
                                            'raw_response': 'a', 'status': 'success', 'surface': 'grounded_api',
                                            'answer_status': 'answered'}])
    return engine


FIXED_NOW = lambda: datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)  # noqa: E731


def test_a_cycle_checks_its_merchants_own_domains(any_engine, network):
    seed_cycle(any_engine)
    supply = Supply()
    record = dc.run_for_cycle(229, engine=any_engine, client=supply, now=FIXED_NOW)
    assert record['merchant'] == 'acme-baby'
    assert record['own_domains'] == ['acmebaby.test'] and record['scored_domain'] == 'acmebaby.test'
    assert record['reference_rows_from'] == 'cycle'
    assert record['domains'][0]['pdp_url'] == PDP           # the own domain's page, not target.test's
    assert 'https://target.test/p/1' not in [u for u, _ in network['requests']]
    assert ('retailer_prices', 'acme-baby') not in supply.calls   # the cycle's own reference read
    assert record['version'] == {'scan': '5', 'extraction_rev': '2', 'adapter_revision': dc.ADAPTER_REVISION}
    assert record['protocol_feed']['score'] == 3.8 and record['value_protocols']['score'] == 9.0


def test_the_record_is_stored_and_read_back(any_engine, network):
    seed_cycle(any_engine)
    record = dc.run_for_cycle(229, engine=any_engine, client=Supply(), now=FIXED_NOW)
    assert dc.store(any_engine, 229, record) is True
    back = dc.stored(any_engine, 229)
    assert back == json.loads(json.dumps(record))
    assert dc.score_entry(back['domains'][0]) == {'protocol_feed': back['protocol_feed'],
                                                  'value_protocols': back['value_protocols']}


def test_without_the_column_nothing_is_written_and_it_says_so(any_engine, network, caplog):
    seed_cycle(any_engine, column=False)
    record = dc.run_for_cycle(229, engine=any_engine, client=Supply(), now=FIXED_NOW)
    assert dc.store(any_engine, 229, record) is False
    assert dc.stored(any_engine, 229) is None
    assert 'migration b4e8f1c3a9d2 not applied' in caplog.text


def test_no_stored_reference_reads_supplys_current_one(any_engine, network):
    seed_cycle(any_engine, reference=None)
    supply = Supply(rows=REFERENCE['prices'])
    record = dc.run_for_cycle(229, engine=any_engine, client=supply, now=FIXED_NOW)
    assert record['reference_rows_from'] == 'supply'
    assert record['domains'][0]['pdp_url'] == PDP


def test_a_brand_merchant_checks_the_brand_site(any_engine, network):
    """A brand merchant's own domain is its brand site; the reference read has
    only retailer pages, so the checks read its store root and protocol files,
    the site is not typed (2E-1), and the probe alone reads the retailer page."""
    network['site']['https://target.test/robots.txt'] = (200, 'User-agent: *\nAllow: /\n', 'text/plain')
    network['site']['https://target.test/p/1'] = (200, (FIX / 'pdp.html').read_text(), 'text/html')
    seed_cycle(any_engine, reference={'prices': [REFERENCE['prices'][0]]})
    record = dc.run_for_cycle(229, engine=any_engine, client=Supply(own=('acmebaby.test',)), now=FIXED_NOW)
    assert record['domains'][0]['pdp_url'] is None
    assert record['value_protocols']['score'] == 9.0
    assert record['protocol_feed']['coverage'] == 'not_measured'
    assert record['signed_probe']['url'] == 'https://target.test/p/1'
    assert record['signed_probe']['page_from'] == dc.FROM_RETAILER
    assert record['signed_probe']['outcome'] == dc.NOT_CHECKED      # no key on the worker in this test


def test_two_own_domains_are_both_recorded_and_the_first_is_scored(any_engine, network):
    network['site']['https://acme-brand.test/robots.txt'] = (404, 'nf', 'text/plain')
    seed_cycle(any_engine)
    record = dc.run_for_cycle(229, engine=any_engine, client=Supply(own=('acmebaby.test', 'acme-brand.test')), now=FIXED_NOW)
    assert [d['domain'] for d in record['domains']] == ['acmebaby.test', 'acme-brand.test']
    assert record['protocol_feed'] == record['domains'][0]['protocol_feed']


# ─── the script, for a cycle scored before 2E ──────────────────────────────

def _script(argv, engine, journal):
    from scripts import run_domain_checks
    out = io.StringIO()
    code = run_domain_checks.main(argv + ['--journal', str(journal)], engine=engine, client=Supply(), out=out)
    return code, out.getvalue()


def test_the_script_dry_run_writes_nothing(any_engine, network, tmp_path):
    seed_cycle(any_engine)
    code, out = _script(['--cycle', '229', '--dry-run'], any_engine, tmp_path / 'j.jsonl')
    assert code == 0
    assert 'dry run — nothing written.' in out
    assert 'protocol_feed     3.8 / 5' in out and 'value_protocols   9.0 / 14' in out
    assert dc.stored(any_engine, 229) is None
    events = [json.loads(line)['event'] for line in (tmp_path / 'j.jsonl').read_text().splitlines()]
    assert events == ['start', 'record', 'end']


def test_the_script_stores_then_refuses_to_replace_without_asking(any_engine, network, tmp_path):
    seed_cycle(any_engine)
    code, out = _script(['--cycle', 'FL3-acme-baby-20261014'], any_engine, tmp_path / 'j.jsonl')
    assert code == 0 and 'stored on soa_cycles.domain_checks, revision 1.' in out
    first = dc.stored(any_engine, 229)
    assert first['merchant'] == 'acme-baby'
    code, out = _script(['--cycle', '229'], any_engine, tmp_path / 'j.jsonl')
    assert code == 2 and '--replace to replace it' in out
    code, out = _script(['--cycle', '229', '--replace'], any_engine, tmp_path / 'j.jsonl')
    assert code == 0
    events = [json.loads(line)['event'] for line in (tmp_path / 'j.jsonl').read_text().splitlines()]
    assert events.count('replaced') == 1


def test_the_script_without_the_column_only_dry_runs(any_engine, network, tmp_path):
    seed_cycle(any_engine, column=False)
    code, out = _script(['--cycle', '229'], any_engine, tmp_path / 'j.jsonl')
    assert code == 2 and 'apply migration b4e8f1c3a9d2 first' in out


# ─── the worker's stage ────────────────────────────────────────────────────

def _orchestrator():
    from orchestrator.pipeline import PipelineOrchestrator
    orch = PipelineOrchestrator.__new__(PipelineOrchestrator)
    orch.cycle = type('Cycle', (), {'id': 229})()
    orch.cycle_code = 'FL3-acme-baby-20261014'
    orch.study_type = 'acme'
    return orch


def _stage(monkeypatch, engine):
    import asyncio

    from clients.truesync_catalog import TrueSyncCatalogClient
    from soa_shared import database
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(TrueSyncCatalogClient, 'for_study', classmethod(lambda cls, st, **kw: Supply()))
    asyncio.run(_orchestrator()._run_domain_checks())


def test_the_worker_runs_the_checks_once_per_cycle_and_keeps_the_record(any_engine, network, monkeypatch):
    seed_cycle(any_engine)
    _stage(monkeypatch, any_engine)
    first = dc.stored(any_engine, 229)
    assert first['protocol_feed']['score'] == 3.8
    n = len(network['requests'])
    _stage(monkeypatch, any_engine)
    assert len(network['requests']) == n          # a re-run fetches nothing and keeps the record
    assert dc.stored(any_engine, 229) == first


def test_the_worker_stage_never_raises(any_engine, network, monkeypatch):
    seed_cycle(any_engine)

    def broken(*a, **k):
        raise RuntimeError('a bug')
    monkeypatch.setattr(dc, 'run_for_cycle', broken)
    _stage(monkeypatch, any_engine)                # no raise
    assert dc.stored(any_engine, 229) is None


def test_the_worker_stage_skips_without_the_column(any_engine, network, monkeypatch):
    seed_cycle(any_engine, column=False)
    _stage(monkeypatch, any_engine)
    assert network['requests'] == []


# ─── the console's fixtures are this module's output ──────────────────────
#
# apps/api reads the record and never imports apps/pipeline, so its tests
# read a record from a file. These two files are written by the code above,
# not by hand: the W&S store's own domain served by the recorded pages, once
# publishing nothing (no llms.txt, no manifest, no protocol markup) and once
# publishing everything the two checks look for. Regenerate with
#
#     WRITE_CONSOLE_FIXTURES=1 pytest tests/test_domain_checks.py -k console_fixtures

import os  # noqa: E402

API_FIXTURES = pathlib.Path(__file__).parents[2] / 'api' / 'tests' / 'fixtures' / 'console'
WS_ORIGIN = 'https://trueshopstore.com'
WS_PDP = f'{WS_ORIGIN}/products/wiggle-snug-diapers-size-3'
WS_HOME_PLAIN = (FIX / 'home.html').read_text().replace('  <link rel="ucp-profile" href="/.well-known/ucp.json">\n', '')


def _ws_site(publishes: bool):
    site = {f'{WS_ORIGIN}/robots.txt': (200, (FIX / 'robots.txt').read_text(), 'text/plain'),
            WS_ORIGIN: (200, (FIX / 'home.html').read_text() if publishes else WS_HOME_PLAIN, 'text/html'),
            WS_PDP: (200, (FIX / 'pdp.html').read_text(), 'text/html')}
    if publishes:
        site[f'{WS_ORIGIN}/llms.txt'] = (200, LLMS_TXT, 'text/plain')
        site[f'{WS_ORIGIN}/.well-known/mcp.json'] = (200, FULL_MANIFEST, 'application/json')
    return site


class _WsSupply(Supply):
    def __init__(self):
        super().__init__(own=('trueshopstore.com',), rows=[{'retailer_domain': 'trueshopstore.com', 'url': WS_PDP,
                                                            'read_status': 'ok', 'method': 'json_ld'}])


def _ws_record(engine, network, publishes):
    network['site'] = _ws_site(publishes)
    with engine.begin() as c:
        c.execute(text("UPDATE soa_queries SET source_ref = :r"), {'r': json.dumps({'merchant_slug': 'wiggle-and-snug'})})
        c.execute(text("UPDATE soa_cycles SET reference_prices = NULL"))
    record = dc.run_for_cycle(229, engine=engine, client=_WsSupply(), now=lambda: datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc))
    record['signed_probe']['key_id'] = record['domains'][0]['signed_probe']['key_id'] = 'test-key'
    return record


@pytest.mark.parametrize('name, publishes', [('domain_checks_ws_none.json', False), ('domain_checks_ws_full.json', True)])
def test_the_console_fixtures_are_this_modules_output(network, signing_on, name, publishes):
    from soa_pg_harness import sqlite_engine
    engine = seed_cycle(sqlite_engine())
    record = json.loads(json.dumps(_ws_record(engine, network, publishes)))
    path = API_FIXTURES / name
    if os.getenv('WRITE_CONSOLE_FIXTURES') == '1':
        path.write_text(json.dumps(record, indent=1) + '\n')
    assert json.loads(path.read_text()) == record
    expected = {False: (0.0, 0.0), True: (3.8, 14.0)}[publishes]
    assert (record['protocol_feed']['score'], record['value_protocols']['score']) == expected
