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
    GET /api/console/answers/summary?cycle=<code>  per tier: every agent together (`all`), then per surface (2C, 2I-8)
    GET /api/console/true-value?cycle=<code>       TrueValue
    GET /api/console/programs?merchant=<slug>      TrueValue.programs, from owned incentives (2C)
    GET /api/console/accessibility?merchant=<slug> Accessibility (from supply)
    GET /api/console/truesync?merchant=<slug>      the TrueSync matrix, assembled from supply (2C)
    GET /api/console/studies?cycle=<code>          StudyRow[]
    GET /api/console/accuracy?cycle=<code>         per-surface accuracy, never pooled
    GET /api/console/visibility?cycle=<code>       who is named and who is named first, `all` then per surface (2C-1, 2I-8)
    GET /api/console/record/list?merchant=<slug>   the merchant's products, for the record list (2C-1)
    GET /api/console/record?merchant=<slug>&product=<sku>  one product's record (Record_), read-only (2C-1)
    GET /api/console/runs                          Run[]   (studio.ts)
    GET /api/console/studio/studies                Study[] with Prompt[] (studio.ts)
    GET /api/console/studio/entities               Entity[] (studio.ts)
    GET /api/console/full-loop/{id}                the full loop's combined status
    GET /api/console/me                            who is signed in and the orgs they may select (2C-0)
    GET /api/console/full-loop/latest              the scope's most recent full loop, or null (2C-0)
    GET /api/console/score?cycle=<code>            the Share of Algorithm, per surface and pooled (2C-3)
    GET|PUT|DELETE /api/console/revenue-inputs?merchant=<slug>  the revenue model's inputs, per merchant (2I-9)
    GET /api/console/revenue?cycle=<code>&merchant=<slug>       the revenue model: inputs, measured shares (2I-9)
    GET /api/console/revenue/history?merchant=<slug>            shares and dollars per scored cycle (2I-9)
"""
import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import text

from app.auth import verify_token
from app.console_scope import console_scope, cycle_customer_org_sql, cycle_in_scope
from app.customer_context import CustomerScope
from app.console_merchants import MerchantScope, check_merchant, merchant_cycles, merchant_scope, study_merchants, with_domains
from app import worker_surfaces
from app.routers import full_loop
from app.routers.customers import _tenant_view
from app.services import console_claims
from app.services import console_measure as measure
from app.services import console_narratives as narratives_svc
from app.services import console_parity as parity
from app.services import console_prompts
from app.services import console_read_models as rm
from app.services import console_revenue as revenue_svc
from app.services import console_cache
from app.services import console_score as score_svc
from clients import truesync_client as supply_fields
from clients.truesync_client import TrueSyncClient
from soa_shared import customers, cycle_compare, severity, surface_accuracy, surfaces
from soa_shared.database import engine

router = APIRouter(prefix="/console", tags=["console"])


def _json(value):
    return rm._json(value)


@router.get("/surfaces")
def get_surfaces(scope: CustomerScope = Depends(console_scope)):
    """Every surface that will run here, with its fidelity label, then the
    two with no verified provider (not available, with the reason). 2I: each
    with `grounded` and the worker's `configured` and `seen_at` (None until
    the worker has reported)."""
    return {"surfaces": worker_surfaces.console_list(engine)}


@router.get("/answers")
async def get_answers(cycle: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    """2K-3: each answer's claim_kind reads the merchant's catalog features
    (_claim_features); a failed catalog read leaves 2K-1's lexicon with the
    endorsement words."""
    row = dict(cycle_in_scope(cycle, scope))
    (features, _error), clubs = await asyncio.gather(_claim_features(row, scope), _club_keys(row, scope))
    with engine.connect() as conn:
        # 2L-3: each answer's narrative, null when it has none
        return narratives_svc.with_answers(rm.load_answers(conn, row, features, club_keys=clubs),
                                           narratives_svc.lines_for(conn, row['id']))


def _study_slug(row: dict) -> Optional[str]:
    """The cycle's study's merchant: tier_config.merchant.slug, else its syndicated merchant."""
    with engine.connect() as conn:
        job = conn.execute(text(
            "SELECT tier_config, syndicated_merchant FROM soa_query_generation_jobs WHERE study_type = :st "
            "ORDER BY id DESC LIMIT 1"), {"st": row.get('study_type')}).mappings().first()
    if not job:
        return None
    return ((_json(job['tier_config']) or {}).get('merchant') or {}).get('slug') or job['syndicated_merchant']


async def _club_keys(row: dict, scope: CustomerScope, merchant: Optional[str] = None) -> Optional[set]:
    """2T-4 (2): the keys of the feed's club-only variants (console_brand_overview.club_lines: every
    retailer the feed lists for it, the brand's own sites aside, a warehouse club), for the severity's
    club rule. None with no merchant, or when the feed or /retailers could not be read: the rule then
    reads nothing, and a read never fails for want of it."""
    from app.services import console_brand_overview as bo
    slug = merchant or _study_slug(row)
    if not slug:
        return None
    reads = _reads(scope)
    try:
        (_fs, feed, f_err), (_rs, retailers, r_err) = await asyncio.gather(
            full_loop._client(scope).get_feed(slug), reads.get_retailers(slug))
    except Exception:  # noqa: BLE001
        return None
    if f_err is not None or r_err is not None or not isinstance(feed, dict) or not isinstance(retailers, dict):
        return None
    own = retailers.get('own_domains') or [retailers.get('own_domain')]
    lines = bo.club_lines(feed.get('rows'), [d for d in own if d])
    return set().union(*(line['keys'] for line in lines)) if lines else set()


async def _claim_features(row: dict, scope: CustomerScope, merchant: Optional[str] = None) -> tuple:
    """2K-3 (B4): (the feature terms of the cycle's merchant's published
    catalog, the read's error or None), for claim_kind (console_claims).
    The merchant is `merchant`, else the study's (tier_config.merchant.slug,
    else its syndicated merchant); the brand's own terms are left out of the
    features, as the brand terms are loaded (load_brand_terms). No merchant:
    no features, no read."""
    with engine.connect() as conn:
        job = conn.execute(text(
            "SELECT tier_config, syndicated_merchant FROM soa_query_generation_jobs WHERE study_type = :st "
            "ORDER BY id DESC LIMIT 1"), {"st": row.get('study_type')}).mappings().first()
        terms = rm.load_brand_terms(conn, row)
    slug = merchant or (((_json(job['tier_config']) or {}).get('merchant') or {}).get('slug') if job else None) or \
        (job['syndicated_merchant'] if job else None)
    if not slug:
        return [], None
    status, catalog, error = await _reads(scope).get_merchant_catalog(slug)
    if error is not None and status and 400 <= status < 500:
        return console_claims.feature_terms(None, terms), None   # a merchant with no catalog: nothing to read
    return console_claims.feature_terms(catalog if error is None else None, terms), error


@router.get("/answers/summary")
async def get_answers_summary(cycle: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    """2C: per tier and per surface, every outcome counted, unverifiable on
    its own, and answered_with_other_brand. 2I-8: every agent together
    (`all`) first, counts summed; each surface beside it. 2T-4 (2):
    `severity`, the Answers list's flagged counts (soa_shared/severity.tally
    over the answers /answers serves). 2T-5 (A1 to A3): the lead over the
    same answers, `flagged`, `hero`, `worst_answer_id`, `chips` and `kinds`
    (console_measure.answers_lead)."""
    row = dict(cycle_in_scope(cycle, scope))
    clubs = await _club_keys(row, scope)
    with engine.connect() as conn:
        body = rm.load_answers_summary(conn, row)
        answers = rm.load_answers(conn, row, club_keys=clubs)
        body['severity'] = severity.tally(answers)
        body.update(measure.answers_lead(answers, rm.load_primary(conn, row)))
        return body


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
async def get_visibility(cycle: str = Query(...), merchant: Optional[str] = Query(None),
                         scope: CustomerScope = Depends(console_scope)):
    """2C-1: Measure > Visibility. Who each answer names and who it names
    first, from the stored mention coding (Layer 1 position, Layer 2
    other_brands_named), every agent together (`all`, 2I-8) and per surface,
    each with a per-agent split; no model call. 2L-4: for a brand whose
    study asks where to buy, `routing`, which reads supply's retailer list
    and reference reads for the cycle's merchant (or the one named)."""
    if merchant:
        await check_merchant(scope, merchant)
    row = dict(cycle_in_scope(cycle, scope))
    facts, errors = await _routing_inputs(scope, row, merchant)
    with engine.connect() as conn:
        body = _visibility(conn, row, facts, errors)
        # 2P-1 (B3): first picks by brand, the routing table and the retired lines against
        # the previous cycle, when the two compare
        compared = _compared(conn, row, _rows(conn, row), body, facts)
    body['previous'] = _previous_block(compared)
    if compared and compared['status'] == 'compared':
        body['moved'] = rm.visibility_movement(body, compared['visibility'], compared['name'])
    # 2T-5 (V1 to V3): a brand at retail's lead, the gap's dollars the revenue model's Lost pool
    # (a brand's ranking opens on its brand-choice answers: build_visibility's `brand_choice`)
    if (body.get('ranking') or {}).get('brand_choice'):
        with engine.connect() as conn:
            slug = merchant or score_svc.cycle_merchant(conn, row)
            brand = rm.load_primary(conn, row)
        lost = await _lost_pool(scope, row, slug, body.get('byQuestion') or [])
        body.update(measure.visibility_lead(body, brand, lost))
    return body


