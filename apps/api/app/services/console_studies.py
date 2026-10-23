"""
2C: the console's Create Study modal, server-side.

The preview is the generation worker's own catalog-tier code
(soa_shared/catalog_tiers.py, moved there from the pipeline so the API can
run it) over a snapshot built from supply the way the worker builds one
(soa_shared/catalog_snapshot.py, apps/pipeline/clients/truesync_catalog.py
TrueSyncCatalogClient.snapshot). What a preview shows is therefore what the
study will contain: the same questions, word for word, with the same typed
expectations, the same variant sample under the cap, and the same tally
against the 100-question cap. Brand-direct is the exception the modal has
always made: a model writes its wording at generation time, so it is a
count and one example marked illustrative.
"""
from typing import Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import text

from soa_shared import catalog_tiers as ct
from soa_shared import expected_answers as ea
from soa_shared.catalog_snapshot import CatalogSnapshot, _now, build_snapshot, merge_merchant_record, merge_reads, price_source
from soa_shared.constants import QUERY_PERSONAS
from soa_shared.database import engine

#: The API validator caps target_count at 100, and catalog-built questions
#: count against the same 100 (CreateStudyModal.jsx MAX_QUESTIONS).
MAX_QUESTIONS = 100
TIER_KEYS = ('brand_direct', 'catalog_accuracy', 'value_incentives', 'category_control')
TIER_SOURCE = {'brand_direct': 'ai_from_catalog', 'catalog_accuracy': 'catalog',
               'value_incentives': 'catalog', 'category_control': 'ai'}
#: 2K-1: the stage whose questions a brand study writes as its comparison
#: tier (generation/query_generator.COMPARISON_STAGE)
COMPARISON_STAGE = 'Comparison'


def comparison_line(count: int) -> str:
    """The preview's Comparison line (generation/syndicated_study.comparison_line
    before any is dropped)."""
    return f"{count} question{'' if count == 1 else 's'}, each naming the brand and a rival"


async def read_snapshot(client, merchant_slug: str) -> CatalogSnapshot:
    """The worker's snapshot (generation path: no price history), read
    with the scope's tenant token. A refused token is a 403, as everywhere;
    every other partial failure costs what it costs the worker."""
    def refused(status, error):
        if status in (401, 403):
            raise HTTPException(status_code=403, detail=f"TrueSync refused this customer's token ({error})")

    status, catalog, error = await client.get_merchant_catalog(merchant_slug)
    if error is not None:
        refused(status, error)
        return CatalogSnapshot(available=False, merchant_slug=merchant_slug, read_at=_now(), error=error)
    m_status, merchants, m_error = await client.get_merchants()
    refused(m_status, m_error)
    i_status, incentives, i_error = await client.get_merchant_incentives(merchant_slug)
    refused(i_status, i_error)
    snapshot = build_snapshot(catalog, merchants=merchants if m_error is None and isinstance(merchants, list) else [],
                              incentives=incentives if i_error is None else None, merchant_slug=merchant_slug)
    t_status, tenant, t_error = await client.get_tenant()
    record = next((m for m in (tenant or {}).get('merchants') or [] if m.get('slug') == merchant_slug), None) \
        if t_error is None else None
    if record is None:
        snapshot.record_error = t_error or f"merchant {merchant_slug!r} is not in this tenant"
        return snapshot
    _, retailers, r_error = await client.get_retailers(merchant_slug)
    feed = None
    if record.get('hosting') == 'external':
        _, feed, f_error = await client.get_feed(merchant_slug)
        if f_error is not None:
            snapshot.record_error = f_error
            feed = None
    merge_merchant_record(snapshot, merchant=record, retailers=retailers if r_error is None else None, feed=feed)
    if snapshot.is_external and snapshot.merchant_kind != 'seller':
        # 2I: a brand's price questions come from the newest page reads.
        p_status, prices, p_error = await client.get_retailer_prices(merchant_slug)
        refused(p_status, p_error)
        merge_reads(snapshot, prices, error=p_error)
    return snapshot


def readback(snapshot: CatalogSnapshot) -> str:
    """"5 products, 19 variants, 6 GTINs, 2 live codes, Member Rewards (2 tiers)"
    (catalogTiers.js catalogReadback, the mock's catalog line)."""
    n = lambda k, word: f"{k} {word}{'' if k == 1 else 's'}"  # noqa: E731
    parts = [n(snapshot.product_count, 'product'), n(snapshot.variant_count, 'variant'),
             n(snapshot.gtin_count, 'GTIN'), n(snapshot.code_count, 'live code')]
    if snapshot.program_name and snapshot.tiers:
        parts.append(f"{snapshot.program_name} ({n(len(snapshot.tiers), 'tier')})")
    return ', '.join(parts)


