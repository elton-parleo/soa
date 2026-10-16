"""
2D: every read-model and router statement whose shape needs an equality or
ordering operator (DISTINCT, GROUP BY, UNION, IN (subquery), =), run on
production's column types.

soa's JSON columns are Postgres `json`, which has neither operator: 2C-3's
SELECT DISTINCT over soa_queries.expected_answer was a 500 on every
production cycle and passed every sqlite test. The sweep that found these
is in docs/console-read-models.md (2D, the json-column sweep). Each test
here calls the real function, on sqlite and on Postgres, over every
soa_shared model's table (soa_pg_harness.model_schema), so a statement
that lands on a json column fails here, not in production.

One hit failed the way #111 did: /api/console/studio/entities ran SELECT
DISTINCT e.* over soa_entities, whose `aliases` is json.
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

import app.console_scope as console_scope_module
import app.routers.console as console_router
import app.routers.metrics as metrics_router
import app.routers.studies as studies_router
from app.services import console_score as score_svc
from app.services import cycle_scoring, full_analysis_extras, lite_score_batch, tier_accuracy, transcript_pick
from app.services import finding_detector
from app.routers import public_lite
from soa_pg_harness import model_schema
from soa_shared import surface_accuracy
from soa_shared.models.soa_models import Base

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
USER = {'organization_id': 10, 'user_id': 'u-1', 'sub': 'u-1', 'email': 'op@parleo.io'}
CYCLE = {'id': 1, 'cycle_code': 'WS-SWEEP', 'customer_org_id': 10}


@pytest.fixture
def db(any_engine, monkeypatch):
    """Every model's table, one cycle with one answered run, its question,
    its brand (with aliases, a json column) and its coded mention."""
    model_schema(any_engine)
    t = Base.metadata.tables
    with any_engine.begin() as c:
        c.execute(t['organizations'].insert(), [{'id': 1, 'name': 'Parleo'}, {'id': 10, 'name': 'Wiggle & Snug'}])
        c.execute(t['soa_query_generation_jobs'].insert(), [{
            'id': 1, 'study_type': 'ws', 'study_name': 'W&S', 'target_count': 1, 'created_count': 1,
            'status': 'complete', 'organization_id': 1, 'customer_organization_id': 10,
            'tier_config': {'brand_direct': 1}, 'allowed_categories': ['diapers']}])
        c.execute(t['soa_entities'].insert(), [
            {'id': 1, 'name': 'Wiggle & Snug', 'slug': 'wiggle-and-snug', 'entity_type': 'brand',
             'aliases': ['W&S', 'Wiggle and Snug']},
            {'id': 2, 'name': 'Pampers', 'slug': 'pampers', 'entity_type': 'brand', 'aliases': ['P&G']}])
        c.execute(t['soa_cycles'].insert(), [{
            'id': 1, 'cycle_code': 'WS-SWEEP', 'start_date': date(2026, 10, 14), 'status': 'complete',
            'study_type': 'ws', 'study_pattern': 'retailer', 'cycle_mode': 'query', 'organization_id': 10,
            'platforms': ['chatgpt', 'gemini_grounded'], 'runs_per_query': 1, 'total_runs_planned': 1,
            'completed_runs': 1, 'reference_prices': {'rows': []}}])
        c.execute(t['soa_cycle_entities'].insert(), [
            {'cycle_id': 1, 'entity_id': 1, 'comparison_code': 'M001', 'role': 'primary'},
            {'cycle_id': 1, 'entity_id': 2, 'comparison_code': 'M002', 'role': 'competitor'}])
        c.execute(t['soa_queries'].insert(), [{
            'id': 1, 'query_code': 'WIG_001', 'query_text': 'Is Wiggle & Snug Bum Balm still sold?',
            'category': 'Cross-Category', 'stage': 'Research', 'specificity': 'Narrow',
            'persona': 'New / First-Time Parent',
            'status': 'Active', 'study_type': 'ws', 'study_pattern': 'retailer', 'organization_id': 10,
            'tier': 'brand_direct',
            'expected_answer': {'type': 'brand_mention', 'brand': 'Wiggle & Snug', 'domain': 'trueshopstore.com'},
            'source_ref': {'merchant_slug': 'wiggle-and-snug', 'variant_id': 'bum-balm-4oz'}}])
        c.execute(t['soa_runs'].insert(), [{
            'id': 1, 'cycle_id': 1, 'query_id': 1, 'platform': 'gemini_grounded', 'run_number': 1,
            'run_at': NOW, 'raw_response': 'Yes, it is.', 'status': 'success', 'surface': 'grounded_api',
            'collector': 'google_genai', 'answer_status': 'answered',
            'retrieved_sources': ['wiggleandsnug.com'], 'grounding': {'sources': [], 'supports': []}}])
        c.execute(t['soa_coded_mentions'].insert(), [
            {'run_id': 1, 'entity_id': 1, 'coded_by': 'pass1', 'mentioned': True, 'position': 1, 'deal_cited': False,
             'deal_types': ['none']},
            {'run_id': 1, 'entity_id': 2, 'coded_by': 'pass1', 'mentioned': True, 'position': 2, 'deal_cited': False,
             'deal_types': []}])
        c.execute(t['soa_expectation_outcomes'].insert(), [{
            'run_id': 1, 'query_id': 1, 'cycle_id': 1, 'platform': 'gemini_grounded', 'tier': 'brand_direct',
            'expected_answer': {'type': 'brand_mention', 'brand': 'Wiggle & Snug'},
            'extraction': {'brand_mentioned': True}, 'outcome': 'echoed', 'flags': [],
            'source_split': {'own_domain': [], 'listed_retailer': [], 'other': []},
            'surface': 'grounded_api', 'source_attribution': 'none'}])
    for module in (console_scope_module, console_router, metrics_router, studies_router):
        monkeypatch.setattr(module, 'engine', any_engine)
    return any_engine


# ═══ the hit that failed: DISTINCT e.* over soa_entities.aliases (json) ══

def test_studio_entities_lists_the_cycles_entities_once_each(db):
    """Was SELECT DISTINCT e.* ... JOIN soa_cycle_entities: on Postgres,
    UndefinedFunction (could not identify an equality operator for type
    json), from soa_entities.aliases. Now one row per entity by IN
    (subquery), as load_score_runs does since #111."""
    t = Base.metadata.tables
    with db.begin() as c:   # the same brand in a second cycle: still listed once
        c.execute(t['soa_cycles'].insert(), [{
            'id': 2, 'cycle_code': 'WS-SWEEP-2', 'start_date': date(2026, 10, 15), 'status': 'planned',
            'study_type': 'ws', 'study_pattern': 'retailer', 'cycle_mode': 'query', 'organization_id': 10}])
        c.execute(t['soa_cycle_entities'].insert(), [
            {'cycle_id': 2, 'entity_id': 1, 'comparison_code': 'M001', 'role': 'primary'}])
    scope = SimpleNamespace(org=SimpleNamespace(id=10))
    names = [e['name'] for e in console_router.get_studio_entities(scope=scope)]
    assert names == ['Pampers', 'Wiggle & Snug']