async def _lost_pool(scope: CustomerScope, row: dict, slug: Optional[str], vis_rows: list) -> dict:
    """2T-5 (V2): {dollars, reason}, the revenue model's Lost pool today as the brand Overview builds it
    (no access line), or why there are no dollars: no merchant, or the model's own dollars_reason."""
    if not slug:
        return {'dollars': None, 'reason': 'no merchant record for this cycle'}
    from sqlalchemy.exc import SQLAlchemyError
    ms = await check_merchant(scope, slug)
    answers, _reference, _r_err = await _attribute_inputs(scope, row, slug)
    try:
        with engine.connect() as conn:
            inputs = revenue_svc.inputs_view(revenue_svc.load_inputs(conn, scope.org.id, slug), slug)
            site = next((a['site'] for a in answers if a.get('site')), None)
            model = _revenue_model(conn, row, inputs, _merchant_meta(ms), None, vis_rows,
                                   attribute_answers=answers or None, site=site)
    except SQLAlchemyError as e:   # the dollars are beside the read: Visibility never fails for want of them
        return {'dollars': None, 'reason': f"the revenue inputs could not be read ({type(e).__name__})"}
    today = model.get('today') if model.get('dollars') else None
    return {'dollars': round(today['lost']) if today else None, 'reason': None if today else model.get('dollars_reason')}


def _visibility(conn, row: dict, merchant: Optional[dict] = None, errors: Optional[dict] = None) -> dict:
    """2C-1's read with 2C-2's headline, matrix and by-stage, per surface.
    2Q-1 (B3): kept per cycle state and merchant facts (console_cache)."""
    def read():
        body = rm.load_visibility(conn, row, merchant)
        ours = next((r['name'] for r in (body.get('ranking') or {}).get('rows') or [] if r.get('you')), None)
        return parity.extend_visibility(body, ours)
    body = console_cache.cycle_read(conn, row, 'visibility', read, merchant)
    if body.get('routing') is not None:
        body['routing']['read_errors'] = errors or {}
    return body


def _rows(conn, row: dict, features=None) -> list:
    """parity.load_overview_rows, kept per cycle state and catalog features (2Q-1, B3)."""
    return console_cache.cycle_read(conn, row, 'overview_rows', lambda: parity.load_overview_rows(conn, row, features),
                                    features)


def _reads(scope: CustomerScope):
    """2Q-1 (B3): supply's client for the console's reads, each read kept a few
    minutes per org (console_cache.reads); a failed read is never kept."""
    return console_cache.reads(full_loop._client(scope), scope.org.id)


def _compared(conn, row: dict, rows: list, vis: dict, facts: Optional[dict] = None,
              prev: Optional[dict] = None) -> Optional[dict]:
    """2P-1 (B3): the newest earlier scored cycle and whether it compares with
    this one, by the rule the Changes block reads (every agent together):
    {code, row, rows, visibility, status, note, condition}, None on a first
    cycle. Visibility, True Value, Prove and Impact read their deltas only
    when `status` is 'compared'. 2R-2 (B3): `prev` names the earlier cycle
    (the last before a stated send), by the same rule."""
    if prev is None:
        prev, _n = parity.previous_scored_cycle(conn, row, cycle_customer_org_sql())
    if prev is None:
        return None
    prev = {**prev, 'customer_org_id': row['customer_org_id']}
    prev_rows = _rows(conn, prev)
    prev_vis = _visibility(conn, prev, facts)
    now_m = {**parity.surface_metrics(rows, vis.get('byQuestion') or [], surfaces.ALL), **rm.study_identity(conn, row),
             'scorer_version': score_svc.outcomes_version(rows)}
    prev_m = {**parity.surface_metrics(prev_rows, prev_vis.get('byQuestion') or [], surfaces.ALL, tier=now_m['tier']),
              **rm.study_identity(conn, prev), 'scorer_version': score_svc.outcomes_version(prev_rows)}
    # 2T-7 (2): copy names the cycle by its day (rm.cycle_label), `code` stays its identifier
    label = rm.cycle_label_of(conn, prev)
    status, note, condition = parity.changes_check(now_m, prev_m, label['name'], surfaces.ALL)
    return {'code': prev['cycle_code'], 'label': label, 'name': label['name'], 'row': prev, 'rows': prev_rows,
            'visibility': prev_vis, 'status': status, 'note': note, 'condition': condition}


def _previous_block(compared: Optional[dict]) -> Optional[dict]:
    """What a read model serves of _compared: {cycle, status, note}, 2T-7 (2): and the cycle's label for copy
    {day, name, since, vs} ("Oct 23", "the Oct 23 cycle", "Since Oct 23", "vs Oct 23")."""
    if compared is None:
        return None
    label = compared.get('label') or {}
    return {'cycle': compared['code'], 'status': compared['status'], 'note': compared['note'],
            'day': label.get('day'), 'name': label.get('name') or compared['code'],
            'since': label.get('since'), 'vs': label.get('vs')}


async def _promo_inputs(scope: CustomerScope, row: dict, slug: Optional[str]) -> tuple:
    """2M-2: (promo_pass_through, deals, as_of, error) for a cycle: the cycle's
    cheapest-place and where-to-buy answers against supply's /deals on the
    cycle's read date (rm.promo_as_of). (None, None, as_of, None) when the
    cycle asked no cheapest-place question, names no merchant, or supply's
    /tenant says the merchant is not a brand (a retailer's deals are its
    own); a failed supply read is (None, None, as_of, error), never zero
    deals."""
    as_of = rm.promo_as_of(row)
    with engine.connect() as conn:
        asks = rm.asks_cheapest_place(conn, row)
        slug = slug or (score_svc.cycle_merchant(conn, row) if asks else None)
        answers = console_cache.cycle_read(conn, row, 'promo_answers', lambda: rm.promo_answers(conn, row)) \
            if asks else []
    if not asks or not slug:
        return None, None, as_of, None
    kind = await _tenant_kind(scope, slug)
    if kind and kind != 'brand':
        return None, None, as_of, None
    _, deals, error = await _reads(scope).get_deals(slug, as_of)
    if error is not None:
        return None, None, as_of, error
    return rm.build_promo_pass_through(answers, deals, as_of), deals, as_of, None


async def _routing_inputs(scope: CustomerScope, row: dict, merchant: Optional[str]) -> tuple:
    """2L-4: (rm.routing_merchant's facts, read errors) for a cycle whose
    study asks where to buy; (None, {}) for one that does not, with no
    supply call. A merchant supply's /tenant says is not a brand gets no
    reads either. A failed read is named, never raised."""
    with engine.connect() as conn:
        if not rm.asks_intents(conn, row):
            return None, {}
        slug = merchant or score_svc.cycle_merchant(conn, row)
    if not slug:
        return None, {'merchant': 'no merchant record for this cycle'}
    kind = await _tenant_kind(scope, slug)
    if kind and kind != 'brand':
        return {'kind': kind}, {}
    client = _reads(scope)
    (_, retailers, r_err), (_, reference, f_err) = await asyncio.gather(client.get_retailers(slug),
                                                                      client.get_reference(slug))
    with engine.connect() as conn:
        facts = rm.routing_merchant(conn, row, kind=kind, retailers=retailers, retailers_error=r_err,
                                    reference=reference if f_err is None else None)
    return facts, {k: v for k, v in (('retailers', r_err), ('reference', f_err)) if v}


async def _attribute_inputs(scope: CustomerScope, row: dict, slug: str) -> tuple:
    """2T-1: (the cycle's judged attribute answers, supply's /reference, its
    read error) as the Overview reads them: cached per cycle and reference.
    ([], None, None) for a cycle that asked no attribute question."""
    with engine.connect() as conn:
        asks = rm.asks_attribute(conn, row)
    if not asks:
        return [], None, None
    _, reference, r_err = await _reads(scope).get_reference(slug)
    reference = reference if r_err is None else None
    with engine.connect() as conn:
        answers = console_cache.cycle_read(conn, row, 'attribute_answers', lambda: rm.attribute_answers(
            conn, row, reference), console_cache.digest(reference))
    return answers, reference, r_err


async def _tenant_kind(scope: CustomerScope, slug: str) -> Optional[str]:
    """2L-4: the merchant's kind ('brand' | 'seller') from supply's /tenant;
    None when it cannot be read or does not list the merchant. 2Q-1 (B3): kept
    a few minutes per org (an overview asked it four times)."""
    from app.console_merchants import org_merchants

    async def read():
        merchants, _error = await org_merchants(scope.org)
        return next((m.get('kind') for m in merchants if m.get('slug') == slug), None)
    return await console_cache.cached(('kind', scope.org.id, slug), read)


