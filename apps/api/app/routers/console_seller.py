"""
2V-2: the reads behind an externally hosted seller's console screens (supply's
`mode` seller_external). The endpoints are console_manufacturer's and
console.py's own (/publishing, /rules, /fixes, /approvals, /truesync,
/overview, /record, /true-value, /prove): each reads the merchant's /tenant
record and, for a seller we do not host, answers from here instead of the
brand-at-retail builders. Supply is read with the org's tenant token,
server-side. Pure builders: app/services/console_seller.py.

2V-4: and retail mode's reading of what brand mode has (the 2T and 2U
rounds) over the seller's shapes: the TrueSync release page (release_page),
the Overview's blocks (retail_overview), the record's derived issues, the
whole Fix queue, every seller rule on Approvals. Pure builders:
app/services/console_retail.py.
"""
import asyncio
from typing import List, Optional

from sqlalchemy import text

from app.console_merchants import MerchantScope
from app.customer_context import CustomerScope
from app.routers import full_loop
from app.services import console_fixes as fx
from app.services import console_manufacturer as manu
from app.services import console_read_models as rm
from app.services import console_retail as rt
from app.services import console_seller as cs
from soa_shared import surfaces as surface_names


def _engine():
    """console_manufacturer's engine, read at call time (the tests set it per module)."""
    from app.routers import console_manufacturer
    return console_manufacturer.engine


def _record(ms: MerchantScope) -> Optional[dict]:
    return next((m for m in ms.merchants or [] if m.get('slug') == ms.slug), None)


def _name(ms: MerchantScope, merchant: str) -> str:
    return (_record(ms) or {}).get('name') or merchant


async def seller_reads(scope: CustomerScope, merchant: str) -> dict:
    """
    supply's reads an external seller's screens share, in one round: {rules,
    pubs (the merchant's publications), paths (/price-paths: the full program
    truth, every SKU), held_paths (each SKU's path as the held deals_api rows
    state it, the rules applied), owned (owned incentives), loyalty (its
    loyalty program), errors}. A failed read is None and named in errors.
    """
    client = full_loop._client(scope)
    (_, rules, r_err), (_, pubs, p_err), (_, paths, pp_err), (_, owned, o_err) = await asyncio.gather(
        client.get_rules(merchant), client.get_publications(limit=1000), client.get_price_paths(merchant),
        client.get_owned_incentives(merchant))
    errors = {n: e for n, e in (('rules', r_err), ('publications', p_err), ('price_paths', pp_err),
                                ('incentives', o_err)) if e}
    mine = manu.merchant_publications(pubs or [], [], merchant) if p_err is None else []
    held_paths = []
    for p in manu.latest_by_record(mine, 'deals_api'):
        if manu.is_held(p):
            held_paths.extend(s for s in (p.get('payload') or {}).get('skus') or [] if isinstance(s, dict))
    owned_rows = (owned or {}).get('incentives') or [] if o_err is None else []
    loyalty = next((i for i in owned_rows if i.get('mechanic') == 'loyalty_program'), None)
    return {'rules': (rules or {}).get('rules') if r_err is None else None, 'pubs': mine,
            'paths': cs.paths_by_sku(paths) if pp_err is None else [], 'held_paths': held_paths,
            'owned': owned_rows, 'loyalty': loyalty, 'errors': errors}


def _scored_cycles(ms: MerchantScope) -> List[dict]:
    from app.routers.console_manufacturer import _scored_cycles as scored
    return scored(ms)


