"""
2B §6: read models for the console, under /api/console/.

Each endpoint returns the console's own shape (parleohq/truesync console-
demo apps/console/src/data/types.ts and studio.ts), built by
app/services/console_read_models.py with every mapping documented in
docs/console-read-models.md. Tenant-scoped (app/console_scope.py): members
read their own org; operators may pass ?org=. Server-side only: the tenant
token never leaves this process. The soa web app's existing report
endpoints are untouched.

    GET /api/console/surfaces                      the modal's surface list
    GET /api/console/answers?cycle=<code>          Answer[]
    GET /api/console/answers/summary?cycle=<code>  per tier x surface counts, never pooled (2C)
    GET /api/console/true-value?cycle=<code>       TrueValue
    GET /api/console/programs?merchant=<slug>      TrueValue.programs, from owned incentives (2C)
    GET /api/console/accessibility?merchant=<slug> Accessibility (from supply)
    GET /api/console/truesync?merchant=<slug>      the TrueSync matrix, assembled from supply (2C)
    GET /api/console/studies?cycle=<code>          StudyRow[]
    GET /api/console/accuracy?cycle=<code>         per-surface accuracy, never pooled
    GET /api/console/visibility?cycle=<code>       who is named and who is named first, per surface (2C-1)
    GET /api/console/record/list?merchant=<slug>   the merchant's products, for the record list (2C-1)
    GET /api/console/record?merchant=<slug>&product=<sku>  one product's record (Record_), read-only (2C-1)
    GET /api/console/runs                          Run[]   (studio.ts)
    GET /api/console/studio/studies                Study[] with Prompt[] (studio.ts)
    GET /api/console/studio/entities               Entity[] (studio.ts)
    GET /api/console/full-loop/{id}                the full loop's combined status
    GET /api/console/me                            who is signed in and the orgs they may select (2C-0)
    GET /api/console/full-loop/latest              the scope's most recent full loop, or null (2C-0)
"""
import asyncio
import json
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.auth import verify_token
from app.console_scope import console_scope, cycle_customer_org_sql, cycle_in_scope
from app.customer_context import CustomerScope
from app.routers import full_loop
from app.routers.customers import _tenant_view
from app.services import console_parity as parity
from app.services import console_read_models as rm
from soa_shared import customers, surface_accuracy, surfaces
from soa_shared.database import engine

router = APIRouter(prefix="/console", tags=["console"])


def _json(value):
    return rm._json(value)


@router.get("/surfaces")
def get_surfaces(scope: CustomerScope = Depends(console_scope)):
    """Every surface that will run here, with its fidelity label, then the
    two with no verified provider (not available, with the reason)."""
    return {"surfaces": surfaces.modal_list()}