@router.get("/overview")
async def get_overview(cycle: str = Query(...), merchant: Optional[str] = Query(None),
                       scope: CustomerScope = Depends(console_scope)):
    """2C-2: This week for one cycle, every agent together (`all`, 2I-8) and
    per surface: the agent table, the
    products, up to four signals, the week in short, the changes against the
    previous scored cycle (none on a first cycle) and Visibility's ranking,
    reused. Every sentence is a template filled from counts (console_parity.
    TEMPLATES). With `merchant`, the last access run feeds the access signal;
    a failed read leaves it out and is named in `read_errors`."""
    started = time.monotonic()
    ms = None
    if merchant:
        ms = await check_merchant(scope, merchant)   # 2H: a slug that is not the org's is a 404
    row = dict(cycle_in_scope(cycle, scope))
    with engine.connect() as conn:
        prev, n_scored = parity.previous_scored_cycle(conn, row, cycle_customer_org_sql())
        asks_promo = rm.asks_cheapest_place(conn, row)
    if prev is not None:
        prev = {**prev, 'customer_org_id': row['customer_org_id']}

    async def merchant_reads():
        if not merchant:
            return None
        client = _reads(scope)
        return await asyncio.gather(client.get_access(merchant), client.get_reference(merchant))

    async def no_promo():
        return None, None, None, None

    # 2Q-1 (B3): supply's reads in one round, not six: the catalog's features (2K-3), the
    # routing facts (2L-4), the access run and the reference, and both cycles' deals (2M-2)
    (features, f_err), (facts, routing_errors), supply_pair, promo_now, promo_prev = await asyncio.gather(
        _claim_features(row, scope, merchant), _routing_inputs(scope, row, merchant), merchant_reads(),
        _promo_inputs(scope, row, merchant),
        _promo_inputs(scope, prev, merchant) if prev is not None and asks_promo else no_promo())
    with engine.connect() as conn:
        rows = _rows(conn, row, features)
        vis = _visibility(conn, row, facts, routing_errors)
        own_domain, variants, scored = _true_value_inputs(conn, row)
        previous = None
        if prev is not None:
            # 2N-1: with the merchant's facts, so its routing (Retailer coverage) compares
            prev_rows = _rows(conn, prev, features)
            # 2P-1 (B2): with the version its outcomes compare under, as the score's previous is
            label = rm.cycle_label_of(conn, prev)
            previous = {'code': prev['cycle_code'], 'name': label['name'], 'label': label, 'rows': prev_rows,
                        'visibility': _visibility(conn, prev, facts),
                        'study': {**rm.study_identity(conn, prev), 'scorer_version': score_svc.outcomes_version(prev_rows)}}
        # 2K-4 (B1): the study and its questions, compared first; 2P-1: and the outcomes' version
        study = {**rm.study_identity(conn, row), 'scorer_version': score_svc.outcomes_version(rows)}
        job = conn.execute(text("SELECT tier_config FROM soa_query_generation_jobs WHERE study_type = :st"),
                           {"st": row['study_type']}).fetchone()
        study_questions = conn.execute(text("SELECT COUNT(*) FROM soa_queries WHERE study_type = :st"),
                                       {"st": row['study_type']}).scalar()
    brand = next((r['name'] for r in (vis.get('ranking') or {}).get('rows') or [] if r.get('you')), None) or \
        (((_json(job[0]) if job else None) or {}).get('merchant') or {}).get('study_brand') or 'the brand'
    access, errors, reads = None, {}, None
    if f_err is not None:
        errors['catalog'] = f_err
    if merchant:
        (_, payload, error), (_, reference, r_err) = supply_pair
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
    body = parity.build_overview(row, rows=rows, visibility=vis, true_value=tv, brand=brand, access=access,
                                 previous=previous, scored_cycles=n_scored if n_scored else 1, read_errors=errors,
                                 study_questions=study_questions, study=study)
    # 2K-3 (B5): the start day in the merchant's zone, beside `started` (the UTC start_date)
    body.update(rm.cycle_dates(row, rm.study_timezone(job[0] if job else None)))
    # 2K-4 (B2): the cycle's study, with its own date in the merchant's zone ("The Oct 20 study")
    with engine.connect() as conn:
        body['study'] = rm.load_study_block(conn, row.get('study_type'))
    # 2L-2: Visibility's retired-line counts, the fifth brand tile's input
    # (2L-4 wires the tile); absent for a brand with no retired line
    if vis.get('retired_named'):
        body['retired_named'] = vis['retired_named']
    # 2L-4: Visibility's routing, whose coverage is the second brand tile's input
    if vis.get('routing'):
        body['routing'] = vis['routing']
    # 2M-1: the Attribute accuracy tile's input (the first brand tile); supply's
    # /reference for its pages half, read here when the call above did not
    with engine.connect() as conn:
        asks = rm.asks_attribute(conn, row)
        slug = merchant or (score_svc.cycle_merchant(conn, row) if asks else None)
    attr_reference = reference if merchant and 'reference' not in errors else None
    if asks and attr_reference is None and slug and not merchant:
        (_, attr_reference, a_err) = await _reads(scope).get_reference(slug)
        if a_err is not None:
            attr_reference = None
            body.setdefault('read_errors', {})['reference'] = a_err
    with engine.connect() as conn:
        answers = console_cache.cycle_read(conn, row, 'attribute_answers', lambda: rm.attribute_answers(
            conn, row, attr_reference), console_cache.digest(attr_reference)) if asks else []
        accuracy = rm.build_attribute_accuracy(answers, attr_reference) if asks or attr_reference else None
        prev_answers = console_cache.cycle_read(conn, prev, 'attribute_answers', lambda: rm.attribute_answers(conn, prev)) \
            if asks and prev is not None else None
    if accuracy is not None:   # absent, as routing and retired_named are, when there is nothing to count
        body['attribute_accuracy'] = accuracy
    # 2M-1: "Size 4 weight range right" in Changes, per size an accuracy answer missed
    site = next((a['site'] for a in answers if a.get('site')), None) or own_domain or 'the brand site'
    # 2P-1 (B2): against another study the lines read "new" (this study's first cycle
    # that asked it); a previous cycle of the same study that is not comparable for
    # another reason (its version, its agents) gets none, as the core lines get none
    lined = {s: b for s, b in (body.get('by_surface') or {}).items()
             if b.get('changes_status') != 'not_comparable' or b.get('changes_condition') == 'study'}
    for s, block in lined.items():
        if answers:
            block['changes'] = list(block.get('changes') or []) + rm.attribute_changes(
                answers, prev_answers, (previous or {}).get('name'), s,
                compared=block.get('changes_status') == 'compared', site=site)
    # 2N-1: a brand's first-cycle Changes, after the weight range and before the deals:
    # Retired product named, First pick (category questions), Retailer coverage
    if (vis.get('ranking') or {}).get('default_tier') == rm.VIS_BRAND_CHOICE:
        for s, block in lined.items():
            block['changes'] = list(block.get('changes') or []) + rm.brand_changes(
                vis, (previous or {}).get('visibility'), (previous or {}).get('name'), s,
                compared=block.get('changes_status') == 'compared', brand=brand)
    # 2M-2: the Promo pass-through tile's input (the fifth brand tile) and its
    # Changes line, "Deals named, cheapest-place answers"; absent when the
    # cycle asked no cheapest-place question
    promo, _deals, _as_of, p_err = promo_now
    if p_err is not None:
        body.setdefault('read_errors', {})['deals'] = p_err
    if promo is not None:
        body['promo_pass_through'] = {k: v for k, v in promo.items() if k != 'judged'}
        prev_promo = promo_prev[0] if prev is not None else None
        for s, block in lined.items():
            block['changes'] = list(block.get('changes') or []) + rm.promo_changes(
                promo, prev_promo, (previous or {}).get('name'), s,
                compared=block.get('changes_status') == 'compared')
    # 2L-3: the products' and the signals' example answers' narratives
    with engine.connect() as conn:
        narratives_svc.with_overview(body, narratives_svc.lines_for(conn, row['id']))
    # 2T-1: a brand at retail (supply's mode manufacturer): the demo's lead, TrueSync card, charter,
    # strip, revenue, week in short, ranked signals, agents' facts, products' deals, first picks, activity
    if ms is not None and (next((m for m in ms.merchants or [] if m.get('slug') == merchant), None) or {}).get(
            'mode') == 'manufacturer':
        from app.routers.console_manufacturer import brand_overview
        await brand_overview(scope, ms, merchant, row, body, prev=prev, rows=rows, vis=vis, true_value=tv,
                             attribute_answers=answers, accuracy=accuracy, promo=promo, deals=_deals,
                             reference=attr_reference, brand=brand)
    # 2Q-1 (B3): how long the read took, and what the cache served
    score_svc.log_event('overview.read', cycle=row['cycle_code'], previous=prev['cycle_code'] if prev else None,
                        ms=int((time.monotonic() - started) * 1000), cache=console_cache.describe())
    return body