def cycle_answers(cycle: Optional[dict]) -> tuple:
    """(answers, price answers) of a cycle: every answered run {run_id, agent, intent, text, keys}, and those asking
    where to buy or where it is cheapest (rm.VALUE_INTENTS). 2V-5 (W4): `keys` the product its question is coded to
    (cs.subject_keys)."""
    if cycle is None:
        return [], []
    with _engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT r.id, r.platform, r.raw_response, r.answer_status, q.source_ref, q.provenance, q.tier
            FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id WHERE r.cycle_id = :c ORDER BY r.id
        """), {'c': cycle['id']}).mappings().all()
    answers = []
    for r in rows:
        if (r['answer_status'] or 'answered') != 'answered':
            continue
        # 2V-3 (Q6): a where-to-buy or cheapest-place answer by its row's source, never its tier label
        answers.append({'run_id': r['id'], 'agent': surface_names.agent_of(r['platform']) or r['platform'],
                        'intent': rm.catalog_intent(r['source_ref'], r['provenance'], r['tier']),
                        'text': r['raw_response'] or '', 'keys': cs.subject_keys(rm._json(r['source_ref']))})
    return answers, [a for a in answers if a['intent'] in rm.VALUE_INTENTS]


# ─── Publishing, the release card ─────────────────────────────────────────

async def publishing(scope: CustomerScope, ms: MerchantScope, merchant: str, channels: List[dict],
                     reads: Optional[dict] = None) -> dict:
    """Publishing for an external seller: {mode, surfaces, diff, preview, artifacts, held, channel_states, release}."""
    record = _record(ms)
    reads = reads or await seller_reads(scope, merchant)
    held = (record or {}).get('held')
    surfaces = cs.build_surfaces(pubs=reads['pubs'], held=held, plan=(record or {}).get('channels'))
    name = _name(ms, merchant)
    skus = len(reads['paths']) or None
    cycles = _scored_cycles(ms)
    return {
        'mode': cs.SELLER_EXTERNAL, 'kind': 'seller', 'surfaces': surfaces,
        'diff': cs.build_diff(paths=reads['held_paths'] or reads['paths'], loyalty=reads['loyalty']),
        'preview': cs.build_preview(surfaces=surfaces, name=name, skus=skus, held=held),
        'artifacts': manu.build_artifacts(merchant, reads['pubs'], channels, held),
        'held': held, 'channel_states': cs.channel_states(surfaces),
        'release': release_card(record, surfaces, name, skus),
        'cycle': (cycles[0] if cycles else {}).get('cycle_code'), 'read_errors': dict(reads['errors']),
    }


def release_card(record: Optional[dict], surfaces: List[dict], name: str, skus: Optional[int]) -> dict:
    """
    The TrueSync release card (and the Overview's TrueSync card): what is
    compiled and held now, what is live on Parleo's own server, what the seller
    says it sent, and the MCP readback. Every count is supply's /tenant `held`.
    """
    held = (record or {}).get('held') or {}
    mcp = ((held.get('published') or {}).get('mcp')) or {}
    holding = [s for s in surfaces if s['status'] == 'held']
    sent = [s for s in holding if s.get('sent')]
    state = 'sent' if holding and len(sent) == len(holding) else 'held' if holding else 'none'
    return {'title': f"{skus or held.get('total') or 0} {name} SKUs, {len(holding)} surfaces" if holding else
            f"No {name} record compiled yet", 'state': state, 'day': manu.short_day(held.get('compiled_at')),
            'compiled_at': held.get('compiled_at'), 'held': len(holding), 'sent': len(sent),
            'surfaces': [{'channel': s['channel'], 'name': s['name'], 'state': s['status'], 'line': s['last']}
                         for s in surfaces],
            'mcp': {'state': 'live' if mcp.get('records') else 'not_compiled', 'acceptance': mcp.get('acceptance'),
                    'verified': mcp.get('verified_skus'), 'reason': mcp.get('reason'), 'server': mcp.get('server')},
            'note': (f"Compiled {manu.short_day(held.get('compiled_at'))} and held. {cs._possessive(name)} own team "
                     f"sends the files. Parleo serves get_product_true_cost itself.") if holding else ''}


# ─── Rules, Fix queue, Approvals ──────────────────────────────────────────

async def rules_body(scope: CustomerScope, ms: MerchantScope, merchant: str) -> dict:
    """The seller's six rules (every word supply's) and the demo's three-row backtest on the newest scored cycle."""
    reads = await seller_reads(scope, merchant)
    cycles = _scored_cycles(ms)
    cycle = cycles[0] if cycles else None
    answers, price_answers = cycle_answers(cycle)
    former = list((reads['loyalty'] or {}).get('former_names') or [])
    sent = manu.first_sent(reads['pubs'])
    return {'merchant': merchant, 'mode': cs.SELLER_EXTERNAL, 'kind': 'seller',
            'rules': manu.build_rules(reads['rules']),
            'backtest': cs.build_backtest(rules=reads['rules'], answers=answers, price_answers=price_answers,
                                          paths=reads['paths'], former=former, name=_name(ms, merchant), cycle=cycle)
            if cycle is not None else [],
            'sent': sent, 'cycle': (cycle or {}).get('cycle_code'), 'after_cycle': None,
            'read_errors': reads['errors']}


