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
    GET /api/console/true-value?cycle=<code>       TrueValue
    GET /api/console/accessibility?merchant=<slug> Accessibility (from supply)
    GET /api/console/studies?cycle=<code>          StudyRow[]
    GET /api/console/accuracy?cycle=<code>         per-surface accuracy, never pooled
    GET /api/console/runs                          Run[]   (studio.ts)
    GET /api/console/studio/studies                Study[] with Prompt[] (studio.ts)
    GET /api/console/studio/entities               Entity[] (studio.ts)
    GET /api/console/full-loop/{id}                the full loop's combined status
"""
import json
from typing import Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.console_scope import console_scope, cycle_customer_org_sql, cycle_in_scope
from app.customer_context import CustomerScope
from app.routers import full_loop
from app.services import console_read_models as rm
from soa_shared import surface_accuracy, surfaces
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


@router.get("/true-value")
def get_true_value(cycle: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    row = cycle_in_scope(cycle, scope)
    with engine.connect() as conn:
        questions = conn.execute(text("""
            SELECT q.id, q.query_text, q.expected_answer, q.source_ref
            FROM soa_queries q
            WHERE q.study_type = :st AND q.tier = 'catalog_accuracy'
        """), {"st": row['study_type']}).mappings().all()
        outcomes = conn.execute(text("""
            SELECT o.query_id, o.outcome, o.claim_results, o.expected_answer
            FROM soa_expectation_outcomes o WHERE o.cycle_id = :c AND o.tier = 'catalog_accuracy'
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
                             'list_price': expected.get('amount'), 'currency': expected.get('currency')})
    if own_domain is None:
        with engine.connect() as conn:
            job = conn.execute(text("SELECT tier_config FROM soa_query_generation_jobs WHERE study_type = :st"),
                               {"st": row['study_type']}).fetchone()
        merchant = ((_json(job[0]) if job else None) or {}).get('merchant') or {}
        own_domain = merchant.get('own_domain') or merchant.get('domain')

    scored = []
    for o in outcomes:
        q = by_query.get(o['query_id'])
        if q is None:
            continue
        ref = _json(q['source_ref']) or {}
        expected = _json(o['expected_answer']) or {}
        claims = [c for c in (_json(o['claim_results']) or []) if c.get('target') == 'asked']
        # The quote is the claim that decided the run's outcome, not merely
        # its first: "$11.99 or $12.99" scored exact on the $12.99.
        deciding = next((c for c in claims if c.get('outcome') == o['outcome']), claims[0] if claims else None)
        scored.append({'variant_id': ref.get('variant_id'), 'gtin': ref.get('gtin'),
                       'retailer': expected.get('attributed_to') or own_domain,
                       'outcome': o['outcome'],
                       'stated': deciding.get('stated') if deciding else None})
    return rm.build_true_value(_json(row.get('reference_prices')), scored, own_domain=own_domain,
                               record_variants=variants)


@router.get("/accessibility")
async def get_accessibility(merchant: str = Query(...), scope: CustomerScope = Depends(console_scope)):
    status, payload, error = await full_loop._client(scope).get_access(merchant)
    if error is not None:
        raise HTTPException(status_code=404 if status == 404 else 502,
                            detail=f"TrueSync access payload unavailable: {error}")
    return rm.accessibility_from_supply(payload)


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
            out.append(rm.build_study(job, prompts, cycles, entities))
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


@router.get("/full-loop/{request_id}")
async def get_console_full_loop(request_id: int, scope: CustomerScope = Depends(console_scope)):
    return await full_loop.read_full_loop(request_id, scope)