@router.get("/score")
async def get_score(cycle: str = Query(...), merchant: Optional[str] = Query(None), rescore: bool = Query(False),
                    scope: CustomerScope = Depends(console_scope), user: dict = Depends(verify_token)):
    """2C-3: the Share of Algorithm. The Audit's formula over loop data
    (console_score.py), each surface scored on its own and pooled as the
    equal-weight mean of the surface scores. Stored on the cycle row with
    its scorer_version and served from there; recomputed when the version
    differs, or on an operator's `rescore`. `previous` is the newest earlier
    scored cycle's stored score, compared only under the same scorer version,
    surfaces and agents. With no `merchant`, the cycle's own (its questions'
    source_ref) is read for the access run and the reference read.

    2C-3a: never a 500 for a cycle in scope. A failure while scoring is
    logged (score.failed: the cycle, the step, the exception, no row data)
    and returned as a 422 whose detail is one line the tile shows."""
    if merchant:
        await check_merchant(scope, merchant)   # 2H: a slug that is not the org's is a 404
    if rescore and not customers.is_operator(user.get("sub")):
        raise HTTPException(status_code=403, detail="operator only: re-scoring a cycle is for Parleo staff")
    row = dict(cycle_in_scope(cycle, scope))
    org = scope.org.id
    try:
        return await _score(row, org, merchant, rescore, scope)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - every failure is a readable 422, never a 500
        score_svc.log_event('score.failed', cycle=row['cycle_code'], cycle_id=row['id'], org=org,
                            step=score_svc.current_step(), error=type(exc).__name__, message=str(exc)[:200])
        raise HTTPException(status_code=422, detail=score_svc.unavailable(exc))


async def _score(row: dict, org: int, merchant: Optional[str], rescore: bool, scope: CustomerScope) -> dict:
    body = await _score_body(row, org, merchant, rescore, scope)
    score_svc.at('reading the previous cycle')
    with engine.connect() as conn:
        prev, _ = parity.previous_scored_cycle(conn, row, cycle_customer_org_sql())
        # 2K-4 (B1): each cycle's study and questions, compared first (soa_shared/cycle_compare)
        studies = (rm.study_identity(conn, row), rm.study_identity(conn, prev)) if prev else None
        label = rm.cycle_label_of(conn, prev)
    return score_svc.with_previous(body, prev['cycle_code'] if prev else None,
                                   await _previous_score(prev, row, org, merchant, scope), studies=studies, label=label)


async def _previous_score(prev: Optional[dict], row: dict, org: int, merchant: Optional[str],
                          scope: CustomerScope) -> Optional[dict]:
    """2Q-1 (B2): the previous cycle's score as its own read serves it: the
    stored one, recomputed (and stored) when a refresh or a rescore made it
    stale (score_svc.needs_recompute, 2N-2), never a stored score that
    predates them. FL15's Attribute accuracy tile read +5 against FL14's score
    stored before its reference refresh (48 of 68) while Impact read -1
    against FL14 recomputed (54 of 77). Every delta's prior is now the
    previous cycle's current read: the tiles here, and the Changes block,
    Visibility, True Value, Trade promotions and Impact, which read it live.
    A prior stored under another scorer version, or never stored, is served
    as it is: compare() says "re-score to compare" or "open it to score it",
    never a delta. A prior that cannot be recomputed is no prior (None),
    never the stale one."""
    if prev is None:
        return None
    stored = score_svc.stored_score(engine, prev['id'])
    if not score_svc.is_current(stored):
        return stored
    try:
        return await _score_body({**prev, 'customer_org_id': row['customer_org_id']}, org, merchant, False, scope)
    except Exception as exc:  # noqa: BLE001 - the cycle's own score still reads; its delta says why not
        score_svc.log_event('score.previous_failed', cycle=row['cycle_code'], previous=prev.get('cycle_code'),
                            error=type(exc).__name__, message=str(exc)[:200])
        return None