def _program_of(reads: dict, name: str) -> Optional[str]:
    return next((cs._program(i.get('name'), name) for i in reads['owned'] if i.get('mechanic') == 'subscription_discount'),
                None)


async def _access(scope: CustomerScope, merchant: str, errors: dict) -> Optional[dict]:
    """supply's /access for the merchant (the console's cached read), as Accessibility reads it; a 5xx is named in
    `errors`, a merchant supply has no access run for is none."""
    from app.routers.console import _reads
    status, payload, error = await _reads(scope).get_access(merchant)
    if error is not None:
        if not (status and 400 <= status < 500):
            errors['access'] = error
        return None
    return rm.accessibility_from_supply(payload)


async def _fix_inputs(scope: CustomerScope, ms: MerchantScope, merchant: str, *, access: Optional[dict] = None,
                      access_read: bool = True, reads: Optional[dict] = None) -> dict:
    """The whole Fix queue (2V-4, B5): console_seller's fixes (first-order prices while s1 waits, the retired
    name's copy while s4 is off, the held files) and console_retail's (the edge path, the Rx terms, order data for
    Impact), numbered in that order."""
    reads = reads or await seller_reads(scope, merchant)
    cycles = _scored_cycles(ms)
    cycle = cycles[0] if cycles else None
    answers, price_answers = cycle_answers(cycle)
    name = _name(ms, merchant)
    body = cs.build_fixes(rules=reads['rules'], paths=reads['paths'], answers=answers, price_answers=price_answers,
                          loyalty=reads['loyalty'], pubs=reads['pubs'], name=name, program=_program_of(reads, name))
    if access is None and access_read:
        access = await _access(scope, merchant, reads['errors'])
    issues = {str(r.get('sku')): rt.build_issues(row=r, held_rows={}, feed_row=None, feed_version=None, page_rows=[],
                                                 loyalty=reads['loyalty'], owned=reads['owned'], rules=reads['rules'],
                                                 name=name, merchant=name, domain=_domain(ms))
              for r in reads['paths']}
    queue = rt.finish_fixes(body['fixes'] + rt.more_fixes(paths=reads['paths'], rules=reads['rules'], access=access,
                                                          domain=_domain(ms), issues=issues))
    return {'reads': reads, 'cycle': cycle, 'fixes': queue, 'answers': answers, 'price_answers': price_answers,
            'access': access}


def _domain(ms: MerchantScope) -> Optional[str]:
    """The seller's own domain, as its /tenant record states it."""
    d = (_record(ms) or {}).get('domain') or next(iter((_record(ms) or {}).get('own_domains') or []), None)
    return str(d).lower().removeprefix('www.') if d else None


async def fixes(scope: CustomerScope, ms: MerchantScope, merchant: str) -> dict:
    got = await _fix_inputs(scope, ms, merchant)
    return {'merchant': merchant, 'mode': cs.SELLER_EXTERNAL, **got['fixes'],
            'cycle': (got['cycle'] or {}).get('cycle_code'), 'read_errors': got['reads']['errors']}


