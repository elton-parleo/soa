"""
2R-2: manufacturer mode, under /api/console/. A brand at retail: supply
(parleo-supply-app#33) compiles its records from its SKU feed and holds them;
the brand's own team sends them.

    GET  /api/console/rules?merchant=<slug>              the compliance rules, their approval, the backtest (B2)
    PUT  /api/console/rules/{code}?merchant=<slug>        on / approval / note, forwarded to supply (operator only) (B2)
    GET  /api/console/publishing?merchant=<slug>          surfaces, diff, preview, artifacts (B1's objects) (B2)
    POST /api/console/publishing/compile?merchant=&dry_run=  compile and hold the brand's records (operator only) (2R-2a A2)
    POST /api/console/publishing/sent?merchant=<slug>     the brand states it sent a held file (B3)
    GET  /api/console/truesync/artifact?merchant=&channel=[&publication_id=]  the compiled file, through soa (B4)

/truesync carries the same surfaces, diff, preview and artifacts when the
merchant is in manufacturer mode (publishing_view, called from console.py),
so the two screens never disagree; /revenue carries Impact's `locked` block
(impact_block). Supply is read and written with the org's tenant token,
server-side: the token never reaches the browser, the file included. The
builders are app/services/console_manufacturer.py; the counts are the
Overview's own helpers (console.py's _routing_inputs, _visibility,
_promo_inputs, the cached attribute answers), never a second implementation.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import verify_token
from app.console_merchants import MerchantScope, check_merchant, merchant_cycles
from app.console_scope import console_scope
from app.customer_context import CustomerScope
from app.routers import full_loop
from app.routers.console import (_baseline_rows, _compared, _json, _merchant_meta, _promo_inputs, _reads,
                                 _routing_inputs, _rows, _true_value_inputs, _visibility)
from app.routers.console_ops import operator_scope
from app.routers.truesync import _unwrap
from app.services import console_cache
from app.services import console_manufacturer as manu
from app.services import console_read_models as rm
from app.services import console_release as rel
from app.services import console_score as score_svc
from soa_shared import severity, surfaces
from soa_shared.database import engine

router = APIRouter(prefix="/console", tags=["console-manufacturer"])

#: supply's file headers soa passes through (#33: every file response carries them).
ARTIFACT_HEADERS = ('content-disposition', 'x-truesync-compiled-at', 'x-truesync-record-count',
                    'x-truesync-validator', 'x-truesync-merchant-kind', 'x-truesync-mode', 'x-truesync-reason')


def _record(ms: MerchantScope) -> Optional[dict]:
    return next((m for m in ms.merchants or [] if m.get('slug') == ms.slug), None)


async def _manufacturer(scope: CustomerScope, merchant: str) -> tuple:
    """(MerchantScope, the merchant's /tenant record) for a merchant in
    manufacturer mode; 404 for one that is not (or a slug not the org's)."""
    ms = await check_merchant(scope, merchant)
    record = _record(ms)
    if not manu.is_manufacturer(record):
        raise HTTPException(status_code=404, detail=f"merchant {merchant!r} is not in manufacturer mode")
    return ms, record


def _scored_cycles(ms: MerchantScope) -> List[dict]:
    """The merchant's complete, scored cycles, newest first."""
    with engine.connect() as conn:
        scored = {r[0] for r in conn.execute(text("SELECT DISTINCT cycle_id FROM soa_expectation_outcomes"))}
        return [{**c, 'customer_org_id': ms.scope.org.id} for c in merchant_cycles(conn, ms)
                if c['id'] in scored and c.get('status') == 'complete']


def _listing_ids(catalog: Optional[dict]) -> List:
    return [l.get('listing_id') for l in (catalog or {}).get('listings') or []]


def _brand(catalog: Optional[dict]) -> Optional[str]:
    return (catalog or {}).get('brand') or next((l.get('brand') for l in (catalog or {}).get('listings') or []
                                                 if l.get('brand')), None)


def _own_domain(retailers: Optional[dict], record: Optional[dict]) -> Optional[str]:
    own = ((retailers or {}).get('own_domains') or [None])[0] or (retailers or {}).get('own_domain') or \
        ((record or {}).get('own_domains') or [None])[0] or (record or {}).get('domain')
    return str(own).lower().removeprefix('www.') if own else None


async def _held_inputs(scope: CustomerScope, merchant: str) -> tuple:
    """(catalog, the merchant's publications, errors): what the sent facts and
    the artifacts read."""
    client = full_loop._client(scope)
    (k_status, catalog, k_err), (_, pubs, p_err) = await asyncio.gather(
        _reads(scope).get_merchant_catalog(merchant), client.get_publications(limit=1000))
    errors = {'publications': p_err} if p_err else {}
    if k_err is not None and k_status != 404:
        errors['catalog'] = k_err
    mine = manu.merchant_publications(pubs or [], _listing_ids(catalog), merchant) if p_err is None else []
    return (catalog if k_err is None else None), mine, errors


def named_by_variant(conn, cycle: dict) -> dict:
    """{variant id or sku: [store names, most named first]}: the stores the
    cycle's answered where-to-buy and cheapest-place answers about the SKU sent
    the shopper to (rm.stores_in_order: `named_stores`, else the Layer 2
    coding, as Visibility's routing reads them)."""
    rows = conn.execute(text("""
        SELECT r.id, q.source_ref, o.extraction, r.answer_status FROM soa_runs r
        JOIN soa_queries q ON q.id = r.query_id JOIN soa_expectation_outcomes o ON o.run_id = r.id
        WHERE r.cycle_id = :c AND q.tier = 'brand_direct' ORDER BY r.id
    """), {'c': cycle['id']}).mappings().all()
    counts: dict = {}
    for r in rows:
        ref = rm._json(r['source_ref']) or {}
        if ref.get('intent') not in rm.ROUTING_INTENTS or (r['answer_status'] or 'answered') != 'answered':
            continue
        stores = rm.stores_in_order(rm._json(r['extraction'])) or []
        for key in {ref.get('variant_id'), ref.get('sku')} - {None}:
            bucket = counts.setdefault(key, {})
            for i, st in enumerate(stores):
                n, first = bucket.get(st['name'], (0, (r['id'], i)))
                bucket[st['name']] = (n + 1, first)
    return {k: [name for name, _ in sorted(b.items(), key=lambda kv: (-kv[1][0], kv[1][1]))] for k, b in counts.items()}


async def brand_reads(scope: CustomerScope, merchant: str) -> dict:
    """supply's reads a brand at retail's TrueSync, Publishing and Overview
    share, in one round: {rules, feed, retailers, prices (retailer-prices
    rows), errors}; a failed read is None and named in `errors`."""
    client = full_loop._client(scope)
    (_, rules, rules_err), (f_status, feed, f_err), (_, retailers, o_err), (_, prices, rp_err) = await asyncio.gather(
        client.get_rules(merchant), client.get_feed(merchant), _reads(scope).get_retailers(merchant),
        client.get_retailer_prices(merchant))
    errors = {n: e for n, e in (('rules', rules_err), ('retailers', o_err), ('retailer_prices', rp_err)) if e}
    if f_err is not None and f_status != 404:   # a merchant with no feed has no sellers to compare
        errors['feed'] = f_err
    return {'rules': (rules or {}).get('rules') if rules_err is None else None,
            'feed': feed if f_err is None else None,
            'retailers': retailers if o_err is None else None,
            'prices': (prices or {}).get('prices') if rp_err is None else None,
            'errors': errors}


async def publishing_view(scope: CustomerScope, ms: MerchantScope, merchant: str, *, channels: List[dict],
                          publications: List[dict], catalog: Optional[dict], reference: Optional[dict],
                          drift: List[dict], reads: Optional[dict] = None) -> dict:
    """B1: {mode, surfaces, diff, preview, artifacts, cycle, read_errors} for
    a merchant in manufacturer mode, from the reads /truesync already holds
    (channels, publications, catalog, reference and its weight rows), the
    merchant's /tenant record (`held`), its rules, feed, retailer list and
    brand pages (retailer-prices, brand_reads: `reads` when the caller
    already holds them), and the newest scored cycle's answers."""
    record = _record(ms)
    reads = reads if reads is not None else await brand_reads(scope, merchant)
    errors = dict(reads['errors'])
    pubs = manu.merchant_publications(publications, _listing_ids(catalog), merchant)
    own = _own_domain(reads['retailers'], record)
    price_rows = reads['prices']
    pages = manu.brand_pages(price_rows, [own] if own else [])
    read_at = manu.brand_page_read_at(price_rows)
    feed_rows = (reads['feed'] or {}).get('rows') if reads['feed'] is not None else None
    flags = manu.gtin_flags(pages, feed_rows, brand=_brand(catalog))
    held = (record or {}).get('held')
    surfaces = manu.build_surfaces(pubs=pubs, channels=channels, drift=drift, reference=reference, pages=pages,
                                   flags=flags, own_domain=own, held=held, read_at=read_at, rules=reads['rules'])
    cycles = _scored_cycles(ms)
    cycle = cycles[0] if cycles else None
    lifecycle, sellers = [], []
    if cycle is not None:
        facts, routing_errors = await _routing_inputs(scope, cycle, merchant)
        errors.update(routing_errors)
        with engine.connect() as conn:
            vis = _visibility(conn, cycle, facts, routing_errors)
            named = named_by_variant(conn, cycle)
        lifecycle = manu.lifecycle_rows(vis.get('retired_named'), cycle)
        sellers = manu.seller_rows(named, feed_rows, cycle, own_domains=[own] if own else [])
    return {
        'mode': manu.MANUFACTURER,
        'surfaces': surfaces,
        'diff': manu.build_diff(drift=drift, flags=flags, lifecycle=lifecycle, sellers=sellers, cycle=cycle,
                                read_at=read_at),
        'preview': manu.build_preview(surfaces=surfaces, brand=_brand(catalog), name=(record or {}).get('name'),
                                      domain=own),
        'artifacts': manu.build_artifacts(merchant, pubs, channels, held),
        'held': held,
        'cycle': (cycle or {}).get('cycle_code'),
        'read_errors': errors,
    }


async def cycle_facts(scope: CustomerScope, cycle: dict, merchant: str, reference: Optional[dict]) -> dict:
    """2T-1 (B3): what one cycle's answers say, as the Overview's own helpers
    read them (no second count): the attribute answers (cached per cycle and
    reference, as the Overview keeps them), the True Value rows (each
    retailer's live price and the agents' quotes), the promo pass-through
    with its judged answers and supply's deals that day, the agents that ran."""
    with engine.connect() as conn:
        asks = rm.asks_attribute(conn, cycle)
        answers = console_cache.cycle_read(conn, cycle, 'attribute_answers', lambda: rm.attribute_answers(
            conn, cycle, reference), console_cache.digest(reference)) if asks else []
        own_domain, variants, scored = _true_value_inputs(conn, cycle)
        platforms = [r[0] for r in conn.execute(text("SELECT DISTINCT platform FROM soa_runs WHERE cycle_id = :c"),
                                                {'c': cycle['id']})]
    tv = rm.build_true_value(_json(cycle.get('reference_prices')), scored, own_domain=own_domain,
                             record_variants=variants, reads=(reference or {}).get('rows'))
    promo, deals, _as_of, p_err = await _promo_inputs(scope, cycle, merchant)
    return {'attribute_answers': answers, 'true_value_rows': tv.get('rows') or [], 'promo': promo, 'deals': deals,
            'agents': sorted({surfaces.agent_of(p) or p for p in platforms if p}),
            'errors': {'deals': p_err} if p_err else {}}


async def release_view(scope: CustomerScope, ms: MerchantScope, merchant: str, *, channels: List[dict],
                       publications: List[dict], catalog: Optional[dict], reference: Optional[dict],
                       reads: Optional[dict] = None, cycle: Optional[dict] = None,
                       facts: Optional[dict] = None) -> dict:
    """2T-1 (B3): TrueSync as a release page for a brand at retail:
    {workspace, release, destinations, records (the matrix, one row per held
    record), releases, cell_states, pass_channels, read_errors}. `cycle` the
    cycle whose answers the readback reads (the newest scored one when not
    given), `facts` its cycle_facts when the caller already holds them. The
    Overview's TrueSync card reads the same workspace: no second count."""
    record = _record(ms)
    reads = reads if reads is not None else await brand_reads(scope, merchant)
    errors = dict(reads['errors'])
    pubs = manu.merchant_publications(publications, _listing_ids(catalog), merchant)
    own = _own_domain(reads['retailers'], record)
    own_domains = [own] if own else []
    if cycle is None:
        cycles = _scored_cycles(ms)
        cycle = cycles[0] if cycles else None
    if facts is None and cycle is not None:
        facts = await cycle_facts(scope, cycle, merchant, reference)
    facts = facts or {}
    errors.update(facts.get('errors') or {})
    brand, name = _brand(catalog), (record or {}).get('name') or merchant
    feed = reads['feed'] or {}
    records = rel.build_records(
        pubs=pubs, catalog=catalog, feed_rows=feed.get('rows'), prices=reads['prices'],
        retailers=(reads['retailers'] or {}).get('domains') or [], own_domains=own_domains, channels=channels,
        brand=brand, cycle=cycle, attribute_answers=facts.get('attribute_answers') or [],
        true_value_rows=facts.get('true_value_rows') or [], promo=facts.get('promo'), deals=facts.get('deals'),
        agents=facts.get('agents') or [], rules=reads['rules'])
    return {
        'workspace': rel.build_workspace(pubs=pubs, records=records, prices=reads['prices'], own_domains=own_domains,
                                         brand=brand or name, domain=own),
        'release': rel.build_release(pubs=pubs, records=records, channels=channels, rules=reads['rules'], name=name,
                                     brand=brand),
        'destinations': rel.build_destinations(pubs=pubs, all_pubs=publications, merchants=ms.merchants or [],
                                               slug=merchant, name=name, brand=brand, domain=own, channels=channels),
        'records': records,
        'releases': rel.build_releases(pubs=pubs, feed_version=feed.get('version'), rules=reads['rules']),
        'cell_states': list(rel.CELL_STATES),
        'pass_channels': rel.pass_channels(pubs),
        'readback_cycle': (cycle or {}).get('cycle_code'),
        # 2T-3 (10): the agents the readback cycle ran, for the explainer's "Six agents read those surfaces"
        'agents_count': len(facts.get('agents') or []) if cycle is not None else None,
        'read_errors': errors,
    }


def store_answers(conn, cycle: dict) -> List[dict]:
    """Each answered where-to-buy and cheapest-place answer of the cycle:
    {run_id, intent, keys (the variant's id and sku), stores (names, in the
    order the answer named them: rm.stores_in_order)}."""
    rows = conn.execute(text("""
        SELECT r.id, q.source_ref, o.extraction, r.answer_status FROM soa_runs r
        JOIN soa_queries q ON q.id = r.query_id JOIN soa_expectation_outcomes o ON o.run_id = r.id
        WHERE r.cycle_id = :c AND q.tier = 'brand_direct' ORDER BY r.id
    """), {'c': cycle['id']}).mappings().all()
    out = []
    for r in rows:
        ref = rm._json(r['source_ref']) or {}
        if ref.get('intent') not in rm.ROUTING_INTENTS or (r['answer_status'] or 'answered') != 'answered':
            continue
        out.append({'run_id': r['id'], 'intent': ref.get('intent'),
                    'keys': [k for k in (ref.get('variant_id'), ref.get('sku')) if k],
                    'stores': [s['name'] for s in rm.stores_in_order(rm._json(r['extraction'])) or []]})
    return out


async def brand_overview(scope: CustomerScope, ms: MerchantScope, merchant: str, row: dict, body: dict, *,
                         prev: Optional[dict], rows: List[dict], vis: dict, true_value: dict,
                         attribute_answers: List[dict], accuracy: Optional[dict], promo: Optional[dict],
                         deals: Optional[dict], reference: Optional[dict], brand: str) -> None:
    """2T-1 (B1, B2, B4): the Overview of a brand at retail, added to `body`
    in place: lead, truesync_card, charter, strip, revenue, week_in_short,
    first_pick, activity, header, vs_label / vs_cycle; each surface's agents
    with facts_right and deals_line, its signals ranked by pool (the new
    generators on `all`), its products with live deals, check, the weight
    fact and the quotes collapsed. Every count from a tile's or a block's own
    helper: the score's tiles (/score's read), TrueSync's workspace
    (release_view), the revenue model's pools."""
    from app.routers.console import _revenue_model, _score
    from app.services import console_brand_overview as bo
    from app.services import console_revenue as revenue_svc

    record = _record(ms)
    if not manu.is_manufacturer(record):
        return
    client = full_loop._client(scope)
    errors = body.setdefault('read_errors', {})
    (c_status, channels, c_err), (_, pubs, p_err), (_, catalog, k_err), reads = await asyncio.gather(
        client.get_channels(), client.get_publications(limit=1000), _reads(scope).get_merchant_catalog(merchant),
        brand_reads(scope, merchant))
    for name, err in (('channels', c_err), ('publications', p_err), ('catalog', k_err)):
        if err is not None:
            errors[name] = err
    errors.update(reads['errors'])
    channels = [c for c in (channels or []) if c.get('is_active', True)] if c_err is None else []
    pubs = (pubs or []) if p_err is None else []
    catalog = catalog if k_err is None else None
    name = (record or {}).get('name') or merchant
    domain = _own_domain(reads['retailers'], record) or 'the brand site'
    own_domains = [domain]
    facts = {'attribute_answers': attribute_answers, 'true_value_rows': true_value.get('rows') or [], 'promo': promo,
             'deals': deals, 'agents': sorted({surfaces.agent_of(r.get('platform')) or r.get('platform') for r in rows})}
    release = await release_view(scope, ms, merchant, channels=channels, publications=pubs, catalog=catalog,
                                 reference=reference, reads=reads, cycle=row, facts=facts)
    errors.update(release.get('read_errors') or {})
    workspace = release['workspace'] if pubs else None
    mine = manu.merchant_publications(pubs, _listing_ids(catalog), merchant)
    score = await _score(row, scope.org.id, merchant, False, scope)
    feed_rows = (reads['feed'] or {}).get('rows')
    drift = rm.build_weight_drift(reference, brand=_brand(catalog))
    pages = manu.brand_pages(reads['prices'], own_domains)
    flags = manu.gtin_flags(pages, feed_rows, brand=_brand(catalog))
    with engine.connect() as conn:
        inputs = revenue_svc.inputs_view(revenue_svc.load_inputs(conn, scope.org.id, merchant), merchant)
        site = next((a['site'] for a in attribute_answers if a.get('site')), None) or domain
        model = _revenue_model(conn, row, inputs, _merchant_meta(ms), None, vis.get('byQuestion') or [],
                               attribute_answers=attribute_answers or None, site=site)
        club_lines = bo.club_lines(feed_rows, own_domains)
        clubs = bo.club_counts(club_lines, store_answers(conn, row))
        # 2T-4 (2): the Answers list's flagged counts, by the one severity rule (soa_shared/severity.py)
        body['flagged'] = severity.tally(rm.load_answers(
            conn, row, club_keys=set().union(*(line['keys'] for line in club_lines)) if club_lines else set()))
        first_at, last_at = conn.execute(text("SELECT MIN(run_at), MAX(run_at) FROM soa_runs WHERE cycle_id = :c"),
                                         {'c': row['id']}).fetchone()
    retired_named = vis.get('retired_named')
    # 2T-3 (2, 4): each line's truth is its own chart on the brand's page (rel.line_charts), as the matrix reads it
    # 2T-4 (5): each feed line's chart is the page its rows link to (rel.feed_line_charts), by name only without one
    charts = rel.feed_line_charts(reads['prices'], feed_rows, own_domains, _brand(catalog) or brand) \
        if reads['prices'] is not None else None
    size_signal = bo.size_chart_signal(drift, reference, accuracy, domain=domain, brand=_brand(catalog) or brand,
                                       charts=charts, feed_rows=feed_rows)
    new = [size_signal, bo.retired_signal(retired_named), bo.store_signal(clubs, _brand(catalog) or brand),
           bo.deal_signal(promo, manu.short_day((promo or {}).get('read_date') or (promo or {}).get('as_of')))]
    values = bo.pool_values(model)
    agent_of_run = {r['run_id']: surfaces.agent_of(r.get('platform')) or r.get('platform') for r in rows}
    for s, block in (body.get('by_surface') or {}).items():
        block['signals'] = bo.rank_signals(block.get('signals') or [], new if s == surfaces.ALL else [], values)
        block['agents'] = bo.extend_agents(block.get('agents') or [], attribute_answers=attribute_answers, promo=promo,
                                           agent_of_run=agent_of_run, surface=s)
        block['products'] = bo.extend_products(block.get('products') or [], attribute_answers=attribute_answers,
                                               deals=deals, true_value=true_value, surface=s, signals=block['signals'])
    every = (body.get('by_surface') or {}).get(surfaces.ALL) or {}
    ranked = every.get('signals') or []
    product_brand = _brand(catalog) or brand
    body['lead'] = bo.build_lead(ranked, brand=product_brand, name=name, domain=domain, totals=every.get('totals') or {},
                                 promo=promo, workspace=workspace)
    body['truesync_card'] = bo.build_truesync_card(workspace)
    body['charter'] = bo.build_charter(score, domain=domain, club=clubs, promo=promo)
    body['strip'] = bo.build_strip(score)
    body['revenue'] = bo.build_revenue(model, headline=bo.revenue_headline(
        ranked[0] if ranked else None, model=model, brand=product_brand, name=name,
        things=bo.size_things(drift, retired_named, flags)), brand=product_brand)
    body['week_in_short'] = bo.week_in_short(accuracy=accuracy, size_signal=size_signal, retired_named=retired_named,
                                             routing=vis.get('routing'), promo=promo, domain=domain)
    body['first_pick'] = bo.first_pick_footnote(vis, retired_named=retired_named)
    answered = sum(1 for r in rows if r.get('answer_status') == surfaces.ANSWERED)
    body['activity'] = bo.build_activity(cycle=row, first_at=first_at, last_at=last_at, answers=len(rows),
                                         usable=answered, agents=len(facts['agents']),
                                         questions=(body.get('coverage') or {}).get('asked') or 0,
                                         prices=reads['prices'], own_domains=own_domains, pubs=mine,
                                         workspace=workspace)
    # B4: the header's fields, each its own
    checked = [c['id'] for c in true_value.get('retailer_columns') or true_value.get('columns') or []
               if not c.get('you') and c.get('id') not in own_domains]
    body['header'] = {'skus': len(feed_rows) if feed_rows is not None else None, 'records': (workspace or {}).get('records'),
                      'retailers_checked': len(checked), 'retailers': checked, 'brand_domain': domain}
    prev_day = None
    if prev is not None:
        prev_day = rm.cycle_dates(prev, body.get('timezone')).get('start_date_local') or rm._iso(prev.get('start_date'))
    body['vs_label'] = bo.vs_label(prev_day)
    body['vs_cycle'] = (prev or {}).get('cycle_code')
    body['mode'] = manu.MANUFACTURER


@router.get("/publishing")
async def get_publishing(merchant: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    """B2: Publishing, B1's surfaces, diff, preview and artifacts (the objects
    /truesync carries for the same merchant). 404 for a merchant not in
    manufacturer mode."""
    ms, _record_ = await _manufacturer(scope, merchant)
    client = full_loop._client(scope)
    reads = _reads(scope)
    (c_status, channels, c_err), (p_status, pubs, p_err), (k_status, catalog, k_err), (_, reference, r_err) = \
        await asyncio.gather(client.get_channels(), client.get_publications(limit=1000),
                             reads.get_merchant_catalog(merchant), reads.get_reference(merchant))
    for status, error in ((c_status, c_err), (p_status, p_err)):
        if error is not None:
            raise HTTPException(status_code=404 if status == 404 else 502,
                                detail=f"TrueSync publishing unavailable: {error}")
    reference = reference if r_err is None else None
    catalog = catalog if k_err is None else None
    drift = rm.build_weight_drift(reference, brand=_brand(catalog))
    body = await publishing_view(scope, ms, merchant, channels=[c for c in channels or [] if c.get('is_active', True)],
                                 publications=pubs or [], catalog=catalog, reference=reference, drift=drift)
    if r_err is not None:
        body['read_errors']['reference'] = r_err
    if k_err is not None and k_status != 404:
        body['read_errors']['catalog'] = k_err
    body['merchant'] = merchant
    return body


@router.post("/publishing/compile")
async def post_compile(merchant: str = Query(...), dry_run: bool = Query(False),
                       scope: CustomerScope = Depends(operator_scope), user: dict = Depends(verify_token)):
    """2R-2a (A2): compile the brand's current SKU feed in manufacturer mode
    and hold it (supply's POST /merchants/{slug}/publish, with the tenant
    token). Operator only. This is the one call here that changes supply's
    state, and what it writes is held rows only: every row
    compiled_not_published (held_for_merchant, or blocked). Nothing is sent
    anywhere, to Google or a retailer. `dry_run` writes nothing. The answer
    is the re-read Publishing with `compile`: {dry_run, rows, by_channel,
    not_compiled: supply's notes per channel it did not compile}."""
    await _manufacturer(scope, merchant)
    body = _unwrap(*await full_loop._client(scope).publish_merchant(merchant, dry_run=dry_run))
    rows = (body or {}).get('rows') or []
    by_channel: dict = {}
    for r in rows:
        counts = by_channel.setdefault(r.get('channel_slug') or r.get('channel'), {})
        reason = r.get('reason') or r.get('status')
        counts[reason] = counts.get(reason, 0) + 1
    by = user.get('email') or user.get('sub')
    score_svc.log_event('publishing.compile', org=scope.org.id, merchant=merchant, dry_run=dry_run, rows=len(rows),
                        by=by)
    out = await get_publishing(merchant=merchant, scope=scope)
    out['compile'] = {'dry_run': dry_run, 'rows': len(rows), 'by_channel': by_channel,
                      'not_compiled': (body or {}).get('skipped') or []}
    return out


# ─── Rules ────────────────────────────────────────────────────────────────

async def _counts(scope: CustomerScope, row: dict, merchant: str, errors: dict) -> dict:
    """The backtest's three counts for one cycle, by the Overview's helpers:
    the attribute answers (cached per cycle and reference, as the Overview
    keeps them), Visibility's retired lines, the promo pass-through."""
    (facts, routing_errors), (promo, _deals, _as_of, p_err) = await asyncio.gather(
        _routing_inputs(scope, row, merchant), _promo_inputs(scope, row, merchant))
    errors.update(routing_errors)
    if p_err is not None:
        errors['deals'] = p_err
    with engine.connect() as conn:
        vis = _visibility(conn, row, facts, routing_errors)
        asks = rm.asks_attribute(conn, row)
    reference = None
    if asks:
        _, reference, r_err = await _reads(scope).get_reference(merchant)
        if r_err is not None:
            errors['reference'], reference = r_err, None
    with engine.connect() as conn:
        answers = console_cache.cycle_read(conn, row, 'attribute_answers', lambda: rm.attribute_answers(
            conn, row, reference), console_cache.digest(reference)) if asks else []
    return manu.backtest_counts(attribute_answers=answers, retired_named=vis.get('retired_named'), promo=promo)


async def _rules_body(scope: CustomerScope, ms: MerchantScope, merchant: str) -> dict:
    """The rules screen: every word of the rules is supply's (2R-2a A3); soa
    adds only the backtest."""
    record = _record(ms)
    client = full_loop._client(scope)
    (_, rules, rules_err), (catalog, pubs, held_errors) = await asyncio.gather(
        client.get_rules(merchant), _held_inputs(scope, merchant))
    errors = dict(held_errors)
    if rules_err is not None:
        errors['rules'] = rules_err
    sent = manu.first_sent(pubs)
    name = (record or {}).get('name') or merchant
    before, after = manu.around_send(_scored_cycles(ms), sent)
    backtest = []
    if before is not None:
        before_counts = await _counts(scope, before, merchant, errors)
        after_counts = await _counts(scope, after, merchant, errors) if after is not None else None
        backtest = manu.build_backtest(before_counts, before, after_counts, after, sent, name)
    return {'merchant': merchant, 'mode': manu.MANUFACTURER, 'kind': (rules or {}).get('kind'),
            'rules': manu.build_rules((rules or {}).get('rules') if rules_err is None else None),
            'backtest': backtest, 'sent': sent,
            'cycle': (before or {}).get('cycle_code'), 'after_cycle': (after or {}).get('cycle_code'),
            'read_errors': errors}


@router.get("/rules")
async def get_rules(merchant: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    """B2: supply's six compliance rules with their approval, and the backtest:
    before measured on the newest scored cycle (the last before a stated
    send), after "Next read" until the brand states a send, then the first
    cycle scored after it."""
    ms, _record_ = await _manufacturer(scope, merchant)
    return await _rules_body(scope, ms, merchant)


class RuleChange(BaseModel):
    on: Optional[bool] = None
    approval: Optional[str] = None
    note: Optional[str] = None


@router.put("/rules/{code}")
async def put_rule(code: str, body: RuleChange, merchant: str = Query(...),
                   scope: CustomerScope = Depends(operator_scope), user: dict = Depends(verify_token)):
    """B2: switch a rule on or off, record its approval or a note, forwarded to
    supply with the tenant token and the operator as `actor` (supply journals
    each changed field). Operator only. The answer is the re-read list.
    Reversible: the same call sets it back."""
    ms, _record_ = await _manufacturer(scope, merchant)
    change = body.model_dump(exclude_none=True)
    if not change:
        raise HTTPException(status_code=422, detail="nothing to change: send on, approval or note")
    if 'approval' in change and change['approval'] not in manu.APPROVAL_STATES:
        raise HTTPException(status_code=422, detail=f"approval must be one of {', '.join(manu.APPROVAL_STATES)}")
    actor = user.get('email') or user.get('sub')
    _unwrap(*await full_loop._client(scope).put_rule(merchant, code, {**change, 'actor': actor}))
    score_svc.log_event('rules.put', org=scope.org.id, merchant=merchant, code=code, fields=sorted(change), actor=actor)
    return await _rules_body(scope, ms, merchant)


# ─── Sent: a fact the brand states ────────────────────────────────────────

class SentStatement(BaseModel):
    channel: str
    sent_at: str
    #: who says it was sent (the brand's team)
    stated_by: str
    note: Optional[str] = None
    publication_ids: Optional[List[int]] = None


#: supply refuses a sent_at more than this ahead of its clock (#33); soa says so first.
SENT_CLOCK_SKEW = timedelta(minutes=5)


def _when(value: str) -> datetime:
    try:
        when = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        raise HTTPException(status_code=422, detail="sent_at must be an ISO 8601 date or date-time")
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


@router.post("/publishing/sent")
async def post_sent(body: SentStatement = Body(...), merchant: str = Query(...),
                    scope: CustomerScope = Depends(console_scope), user: dict = Depends(verify_token)):
    """B3: the brand says its team (`stated_by`) sent the held file for
    `channel` on `sent_at`. Parleo never sends it, so the system cannot
    observe the send: supply journals the statement on the channel's held
    publications as `sent_by_merchant`, with the signed-in user as `actor`.
    Members and operators. A blocked channel (ACP) holds nothing to send:
    409. The answer is the re-read Publishing with supply's `recorded`."""
    ms, _record_ = await _manufacturer(scope, merchant)
    if not body.stated_by.strip():
        raise HTTPException(status_code=422, detail="stated_by is required: who says it was sent")
    if _when(body.sent_at) > datetime.now(timezone.utc) + SENT_CLOCK_SKEW:
        raise HTTPException(status_code=422, detail="sent_at is in the future")
    _catalog, pubs, errors = await _held_inputs(scope, merchant)
    if 'publications' in errors:
        raise HTTPException(status_code=502, detail=f"TrueSync publications unavailable: {errors['publications']}")
    rows = manu.latest_by_record(pubs, body.channel)
    held = [p for p in rows if manu.is_held(p)]
    if not held:
        why = 'is blocked' if any(manu.is_blocked(p) for p in rows) else 'holds nothing'
        raise HTTPException(status_code=409, detail=f"{body.channel} {why} for {merchant!r}; nothing was held to send")
    # 2R-2b: a file cannot have been sent before it was compiled (supply accepts it; soa says no first)
    compiled = max((_when(str(p['compiled_at'])) for p in held if p.get('compiled_at')), default=None)
    if compiled is not None and _when(body.sent_at) < compiled:
        raise HTTPException(status_code=422, detail=(
            f"sent_at {body.sent_at} is before the held {body.channel} file was compiled "
            f"({compiled.isoformat()}): a file cannot be sent before it exists"))
    actor = user.get('email') or user.get('sub')
    statement = {'channel': body.channel, 'sent_at': body.sent_at, 'stated_by': body.stated_by, 'actor': actor,
                 'note': body.note, **({'publication_ids': body.publication_ids} if body.publication_ids else {})}
    answer = _unwrap(*await full_loop._client(scope).post_sent(merchant, statement))
    score_svc.log_event('publishing.sent', org=scope.org.id, merchant=merchant, channel=body.channel,
                        sent_at=body.sent_at, actor=actor, recorded=(answer or {}).get('recorded'))
    out = await get_publishing(merchant=merchant, scope=scope)
    out['recorded'] = (answer or {}).get('recorded')
    return out


# ─── Artifacts through soa ────────────────────────────────────────────────

def _detail(error: Optional[str]):
    """supply's JSON error body's `detail`, or the text as it came."""
    try:
        return json.loads(error or '').get('detail', error)
    except (ValueError, AttributeError):
        return error


@router.get("/truesync/artifact")
async def get_artifact(merchant: str = Query(...), channel: str = Query(...),
                       publication_id: Optional[int] = Query(None), scope: CustomerScope = Depends(console_scope)):
    """B4: the compiled file for a channel (every held product's, supply's
    /merchants/{slug}/artifacts), or one publication's (`publication_id`,
    which must be the merchant's), from supply with the org's tenant token,
    with supply's filename, content type and X-TrueSync-* headers. Members and
    operators. A blocked channel (ACP while it is) is supply's 409 with its
    clause, answered as JSON, never a file. Kept per supply's compiled_at, so
    a recompile is a new file and a repeat is not a second supply call."""
    await check_merchant(scope, merchant)
    _catalog, pubs, errors = await _held_inputs(scope, merchant)
    if 'publications' in errors:
        raise HTTPException(status_code=502, detail=f"TrueSync publications unavailable: {errors['publications']}")
    if publication_id is not None:
        pub = next((p for p in pubs if p.get('id') == publication_id
                    and (p.get('channel_slug') or p.get('channel')) == channel), None)
        if pub is None:
            raise HTTPException(status_code=404, detail=f"publication {publication_id} is not {merchant!r}'s on {channel}")
        rows = [pub]
    else:
        rows = [p for p in manu.latest_by_record(pubs, channel) if manu.is_held(p) or manu.is_blocked(p)
                or p.get('status') == manu.LIVE_STATUS]
    if not rows:
        raise HTTPException(status_code=404, detail=f"no {channel!r} file for {merchant!r}")
    compiled_at = max(str(p.get('compiled_at') or '') for p in rows)
    client = full_loop._client(scope)

    async def fetch():
        if publication_id is not None:
            status, response, error = await client.get_publication_artifact(publication_id)
        else:
            status, response, error = await client.get_merchant_artifacts(merchant, channel)
        if error is not None:
            if status == 409:   # blocked: supply's clause, never a file (and never kept)
                return {'refused': _detail(error)}
            _unwrap(status, response, error)
        headers = {k.lower(): v for k, v in (getattr(response, 'headers', None) or {}).items()}
        return {'content': response.content, 'content_type': headers.get('content-type') or 'application/json',
                'headers': {k: headers[k] for k in ARTIFACT_HEADERS if headers.get(k)}}
    key = ('artifact', scope.org.id, merchant, channel, publication_id, compiled_at)
    got = await fetch() if any(manu.is_blocked(p) for p in rows) else \
        await console_cache.cached(key, fetch, ttl=console_cache.CYCLE_TTL)
    if 'refused' in got:
        refused = got['refused']
        return JSONResponse(status_code=409, content=refused if isinstance(refused, dict) else {'detail': refused})
    headers = dict(got['headers'])
    headers.setdefault('content-disposition', f'attachment; filename="{merchant}-{channel}-{compiled_at[:10]}.json"')
    return Response(content=got['content'], media_type=got['content_type'], headers=headers)


# ─── Impact ───────────────────────────────────────────────────────────────

async def impact_block(scope: CustomerScope, ms: MerchantScope, errors: dict) -> Optional[dict]:
    """B3: Impact's `locked` block for a merchant in manufacturer mode, None
    otherwise. Locked (the demo's text, the merchant's name) until the brand
    states a send; then "What moved since the record was sent (<date>)": the
    first cycle scored after the send against the last before it, through
    the one comparability rule (_compared), Impact's baseline rows each."""
    record = _record(ms)
    if not manu.is_manufacturer(record):
        return None
    meta = _merchant_meta(ms)
    (catalog, pubs, held_errors), (_, retailers, o_err) = await asyncio.gather(
        _held_inputs(scope, ms.slug), _reads(scope).get_retailers(ms.slug))
    errors.update(held_errors)
    domain = _own_domain(retailers if o_err is None else None, record)
    sent = manu.first_sent(pubs)
    if sent is None:
        return manu.locked_block(name=meta['name'], brand=_brand(catalog), domain=domain)
    t = manu.MANUFACTURER_TEMPLATES
    day = manu.short_day(sent['sent_at'])
    before, after = manu.around_send(_scored_cycles(ms), sent)
    block = {'state': 'unlocked', 'title': t['unlocked.title'].format(sent=day), 'sent': sent,
             'before': (before or {}).get('cycle_code'), 'after': (after or {}).get('cycle_code'),
             'status': None, 'note': None, 'rows': None}
    if after is None:
        block['note'] = t['unlocked.waiting'].format(sent=day)
        return block
    if before is None:
        block['note'] = t['unlocked.no_before'].format(sent=day)
        return block
    facts, routing_errors = await _routing_inputs(scope, after, ms.slug)
    with engine.connect() as conn:
        compared = _compared(conn, after, _rows(conn, after), _visibility(conn, after, facts, routing_errors), facts,
                             prev=before)
    block['status'], block['note'] = compared['status'], compared['note']
    if compared['status'] == 'compared':
        now_rows, _vis = await _baseline_rows(scope, after, ms, meta, errors)
        then_rows, _vis = await _baseline_rows(scope, before, ms, meta, {})
        block['rows'] = rm.since_baseline(now_rows, then_rows, before['cycle_code'])
    return block