async def _score_body(row: dict, org: int, merchant: Optional[str], rescore: bool, scope: CustomerScope) -> dict:
    """One cycle's score, served from its row or recomputed (and stored), with no previous."""
    score_svc.at('reading the stored score')
    stored = score_svc.stored_score(engine, row['id'])
    body = dict(stored or {}, stored=True)
    # 2E: the cycle's domain checks (soa_cycles.domain_checks), on the row
    # cycle_in_scope already read; absent before migration b4e8f1c3a9d2
    domain_checks = _json(row.get('domain_checks'))
    domain_checks = domain_checks if isinstance(domain_checks, dict) else None
    # 2J-4: the cycle's cached retailer-prices, for its refresh stamp
    cached_reference = _json(row.get('reference_prices'))
    # 2N-2: and when the cycle's outcomes were last written, for a re-score with no refresh
    with engine.connect() as conn:
        outcomes_at = score_svc.outcomes_scored_at(conn, row['id']) if stored else None
    why = ('rescore' if rescore else score_svc.needs_recompute(stored, domain_checks, cached_reference, outcomes_at)
           or ('merchant' if merchant and (body.get('inputs') or {}).get('merchant') != merchant else None))
    if why:
        started = time.monotonic()
        score_svc.log_event('score.start', cycle=row['cycle_code'], cycle_id=row['id'], org=org, reason=why)
        with engine.connect() as conn:
            runs = score_svc.load_score_runs(conn, row)
            mentions = score_svc.load_score_mentions(conn, row)
            rivals = score_svc.load_tracked_rivals(conn, row)
            terms = rm.load_brand_terms(conn, row)
            slug = merchant or score_svc.cycle_merchant(conn, row)
            stored_kind = (rm.study_merchant_block(conn, row) or {}).get('kind')
        # 2L-4: the merchant's kind picks the five rows; a brand's tiles read
        # Visibility's routing (supply's retailer list) and retired lines
        score_svc.at('reading the merchant kind')
        kind = (await _tenant_kind(scope, slug) if slug else None) or stored_kind
        facts, routing_errors = await _routing_inputs(scope, row, slug) if kind == 'brand' else (None, {})
        with engine.connect() as conn:
            score_svc.at('loading visibility')
            vis = rm.load_visibility(conn, row, facts)
        vis_rows = vis.get('byQuestion') or []
        ours = next((r['name'] for r in (vis.get('ranking') or {}).get('rows') or [] if r.get('you')), None)
        brand_inputs = {'routing': vis.get('routing'), 'retired_named': vis.get('retired_named'),
                        'brand': ours or (facts or {}).get('brand')}
        access, reference_rows, errors = None, None, dict(routing_errors)
        reference_run, access_run = None, None
        if slug:
            score_svc.at('reading supply')
            client = full_loop._client(scope)
            (_, payload, a_err), (_, reference, r_err) = await asyncio.gather(client.get_access(slug),
                                                                              client.get_reference(slug))
            if a_err is None:
                access = rm.accessibility_from_supply(payload)
                access_run = access.get('access_run')
            else:
                errors['access'] = a_err
            if r_err is None:
                reference_rows = (reference or {}).get('rows')
                reference_run = (reference or {}).get('reference_run')
            else:
                errors['reference'] = r_err
            # 2M-1: the Attribute accuracy tile, supply's pages and the cycle's accuracy answers
            with engine.connect() as conn:
                brand_inputs['attribute_accuracy'] = rm.load_attribute_accuracy(
                    conn, row, reference if r_err is None else None)
            # 2M-2: the Promo pass-through tile, the cycle's cheapest-place answers against supply's deals
            if kind == 'brand':
                promo, _deals, _as_of, p_err = await _promo_inputs(scope, row, slug)
                brand_inputs['promo_pass_through'] = promo
                if p_err is not None:
                    errors['deals'] = p_err
        else:
            errors['merchant'] = 'no merchant record for this cycle'
        body = score_svc.build_score(row['cycle_code'], runs=runs, mentions=mentions, vis_rows=vis_rows, access=access,
                                     reference_rows=reference_rows, read_errors=errors,
                                     inputs={'merchant': slug, 'reference_run': reference_run, 'access_run': access_run,
                                             'scored_at': datetime.now(timezone.utc).isoformat(),
                                             **score_svc.reference_input(cached_reference)},
                                     domain_checks=domain_checks, rivals=rivals, terms=terms,
                                     kind=kind, brand_inputs=brand_inputs)
        # the value it replaces stays in its history (2E)
        body = score_svc.carry_history(body, stored, why)
        # a failed supply read is served, never stored: the next read tries again
        score_svc.at('storing the score')
        body['stored'] = not errors and score_svc.store_score(engine, row['id'], body)
        score_svc.log_event('score.end', cycle=row['cycle_code'], cycle_id=row['id'], org=org,
                            surfaces=[s['surface'] for s in body['surfaces']], score=body['score'],
                            stored=body['stored'], read_errors=sorted(errors), ms=int((time.monotonic() - started) * 1000))
    return body


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
        SELECT o.run_id, o.query_id, o.outcome, o.reason_code, o.outcome_reason, o.claim_results, o.expected_answer,
               r.platform, r.surface
        FROM soa_expectation_outcomes o JOIN soa_runs r ON r.id = o.run_id
        WHERE o.cycle_id = :c AND o.tier = 'catalog_accuracy'
    """), {"c": row['id']}).mappings().all()
    unpriced = rm.brand_sets_no_price_runs(conn, row)   # 2K-1
    outcomes = [rm.not_priced(dict(o), unpriced) for o in outcomes]

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
                       'outcome': rm.read_outcome(o['outcome'], o['reason_code']), 'reason_code': o['reason_code'],
                       'stated': deciding.get('stated') if deciding else None,
                       # 2C-2c: the sibling resolved to its record name, once
                       'swap_product': rm.sibling_name(swap, names) if swap else None,
                       'swap_variant': swap.get('variant_id') if swap else None,
                       # 2Q-1 (B4): the pack the quote was for, when the check moved it off the asked one for its count
                       'pack': rm.pack_conflict(deciding),
                       # 2R-2 (B5): the variant it named, when the check found it is not one of the record's
                       'clash': rm.clash_named(deciding, o['reason_code']),
                       # 2T-4 (3): the read the run was judged against, so the cell shows that one
                       'judged': rm.judged_read(deciding, o['outcome'], o.get('outcome_reason')),
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
        lines = narratives_svc.lines_for(conn, row['id'])   # 2L-3: each row's caption
        # 2P-1 (B3): the previous cycle's grid, for the cells that changed verdict
        rows = parity.load_overview_rows(conn, dict(row))
        compared = _compared(conn, dict(row), rows, rm.load_visibility(conn, dict(row)))
        prev_tv = None
        if compared and compared['status'] == 'compared':
            p_own, p_variants, p_scored = _true_value_inputs(conn, compared['row'])
            prev_tv = rm.build_true_value(_json(compared['row'].get('reference_prices')), p_scored,
                                          own_domain=p_own, record_variants=p_variants)

    def with_drift(body):
        body['previous'] = _previous_block(compared)
        if prev_tv is not None:
            body['drift'] = rm.true_value_drift(body, prev_tv, compared['name'])
        return body

    if not merchant:
        return with_drift(narratives_svc.with_true_value(rm.build_true_value(
            _json(row.get('reference_prices')), scored, own_domain=own_domain, record_variants=variants), lines))
    client = full_loop._client(scope)
    (_, owned, o_err), (_, incentives, i_err), (_, catalog, k_err), (_, reference, r_err), (history, h_err), \
        (f_status, feed, f_err) = \
        await asyncio.gather(client.get_owned_incentives(merchant), client.get_merchant_incentives(merchant),
                             client.get_merchant_catalog(merchant), client.get_reference(merchant),
                             _member_reads(client, merchant), client.get_feed(merchant))
    errors = {n: e for n, e in (('owned_incentives', o_err), ('incentives', i_err), ('catalog', k_err),
                                ('reference', r_err), ('retailer_prices', h_err)) if e is not None}
    if f_err is not None and not (f_status and 400 <= f_status < 500):
        errors['feed'] = f_err   # 2K-3: a merchant with no feed (hosted, or none committed) is not an error
    # 2C-2a: the newest page read is the reference when the cycle cached none
    body = rm.build_true_value(_json(row.get('reference_prices')), scored, own_domain=own_domain,
                               record_variants=variants, reads=(reference or {}).get('rows') if r_err is None else None,
                               feed_rows=rm.feed_sku_rows(feed if f_err is None else None,
                                                          catalog if k_err is None else None),
                               brands=rm.catalog_brands(catalog if k_err is None else None))
    programs = rm.build_programs((owned or {}).get('incentives') or [] if o_err is None else [], value_outcomes,
                                 record=incentives if i_err is None else None)
    body['programs'] = programs
    body['ladder'], body['receipt'] = parity.build_ladder(
        catalog if k_err is None else None, incentives if i_err is None else None,
        (owned or {}).get('incentives') if o_err is None else None, scored, own_domain=own_domain,
        reads=(reference or {}).get('rows') if r_err is None else None, member_reads=history)
    body['member_reads'] = 'history' if history is not None else 'reference'
    # 2G: the caption under each product: its program price by the ladder's
    # rule, and the agents that quoted it on each surface
    body['program_lines'] = parity.program_lines(
        catalog if k_err is None else None, incentives if i_err is None else None, value_outcomes,
        reads=history if history is not None else ((reference or {}).get('rows') if r_err is None else None))
    body['read_errors'] = errors
    # 2T-5 (TV1 to TV9): a brand at retail's True Value in the demo's shape
    ms = await check_merchant(scope, merchant)
    record_row = next((m for m in getattr(ms, 'merchants', None) or [] if m.get('slug') == merchant), None) or {}
    if record_row.get('mode') == 'manufacturer':
        await _true_value_brand(scope, dict(row), merchant, body, record_row,
                                reference=reference if r_err is None else None,
                                feed_rows=(feed or {}).get('rows') if f_err is None else None)
    return with_drift(narratives_svc.with_true_value(body, lines))


async def _true_value_brand(scope: CustomerScope, row: dict, merchant: str, body: dict, record_row: dict, *,
                            reference: Optional[dict], feed_rows: Optional[list]) -> None:
    """2T-5: the deals live that day and the cheapest-place answers judged against them (_promo_inputs), the
    weight answers (_attribute_inputs) and the brand's own domains (/retailers) beside the reads /true-value
    made, then console_measure.true_value_brand. A failed read is named in read_errors, never raised."""
    (promo, deals, _as_of, p_err), (answers, _ref, a_err), (_, retailers, o_err) = await asyncio.gather(
        _promo_inputs(scope, row, merchant), _attribute_inputs(scope, row, merchant),
        _reads(scope).get_retailers(merchant))
    own = (retailers or {}).get('own_domains') or [(retailers or {}).get('own_domain')] if o_err is None else []
    own = [str(d).lower().removeprefix('www.') for d in own or record_row.get('own_domains') or [] if d]
    with engine.connect() as conn:
        brand = record_row.get('brand') or rm.load_primary(conn, row)
    measure.true_value_brand(body, reads=(reference or {}).get('rows'), deals=deals, promo=promo,
                             attribute_answers=answers or [], feed_rows=feed_rows, own_domains=own, brand=brand)
    body['read_errors'].update({k: e for k, e in (('deals', p_err), ('attribute_reference', a_err),
                                                  ('retailers', o_err)) if e})


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
    ms = await check_merchant(scope, merchant)   # 2H: a slug that is not the org's is a 404
    client = full_loop._client(scope)
    (status, payload, error), (_, reference, r_err), (_, retailers, o_err) = await asyncio.gather(
        client.get_access(merchant), client.get_reference(merchant), client.get_retailers(merchant))
    if error is not None:
        raise HTTPException(status_code=404 if status == 404 else 502,
                            detail=f"TrueSync access payload unavailable: {error}")
    # 2C-2: the merchant-level checks from the latest reference read; a
    # failed read leaves them 'not_checked' and is named in read_errors.
    # 2E: robots from supply #21's roll-up on the merchant's own domain, the
    # signed probe and the protocol profile from the newest cycle's domain checks
    cycle_code, record = _latest_domain_checks(merchant, scope)
    own = [d for d in (record or {}).get('own_domains') or []]
    if not own and o_err is None:
        listed = (retailers or {}).get('own_domains') or [(retailers or {}).get('own_domain')]
        own = [str(d).lower().removeprefix('www.') for d in listed if d]
    record_row = next((m for m in getattr(ms, 'merchants', None) or [] if m.get('slug') == merchant), None) or {}
    if record_row.get('mode') == 'manufacturer':
        return await _brand_accessibility(client, merchant, payload, reference if r_err is None else None, r_err,
                                          retailers if o_err is None else None, own, record, cycle_code, record_row)
    return parity.extend_accessibility(rm.accessibility_from_supply(payload), reference if r_err is None else None,
                                       reference_error=r_err, robots=supply_fields.robots_by_domain(payload),
                                       own_domains=own, domain_checks=record, domain_cycle=cycle_code)


async def _brand_accessibility(client, merchant: str, payload: dict, reference: Optional[dict], r_err,
                               retailers: Optional[dict], own: list, record: Optional[dict], cycle_code,
                               merchant_row: dict) -> dict:
    """2T-4 (4): a brand at retail. `checks` are the demo's six over the brand's own pages
    (console_accessibility_brand), `retailer_checks` the merchant-level checks over the retailer
    pages only, `hero` the lead from the data. The feed and the retailer-prices rows are read beside
    the three reads above; a failed one is named in read_errors and its checks say not checked."""
    from app.services import console_accessibility_brand as acc
    from app.services.console_manufacturer import _brand_word as manu_brand
    (_ps, prices, p_err), (_fs, feed, f_err) = await asyncio.gather(
        client.get_retailer_prices(merchant), client.get_feed(merchant))
    own = own or [str(d).lower().removeprefix('www.') for d in merchant_row.get('own_domains') or [] if d]
    robots = supply_fields.robots_by_domain(payload)
    body = parity.extend_accessibility(rm.accessibility_from_supply(payload), acc.retailer_rows(reference, own),
                                       reference_error=r_err, robots=robots, own_domains=own, domain_checks=record,
                                       domain_cycle=cycle_code)
    brand = merchant_row.get('brand') or manu_brand((feed or {}).get('rows') if f_err is None else None)
    built = acc.build(prices=(prices or {}).get('prices') if p_err is None else None,
                      feed_rows=(feed or {}).get('rows') if f_err is None else None, reference=reference,
                      access=payload, robots=robots, own_domains=own,
                      retailers=(retailers or {}).get('domains') or [], brand=brand)
    body['retailer_checks'] = body['checks']
    body['checks'] = built['checks']
    body['brand_pages'] = built['brand_pages']
    body['hero'] = built['hero']
    body['mode'] = 'manufacturer'
    errors = dict(body.get('read_errors') or {})
    errors.update({k: e for k, e in (('retailer_prices', p_err), ('feed', f_err)) if e})
    body['read_errors'] = errors
    # 2T-5 (AC2, AC6): the identities supply ran against the demo's, and no rivals table yet
    return measure.accessibility_brand(body)


def _latest_domain_checks(merchant: str, scope: CustomerScope) -> tuple:
    """(cycle_code, record) of the scope's newest cycle whose domain checks
    are this merchant's, or (None, None): none yet, or the column is not
    there (migration b4e8f1c3a9d2)."""
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT c.cycle_code, c.domain_checks FROM soa_cycles c
                WHERE c.domain_checks IS NOT NULL AND {cycle_customer_org_sql()} = :org
                ORDER BY c.start_date DESC, c.id DESC
            """), {"org": scope.org.id}).all()
    except Exception:  # noqa: BLE001 - column missing before the migration is applied
        return None, None
    for code, raw in rows:
        record = _json(raw)
        if isinstance(record, dict) and record.get('merchant') == merchant:
            return code, record
    return None, None


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
    ms = await check_merchant(scope, merchant)   # 2H: a slug that is not the org's is a 404
    client = full_loop._client(scope)
    (c_status, channels, c_err), (p_status, pubs, p_err), (k_status, catalog, k_err), (_, prov, prov_err), \
        (_, reference, r_err) = \
        await asyncio.gather(client.get_channels(), client.get_publications(limit=500),
                             client.get_merchant_catalog(merchant), client.get_provenance(merchant),
                             client.get_reference(merchant))
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
    # 2M-1: the records preview's weight rows (markup against chart, retailer
    # pages against the truth); absent when there are none, named when unread
    listing_brand = next((l.get('brand') for l in (catalog or {}).get('listings') or [] if l.get('brand')), None)
    drift = rm.build_weight_drift(reference if r_err is None else None,
                                  brand=(catalog or {}).get('brand') or listing_brand)
    if drift:
        body['weight_drift'] = drift
    if r_err is not None:
        body.setdefault('read_errors', {})['reference'] = r_err
    # 2R-2 (B1): a brand at retail (supply's `mode` manufacturer): the five surfaces, what
    # changes on publish, the held file's preview and the artifacts, as /publishing serves them
    record = next((m for m in ms.merchants or [] if m.get('slug') == merchant), None)
    if (record or {}).get('mode') == 'manufacturer':
        from app.routers.console_manufacturer import brand_reads, publishing_view, release_view
        active = [c for c in channels or [] if c.get('is_active', True)]
        reads = await brand_reads(scope, merchant)
        view = await publishing_view(scope, ms, merchant, channels=active, publications=pubs or [], catalog=catalog,
                                     reference=reference if r_err is None else None, drift=drift, reads=reads)
        errors = view.pop('read_errors')
        # 2T-1 (B3): the diff stays on /publishing; TrueSync is the release page
        for key in ('diff', 'diff_all', 'gtin_line'):
            view.pop(key, None)
        body.update(view)
        release = await release_view(scope, ms, merchant, channels=active, publications=pubs or [], catalog=catalog,
                                     reference=reference if r_err is None else None, reads=reads)
        errors.update(release.pop('read_errors'))
        # the matrix is one row per held record, on the channels this pass compiled for only
        body['products'] = release.pop('records')
        body['channels'] = [c for c in body.get('channels') or [] if c.get('id') in release['pass_channels']]
        body.update(release)
        if errors:
            body.setdefault('read_errors', {}).update(errors)
    return body