async def approvals(scope: CustomerScope, ms: MerchantScope, merchant: str) -> dict:
    """2V-4 (B5): every seller rule s1..s6 as a request (each fix a rule gates named on it), the held release, and
    the signed rules (who, when), as fx.build_approvals reads them."""
    got = await _fix_inputs(scope, ms, merchant)
    reads = got['reads']
    name = _name(ms, merchant)
    release_fix = [{**f, 'pool': 'both'} for f in got['fixes']['fixes'] if f['id'] == 'release']
    body = fx.build_approvals(fixes=rt.rule_fixes(reads['rules'], got['fixes']['fixes']) + release_fix,
                              rules=reads['rules'], pubs=reads['pubs'], records=len(reads['paths']),
                              skus=len(reads['paths']), brand=name)
    for request in body['requests']:
        if request['kind'] == 'rule':
            rule = cs._rule(reads['rules'], request['code']) or {}
            request['scope_text'] = rule.get('scope')
            request['audience'] = rule.get('audience')
            request['outcome'] = rule.get('outcome')
            if not request.get('fix'):
                request['fix_title'] = None
        if request['code'] == 'release':
            request['title'] = f"{len(reads['paths'])} {name} SKUs, held for {cs._possessive(name)} team"
            request['text'] = (f"The held files: {len(reads['paths'])} SKUs with {cs._possessive(name)} own prices and "
                               f"program steps as its rules allow. {cs._possessive(name)} own team sends them.")
    return {'merchant': merchant, 'mode': cs.SELLER_EXTERNAL, **body,
            'cycle': (got['cycle'] or {}).get('cycle_code'), 'read_errors': reads['errors']}


# ─── True Value, Prove, the Product record ────────────────────────────────

async def true_value(scope: CustomerScope, ms: MerchantScope, merchant: str, body: dict, cycle: dict,
                     value_outcomes: Optional[List[dict]] = None) -> None:
    """True Value's program cards, each row's program line, the ladder and the receipt, from the price paths. 2V-6
    (X3): `value_outcomes` the cycle's value-tier rows (console._value_outcomes), which the cards' read-out keys on."""
    reads = await seller_reads(scope, merchant)
    answers, _price = cycle_answers(cycle)
    name = _name(ms, merchant)
    lines = cs.program_lines(paths=reads['paths'], answers=answers, merchant=name)
    # the console's shape (2G): {variant_id: {line, by_surface}}; the seller's line over parity's
    program_lines = dict(body.get('program_lines') or {})
    for vid, line in lines.items():
        program_lines[vid] = {**(program_lines.get(vid) or {}), 'line': line, 'by_surface': {}}
    body.update({'mode': cs.SELLER_EXTERNAL, 'program_lines': program_lines,
                 'programs': cs.build_programs(owned=reads['owned'], paths=reads['paths'], answers=answers,
                                               merchant=name, value_outcomes=value_outcomes),
                 'ladder': cs.build_ladder(paths=reads['paths'], answers=answers, name=name),
                 # 2V-5 (V3): each SKU's own price path, for a screen that selects one
                 'ladders': {str(r.get('sku')): cs.build_ladder(paths=reads['paths'], answers=answers, name=name,
                                                                sku=r.get('sku'))
                             for r in reads['paths'] if cs._stepped(r)},
                 'receipt': cs.build_receipt(paths=reads['paths'], merchant=name)})
    body.setdefault('read_errors', {}).update(reads['errors'])


async def prove(scope: CustomerScope, ms: MerchantScope, merchant: str, cycle: Optional[dict]) -> dict:
    reads = await seller_reads(scope, merchant)
    answers, _price = cycle_answers(cycle)
    body = cs.build_funded_offers(paths=reads['paths'], answers=answers, name=_name(ms, merchant))
    passed = cs.funded_pass_through(paths=reads['paths'], answers=answers)
    return {'merchant': merchant, 'mode': cs.SELLER_EXTERNAL, 'state': 'measured' if cycle else 'not_measured',
            **body, **({'promo_pass_through': passed} if passed else {}),
            'cycle': (cycle or {}).get('cycle_code'), 'read_errors': reads['errors']}


async def record_list(scope: CustomerScope, ms: MerchantScope, merchant: str) -> dict:
    reads = await seller_reads(scope, merchant)
    sent = manu.first_sent(reads['pubs'])
    held_any = any(manu.is_held(p) for p in reads['pubs'])
    rows = [{'sku': r.get('sku'), 'variant_id': r.get('variant_id'), 'name': ' '.join(filter(None, [
        r.get('product_name'), r.get('title') if r.get('title') != r.get('product_name') else None])),
        'price': cs.money((r.get('price_path') or {}).get('list_price')),
        'status': 'Rx, list price' if (r.get('price_path') or {}).get('rx') else
        'Ladder' if ((r.get('price_path') or {}).get('steps') or [{}])[0].get('funded_by') else
        'Standard first order' if (r.get('price_path') or {}).get('steps') else 'List price',
        'state': 'sent' if sent else 'held' if held_any else 'none'} for r in reads['paths']]
    return {'merchant': merchant, 'mode': cs.SELLER_EXTERNAL, 'kind': 'seller', 'products': rows,
            'read_errors': reads['errors']}