@router.get("/answers")
def get_answers(cycle: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    row = cycle_in_scope(cycle, scope)
    with engine.connect() as conn:
        return rm.load_answers(conn, dict(row))


@router.get("/answers/summary")
def get_answers_summary(cycle: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    """2C: per tier and per surface, every outcome counted, unverifiable on
    its own, and answered_with_other_brand. Never pooled across surfaces."""
    row = cycle_in_scope(cycle, scope)
    with engine.connect() as conn:
        return rm.load_answers_summary(conn, dict(row))


def _label_from_question(query_text: str) -> str:
    """'What does the X cost at Target?' -> 'X'. The catalog tier's wording
    is fixed (generation/catalog_tiers.py), so this is a parse, not a guess."""
    label = query_text or ''
    for prefix in ('What does the ',):
        if label.startswith(prefix):
            label = label[len(prefix):]
    for suffix in (' cost?',):
        if label.endswith(suffix):
            label = label[:-len(suffix)]
    if ' cost at ' in label:
        label = label.split(' cost at ', 1)[0]
    return label


@router.get("/visibility")
def get_visibility(cycle: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    """2C-1: Measure > Visibility. Who each answer names and who it names
    first, from the stored mention coding (Layer 1 position, Layer 2
    other_brands_named), per surface with a per-agent split. Never pooled
    across surfaces; no model call."""
    row = cycle_in_scope(cycle, scope)
    with engine.connect() as conn:
        return _visibility(conn, dict(row))


def _visibility(conn, row: dict) -> dict:
    """2C-1's read with 2C-2's headline, matrix and by-stage, per surface."""
    body = rm.load_visibility(conn, row)
    ours = next((r['name'] for r in (body.get('ranking') or {}).get('rows') or [] if r.get('you')), None)
    return parity.extend_visibility(body, ours)


@router.get("/overview")
async def get_overview(cycle: str = Query(...), merchant: Optional[str] = Query(None),
                       scope: CustomerScope = Depends(console_scope)):
    """2C-2: This week for one cycle, per surface: the agent table, the
    products, up to four signals, the week in short, the changes against the
    previous scored cycle (none on a first cycle) and Visibility's ranking,
    reused. Every sentence is a template filled from counts (console_parity.
    TEMPLATES). With `merchant`, the last access run feeds the access signal;
    a failed read leaves it out and is named in `read_errors`."""
    row = dict(cycle_in_scope(cycle, scope))
    with engine.connect() as conn:
        rows = parity.load_overview_rows(conn, row)
        vis = _visibility(conn, row)
        own_domain, variants, scored = _true_value_inputs(conn, row)
        prev, n_scored = parity.previous_scored_cycle(conn, row, cycle_customer_org_sql())
        previous = None
        if prev is not None:
            prev = {**prev, 'customer_org_id': row['customer_org_id']}
            previous = {'code': prev['cycle_code'], 'rows': parity.load_overview_rows(conn, prev),
                        'visibility': _visibility(conn, prev)}
        job = conn.execute(text("SELECT tier_config FROM soa_query_generation_jobs WHERE study_type = :st"),
                           {"st": row['study_type']}).fetchone()
        study_questions = conn.execute(text("SELECT COUNT(*) FROM soa_queries WHERE study_type = :st"),
                                       {"st": row['study_type']}).scalar()
    brand = next((r['name'] for r in (vis.get('ranking') or {}).get('rows') or [] if r.get('you')), None) or \
        (((_json(job[0]) if job else None) or {}).get('merchant') or {}).get('study_brand') or 'the brand'
    access, errors, reads = None, {}, None
    if merchant:
        client = full_loop._client(scope)
        (_, payload, error), (_, reference, r_err) = await asyncio.gather(client.get_access(merchant),
                                                                          client.get_reference(merchant))
        if error is None:
            access = rm.accessibility_from_supply(payload)
        else:
            errors['access'] = error
        if r_err is None:
            reads = (reference or {}).get('rows')
        else:
            errors['reference'] = r_err
    # 2C-2a: the newest page read is the reference when the cycle cached none
    tv = rm.build_true_value(_json(row.get('reference_prices')), scored, own_domain=own_domain,
                             record_variants=variants, reads=reads)
    return parity.build_overview(row, rows=rows, visibility=vis, true_value=tv, brand=brand, access=access,
                                 previous=previous, scored_cycles=n_scored if n_scored else 1, read_errors=errors,
                                 study_questions=study_questions)


def _true_value_inputs(conn, row) -> tuple:
    """(own_domain, record variants, scored items) for a cycle's catalog
    tier: what build_true_value reads. 2C-2: each scored item carries its
    run, agent and surface, so a cell is per surface."""
    questions = conn.execute(text("""
        SELECT q.id, q.query_text, q.expected_answer, q.source_ref
        FROM soa_queries q
        WHERE q.study_type = :st AND q.tier = 'catalog_accuracy'
    """), {"st": row['study_type']}).mappings().all()
    outcomes = conn.execute(text("""
        SELECT o.run_id, o.query_id, o.outcome, o.reason_code, o.claim_results, o.expected_answer,
               r.platform, r.surface
        FROM soa_expectation_outcomes o JOIN soa_runs r ON r.id = o.run_id
        WHERE o.cycle_id = :c AND o.tier = 'catalog_accuracy'
    """), {"c": row['id']}).mappings().all()

    by_query = {q['id']: q for q in questions}
    own_domain, variants = None, []
    for q in questions:
        ref = _json(q['source_ref']) or {}
        expected = _json(q['expected_answer']) or {}
        own_domain = own_domain or ref.get('own_domain') or ref.get('domain')
        if expected.get('type') == 'price':
            variants.append({'variant_id': ref.get('variant_id'), 'gtin': ref.get('gtin'),
                             'label': _label_from_question(q['query_text']),
                             'list_price': expected.get('amount'), 'currency': expected.get('currency'),
                             'published_at': ref.get('published_at'), 'listing_id': ref.get('listing_id')})
    if own_domain is None:
        job = conn.execute(text("SELECT tier_config FROM soa_query_generation_jobs WHERE study_type = :st"),
                           {"st": row['study_type']}).fetchone()
        study_questions = conn.execute(text("SELECT COUNT(*) FROM soa_queries WHERE study_type = :st"),
                                       {"st": row['study_type']}).scalar()
        merchant = ((_json(job[0]) if job else None) or {}).get('merchant') or {}
        own_domain = merchant.get('own_domain') or merchant.get('domain')

    names = rm.load_variant_names(conn, row)
    scored = []
    for o in outcomes:
        q = by_query.get(o['query_id'])
        if q is None:
            continue
        ref = _json(q['source_ref']) or {}
        expected = _json(o['expected_answer']) or {}
        all_claims = _json(o['claim_results']) or []
        claims = [c for c in all_claims if c.get('target') == 'asked']
        # The quote is the claim that decided the run's outcome, not merely
        # its first: "$11.99 or $12.99" scored exact on the $12.99. 2C-2a:
        # with no claim about the variant asked, a swap or clash claim that
        # decided it is the quote (the price stated for a sibling), named.
        deciding = next((c for c in claims if c.get('outcome') == o['outcome']), claims[0] if claims else None)
        swap = None
        if deciding is None:
            swap = rm.deciding_swap(all_claims, o['outcome'])
            deciding = swap
        scored.append({'variant_id': ref.get('variant_id'), 'gtin': ref.get('gtin'),
                       'retailer': expected.get('attributed_to') or own_domain,
                       'outcome': o['outcome'], 'reason_code': o['reason_code'],
                       'stated': deciding.get('stated') if deciding else None,
                       # 2C-2c: the sibling resolved to its record name, once
                       'swap_product': rm.sibling_name(swap, names) if swap else None,
                       'swap_variant': swap.get('variant_id') if swap else None,
                       'run': f"run-{o['run_id']}", 'platform': o['platform'],
                       'agent': surfaces.agent_of(o['platform']) or o['platform'],
                       'surface': o['surface'] or surfaces.surface_of(o['platform']) or 'unlabelled'})
    return own_domain, variants, scored


@router.get("/true-value")
async def get_true_value(cycle: str = Query(...), merchant: Optional[str] = Query(None),
                         scope: CustomerScope = Depends(console_scope)):
    """TrueValue for one cycle, per surface (2C-2). With `merchant`, also the
    merchant's programs (owned incentives, each with how many agents quoted
    it right) and the ladder for its primary product (list price, then each
    stated member price). A supply read that fails leaves its part out and is
    named in `read_errors`."""
    row = cycle_in_scope(cycle, scope)
    with engine.connect() as conn:
        own_domain, variants, scored = _true_value_inputs(conn, row)
        value_outcomes = _value_outcomes(conn, row) if merchant else []
    if not merchant:
        return rm.build_true_value(_json(row.get('reference_prices')), scored, own_domain=own_domain,
                                   record_variants=variants)
    client = full_loop._client(scope)
    (_, owned, o_err), (_, incentives, i_err), (_, catalog, k_err), (_, reference, r_err), (history, h_err) = \
        await asyncio.gather(client.get_owned_incentives(merchant), client.get_merchant_incentives(merchant),
                             client.get_merchant_catalog(merchant), client.get_reference(merchant),
                             _member_reads(client, merchant))
    errors = {n: e for n, e in (('owned_incentives', o_err), ('incentives', i_err), ('catalog', k_err),
                                ('reference', r_err), ('retailer_prices', h_err)) if e is not None}
    # 2C-2a: the newest page read is the reference when the cycle cached none
    body = rm.build_true_value(_json(row.get('reference_prices')), scored, own_domain=own_domain,
                               record_variants=variants, reads=(reference or {}).get('rows') if r_err is None else None)
    programs = rm.build_programs((owned or {}).get('incentives') or [] if o_err is None else [], value_outcomes,
                                 record=incentives if i_err is None else None)
    body['programs'] = programs
    body['ladder'], body['receipt'] = parity.build_ladder(
        catalog if k_err is None else None, incentives if i_err is None else None,
        (owned or {}).get('incentives') if o_err is None else None, scored, own_domain=own_domain,
        reads=(reference or {}).get('rows') if r_err is None else None, member_reads=history)
    body['member_reads'] = 'history' if history is not None else 'reference'
    body['read_errors'] = errors
    return body


#: 2C-2c: reads per variant x retailer a member price is looked for in.
MEMBER_READ_HISTORY = 10


async def _member_reads(client, merchant: str) -> tuple:
    """(rows, error) for the member-price rule: every readable read per
    variant x retailer, newest first, from supply's retailer-prices with
    `history=1` (supply #20). /reference holds only the newest read per page,
    so a member price an older read saw (Oct 9) and the newest did not (Oct
    14) was out of reach. A supply that does not honour `history` answers
    without `history: true`: then (None, None) and the caller keeps reading
    /reference, as before."""
    status, body, error = await client.get_retailer_prices(merchant, history=True, limit=MEMBER_READ_HISTORY)
    if error is not None:
        return None, error
    if not isinstance(body, dict) or body.get('history') is not True:
        return None, None
    return body.get('prices') or [], None


def _value_outcomes(conn, row) -> list:
    """2C-2a: with the question's source_ref (offer_id, variant_id), which
    the program join reads alongside the expectation."""
    return [dict(o) for o in conn.execute(text("""
        SELECT o.outcome, o.expected_answer, r.platform, COALESCE(r.surface, o.surface) AS surface,
               q.source_ref
        FROM soa_expectation_outcomes o JOIN soa_runs r ON r.id = o.run_id
        JOIN soa_queries q ON q.id = r.query_id
        WHERE o.cycle_id = :c AND o.tier = 'value_incentives'
    """), {"c": row['id']}).mappings()]


@router.get("/accessibility")
async def get_accessibility(merchant: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    client = full_loop._client(scope)
    (status, payload, error), (_, reference, r_err) = await asyncio.gather(
        client.get_access(merchant), client.get_reference(merchant))
    if error is not None:
        raise HTTPException(status_code=404 if status == 404 else 502,
                            detail=f"TrueSync access payload unavailable: {error}")
    # 2C-2: the merchant-level checks from the latest reference read; a
    # failed read leaves them 'not_checked' and is named in read_errors.
    return parity.extend_accessibility(rm.accessibility_from_supply(payload), reference if r_err is None else None,
                                       reference_error=r_err)


@router.get("/programs")
async def get_programs(merchant: str = Query(...), cycle: Optional[str] = Query(None),
                       scope: CustomerScope = Depends(console_scope)):
    """2C: TrueValue.programs from the merchant's owned incentives (supply,
    with the tenant token), each with how this cycle's value & incentives
    answers did on it when `cycle` is given."""
    client = full_loop._client(scope)
    (status, payload, error), (_, record, i_err) = await asyncio.gather(
        client.get_owned_incentives(merchant), client.get_merchant_incentives(merchant))
    if error is not None:
        raise HTTPException(status_code=404 if status == 404 else 502,
                            detail=f"TrueSync incentives unavailable: {error}")
    outcomes = []
    if cycle:
        row = cycle_in_scope(cycle, scope)
        with engine.connect() as conn:
            outcomes = _value_outcomes(conn, row)
    return {'merchant': (payload or {}).get('merchant') or merchant,
            'programs': rm.build_programs((payload or {}).get('incentives') or [], outcomes,
                                          record=record if i_err is None else None)}


@router.get("/truesync")
async def get_truesync(merchant: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    """2C: the TrueSync matrix (Command Center) for one of the scope's
    merchants: publish state per product x channel, drift, acceptance
    (Merchant Center, and Manufacturer Center with its gmc_sync origin and
    "not connected" for a tenant with no MC account), last verified, and
    the validator lines and artifact per cell. Assembled from supply with
    the tenant token (rm.build_truesync)."""
    client = full_loop._client(scope)
    (c_status, channels, c_err), (p_status, pubs, p_err), (k_status, catalog, k_err), (_, prov, prov_err) = \
        await asyncio.gather(client.get_channels(), client.get_publications(limit=500),
                             client.get_merchant_catalog(merchant), client.get_provenance(merchant))
    for status, error in ((k_status, k_err), (c_status, c_err), (p_status, p_err)):
        if error is not None:
            raise HTTPException(status_code=404 if status == 404 else 502,
                                detail=f"TrueSync matrix unavailable: {error}")
    slugs = [c['slug'] for c in channels or [] if c.get('is_active', True)]
    reads = await asyncio.gather(*(client.get_merchant_verifications(merchant, channel=s, limit=100) for s in slugs))
    verifications = {s: (body if err is None else {}) for s, (_, body, err) in zip(slugs, reads)}
    body = rm.build_truesync(merchant, channels=channels or [], publications=pubs or [], catalog=catalog or {},
                             verifications=verifications, provenance=prov if prov_err is None else None)
    # 2C-2c: each product's publish timeline from the journal this read already
    # holds (publications and channel checks), so the console makes no second
    # call per product (the full /record read was what kept it waiting).
    names = {c.get('slug'): c.get('name') or c.get('slug') for c in channels or []}
    for product in body['products']:
        lid = product.get('listing_id')
        ver = [v for env in verifications.values() for e in (env or {}).get('listings') or []
               if e.get('listing_id') == lid for v in e.get('verifications') or []]
        product['timeline'] = parity.record_history(lid, publications=pubs or [], verifications=ver,
                                                    reference_rows=[], channel_names=names)
    return body


async def _record_inputs(merchant: str, scope: CustomerScope, *, incentives: bool) -> dict:
    """2C-1: what the record reads from supply, with the org's tenant token.
    The catalog is required (a 404 is "no record yet"); the rest degrade:
    each failure is named in `read_errors` and its part is left out."""
    client = full_loop._client(scope)
    reads = [client.get_merchant_catalog(merchant), client.get_publications(limit=500), client.get_channels(),
             client.get_provenance(merchant), client.get_reference(merchant)]
    if incentives:
        reads += [client.get_merchant_incentives(merchant), client.get_owned_incentives(merchant)]
    view, *results = await asyncio.gather(_tenant_view(scope.org), *reads)
    (k_status, catalog, k_err), *rest = results
    if k_err is not None and k_status != 404:
        raise HTTPException(status_code=502, detail=f"TrueSync catalog unavailable: {k_err}")
    names = ('publications', 'channels', 'provenance', 'reference', 'incentives', 'owned_incentives')
    errors = {n: err for n, (_, _, err) in zip(names, rest) if err is not None}
    if view.get('error'):
        errors['tenant'] = view['error']
    body = {n: (b if err is None else None) for n, (_, b, err) in zip(names, rest)}
    return {
        'catalog': catalog if k_err is None else None,
        'merchant_record': next((m for m in view.get('merchants') or [] if m.get('slug') == merchant), None),
        'publications': body['publications'] or [], 'channels': body['channels'] or [],
        'provenance': body['provenance'], 'reference': body['reference'],
        'incentives': body.get('incentives'), 'owned_incentives': (body.get('owned_incentives') or {}).get('incentives'),
        'read_errors': errors,
    }


@router.get("/record/list")
async def get_record_list(merchant: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    """2C-1: Fix > Offer record, the product list. Every product in the
    merchant's record (supply's published catalog, or an external merchant's
    current feed), each with its status. A merchant with no record yet is an
    empty list, not an error."""
    got = await _record_inputs(merchant, scope, incentives=False)
    return rm.build_record_list(merchant, got['catalog'], merchant_record=got['merchant_record'],
                                publications=got['publications'], channels=got['channels'],
                                provenance=got['provenance'], reference=got['reference'],
                                read_errors=got['read_errors'])


@router.get("/record")
async def get_record(merchant: str = Query(...), product: str = Query(...),
                     scope: CustomerScope = Depends(console_scope)):
    """2C-1: one product's record (Record_), read-only: its fields with
    provenance, where the latest reference read disagrees (`was`, `diff`),
    the validator's issues, the variants with member prices, and the
    compiled schema.org artifact. `product` is the list's `sku` (or the
    listing id)."""
    got = await _record_inputs(merchant, scope, incentives=True)
    listing = next((l for l in (got['catalog'] or {}).get('listings') or []
                    if product in (rm._listing_sku(l), str(l.get('listing_id')))), None)
    if listing is None:
        raise HTTPException(status_code=404, detail=f"product {product!r} is not in {merchant!r}'s record")
    client = full_loop._client(scope)
    history, h_err = await _member_reads(client, merchant)
    record = rm.build_record(merchant, listing, merchant_record=got['merchant_record'],
                             publications=got['publications'], channels=got['channels'],
                             provenance=got['provenance'], reference=got['reference'],
                             incentives=got['incentives'],
                             read_errors={**got['read_errors'], **({'retailer_prices': h_err} if h_err else {})},
                             member_reads=history)
    # 2C-2: the offer fields, history, surfaces (the TrueSync matrix's cells
    # for this product, reused) and the issues grouped by channel.
    slugs = [c['slug'] for c in got['channels'] if c.get('is_active', True)]
    reads = await asyncio.gather(*(client.get_merchant_verifications(merchant, channel=sl, limit=100) for sl in slugs))
    verifications = {sl: (b if err is None else {}) for sl, (_, b, err) in zip(slugs, reads)}
    failed = [sl for sl, (_, _, err) in zip(slugs, reads) if err is not None]
    if failed:
        record['read_errors'] = {**record.get('read_errors', {}), 'verifications': ', '.join(failed)}
    matrix = rm.build_truesync(merchant, channels=got['channels'], publications=got['publications'],
                               catalog={'listings': [listing]}, verifications=verifications,
                               provenance=got['provenance'])
    return parity.extend_record(record, listing=listing, owned=got['owned_incentives'], reference=got['reference'],
                                publications=got['publications'], verifications=verifications,
                                channels=got['channels'], truesync_product=(matrix['products'] or [None])[0],
                                truesync_channels=matrix['channels'])


@router.get("/studies")
def get_studies(cycle: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    row = cycle_in_scope(cycle, scope)
    with engine.connect() as conn:
        runs = [dict(r) for r in conn.execute(text(
            "SELECT * FROM soa_runs WHERE cycle_id = :c"), {"c": row['id']}).mappings()]
        query_ids = sorted({r['query_id'] for r in runs})
        queries = [dict(q) for q in conn.execute(text(
            "SELECT id, query_code, query_text, tier, stage FROM soa_queries WHERE study_type = :st "
            "ORDER BY query_code"), {"st": row['study_type']}).mappings() if q['id'] in query_ids]
        outcomes = {o['run_id']: dict(o) for o in conn.execute(text(
            "SELECT * FROM soa_expectation_outcomes WHERE cycle_id = :c"), {"c": row['id']}).mappings()}
        picks: Dict[int, str] = {}
        primary_named: Dict[int, bool] = {}
        for m in conn.execute(text("""
            SELECT cm.run_id, e.name, cm.position, cm.mentioned, ce.role
            FROM soa_coded_mentions cm
            JOIN soa_entities e ON e.id = cm.entity_id
            JOIN soa_runs r ON r.id = cm.run_id
            LEFT JOIN soa_cycle_entities ce ON ce.cycle_id = r.cycle_id AND ce.entity_id = cm.entity_id
            WHERE r.cycle_id = :c
        """), {"c": row['id']}).mappings():
            if m['mentioned'] and m['position'] == 1:
                picks[m['run_id']] = m['name']
            if m['role'] == 'primary':
                primary_named[m['run_id']] = bool(m['mentioned'])
    return rm.build_study_rows(queries, runs, outcomes, picks, primary_named)


@router.get("/accuracy")
def get_accuracy(cycle: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    row = cycle_in_scope(cycle, scope)
    with engine.connect() as conn:
        return {'cycle': row['cycle_code'], 'surfaces': surface_accuracy.for_cycle(conn, row['id'])}


def _scope_cycles(conn, scope):
    return [dict(c) for c in conn.execute(text(f"""
        SELECT c.* FROM soa_cycles c
        WHERE {cycle_customer_org_sql()} = :org
        ORDER BY c.start_date DESC, c.id DESC
    """), {"org": scope.org.id}).mappings()]


@router.get("/runs")
def get_runs(scope: CustomerScope = Depends(console_scope)):
    with engine.connect() as conn:
        cycles = _scope_cycles(conn, scope)
        out = []
        for cycle in cycles:
            counts = conn.execute(text("""
                SELECT SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN answer_status = 'answered' THEN 1 ELSE 0 END)
                FROM soa_runs WHERE cycle_id = :c
            """), {"c": cycle['id']}).fetchone()
            out.append(rm.build_run(cycle, int(counts[0] or 0), int(counts[1] or 0)))
    return out


@router.get("/studio/studies")
def get_studio_studies(scope: CustomerScope = Depends(console_scope)):
    with engine.connect() as conn:
        jobs = [dict(j) for j in conn.execute(text("""
            SELECT * FROM soa_query_generation_jobs
            WHERE COALESCE(customer_organization_id, organization_id) = :org ORDER BY created_at DESC
        """), {"org": scope.org.id}).mappings()]
        out = []
        for job in jobs:
            brand = ((_json(job.get('tier_config')) or {}).get('merchant') or {}).get('study_brand')
            prompts = [rm.build_prompt(dict(q), brand) for q in conn.execute(text(
                "SELECT * FROM soa_queries WHERE study_type = :st ORDER BY query_code"),
                {"st": job['study_type']}).mappings()]
            cycles = [dict(c) for c in conn.execute(text(
                "SELECT * FROM soa_cycles WHERE study_type = :st ORDER BY start_date DESC, id DESC"),
                {"st": job['study_type']}).mappings()]
            entities = []
            if cycles:
                entities = [dict(e) for e in conn.execute(text("""
                    SELECT e.slug, ce.role FROM soa_cycle_entities ce
                    JOIN soa_entities e ON e.id = ce.entity_id WHERE ce.cycle_id = :c
                """), {"c": cycles[0]['id']}).mappings()]
            study = rm.build_study(job, prompts, cycles, entities)
            # 2C-2c: branded = the tiered questions (they name the brand)
            study['prompt_counts'] = rm.prompt_counts(prompts)
            out.append(study)
    return out


@router.get("/studio/entities")
def get_studio_entities(scope: CustomerScope = Depends(console_scope)):
    """The entities this tenant's cycles compare: soa_entities is a global
    registry, so it is narrowed to what this org's studies actually use."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT DISTINCT e.* FROM soa_entities e
            JOIN soa_cycle_entities ce ON ce.entity_id = e.id
            JOIN soa_cycles c ON c.id = ce.cycle_id
            WHERE {cycle_customer_org_sql()} = :org
            ORDER BY e.name
        """), {"org": scope.org.id}).mappings().all()
    return [rm.build_entity(dict(r)) for r in rows]


@router.get("/me")
async def get_me(user: dict = Depends(verify_token)):
    """2C-0: the console's workspace switcher. The orgs this login may select
    (soa_shared/customers.py decides: operators every linked org, members
    their own), each with its first merchant's kind, hosting and domain from
    the merchant record supply holds (read with that org's own token, as
    /api/customers does). Not scoped to one org: it is the list the scope is
    chosen from, and it names nothing the user may not select.

    `slug` is the merchant's slug (what /accessibility?merchant= takes);
    `tenant_slug`, `merchants` and `error` ride beside it. An org whose
    record read fails is still listed, with kind/hosting/domain null and the
    error, rather than vanishing from the switcher."""
    user_id = user.get("sub")
    views = await asyncio.gather(*(_tenant_view(org) for org in customers.selectable_orgs(user_id)))
    orgs = []
    for view in views:
        first = (view.get("merchants") or [None])[0] or {}
        orgs.append({
            "id": view["org_id"],
            "slug": first.get("slug") or view["tenant_slug"],
            "name": view["name"],
            "kind": first.get("kind"),
            "hosting": first.get("hosting"),
            "domain": first.get("domain"),
            "tenant_slug": view["tenant_slug"],
            "merchants": view.get("merchants") or [],
            "error": view.get("error"),
        })
    return {
        "user": {"id": user_id, "email": user.get("email")},
        "is_operator": customers.is_operator(user_id),
        "orgs": orgs,
    }


@router.get("/full-loop/latest")
async def get_console_full_loop_latest(scope: CustomerScope = Depends(console_scope)):
    """2C-0: the scope's most recent full loop in the shape /full-loop/{id}
    returns, or null when the org has never run one (the console's status
    strip shows "no run yet", which is not an error). Declared before
    /full-loop/{request_id} so 'latest' is never read as an id."""
    with engine.connect() as conn:
        request_id = conn.execute(text("""
            SELECT id FROM soa_full_loop_requests WHERE organization_id = :org
            ORDER BY created_at DESC, id DESC LIMIT 1
        """), {"org": scope.org.id}).scalar()
    if request_id is None:
        return None
    return await full_loop.read_full_loop(request_id, scope)


@router.get("/full-loop/{request_id}")
async def get_console_full_loop(request_id: int, scope: CustomerScope = Depends(console_scope)):
    return await full_loop.read_full_loop(request_id, scope)