async def _record_inputs(merchant: str, scope: CustomerScope, *, incentives: bool) -> dict:
    """2C-1: what the record reads from supply, with the org's tenant token.
    The catalog is required (a 404 is "no record yet"); the rest degrade:
    each failure is named in `read_errors` and its part is left out."""
    client = full_loop._client(scope)
    reads = [client.get_merchant_catalog(merchant), client.get_publications(limit=500), client.get_channels(),
             client.get_provenance(merchant), client.get_reference(merchant)]
    if incentives:
        # 2G: supply's retailer-prices too: its rows carry availability, which /reference drops
        reads += [client.get_merchant_incentives(merchant), client.get_owned_incentives(merchant),
                  client.get_retailer_prices(merchant)]
    view, *results = await asyncio.gather(_tenant_view(scope.org), *reads)
    (k_status, catalog, k_err), *rest = results
    if k_err is not None and k_status != 404:
        raise HTTPException(status_code=502, detail=f"TrueSync catalog unavailable: {k_err}")
    names = ('publications', 'channels', 'provenance', 'reference', 'incentives', 'owned_incentives', 'retailer_prices')
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
        'prices': (body.get('retailer_prices') or {}).get('prices'),
        'read_errors': errors,
    }


def _is_brand_at_retail(ms: MerchantScope, merchant: str) -> bool:
    """supply's `mode` manufacturer on the merchant's /tenant record (2R-2)."""
    return (next((m for m in ms.merchants or [] if m.get('slug') == merchant), None) or {}).get('mode') == 'manufacturer'