async def record(scope: CustomerScope, ms: MerchantScope, merchant: str, product: str) -> Optional[dict]:
    reads = await seller_reads(scope, merchant)
    row = next((r for r in reads['paths'] if product in (str(r.get('sku')), str(r.get('variant_id')))), None)
    if row is None:
        return None
    name = _name(ms, merchant)
    errors = dict(reads['errors'])
    feed, reference = await _feed_and_reference(scope, merchant, errors)
    feed_row = next((f for f in (feed or {}).get('rows') or [] if str(f.get('sku')) == str(row.get('sku'))), None)
    body = cs.build_record(row=row, feed_row=feed_row, name=name, merchant=name,
                           sent=manu.first_sent(reads['pubs']), held_any=any(manu.is_held(p) for p in reads['pubs']),
                           owned=reads['owned'])
    # 2V-4 (B4): the issues the record, the held files, the feed and the page read prove, each with its source
    domain = _domain(ms)
    body['issues'] = rt.build_issues(row=row, held_rows=rt.hold(reads['pubs']).get(rt.ref_of(row, merchant)) or {},
                                     feed_row=feed_row, feed_version=(feed or {}).get('version'),
                                     page_rows=rt.own_page_rows(reference, row, domain), loyalty=reads['loyalty'],
                                     owned=reads['owned'], rules=reads['rules'], name=name, merchant=name, domain=domain)
    return {'merchant': merchant, 'mode': cs.SELLER_EXTERNAL, **body, 'read_errors': errors}


async def _feed_and_reference(scope: CustomerScope, merchant: str, errors: dict) -> tuple:
    """(supply's current feed, its /reference page reads) for the merchant; a 5xx is named in `errors`, a read
    supply has nothing for (a 4xx) is none."""
    client = full_loop._client(scope)
    (f_status, feed, f_err), (r_status, reference, r_err) = await asyncio.gather(
        client.get_feed(merchant), client.get_reference(merchant))
    for key, status, err in (('feed', f_status, f_err), ('reference', r_status, r_err)):
        if err is not None and not (status and 400 <= status < 500):
            errors[key] = err
    return (feed if f_err is None else None), (reference if r_err is None else None)


# ─── 2V-4: the TrueSync release page ──────────────────────────────────────

