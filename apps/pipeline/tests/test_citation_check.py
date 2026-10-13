"""
2B §2: fabricated_citation.

The September Gemini answer that cited wiggleandsnug.com when it did not
resolve is the fixture (golden row seed5_row40). That domain resolves now,
so the test replays the recorded DNS failure through an injected resolver:
nothing here performs a live lookup or a live request.
"""
import json
import os
import socket
from datetime import datetime, timedelta, timezone

import pytest

from scoring import expectation_comparator as cmp
from scoring.citation_check import (
    CACHE_TTL, DomainCheck, DomainChecker, MemoryDomainCheckStore,
)
from soa_shared import expected_answers as ea

FIXTURES = os.path.join(os.path.dirname(__file__), 'fixtures')
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)


def _pinned():
    with open(os.path.join(FIXTURES, 'citation_checks', 'wiggleandsnug_com_dns_failure.json')) as fh:
        return json.load(fh)


def _golden_row():
    path = os.path.join(FIXTURES, 'extraction_golden', _pinned()['golden_row'])
    with open(path) as fh:
        return json.load(fh)


class RecordedResolver:
    """Replays the pinned failure for its domain; anything else resolves
    to a public-range literal; the prober is fake, so nothing is contacted."""

    def __init__(self, failures):
        self.failures = failures
        self.calls = []

    def __call__(self, domain):
        self.calls.append(domain)
        if domain in self.failures:
            raise socket.gaierror(self.failures[domain])
        return ['93.184.215.14']


class FixedProber:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def __call__(self, url, timeout):
        self.calls.append(url)
        return self.status


def checker(store=None, clock=None, status=200, failures=None):
    pinned = _pinned()
    resolver = RecordedResolver(failures if failures is not None
                                else {pinned['domain']: pinned['resolver_error']})
    prober = FixedProber(status)
    return DomainChecker(resolver=resolver, prober=prober, store=store or MemoryDomainCheckStore(),
                         clock=clock or (lambda: NOW)), resolver, prober


def test_the_september_gemini_citation_is_fabricated():
    row = _golden_row()
    assert row['platform'] == 'gemini'
    assert 'wiggleandsnug.com' in row['as_extracted']['sources_cited']

    check_, _resolver, prober = checker()
    result = check_.check('wiggleandsnug.com')
    assert result.fabricated and result.resolves is False
    assert prober.calls == []  # nothing to request on a name that does not resolve


def test_the_flag_is_on_the_answer_not_a_span():
    row = _golden_row()
    check_, *_ = checker()
    dead = {d: check_.check(d).as_dict() for d in row['as_extracted']['sources_cited']
            if check_.check(d).fabricated}
    verdict = cmp.compare(ea.brand_mention('Wiggle & Snug', 'trueshopstore.com'),
                          row['as_extracted'], tier='brand_direct',
                          brand_domain='trueshopstore.com', dead_domains=dead)
    (flag,) = [f for f in verdict.flags if f['flag'] == 'fabricated_citation']
    assert flag['domains'][0]['domain'] == 'wiggleandsnug.com'
    # The outcome is the brand classifier's, untouched by the flag.
    assert verdict.outcome in ea.BRAND_OUTCOMES


def test_once_per_domain_per_cycle():
    check_, resolver, prober = checker()
    for _ in range(5):
        check_.check('target.com')
    assert resolver.calls == ['target.com']
    assert check_.live_checks == 1


def test_the_24h_cache_across_batches():
    store = MemoryDomainCheckStore()
    first, *_ = checker(store=store, clock=lambda: NOW)
    first.check('target.com')
    second, resolver, _ = checker(store=store, clock=lambda: NOW + timedelta(hours=23))
    second.check('target.com')
    assert resolver.calls == [] and second.live_checks == 0
    third, resolver, _ = checker(store=store, clock=lambda: NOW + CACHE_TTL + timedelta(minutes=1))
    third.check('target.com')
    assert resolver.calls == ['target.com']


def test_any_http_status_is_a_response():
    check_, *_ = checker(status=403)
    result = check_.check('target.com')
    assert result.responds is True and not result.fabricated


def test_resolving_without_any_response_is_fabricated():
    check_, _resolver, prober = checker(status=None)
    result = check_.check('example-dead-root.com')
    assert result.fabricated and result.resolves is True and result.responds is False
    assert prober.calls == ['https://example-dead-root.com/', 'http://example-dead-root.com/']


def test_a_private_address_is_never_requested_and_never_fabricated():
    check_ = DomainChecker(resolver=lambda d: ['10.0.0.5'], prober=FixedProber(),
                           store=MemoryDomainCheckStore(), clock=lambda: NOW)
    result = check_.check('intranet.example')
    assert result.responds is None and not result.fabricated


def test_the_honest_ua_is_the_declared_bot():
    from scan.fetcher import USER_AGENT
    import inspect
    from scoring import citation_check
    assert 'USER_AGENT' in inspect.getsource(citation_check.default_prober)
    assert 'Parleo' in USER_AGENT or 'parleo' in USER_AGENT.lower()


def test_a_cached_row_round_trips():
    check = DomainCheck('x.com', False, None, 'does not resolve', NOW.isoformat())
    assert check.as_dict()['fabricated'] is True