def _money(amount, currency='USD') -> str:
    amount = ea.normalize_money(amount) if amount is not None else None
    if amount is None:
        return 'not given'
    return f"${amount}" if (currency or 'USD') == 'USD' else f"{amount} {currency}"


def expectation_chips(expected: dict, retailer_name=None) -> List[str]:
    """One typed expectation as the mock's chips: "Expected: $22.99", "GTIN …", "84 count"."""
    kind = expected.get('type')
    chips: List[str] = []
    if kind == 'price':
        at = expected.get('attributed_to')
        if expected.get('amount') is None and at:
            # 2I: a page not read yet: expected as the cycle reads it.
            chips.append(f"Expected: the price at {retailer_name(at) if retailer_name else at}, as read")
        else:
            chips.append(f"Expected: {_money(expected.get('amount'), expected.get('currency'))}"
                         + (f" at {retailer_name(at) if retailer_name else at}" if at else ''))
    elif kind == 'member_price':
        chips.append(f"Expected: {_money(expected.get('amount'), expected.get('currency'))} ({expected.get('tier_name')})")
    elif kind == 'code':
        value = expected.get('value')
        off = {'amount_off': f"{_money(value)} off", 'percent_off': f"{ea.normalize_money(value) or value}% off",
               'member_price': f"member price {_money(value)}"}.get(expected.get('value_kind'), str(value or ''))
        chips.append(f"Expected: {expected.get('code')}, {off}".rstrip(', '))
    elif kind == 'points':
        rule = expected.get('rule') or {}
        chips.append(f"Expected: {rule.get('rate')} per dollar" if rule.get('kind') == 'per_dollar'
                     else f"Expected: {rule.get('points') or rule.get('rate')} points")
    elif kind == 'brand_mention':
        chips.append(f"Expected: brand named{', ' + expected['domain'] + ' cited' if expected.get('domain') else ''}")
    elif kind:
        chips.append(f"Expected: {kind.replace('_', ' ')}")
    for secondary in expected.get('secondary') or []:
        if secondary.get('type') == 'gtin':
            chips.append(f"GTIN {secondary.get('value')}")
        elif secondary.get('type') == 'pack_count':
            chips.append(f"{secondary.get('value')} count")
    return chips


def _question(row: dict) -> dict:
    from soa_shared import retailers
    return {'query_text': row['query_text'], 'tier': row.get('tier'), 'stage': row.get('stage'),
            'provenance': row.get('provenance'), 'expected_answer': row.get('expected_answer'),
            'expected': expectation_chips(row.get('expected_answer') or {}, retailers.retailer_name),
            'variant_id': (row.get('source_ref') or {}).get('variant_id')}


def absorbed_line(absorbed: int, left: int) -> Optional[str]:
    """2L-4: the preview's line under the intent lines, when any were absorbed."""
    if not absorbed and not left:
        return None
    line = f"{absorbed} taken out of the stage counts, Ready to Buy first, so the study stays the size you set"
    if left:
        line = (f"{absorbed} taken out of the stage counts, Ready to Buy first; {left} more than the stages "
                "outside Comparison hold, added to the total")
    return line


def tier_config(tiers: Dict[str, bool], brand_direct_count: Optional[int] = None) -> dict:
    """The request's tier_config, as the web modal's brandPayload() sends it."""
    return {k: ({'enabled': bool(tiers.get(k)), 'count': brand_direct_count or ct.DEFAULT_BRAND_DIRECT_COUNT}
                if k == 'brand_direct' else {'enabled': bool(tiers.get(k))}) for k in TIER_KEYS}


