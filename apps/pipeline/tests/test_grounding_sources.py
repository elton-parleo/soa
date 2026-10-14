"""
Grounding sources: what each grounded runner keeps (runners/grounding.py),
how the brand-direct classifier reads it, the merchant's own-domain list,
the programme-name rule, and the redirect backfill. No network, no model.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from runners import grounding as gr
from runners.gemini_grounded_runner import GeminiGroundedRunner
from scoring import brand_direct_classifier as bdc
from scoring import expectation_comparator as cmp
from scripts import resolve_grounding_redirects as rgr
from soa_shared import expected_answers as ea
from soa_shared.catalog_snapshot import CatalogSnapshot, merge_merchant_record

REDIRECT = 'https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQ'
CLAIM = 'It is listed as "In stock" for $6.99 on the Wiggle & Snug website.'
FACTS = {'brand': 'Wiggle & Snug', 'domain': 'trueshopstore.com',
         'own_domains': ['trueshopstore.com', 'wiggleandsnug.com'],
         'retailer_list': ['trueshopstore.com'], 'program_name': 'Member Rewards',
         'tier_names': ['Member', 'Member+'], 'product_titles': ['Snug-Fit Trial Pack']}
EXPECTATION = ea.brand_mention('Wiggle & Snug', 'trueshopstore.com')


def claim(text, kind='retail'):
    return {'claim': text, 'claim_kind': kind, 'kind': 'assertion', 'modality': 'asserted',
            'effective_modality': 'asserted'}


def extraction(claims=(), sources=(), tiers=()):
    return {'brand_mentioned': True, 'brand_claims': list(claims), 'sources_cited': list(sources),
            'loyalty_tiers_named': list(tiers), 'other_brands_named': [],
            'retailer_mentions': [], 'extraction_confident': True}


def grounding_at(domain, segment=CLAIM):
    return {'sources': [{'uri': REDIRECT, 'title': domain, 'domain': domain}],
            'supports': [{'text': segment, 'start': 0, 'end': 10, 'sources': [0]}]}


# ═══ Runners ══════════════════════════════════════════════════════════════

def _gemini_response():
    web = [SimpleNamespace(uri=f'{REDIRECT}1', title='wiggleandsnug.com', domain=None),
           SimpleNamespace(uri=f'{REDIRECT}2', title='Huggies Little Snugglers', domain='huggies.com')]
    supports = [SimpleNamespace(segment=SimpleNamespace(start_index=0, end_index=66, text=CLAIM),
                                grounding_chunk_indices=[0])]
    meta = SimpleNamespace(grounding_chunks=[SimpleNamespace(web=w) for w in web],
                           grounding_supports=supports)
    return SimpleNamespace(text=CLAIM, candidates=[SimpleNamespace(grounding_metadata=meta)],
                           usage_metadata=SimpleNamespace(prompt_token_count=1,
                                                          candidates_token_count=2))


def test_gemini_keeps_title_domain_and_supports():
    runner = GeminiGroundedRunner()
    runner._client.aio.models.generate_content = AsyncMock(return_value=_gemini_response())
    result = asyncio.run(runner._call_api('q'))
    assert result.retrieved_sources == [f'{REDIRECT}1', f'{REDIRECT}2']
    sources = result.grounding['sources']
    # The title names the site; the redirect host never does.
    assert [s['domain'] for s in sources] == ['wiggleandsnug.com', 'huggies.com']
    assert result.grounding['supports'] == [
        {'text': CLAIM, 'start': 0, 'end': 66, 'sources': [0]}]


def test_a_redirect_with_no_site_title_has_no_domain():
    assert gr.source(REDIRECT, 'Diaper sizing guide')['domain'] is None
    assert gr.source('https://www.huggies.com/en-us')['domain'] == 'huggies.com'


def test_openai_url_citations_are_supports():
    text = 'Size 2 fits 12-18 lb. More text.'
    output = [
        {'type': 'web_search_call', 'action': {'sources': [{'url': 'https://huggies.com/a'}]}},
        {'type': 'message', 'content': [{'type': 'output_text', 'text': text, 'annotations': [
            {'type': 'url_citation', 'url': 'https://huggies.com/a', 'title': 'Huggies',
             'start_index': 0, 'end_index': 21}]}]},
    ]
    result = gr.from_openai(output, text)
    assert result['sources'] == [{'uri': 'https://huggies.com/a', 'title': 'Huggies',
                                  'domain': 'huggies.com'}]
    assert result['supports'] == [{'text': 'Size 2 fits 12-18 lb.', 'start': 0, 'end': 21,
                                   'sources': [0]}]


def test_perplexity_markers_are_supports():
    response = SimpleNamespace(citations=['https://trueshopstore.com/p', 'https://huggies.com'],
                               search_results=[{'url': 'https://trueshopstore.com/p',
                                                'title': 'Trial Pack'}])
    result = gr.from_perplexity(response, 'It costs $6.99.[1] Huggies differ.[2][1]')
    assert result['sources'][0] == {'uri': 'https://trueshopstore.com/p', 'title': 'Trial Pack',
                                    'domain': 'trueshopstore.com'}
    assert [(s['text'], s['sources']) for s in result['supports']] == [
        ('It costs $6.99.', [0]), ('Huggies differ.', [0, 1])]


def test_serpapi_reference_indexes_are_supports():
    body = {'references': [{'index': 0, 'title': 'babylist.com', 'link': 'https://www.babylist.com/x'}],
            'text_blocks': [{'type': 'paragraph', 'snippet': 'Huggies are unscented.',
                             'reference_indexes': [0]}]}
    result = gr.from_serpapi(body)
    assert result['sources'][0]['domain'] == 'babylist.com'
    assert result['supports'] == [{'text': 'Huggies are unscented.', 'start': None, 'end': None,
                                   'sources': [0]}]


# ═══ Classifier ═══════════════════════════════════════════════════════════

def classify(ext, grounding=None, facts=FACTS):
    return bdc.classify_with_code(ext, EXPECTATION, brand_facts=facts, grounding=grounding)


def test_a_claim_backed_by_a_merchant_support_is_grounded():
    outcome, reason, code = classify(extraction([claim(CLAIM)]), grounding_at('wiggleandsnug.com'))
    assert outcome == bdc.GROUNDED
    assert code == bdc.CODE_GROUNDING_SUPPORT
    assert 'wiggleandsnug.com' in reason


def test_a_listed_retailer_support_grounds_too():
    facts = {**FACTS, 'own_domains': ['wiggleandsnug.com'], 'domain': None,
             'retailer_list': ['target.com']}
    outcome, _reason, _code = classify(extraction([claim(CLAIM)]), grounding_at('target.com'), facts)
    assert outcome == bdc.GROUNDED


def test_a_support_elsewhere_or_unresolved_grounds_nothing():
    for grounding in (grounding_at('huggies.com'), grounding_at(None)):
        outcome, reason, _code = classify(extraction([claim(CLAIM)]), grounding)
        assert outcome == bdc.FABRICATED
        assert 'stated with no source' in reason


def test_every_unsourced_claim_still_counts():
    """One claim grounded, another with no support: still fabricated."""
    ext = extraction([claim(CLAIM), claim('Wiggle & Snug ships to Canada for free.')])
    outcome, _reason, _code = classify(ext, grounding_at('wiggleandsnug.com'))
    assert outcome == bdc.FABRICATED


def test_a_short_claim_is_not_covered_by_containment_alone():
    assert not bdc._covers('Yes, it is still available to buy today.', 'Yes')


def test_text_citations_work_as_before():
    outcome, reason, code = classify(extraction([claim(CLAIM)], sources=['trueshopstore.com']))
    assert (outcome, reason, code) == (bdc.GROUNDED, 'cited trueshopstore.com', None)


def test_own_domains_is_a_list():
    outcome, reason, code = classify(extraction([claim(CLAIM)], sources=['wiggleandsnug.com']))
    assert (outcome, code) == (bdc.GROUNDED, bdc.CODE_OWN_DOMAINS)
    # Without the list, the same answer names nothing of W&S's.
    single = {**FACTS, 'own_domains': ['trueshopstore.com']}
    assert classify(extraction([], sources=['wiggleandsnug.com']), facts=single)[0] == bdc.ECHOED


def test_an_ownership_claim_at_any_own_domain_is_not_contradicted():
    ext = extraction([claim('Their official website is wiggleandsnug.com.', 'ownership')],
                     sources=['trueshopstore.com'])
    assert classify(ext)[0] == bdc.GROUNDED


def test_the_programme_name_is_not_a_tier():
    ext = extraction([claim(CLAIM)], sources=['trueshopstore.com'], tiers=['Member Rewards'])
    outcome, _reason, code = classify(ext)
    assert (outcome, code) == (bdc.GROUNDED, bdc.CODE_PROGRAM_NAME)
    invented = extraction([claim(CLAIM)], sources=['trueshopstore.com'],
                          tiers=['Member Rewards', 'Snuggle Pal'])
    assert classify(invented)[0] == bdc.FABRICATED


def test_the_comparator_carries_grounding_and_the_code():
    verdict = cmp.compare(EXPECTATION, extraction([claim(CLAIM)]), tier='brand_direct',
                          brand_facts=FACTS, grounding=grounding_at('wiggleandsnug.com'),
                          retrieved_sources=[REDIRECT])
    assert verdict.outcome == bdc.GROUNDED
    assert verdict.reason_code == bdc.CODE_GROUNDING_SUPPORT
    # The split names the site, not the redirector, and knows it is W&S's.
    assert verdict.source_split == {'own_domain': ['wiggleandsnug.com'], 'listed_retailer': [],
                                    'other': []}


# ═══ The record's own domains ═════════════════════════════════════════════

def test_snapshot_reads_own_domains_from_the_record():
    snapshot = merge_merchant_record(
        CatalogSnapshot(merchant_slug='wiggle-and-snug', available=True), merchant={'domain': 'trueshopstore.com'},
        retailers={'own_domain': 'trueshopstore.com',
                   'own_domains': ['trueshopstore.com', 'https://www.wiggleandsnug.com/']})
    assert snapshot.own_domain == 'trueshopstore.com'
    assert snapshot.own_domains == ['trueshopstore.com', 'wiggleandsnug.com']


def test_snapshot_without_a_list_has_its_one_domain():
    snapshot = merge_merchant_record(CatalogSnapshot(merchant_slug='x', available=True),
                                     merchant={'domain': 'acmebaby.example'})
    assert snapshot.own_domains == ['acmebaby.example']


# ═══ Redirect backfill ════════════════════════════════════════════════════

NOW = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)


def test_backfill_builds_grounding_and_resolves_each_uri_once():
    calls = []

    def resolver(uri):
        calls.append(uri)
        return {'resolved_url': 'https://trueshopstore.com/', 'status': 200}

    memo = {}
    first, counts = rgr.resolve_run([REDIRECT, 'https://huggies.com/a'], None,
                                    resolver=resolver, now=NOW, memo=memo)
    assert [s['domain'] for s in first['sources']] == ['trueshopstore.com', 'huggies.com']
    assert first['sources'][0]['resolved_at'] == NOW.isoformat()
    assert first['supports'] == []
    rgr.resolve_run([REDIRECT], None, resolver=resolver, now=NOW, memo=memo)
    assert calls == [REDIRECT]  # the direct URL is never requested; the redirect once
    assert counts['resolved'] == 1


def test_backfill_records_a_failure_and_retries_after_24_hours():
    failed, counts = rgr.resolve_run([REDIRECT], None, resolver=lambda u: {'error': 'ConnectError'},
                                     now=NOW)
    assert failed['sources'][0]['domain'] is None
    assert failed['sources'][0]['resolve_error'] == 'ConnectError'
    assert counts['failed'] == 1

    def never(uri):
        raise AssertionError('cached for 24 hours')

    _same, counts = rgr.resolve_run([REDIRECT], failed, resolver=never, now=NOW + timedelta(hours=23))
    assert counts['cached'] == 1
    later, counts = rgr.resolve_run(
        [REDIRECT], failed, now=NOW + timedelta(hours=25),
        resolver=lambda u: {'resolved_url': 'https://www.wiggleandsnug.com/x', 'status': 200})
    assert later['sources'][0]['domain'] == 'wiggleandsnug.com'
    assert 'resolve_error' not in later['sources'][0]