async def release_page(scope: CustomerScope, ms: MerchantScope, merchant: str, channels: List[dict], *,
                       view: dict, reads: Optional[dict] = None) -> dict:
    """
    2V-4 (B3): TrueSync as a release page for an external seller, in the brand
    page's shape (console_manufacturer.release_view): {workspace (in SKUs),
    release (the newest hold, with 2V-2's release card's fields beside it),
    releases, channels (the eight, each with its state and line), pass_channels,
    products (the matrix: one row per SKU, its cells with the seller's states
    and reasons, the master record with the price path, the drift rows, the
    compiler's lines per channel), destinations, readback_cycle, agents_count,
    read_errors}. `view` is /publishing's (its surfaces and release card).
    """
    record = _record(ms)
    reads = reads or await seller_reads(scope, merchant)
    errors = dict(reads['errors'])
    name = _name(ms, merchant)
    held = (record or {}).get('held')
    feed, _reference = await _feed_and_reference(scope, merchant, errors)
    cycles = _scored_cycles(ms)
    cycle = cycles[0] if cycles else None
    answers, price_answers = cycle_answers(cycle)
    agents = sorted({a['agent'] for a in answers if a.get('agent')})
    refs = [rt.ref_of(r, merchant) for r in reads['paths']]
    states = rt.channel_states(surfaces=view['surfaces'], per_sku=rt.hold(reads['pubs']), refs=refs, channels=channels,
                               held=held, pubs=reads['pubs'])
    records = rt.build_records(paths=reads['paths'], held_paths=reads['held_paths'], pubs=reads['pubs'], states=states,
                               channels=channels, rules=reads['rules'], name=name, slug=merchant, held=held, cycle=cycle,
                               price_answers=price_answers, agents=agents, merchant=name,
                               feed_rows=(feed or {}).get('rows'), owned=reads['owned'])
    release = rt.build_release(pubs=reads['pubs'], states=states, rules=reads['rules'], name=name, skus=len(refs),
                               held=held)
    card = view.get('release') or {}
    if release is not None:
        # 2V-2's card beside the brand page's fields: one object, its surfaces each with both
        by = {sf['channel']: sf for sf in card.get('surfaces') or []}
        release = {**release, **{k: v for k, v in card.items() if k != 'surfaces'},
                   'surfaces': [{**sf, **by.get(sf['channel'], {})} for sf in release['surfaces']]}
    return {
        'workspace': rt.build_workspace(records=records, states=states, held=held, name=name),
        'release': release if release is not None else card,
        'releases': rt.build_releases(pubs=reads['pubs'], feed_version=(feed or {}).get('version'), rules=reads['rules'],
                                      held=held),
        'channels': states, 'pass_channels': [c['channel'] for c in states if c['in_pass']],
        'records': records, 'destinations': [], 'cell_states': ['held', 'live', 'blocked', 'not_for_seller', 'na'],
        'readback_cycle': (cycle or {}).get('cycle_code'), 'agents_count': len(agents) if cycle is not None else None,
        'read_errors': errors,
    }


# ─── 2V-4: the Overview ───────────────────────────────────────────────────