def tally(stage_total: int, tiers: dict) -> dict:
    """Who wrote the question (syndicated_study.tally, catalogTiers.js tallyText):
    brand-direct is AI-written with the catalog open; accuracy and value are
    templates over the record; category control is a tag and adds nothing.
    2L-4: the where-to-buy and cheapest-place questions are templates too,
    and the stage counts absorbed what they could of them."""
    bd = tiers['brand_direct']
    intents = sum(i['count'] for i in bd.get('intents') or []) if bd['enabled'] else 0
    absorbed = (bd.get('absorbed') or 0) if bd['enabled'] else 0
    ai = (stage_total or 0) - absorbed + (bd['count'] if bd['enabled'] else 0)
    catalog = intents + sum(tiers[k]['count'] for k in ('catalog_accuracy', 'value_incentives') if tiers[k]['enabled'])
    total = ai + catalog
    parts = (f"{ai} AI-written + {catalog} from the catalog = {total} questions" if catalog
             else f"{total} question{'' if total == 1 else 's'} total")
    if total == 0:
        return {'ai_written': 0, 'from_catalog': 0, 'total': 0, 'limit': MAX_QUESTIONS, 'within': True,
                'tone': 'off', 'text': 'No questions allocated yet'}
    within = total <= MAX_QUESTIONS
    return {'ai_written': ai, 'from_catalog': catalog, 'total': total, 'limit': MAX_QUESTIONS, 'within': within,
            'tone': 'ok' if within else 'off',
            'text': f"{parts}, within the {MAX_QUESTIONS} limit" if within
            else f"{parts}, over the {MAX_QUESTIONS} limit. Reduce a stage or untick a tier."}


def build_preview(snapshot: CatalogSnapshot, *, tiers: Dict[str, bool], stage_total: int,
                  brand_direct_count: Optional[int] = None, variant_cap: Optional[int] = None,
                  allowed_categories: Optional[List[str]] = None, personas: Optional[List[str]] = None,
                  study_pattern: Optional[str] = None, stage_targets: Optional[Dict[str, int]] = None) -> dict:
    """stage_targets (2K-1): the per-stage counts, when the caller sends
    them; with category control on and a brand, the Comparison stage's are
    the comparison tier, its own line, and category control is the rest."""
    enabled = {k: bool(tiers.get(k)) for k in TIER_KEYS}
    category = (allowed_categories or ['General'])[0] or 'General'
    persona = (personas or [None])[0] or QUERY_PERSONAS[0]
    pattern = study_pattern or 'brand_at_retail'
    cap = variant_cap or ct.DEFAULT_VARIANT_CAP
    out = {k: {'enabled': enabled[k], 'count': 0, 'source': TIER_SOURCE[k], 'questions': []} for k in TIER_KEYS}
    if snapshot.available:
        if enabled['catalog_accuracy']:
            rows, report = ct.build_catalog_accuracy(snapshot, category=category, persona=persona,
                                                     study_pattern=pattern, cap=cap)
            out['catalog_accuracy'].update(count=len(rows), questions=[_question(r) for r in rows],
                                           sampled=report.get('sampled'), variants_available=report.get('variants_available'),
                                           variant_cap=report.get('variant_cap'), unavailable=report.get('unavailable'),
                                           skipped_no_price=report.get('skipped_no_price') or [])
            if 'price_source' in report:
                # 2I: a brand's prices come from its pages as read.
                out['catalog_accuracy'].update(price_source=report['price_source'],
                                               unread_pages=report.get('unread_pages') or [])
        if enabled['value_incentives']:
            rows, report = ct.build_value_incentives(snapshot, category=category, persona=persona, study_pattern=pattern)
            out['value_incentives'].update(count=len(rows), questions=[_question(r) for r in rows],
                                           mechanics=report.get('mechanics'), mechanics_absent=report.get('mechanics_absent'))
            if snapshot.is_external and snapshot.merchant_kind != 'seller' and not rows:
                # 2I (option A): a brand's value tier is its own offers only.
                out['value_incentives']['note'] = "no offers of the brand's own"
        if enabled['brand_direct']:
            first = snapshot.products[0] if snapshot.products else None
            brand = snapshot.study_brand or snapshot.brand
            out['brand_direct'].update(count=brand_direct_count or ct.DEFAULT_BRAND_DIRECT_COUNT, illustrative=True,
                                       questions=[{'query_text': f"Where can I buy {brand}{' ' + first.title if first and first.title else ''}?",
                                                   'tier': 'brand_direct', 'illustrative': True,
                                                   'expected': expectation_chips({'type': 'brand_mention', 'domain': snapshot.domain})}] if brand else [])
            # 2L-4: the two intent lines under Brand-direct, word for word, and
            # what the stage counts absorb of them (catalog_tiers.absorb_intents)
            rows, report = ct.build_intent_questions(snapshot, category=category, persona=persona,
                                                     study_pattern=pattern, cap=cap)
            targets = stage_targets if stage_targets else ({'Ready to Buy': stage_total} if stage_total else {})
            # 2M-1: the attribute questions add to the study; only the two routing intents are absorbed
            _, taken, left = ct.absorb_intents(targets, sum(report[i] for i in ct.ABSORBED_INTENTS))
            out['brand_direct'].update(
                intents=[{'intent': i, 'label': ct.INTENT_LABELS[i], 'count': report[i], 'line': ct.intent_line(i, report[i]),
                          'stage': ct.INTENT_STAGE,
                          'questions': [_question(r) for r in rows if (r.get('source_ref') or {}).get('intent') == i]}
                         for i in ct.INTENTS if report[i]],
                absorbed=sum(taken.values()), absorbed_by_stage=taken, not_absorbed=left,
                absorbed_line=absorbed_line(sum(taken.values()), left))
        for k in TIER_KEYS:
            if enabled[k]:
                out[k]['expected_nulls'] = ct.expected_nulls(snapshot, k)
    else:
        for k in ('brand_direct', 'catalog_accuracy', 'value_incentives'):
            if enabled[k]:
                out[k]['unavailable'] = snapshot.error or 'catalog unavailable'
    if enabled['category_control']:
        # 2I-7: the generator checks every one against the brand's terms
        # (soa_shared/unprompted.py) and drops one that still names it
        n = stage_total or 0
        brand = snapshot.study_brand or snapshot.brand
        compared = int((stage_targets or {}).get(COMPARISON_STAGE) or 0) if brand else 0
        # 2L-4: what the intent questions took out of the stage counts
        n = max(n - (out['brand_direct'].get('absorbed') or 0), 0)
        if compared:
            n = max(n - compared, 0)
            out['comparison'] = {'enabled': True, 'count': compared, 'additive': False, 'source': 'ai',
                                 'questions': [], 'stage': COMPARISON_STAGE, 'line': comparison_line(compared)}
        out['category_control'].update(
            count=n, additive=False, checked=bool(brand),
            line=(f"{n} question{'' if n == 1 else 's'}, none naming the brand" if brand
                  else f"{n} question{'' if n == 1 else 's'}, not checked: no brand to check against"))
    return {
        'merchant': {'slug': snapshot.merchant_slug, 'brand': snapshot.brand, 'domain': snapshot.domain,
                     'kind': snapshot.merchant_kind, 'hosting': snapshot.hosting, 'available': snapshot.available,
                     'error': snapshot.error, 'record_error': snapshot.record_error, 'read_at': snapshot.read_at,
                     'products': snapshot.product_count, 'variants': snapshot.variant_count,
                     'gtins': snapshot.gtin_count, 'codes': snapshot.code_count,
                     'readback': readback(snapshot) if snapshot.available else None},
        'tiers': out,
        'stage_total': stage_total or 0,
        'tally': tally(stage_total, out),
    }