@router.get("/record/list")
async def get_record_list(merchant: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    """2C-1: Fix > Offer record, the product list. Every product in the
    merchant's record (supply's published catalog, or an external merchant's
    current feed), each with its status. A merchant with no record yet is an
    empty list, not an error."""
    ms = await check_merchant(scope, merchant)   # 2H: a slug that is not the org's is a 404
    if _is_brand_at_retail(ms, merchant):
        # 2T-8 (B2): one row per feed SKU with its state from the readback, and the hero
        from app.routers.console_manufacturer import brand_record_list
        return await brand_record_list(scope, ms, merchant)
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
    ms = await check_merchant(scope, merchant)   # 2H: a slug that is not the org's is a 404
    if _is_brand_at_retail(ms, merchant):
        # 2T-8 (B2): the demo's master record for one feed SKU
        from app.routers.console_manufacturer import brand_record
        return await brand_record(scope, ms, merchant, product)
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
                                prices=got.get('prices'),
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
        unpriced = rm.brand_sets_no_price_runs(conn, row)   # 2K-1
        outcomes = {o['run_id']: rm.not_priced(dict(o), unpriced) for o in conn.execute(text(
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
def get_runs(ms: MerchantScope = Depends(merchant_scope)):
    """The scope's cycles, newest first. 2H: the merchant's only (`?merchant=`,
    else the primary): a merchant with none gets an empty list, never another
    merchant's cycles."""
    with engine.connect() as conn:
        cycles = merchant_cycles(conn, ms)
        zones = rm.study_timezones(conn, [c['study_type'] for c in cycles])   # 2K-1
        out = []
        for cycle in cycles:
            counts = conn.execute(text("""
                SELECT SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END),
                       SUM(CASE WHEN answer_status = 'answered' THEN 1 ELSE 0 END)
                FROM soa_runs WHERE cycle_id = :c
            """), {"c": cycle['id']}).fetchone()
            ran = [r[0] for r in conn.execute(text("SELECT DISTINCT platform FROM soa_runs WHERE cycle_id = :c"),
                                              {"c": cycle['id']})]
            run = rm.build_run(cycle, int(counts[0] or 0), int(counts[1] or 0), zones.get(cycle['study_type']))
            # 2I: what the run dialog's comparable line compares against
            run.update(rm.run_identity(cycle, ran))
            out.append(run)
    return out


@router.get("/studio/studies")
def get_studio_studies(ms: MerchantScope = Depends(merchant_scope),
                       archived: bool = Query(False, description="2L-1: include archived studies")):
    """2H: the studies generated for the merchant (`?merchant=`, else the
    primary), each naming its merchant. 2L-1: an archived study is left out
    unless ?archived=1 (then every study, each with `archived`)."""
    scope = ms.scope
    names = {m.get('slug'): m.get('name') for m in ms.merchants}
    with engine.connect() as conn:
        studies = study_merchants(conn, scope.org.id)
        jobs = [dict(j) for j in conn.execute(text("""
            SELECT * FROM soa_query_generation_jobs
            WHERE COALESCE(customer_organization_id, organization_id) = :org ORDER BY created_at DESC
        """), {"org": scope.org.id}).mappings()]
        jobs = [j for j in jobs if ms.owns(studies.get(j['study_type'])) and (archived or j.get('archived_at') is None)]
        out = []
        for job in jobs:
            brand = ((_json(job.get('tier_config')) or {}).get('merchant') or {}).get('study_brand')
            cycles = [dict(c) for c in conn.execute(text(
                "SELECT * FROM soa_cycles WHERE study_type = :st ORDER BY start_date DESC, id DESC"),
                {"st": job['study_type']}).mappings()]
            entities = []
            if cycles:
                entities = [dict(e) for e in conn.execute(text("""
                    SELECT e.slug, e.name, e.aliases, ce.role FROM soa_cycle_entities ce
                    JOIN soa_entities e ON e.id = ce.entity_id WHERE ce.cycle_id = :c
                """), {"c": cycles[0]['id']}).mappings()]
            # 2I-7: the brand's terms, as the score reads them; the study's
            # brand when no cycle has named its primary entity yet
            primary = next((e for e in entities if e.get('role') == 'primary'), None) or {'name': brand}
            terms = rm.study_brand_terms(job.get('tier_config'), primary)
            prompts = [rm.build_prompt(dict(q), brand, terms) for q in conn.execute(text(
                "SELECT * FROM soa_queries WHERE study_type = :st ORDER BY query_code"),
                {"st": job['study_type']}).mappings()]
            study = rm.build_study(job, prompts, cycles, entities)
            # 2C-2c: branded = the tiered questions (they name the brand);
            # 2I-7: and any other question whose text names it
            study['prompt_counts'] = rm.prompt_counts(prompts, terms)
            slug = studies.get(job['study_type']) or ms.primary
            study['merchant'] = {'slug': slug, 'name': names.get(slug) or slug} if slug else None
            out.append(study)
    return out


@router.get("/prompts")
def get_prompts(ms: MerchantScope = Depends(merchant_scope)):
    """2J-2: the Prompts page for the merchant (`?merchant=`, else the
    primary): its current study's questions in sets (the tiers, in stage
    order) with counts, three examples each and the answers a cycle, the
    runs per question and the agents with their method and last-cycle
    status (console_prompts). No LLM, no new table."""
    scope = ms.scope
    with engine.connect() as conn:
        studies = study_merchants(conn, scope.org.id)
        jobs = [dict(j) for j in conn.execute(text("""
            SELECT * FROM soa_query_generation_jobs
            WHERE COALESCE(customer_organization_id, organization_id) = :org ORDER BY created_at DESC, id DESC
        """), {"org": scope.org.id}).mappings()]
        jobs = [j for j in jobs if ms.owns(studies.get(j['study_type']))]
        cycles = merchant_cycles(conn, ms)
        job = console_prompts.current_study(cycles, jobs)
        questions, cycle, ran, request = [], None, {}, None
        if job is not None:
            questions = [dict(q) for q in conn.execute(text(
                "SELECT tier, query_text, query_code, stage FROM soa_queries WHERE study_type = :st ORDER BY id"),
                {"st": job['study_type']}).mappings()]
            cycle = console_prompts.last_cycle(conn, cycles, job['study_type'])
            ran = console_prompts.agent_runs(conn, cycle)
            request = conn.execute(text("""
                SELECT id, runs_per_query FROM soa_full_loop_requests
                WHERE organization_id = :org AND study_type = :st AND (:m IS NULL OR merchant_slug = :m)
                ORDER BY created_at DESC, id DESC LIMIT 1
            """), {"org": scope.org.id, "st": job['study_type'], "m": ms.slug}).mappings().first()
    return console_prompts.build_prompts(ms.slug, job, questions, cycle, ran, worker_surfaces.console_list(engine),
                                         dict(request) if request else None)


@router.get("/studio/entities")
def get_studio_entities(scope: CustomerScope = Depends(console_scope)):
    """The entities this tenant's cycles compare: soa_entities is a global
    registry, so it is narrowed to what this org's studies actually use.

    2D: no DISTINCT. soa_entities.aliases is a Postgres json column, which
    has no equality operator: SELECT DISTINCT e.* raised UndefinedFunction
    in production, as #111's did (sqlite's TEXT hid it). One row per entity
    by subquery instead."""
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT e.* FROM soa_entities e
            WHERE e.id IN (
                SELECT ce.entity_id FROM soa_cycle_entities ce
                JOIN soa_cycles c ON c.id = ce.cycle_id
                WHERE {cycle_customer_org_sql()} = :org)
            ORDER BY e.name
        """), {"org": scope.org.id}).mappings().all()
    return [rm.build_entity(dict(r)) for r in rows]


async def _none():
    return []


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
    selectable = customers.selectable_orgs(user_id)
    views = await asyncio.gather(*(_tenant_view(org) for org in selectable))
    # 2H: each org's merchants, with their own domains, read with that org's token
    merchant_lists = await asyncio.gather(*(
        with_domains(TrueSyncClient(token=customers.token_for_org(org.id)), view.get("merchants") or [])
        if view.get("merchants") else _none() for org, view in zip(selectable, views)))
    orgs = []
    for view, merchants in zip(views, merchant_lists):
        first = (view.get("merchants") or [None])[0] or {}
        orgs.append({
            "id": view["org_id"],
            "slug": first.get("slug") or view["tenant_slug"],
            "name": view["name"],
            "kind": first.get("kind"),
            "hosting": first.get("hosting"),
            "domain": first.get("domain"),
            "tenant_slug": view["tenant_slug"],
            "merchants": merchants,
            "error": view.get("error"),
        })
    return {
        "user": {"id": user_id, "email": user.get("email")},
        "is_operator": customers.is_operator(user_id),
        "orgs": orgs,
    }


@router.get("/full-loop/latest")
async def get_console_full_loop_latest(ms: MerchantScope = Depends(merchant_scope)):
    """2C-0: the scope's most recent full loop in the shape /full-loop/{id}
    returns, or null when the org has never run one (the console's status
    strip shows "no run yet", which is not an error). Declared before
    /full-loop/{request_id} so 'latest' is never read as an id."""
    # 2H: the merchant's latest (`?merchant=`, else the primary's)
    scope = ms.scope
    with engine.connect() as conn:
        request_id = conn.execute(text("""
            SELECT id FROM soa_full_loop_requests WHERE organization_id = :org
              AND (:m IS NULL OR merchant_slug = :m)
            ORDER BY created_at DESC, id DESC LIMIT 1
        """), {"org": scope.org.id, "m": ms.slug}).scalar()
    if request_id is None:
        return None
    return await full_loop.read_full_loop(request_id, scope)


@router.get("/full-loop/{request_id}")
async def get_console_full_loop(request_id: int, scope: CustomerScope = Depends(console_scope)):
    return await full_loop.read_full_loop(request_id, scope)


# ─── 2I-9: the revenue model's inputs, per merchant ────────────────────────
#
# Sales in scope is the merchant's own financial figure. It is served here,
# on that merchant's console reads (an org member, or an operator naming the
# org), and on /revenue; never on an operator-wide list or the Command Center.

async def _revenue_merchant(scope: CustomerScope, merchant: Optional[str]) -> str:
    ms = await check_merchant(scope, merchant)   # a slug that is not the org's is a 404
    if not ms.slug:
        raise HTTPException(status_code=422, detail="no merchant: name one with ?merchant=")
    return ms.slug


@router.get("/revenue-inputs")
async def get_revenue_inputs(merchant: Optional[str] = Query(None), scope: CustomerScope = Depends(console_scope)):
    """2I-9: the merchant's revenue inputs, each with its default and source."""
    slug = await _revenue_merchant(scope, merchant)
    with engine.connect() as conn:
        return revenue_svc.inputs_view(revenue_svc.load_inputs(conn, scope.org.id, slug), slug)


@router.put("/revenue-inputs")
async def put_revenue_inputs(body: dict = Body(...), merchant: Optional[str] = Query(None),
                             scope: CustomerScope = Depends(console_scope), user: dict = Depends(verify_token)):
    """2I-9: write the fields sent (null resets one to its default). Shares are
    0 to 1, sales in scope 0 or more; anything else is a 422 and nothing is
    written."""
    slug = await _revenue_merchant(scope, merchant)
    try:
        fields = revenue_svc.validated(body)
    except revenue_svc.InputError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    with engine.begin() as conn:
        revenue_svc.save_inputs(conn, scope.org.id, slug, fields, user.get("email") or user.get("sub"))
    with engine.connect() as conn:
        return revenue_svc.inputs_view(revenue_svc.load_inputs(conn, scope.org.id, slug), slug)


@router.delete("/revenue-inputs")
async def delete_revenue_inputs(merchant: Optional[str] = Query(None), scope: CustomerScope = Depends(console_scope)):
    """2I-9: back to the defaults (sales in scope not entered)."""
    slug = await _revenue_merchant(scope, merchant)
    with engine.begin() as conn:
        revenue_svc.delete_inputs(conn, scope.org.id, slug)
    return revenue_svc.inputs_view(None, slug)



def _merchant_meta(ms: MerchantScope) -> dict:
    m = next((x for x in ms.merchants if x.get('slug') == ms.slug), {}) if ms.merchants else {}
    return {'kind': 'brand' if m.get('kind') == 'brand' else 'retailer', 'name': m.get('name') or ms.slug,
            'domain': m.get('domain')}


def _revenue_model(conn, row: dict, inputs: dict, meta: dict, access_requests, vis_rows: Optional[list] = None,
                   attribute_answers: Optional[list] = None, site: Optional[str] = None) -> dict:
    """2T-1 (B2): `attribute_answers` for a brand at retail: Missed is its size answers wrong."""
    if vis_rows is None:
        vis_rows = rm.load_visibility(conn, row).get('byQuestion') or []
    catalog = revenue_svc.load_catalog_rows(conn, row)
    shares = revenue_svc.revenue_shares(vis_rows, catalog, inputs['lost_gainable']['value'], kind=meta['kind'],
                                        attribute_answers=attribute_answers, site=site)
    return revenue_svc.build_model(shares, inputs, cycle=row['cycle_code'], cycle_name=rm.cycle_name(conn, row),
                                   kind=meta['kind'], name=meta['name'],
                                   domain=meta['domain'], access_requests=access_requests)


@router.get("/prove")
async def get_prove(cycle: str = Query(...), merchant: Optional[str] = Query(None),
                    scope: CustomerScope = Depends(console_scope)):
    """2M-2: Prove, the Trade promotions screen for one cycle: one row per deal
    live on a retailer shelf for the cycle's SKUs on its read date (supply's
    /deals), each with how many cheapest-place answers about a SKU it ran on
    named it; the aside (k of n cheapest-place answers named a live deal),
    and the note naming the retailers walled that day (rm.build_prove).
    `state` not_measured when the cycle asked no cheapest-place question or
    supply could not be read (named in read_errors), no_deals when supply
    read the shelves and found none."""
    if merchant:
        await check_merchant(scope, merchant)
    row = dict(cycle_in_scope(cycle, scope))
    promo, deals, as_of, p_err = await _promo_inputs(scope, row, merchant)
    with engine.connect() as conn:
        study = rm.load_study_block(conn, row.get('study_type')) or {}
        job = conn.execute(text("SELECT tier_config FROM soa_query_generation_jobs WHERE study_type = :st"),
                           {"st": row['study_type']}).fetchone()
    brand = (((_json(job[0]) if job else None) or {}).get('merchant') or {}).get('study_brand') or study.get('brand')
    body = rm.build_prove(promo, deals, brand, as_of)
    body.update(cycle=row['cycle_code'], read_errors={'deals': p_err} if p_err else {})
    if promo is not None:
        body['promo_pass_through'] = {k: v for k, v in promo.items() if k != 'judged'}
    # 2P-1 (B3): the deals that ended, the new ones and the pass-through's delta, against a compared cycle
    with engine.connect() as conn:
        rows = parity.load_overview_rows(conn, row)
        compared = _compared(conn, row, rows, rm.load_visibility(conn, row))
    body['previous'] = _previous_block(compared)
    if compared and compared['status'] == 'compared' and deals is not None:
        prev_promo, prev_deals, _pa, prev_err = await _promo_inputs(scope, compared['row'], merchant)
        if prev_err is None and prev_deals is not None:
            rm.prove_changes(body, deals, prev_deals, promo, prev_promo, compared['name'])
        elif prev_err is not None:
            body['read_errors']['previous_deals'] = prev_err
    return body


@router.get("/revenue")
async def get_revenue(cycle: str = Query(...), merchant: Optional[str] = Query(None),
                      scope: CustomerScope = Depends(console_scope)):
    """2I-9: the revenue model for one cycle of one merchant: its inputs, the
    measured shares over every agent and the counts behind them, in the
    RevenueModel shape the console's computeRevenue takes, with byAgent and
    the access line. The console computes the dollars; `today` and `by_2030`
    ride beside for checking. With no unprompted question, or no sales in
    scope, `dollars` is false and `dollars_reason` says why: never a $0."""
    ms = await check_merchant(scope, merchant)
    if not ms.slug:
        raise HTTPException(status_code=422, detail="no merchant: name one with ?merchant=")
    row = dict(cycle_in_scope(cycle, scope))
    errors, requests = {}, None
    _, payload, error = await full_loop._client(scope).get_access(ms.slug)
    if error is None:
        requests = [{**r, 'measured': parity._measured(r)} for r in (rm.accessibility_from_supply(payload).get('requests') or [])]
    else:
        errors['access'] = error
    # 2T-1 (B2): a brand at retail's Missed is its size answers wrong, as its Overview reads it
    answers, site = None, None
    if (next((m for m in ms.merchants or [] if m.get('slug') == ms.slug), None) or {}).get('mode') == 'manufacturer':
        answers, _reference, a_err = await _attribute_inputs(scope, row, ms.slug)
        if a_err is not None:
            errors['reference'] = a_err
        site = next((a['site'] for a in answers if a.get('site')), None)
    with engine.connect() as conn:
        inputs = revenue_svc.inputs_view(revenue_svc.load_inputs(conn, scope.org.id, ms.slug), ms.slug)
        body = _revenue_model(conn, row, inputs, _merchant_meta(ms), requests, attribute_answers=answers, site=site)
    meta = _merchant_meta(ms)
    rows, vis = await _baseline_rows(scope, row, ms, meta, errors)
    if rows:
        body['baseline'] = list(body.get('baseline') or []) + rows
    # 2P-1 (B3): the baseline is the first cycle of the run of compared cycles that ends
    # here (this cycle on a first cycle, or after one that does not compare), and what
    # moved since it
    body['baseline_cycle'], body['since_baseline'] = row['cycle_code'], None
    with engine.connect() as conn:
        base, here, chain = None, row, []
        while True:
            here_rows = parity.load_overview_rows(conn, here)
            compared = _compared(conn, here, here_rows, vis if here is row and vis else rm.load_visibility(conn, here))
            if not compared or compared['status'] != 'compared' or compared['code'] in chain:
                break
            chain.append(compared['code'])
            base = here = compared['row']
    if base is not None:
        base_rows, _vis = await _baseline_rows(scope, base, ms, meta, {})
        body['baseline_cycle'] = base['cycle_code']
        body['baseline_started'] = rm._iso(base.get('start_date'))
        with engine.connect() as conn:
            body['since_baseline'] = rm.since_baseline(rows, base_rows, rm.cycle_name(conn, base))
    # 2R-2 (B3): a brand at retail: locked until it states it sent the record, then what moved since
    from app.routers.console_manufacturer import impact_block
    locked = await impact_block(scope, ms, errors)
    if locked is not None:
        body['locked'] = locked
    body['merchant'] = ms.slug
    body['read_errors'] = errors
    return body


async def _baseline_rows(scope: CustomerScope, row: dict, ms: MerchantScope, meta: dict, errors: dict) -> tuple:
    """(Impact's baseline rows for the cycle, its visibility or None). 2M-2: promo
    pass-through, absent when not measured; 2N-1: for a brand, the demo's other
    three: Attribute accuracy, Retailer coverage, Category presence."""
    promo, _deals, _as_of, p_err = await _promo_inputs(scope, row, ms.slug)
    if p_err is not None:
        errors['deals'] = p_err
    if meta['kind'] != 'brand':
        baseline = rm.promo_baseline(promo)
        return ([baseline] if baseline is not None else []), None
    facts, routing_errors = await _routing_inputs(scope, row, ms.slug)
    errors.update(routing_errors)
    with engine.connect() as conn:
        vis = _visibility(conn, row, facts, routing_errors)
        asks = rm.asks_attribute(conn, row)
    reference = None
    if asks:
        _, reference, r_err = await _reads(scope).get_reference(ms.slug)
        if r_err is not None:
            errors['reference'], reference = r_err, None
    with engine.connect() as conn:
        attribute = rm.load_attribute_accuracy(conn, row, reference) if asks else None
    return rm.brand_baseline(attribute=attribute, vis=vis, promo=promo, brand=meta['name'],
                             day=parity._short_day(row.get('start_date'))), vis


@router.get("/revenue/history")
async def get_revenue_history(merchant: Optional[str] = Query(None), scope: CustomerScope = Depends(console_scope)):
    """2I-9: the shares and today's at stake and gainable per scored cycle of
    the merchant, oldest first, recomputed with the current inputs (nothing is
    stored). No scenario lines. 2K-4 (B1): each cycle's `vs_previous`
    ({comparable, condition, reason}) against the cycle before it, by the
    rule the score and the Changes block read (soa_shared/cycle_compare);
    null on the first."""
    ms = await check_merchant(scope, merchant)
    if not ms.slug:
        raise HTTPException(status_code=422, detail="no merchant: name one with ?merchant=")
    meta = _merchant_meta(ms)
    out = []
    with engine.connect() as conn:
        inputs = revenue_svc.inputs_view(revenue_svc.load_inputs(conn, scope.org.id, ms.slug), ms.slug)
        scored = {r[0] for r in conn.execute(text("SELECT DISTINCT cycle_id FROM soa_expectation_outcomes"))}
        cycles = [c for c in merchant_cycles(conn, ms) if c['id'] in scored and c.get('status') == 'complete']
        zones = rm.study_timezones(conn, [c['study_type'] for c in cycles])   # 2K-3
        before = None
        for c in reversed(cycles):
            c = {**c, 'customer_org_id': scope.org.id}
            vis_rows = rm.load_visibility(conn, c).get('byQuestion') or []
            m = _revenue_model(conn, c, inputs, meta, None, vis_rows)
            # every agent together, as the revenue model counts them
            here = {**parity.surface_metrics([], vis_rows, surfaces.ALL), **rm.study_identity(conn, c),
                    # 2P-1 (B2): the version its outcomes compare under, as the score's
                    'scorer_version': score_svc.outcomes_version(parity.load_overview_rows(conn, c))}
            vs = None
            if before is not None:
                ok, condition, reason = cycle_compare.cycles_comparable(
                    parity.comparison_facts('this cycle', here), parity.comparison_facts(before[2], before[1], measured=True),
                    agent_name=parity._agent)
                vs = {'cycle': before[0], 'comparable': ok, 'condition': condition, 'reason': reason}
            # 2T-7 (2): the reason names the cycle by its day (rm.cycle_label)
            before = (c['cycle_code'], here, rm.cycle_label(c, zones.get(c['study_type']))['name'])
            out.append({'cycle': c['cycle_code'], 'started': rm._iso(c.get('start_date')), 'vs_previous': vs,
                        'start_date_local': rm.cycle_dates(c, zones.get(c['study_type']))['start_date_local'],
                        'measured': m['measured'],
                        'reason': m['reason'], 'shares': m['shares'], 'counts': m['counts'],
                        'exposed': (m['today'] or {}).get('exposed'), 'gainable': (m['today'] or {}).get('gainable')})
    return {'merchant': ms.slug, 'dollars': inputs['scope']['entered'], 'currency': inputs['currency'], 'cycles': out}