async def retail_overview(scope: CustomerScope, ms: MerchantScope, merchant: str, row: dict, body: dict, *,
                          prev: Optional[dict], rows: List[dict], vis: dict, access: Optional[dict]) -> None:
    """
    2V-4 (B2): the Overview of an external seller, added to `body` in place, in
    the demo's order: lead (the cycle's worst signal, Visibility's unprompted
    read first), truesync_card (TrueSync's workspace and 2V-2's release card),
    strip, revenue, week_in_short, actions, fix_queue, each surface's signals
    (the seller's kinds ranked first on `all`) and products (named as the
    Product record names them, 2V-3 Q5), activity, header, vs_label. `mode`
    seller_external.
    """
    from app.routers.console import _merchant_meta, _revenue_model, _score
    from app.services import console_brand_overview as bo
    from app.services import console_revenue as revenue_svc

    client = full_loop._client(scope)
    errors = body.setdefault('read_errors', {})
    (c_status, channels, c_err) = await client.get_channels()
    if c_err is not None:
        errors['channels'] = c_err
    channels = [c for c in channels or [] if c.get('is_active', True)] if c_err is None else []
    reads = await seller_reads(scope, merchant)
    errors.update(reads['errors'])
    name = _name(ms, merchant)
    domain = _domain(ms)
    view = await publishing(scope, ms, merchant, channels, reads=reads)
    page = await release_page(scope, ms, merchant, channels, view=view, reads=reads)
    errors.update(page['read_errors'])
    got = await _fix_inputs(scope, ms, merchant, access=access, access_read=False, reads=reads)
    queue = got['fixes']
    answers, price_answers = cycle_answers(row)
    program = _program_of(reads, name) or 'program'
    counts = rt.unprompted_counts(vis)
    new = [rt.store_signal(counts, name),
           rt.missing_signal(paths=reads['paths'], price_answers=price_answers, name=name, program=program),
           rt.misstated_signal(paths=reads['paths'], answers=answers, name=name, program=program),
           rt.funded_signal(paths=reads['paths'], answers=answers),
           rt.retired_signal(answers=answers, loyalty=reads['loyalty']),
           rt.access_signal(access, domain)]
    feed, _reference = await _feed_and_reference(scope, merchant, errors)
    for s, block in (body.get('by_surface') or {}).items():
        block['signals'] = rt.rank_signals(block.get('signals') or [], new if s == surface_names.ALL else [])
        # 2V-3 (Q5): a seller's rows are named as its Product record names them
        block['products'] = bo.name_products(block.get('products') or [], (feed or {}).get('rows'))
    ranked = ((body.get('by_surface') or {}).get(surface_names.ALL) or {}).get('signals') or []
    workspace = page['workspace']
    card = bo.build_truesync_card(workspace) or {}
    release = view['release']
    by = {sf['channel']: sf for sf in release.get('surfaces') or []}
    body['truesync_card'] = {**card, 'mode': cs.SELLER_EXTERNAL, **{k: v for k, v in release.items() if k != 'surfaces'},
                             'surfaces': [{**sf, **by.get(sf['channel'], {})} for sf in card.get('surfaces') or []],
                             'products': workspace['records']}
    body['lead'] = rt.build_lead(ranked, name=name, counts=counts, fixes=queue['fixes'])
    score = await _score(row, scope.org.id, merchant, False, scope)
    body['strip'] = bo.build_strip(score)
    if body['strip'] is not None:
        body['strip']['approvals'] = sum(1 for r in reads['rules'] or [] if r.get('approval') == 'needs_approval')
        body['strip']['actions'] = None
    with _engine().connect() as conn:
        inputs = revenue_svc.inputs_view(revenue_svc.load_inputs(conn, scope.org.id, merchant), merchant)
        model = _revenue_model(conn, row, inputs, _merchant_meta(ms), None, vis.get('byQuestion') or [])
        first_at, last_at = conn.execute(text("SELECT MIN(run_at), MAX(run_at) FROM soa_runs WHERE cycle_id = :c"),
                                         {'c': row['id']}).fetchone()
    revenue = bo.build_revenue(model, headline=bo.revenue_headline(None, model=model, brand=name, name=name, things=[]),
                               brand=name)
    revenue['mode_note'] = rt.T['revenue.mode_note'].format(name=name)
    body['revenue'] = revenue
    k, n, funder = rt.funded_counts(paths=reads['paths'], answers=answers)
    missing = next((s for s in new if s and s['id'] == 'program_price_missing'), None)
    retired = next((s for s in new if s and s['id'] == 'retired_program'), None)
    body['week_in_short'] = rt.week_in_short(counts=counts, missing=missing, funded=None, funded_counts=(k, n, funder),
                                             retired=retired, access=access,
                                             release={**release, 'products': workspace['records']}, name=name,
                                             former=list((reads['loyalty'] or {}).get('former_names') or []))
    body['actions'] = rt.build_actions(fixes=queue['fixes'], rules=reads['rules'],
                                       release={**release, 'products': workspace['records']}, name=name)
    if body['strip'] is not None:
        body['strip']['actions'] = sum(1 for a in body['actions'] if a['status'] == 'done')
    body['fix_queue'] = {'fixes': queue['fixes'][:3], 'total': len(queue['fixes']),
                         'approved_or_shipped': sum(1 for f in queue['fixes'] if f['state'] in ('in_flight', 'shipped')),
                         'summary': queue['summary']}
    agents = sorted({surface_names.agent_of(r.get('platform')) or r.get('platform') for r in rows})
    answered = sum(1 for r in rows if r.get('answer_status') == surface_names.ANSWERED)
    body['activity'] = rt.build_activity(cycle=row, first_at=first_at, last_at=last_at, answers=len(rows),
                                         usable=answered, agents=len(agents),
                                         questions=(body.get('coverage') or {}).get('asked') or 0, pubs=reads['pubs'],
                                         rules=reads['rules'], held=(_record(ms) or {}).get('held'),
                                         states=page['channels'], skus=workspace['records'], name=name)
    body['header'] = {'skus': workspace['records'], 'records': workspace['records'], 'lines': workspace['lines'],
                      'retailers_checked': None, 'retailers': [], 'brand_domain': domain,
                      'unprompted': (counts or {}).get('n')}
    body['vs_label'] = (rm.cycle_label(prev, body.get('timezone')) or {}).get('vs')
    body['vs_cycle'] = (prev or {}).get('cycle_code')
    body['mode'] = cs.SELLER_EXTERNAL
    body['kind'] = 'seller'