# ═══ the hits that were already safe, now proven so on Postgres ══════════

def test_score_runs_read_one_row_per_asked_question(db):
    """#111's fix: IN (subquery) over soa_queries, expected_answer json."""
    with db.connect() as conn:
        runs = score_svc.load_score_runs(conn, CYCLE)
    assert [(r['query_code'], r['expected_type']) for r in runs] == [('WIG_001', 'brand_mention')]


def test_surface_accuracy_groups_by_text_columns(db):
    with db.connect() as conn:
        assert surface_accuracy.for_cycle(conn, 1)


def test_tier_accuracy_groups_by_text_columns(db):
    with db.connect() as conn:
        assert list(tier_accuracy._outcome_rows(conn, 1))
        assert list(tier_accuracy._visibility_rows(conn, 1, 1))
        assert tier_accuracy._near_miss_counts(conn, 1) is not None


def test_run_signals_group_by_run_id(db):
    with db.connect() as conn:
        assert cycle_scoring._fetch_run_signals(conn, 1, 1)
        assert lite_score_batch._fetch_run_signals_batch(conn, [1])


def test_full_analysis_platform_signals_group_by_platform(db):
    with db.connect() as conn:
        assert full_analysis_extras._fetch_platform_signals(conn, 1, 1)


def test_transcript_pick_distinct_query_ids(db):
    with db.connect() as conn:
        index, total = transcript_pick._fetch_query_index_map(conn, 1)
    assert (index, total) == ({1: 1}, 1)


def test_lite_live_progress_counts_distinct_run_ids(db):
    with db.connect() as conn:
        assert public_lite._fetch_live_progress_counts(conn, 1).coded_runs == 1


def test_cycle_positions_group_by_code_and_position(db):
    body = metrics_router.get_cycle_positions('WS-SWEEP', current_user=USER)
    assert body is not None


def test_study_list_and_breakdown_group_by_text_columns(db):
    assert studies_router.get_studies(current_user=USER)
    assert studies_router.get_study_queries('ws', current_user=USER)


def test_finding_detector_groups_by_entity_and_platform(db):
    thresholds = {'stage': 'Research', 'presence_rate_max': 0.5, 'min_deficient_surfaces': 1,
                  'competitor_presence_min': 0.5, 'min_sample_size': 1}
    with Session(db) as session:
        assert finding_detector.detect_vis_01(1, session, thresholds) == []