class _PrefetchedSupply:
    """2I-5: the two supply reads soa_shared.comparison_sets makes, read
    beforehand with the org's async client and answered synchronously."""

    def __init__(self, record, record_error, retailers, retailers_error):
        self._record, self._retailers = (record, record_error), (retailers, retailers_error)

    def merchant_record(self, slug):
        return self._record

    def retailers(self, slug):
        return self._retailers


async def prefetch_supply(client, merchants: List[dict], merchants_error: Optional[str], slug: str) -> _PrefetchedSupply:
    """The merchant's /tenant record (the switcher's read) and its /retailers."""
    record = next((m for m in merchants if m.get('slug') == slug), None)
    record_error = None if record else (merchants_error or f"merchant {slug!r} is not in this tenant")
    _status, body, error = await client.get_retailers(slug)
    return _PrefetchedSupply(record, record_error, body if isinstance(body, dict) else None, error)


def study_in_org(study_type: str, org_id: int) -> bool:
    with engine.connect() as conn:
        return conn.execute(text("""
            SELECT 1 FROM soa_query_generation_jobs
            WHERE study_type = :st AND COALESCE(customer_organization_id, organization_id) = :org
        """), {"st": study_type, "org": org_id}).fetchone() is not None
        last = conn.execute(text("""
            SELECT id FROM soa_cycles WHERE study_type = :st ORDER BY start_date DESC, id DESC LIMIT 1
        """), {"st": study_type}).scalar()
        if last is not None:
            rows = conn.execute(text("""
                SELECT entity_id, comparison_code, role FROM soa_cycle_entities WHERE cycle_id = :c ORDER BY id
            """), {"c": last}).mappings().all()
            if rows:
                return [dict(r) for r in rows]
        if job['syndicated_merchant']:
            entity = conn.execute(text("SELECT id FROM soa_entities WHERE slug = :s"),
                                  {"s": job['syndicated_merchant']}).scalar()
            if entity is not None:
                return [{'entity_id': entity, 'comparison_code': 'M001', 'role': 'primary'}]
    return []
