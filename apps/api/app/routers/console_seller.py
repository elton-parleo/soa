"""
2V-2: the reads behind an externally hosted seller's console screens (supply's
`mode` seller_external). The endpoints are console_manufacturer's and
console.py's own (/publishing, /rules, /fixes, /approvals, /truesync,
/overview, /record, /true-value, /prove): each reads the merchant's /tenant
record and, for a seller we do not host, answers from here instead of the
brand-at-retail builders. Supply is read with the org's tenant token,
server-side. Pure builders: app/services/console_seller.py.
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
    """(answers, price answers) of a cycle: every answered run {run_id, agent, intent, text}, and those asking where
    to buy or where it is cheapest (rm.VALUE_INTENTS)."""
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
                        'text': r['raw_response'] or ''})
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


async def _fix_inputs(scope: CustomerScope, ms: MerchantScope, merchant: str) -> dict:
    reads = await seller_reads(scope, merchant)
    cycles = _scored_cycles(ms)
    cycle = cycles[0] if cycles else None
    answers, price_answers = cycle_answers(cycle)
    program = next((cs._program(i.get('name'), _name(ms, merchant)) for i in reads['owned']
                    if i.get('mechanic') == 'subscription_discount'), None)
    body = cs.build_fixes(rules=reads['rules'], paths=reads['paths'], answers=answers, price_answers=price_answers,
                          loyalty=reads['loyalty'], pubs=reads['pubs'], name=_name(ms, merchant), program=program)
    return {'reads': reads, 'cycle': cycle, 'fixes': body}


async def fixes(scope: CustomerScope, ms: MerchantScope, merchant: str) -> dict:
    got = await _fix_inputs(scope, ms, merchant)
    return {'merchant': merchant, 'mode': cs.SELLER_EXTERNAL, **got['fixes'],
            'cycle': (got['cycle'] or {}).get('cycle_code'), 'read_errors': got['reads']['errors']}


async def approvals(scope: CustomerScope, ms: MerchantScope, merchant: str) -> dict:
    """The rules that gate a fix (s1, s4), the held release, and the signed rules, as fx.build_approvals reads them."""
    got = await _fix_inputs(scope, ms, merchant)
    reads = got['reads']
    fixes_ = [{**f, 'pool': 'both'} for f in got['fixes']['fixes']]
    name = _name(ms, merchant)
    body = fx.build_approvals(fixes=fixes_, rules=reads['rules'], pubs=reads['pubs'], records=len(reads['paths']),
                              skus=len(reads['paths']), brand=name)
    for request in body['requests']:
        if request['code'] == 'release':
            request['title'] = f"{len(reads['paths'])} {name} SKUs, held for {cs._possessive(name)} team"
            request['text'] = (f"The held files: {len(reads['paths'])} SKUs with {cs._possessive(name)} own prices and "
                               f"program steps as its rules allow. {cs._possessive(name)} own team sends them.")
    return {'merchant': merchant, 'mode': cs.SELLER_EXTERNAL, **body,
            'cycle': (got['cycle'] or {}).get('cycle_code'), 'read_errors': reads['errors']}


# ─── True Value, Prove, the Product record ────────────────────────────────

async def true_value(scope: CustomerScope, ms: MerchantScope, merchant: str, body: dict, cycle: dict) -> None:
    """True Value's program cards, each row's program line, the ladder and the receipt, from the price paths."""
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
                                               merchant=name),
                 'ladder': cs.build_ladder(paths=reads['paths'], answers=answers, name=name),
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
    body = cs.build_record(row=row, feed_row=None, name=_name(ms, merchant), merchant=_name(ms, merchant),
                           sent=manu.first_sent(reads['pubs']), held_any=any(manu.is_held(p) for p in reads['pubs']))
    return {'merchant': merchant, 'mode': cs.SELLER_EXTERNAL, **body, 'read_errors': reads['errors']}
