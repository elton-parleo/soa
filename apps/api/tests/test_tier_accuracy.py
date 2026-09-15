"""
Tier segmentation and Layer 2 aggregation — app/services/tier_accuracy.py.

Every number this service produces is a count of stored rows, so the
tests seed rows and count them. What is actually being held to is
narrower than arithmetic:

  * `absent` and `unscoreable` stay out of the accuracy denominator, and
    stay visible in the counts;
  * a rate is never produced without the sample count it rests on;
  * a rate with no sample is None, never 0.0 — "measured, and it was
    zero" and "we have no sample" are different facts;
  * a study with no syndicated brand gets no section at all.
"""
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, text

from app.services import tier_accuracy


@pytest.fixture
def conn():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_conn, _):
        dbapi_conn.create_function(
            "NOW", 0, lambda: datetime.now(timezone.utc).isoformat(),
        )

    with engine.begin() as c:
        c.exec_driver_sql("""
            CREATE TABLE soa_expectation_outcomes (
                id INTEGER PRIMARY KEY, run_id INTEGER UNIQUE, query_id INTEGER,
                cycle_id INTEGER, platform TEXT, tier TEXT,
                expected_answer TEXT, extraction TEXT, outcome TEXT,
                outcome_reason TEXT, domain_cited BOOLEAN,
                source_attribution TEXT, secondary_results TEXT,
                record_published_at TIMESTAMP, matched_published_at TIMESTAMP,
                near_miss BOOLEAN,
                extraction_model TEXT, scored_at TIMESTAMP
            )
        """)
        c.exec_driver_sql("""
            CREATE TABLE soa_queries (
                id INTEGER PRIMARY KEY, query_code TEXT, query_text TEXT, tier TEXT
            )
        """)
        c.exec_driver_sql("""
            CREATE TABLE soa_runs (
                id INTEGER PRIMARY KEY, cycle_id INTEGER, query_id INTEGER,
                platform TEXT, run_number INTEGER, raw_response TEXT
            )
        """)
        c.exec_driver_sql("""
            CREATE TABLE soa_coded_mentions (
                id INTEGER PRIMARY KEY, run_id INTEGER, entity_id INTEGER,
                mentioned BOOLEAN
            )
        """)
        c.exec_driver_sql("""
            CREATE TABLE soa_cycles (
                id INTEGER PRIMARY KEY, study_type TEXT, extraction_validation TEXT
            )
        """)
        c.exec_driver_sql("""
            CREATE TABLE soa_query_generation_jobs (
                id INTEGER PRIMARY KEY, study_type TEXT,
                syndicated_merchant TEXT, tier_config TEXT
            )
        """)
        c.exec_driver_sql(
            "INSERT INTO soa_cycles (id, study_type) VALUES (1, 'wiggle_abc')"
        )
    with engine.connect() as c:
        yield c
    engine.dispose()


_next_id = [0]


def seed_outcome(conn, *, tier='catalog_accuracy', platform='chatgpt',
                 outcome='exact', source_attribution='brand_domain',
                 query_id=1, answer='It costs $22.99.', matched_at=None,
                 secondary=None, expected=None, near_miss=None):
    _next_id[0] += 1
    run_id = _next_id[0]
    conn.execute(text("""
        INSERT INTO soa_queries (id, query_code, query_text, tier)
        VALUES (:qid, :code, 'What does it cost?', :tier)
        ON CONFLICT(id) DO NOTHING
    """), {"qid": query_id, "code": f"WS_{query_id:03d}", "tier": tier})
    conn.execute(text("""
        INSERT INTO soa_runs (id, cycle_id, query_id, platform, run_number, raw_response)
        VALUES (:rid, 1, :qid, :platform, 1, :answer)
    """), {"rid": run_id, "qid": query_id, "platform": platform, "answer": answer})
    conn.execute(text("""
        INSERT INTO soa_expectation_outcomes (
            run_id, query_id, cycle_id, platform, tier,
            expected_answer, extraction, outcome, outcome_reason,
            source_attribution, matched_published_at, secondary_results,
            near_miss
        ) VALUES (
            :rid, :qid, 1, :platform, :tier,
            :expected, '{}', :outcome, 'because', :attribution, :matched,
            :secondary, :near_miss
        )
    """), {
        "rid": run_id, "qid": query_id, "platform": platform, "tier": tier,
        "expected": json.dumps(
            expected or {"type": "price", "amount": "22.99", "currency": "USD"}
        ),
        "outcome": outcome, "attribution": source_attribution,
        "matched": matched_at,
        "secondary": json.dumps(secondary) if secondary else None,
        "near_miss": near_miss,
    })
    conn.commit()
    return run_id


def seed_mention(conn, run_id, *, mentioned=True, entity_id=9):
    conn.execute(text("""
        INSERT INTO soa_coded_mentions (run_id, entity_id, mentioned)
        VALUES (:rid, :eid, :m)
    """), {"rid": run_id, "eid": entity_id, "m": mentioned})
    conn.commit()


def seed_study(conn, *, merchant='wiggle-and-snug', config=None):
    conn.execute(text("""
        INSERT INTO soa_query_generation_jobs
            (id, study_type, syndicated_merchant, tier_config)
        VALUES (1, 'wiggle_abc', :merchant, :config)
    """), {"merchant": merchant, "config": json.dumps(config or {})})
    conn.commit()


def build(conn, **kwargs):
    kwargs.setdefault('study_type', 'wiggle_abc')
    return tier_accuracy.build_tier_accuracy(conn, 1, **kwargs)


def tier_of(section, name):
    return next(t for t in section['tiers'] if t['tier'] == name)


# ── nothing to say ────────────────────────────────────────────────────────

def test_a_study_with_no_tiers_gets_no_section_at_all(conn):
    """Not an empty section: rendering an empty accuracy panel would
    invite a reader to conclude something about a measurement that was
    never taken."""
    assert build(conn) is None


# ── the accuracy denominator ──────────────────────────────────────────────

def test_accuracy_is_exact_over_exact_stale_and_wrong(conn):
    for outcome in ('exact', 'exact', 'stale', 'wrong'):
        seed_outcome(conn, outcome=outcome)
    entry = tier_of(build(conn), 'catalog_accuracy')

    assert entry['scored'] == 4
    assert entry['accuracy'] == 0.5
    assert entry['staleness'] == 0.25


def test_absent_and_unscoreable_stay_out_of_the_denominator(conn):
    """Neither is a claim: one is the assistant declining to address the
    quantity, the other is us failing to read the answer."""
    for outcome in ('exact', 'wrong', 'absent', 'absent', 'unscoreable'):
        seed_outcome(conn, outcome=outcome)
    entry = tier_of(build(conn), 'catalog_accuracy')

    assert entry['scored'] == 2
    assert entry['accuracy'] == 0.5
    assert entry['samples'] == 5


def test_absent_and_unscoreable_stay_visible_in_the_counts(conn):
    for outcome in ('exact', 'absent', 'unscoreable'):
        seed_outcome(conn, outcome=outcome)
    entry = tier_of(build(conn), 'catalog_accuracy')

    assert entry['counts'] == {
        'exact': 1, 'stale': 0, 'wrong': 0, 'absent': 1, 'unscoreable': 1,
    }


def test_the_unscoreable_rate_is_published_rather_than_hidden(conn):
    """A rising unscoreable share is the signal that the extractor is
    degrading, and it is only visible if it is printed."""
    for outcome in ('exact', 'exact', 'exact', 'unscoreable'):
        seed_outcome(conn, outcome=outcome)
    entry = tier_of(build(conn), 'catalog_accuracy')
    assert entry['unscoreable_rate'] == 0.25


def test_answered_rate_excludes_our_own_failures_from_its_denominator(conn):
    """'The assistant answered' is a fact about the assistant, so runs we
    could not read are not counted against it."""
    for outcome in ('exact', 'absent', 'unscoreable'):
        seed_outcome(conn, outcome=outcome)
    entry = tier_of(build(conn), 'catalog_accuracy')
    assert entry['answered_rate'] == 0.5


# ── a rate is never published without its sample ──────────────────────────

def test_every_rate_carries_the_sample_it_rests_on(conn):
    seed_outcome(conn, outcome='exact')
    entry = tier_of(build(conn), 'catalog_accuracy')
    for key in ('scored', 'samples'):
        assert key in entry


def test_a_rate_with_no_sample_is_none_not_zero(conn):
    """'Measured, and it was zero' and 'we have no sample' are different
    facts, and a report that renders them the same is lying about one."""
    seed_outcome(conn, tier='category_control', outcome='absent')
    entry = tier_of(build(conn), 'category_control')

    assert entry['scored'] == 0
    assert entry['accuracy'] is None
    assert entry['staleness'] is None


def test_a_measured_zero_is_zero(conn):
    for outcome in ('wrong', 'wrong'):
        seed_outcome(conn, outcome=outcome)
    entry = tier_of(build(conn), 'catalog_accuracy')
    assert entry['accuracy'] == 0.0


# ── per surface ───────────────────────────────────────────────────────────

def test_outcomes_split_by_surface(conn):
    seed_outcome(conn, platform='chatgpt', outcome='exact')
    seed_outcome(conn, platform='chatgpt', outcome='exact')
    seed_outcome(conn, platform='perplexity', outcome='wrong')

    entry = tier_of(build(conn), 'catalog_accuracy')
    surfaces = {s['platform']: s for s in entry['surfaces']}

    assert surfaces['chatgpt']['accuracy'] == 1.0
    assert surfaces['chatgpt']['scored'] == 2
    assert surfaces['perplexity']['accuracy'] == 0.0
    assert surfaces['perplexity']['scored'] == 1


# ── Layer 1 visibility, segmented by tier ─────────────────────────────────

def test_visibility_is_segmented_by_the_tier_of_the_question(conn):
    """Layer 1 is not re-derived — the tier is a GROUP BY, which is the
    whole point of stamping it on the question."""
    run_a = seed_outcome(conn, tier='catalog_accuracy', query_id=1)
    run_b = seed_outcome(conn, tier='catalog_accuracy', query_id=1)
    run_c = seed_outcome(conn, tier='category_control', query_id=2)
    seed_mention(conn, run_a, mentioned=True)
    seed_mention(conn, run_b, mentioned=False)
    seed_mention(conn, run_c, mentioned=False)

    section = build(conn, primary_entity_id=9)
    assert tier_of(section, 'catalog_accuracy')['visibility'] == {
        'runs': 2, 'mentioned': 1, 'rate': 0.5,
    }
    assert tier_of(section, 'category_control')['visibility']['rate'] == 0.0


def test_the_brand_direct_tier_reports_no_visibility_at_all(conn):
    """It measured whether the brand was named, which is what `echoed`
    counts — in a word that does not read as a score. Two numbers for one
    fact, one of them called visibility, is how 63 of 66 runs on a brand
    nobody could find came to look like 95% visible."""
    run = seed_outcome(conn, tier='brand_direct', outcome='echoed', query_id=1)
    seed_mention(conn, run, mentioned=True)

    entry = tier_of(build(conn, primary_entity_id=9), 'brand_direct')
    assert 'visibility' not in entry
    assert 'Brand echoed' in entry['visibility_retired']


def test_visibility_is_omitted_when_there_is_no_primary_entity(conn):
    seed_outcome(conn)
    entry = tier_of(build(conn, primary_entity_id=None), 'catalog_accuracy')
    assert entry['visibility']['rate'] is None


# ── source attribution ────────────────────────────────────────────────────

def test_source_attribution_is_counted_per_tier(conn):
    seed_outcome(conn, source_attribution='brand_domain')
    seed_outcome(conn, source_attribution='retailer')
    seed_outcome(conn, source_attribution='retailer')
    seed_outcome(conn, source_attribution='none')

    entry = tier_of(build(conn), 'catalog_accuracy')
    assert entry['source_attribution'] == {
        'brand_domain': 1, 'retailer': 2, 'none': 1,
    }


# ── value survival ────────────────────────────────────────────────────────

def test_value_survival_is_the_value_tier_s_exact_rate(conn):
    """Deliberately not an average across tiers: 'did the member price,
    the code and the points survive' is a question about the value tier,
    and blending catalog prices into it would answer a different one."""
    seed_outcome(conn, tier='catalog_accuracy', outcome='exact')
    seed_outcome(conn, tier='value_incentives', outcome='exact')
    seed_outcome(conn, tier='value_incentives', outcome='wrong')

    section = build(conn)
    assert section['value_survival'] == 0.5
    assert section['value_survival_samples'] == 2


def test_value_survival_is_none_when_the_tier_was_not_run(conn):
    seed_outcome(conn, tier='catalog_accuracy', outcome='exact')
    assert build(conn)['value_survival'] is None


# ── tier order ────────────────────────────────────────────────────────────

def test_tiers_render_in_their_designed_order(conn):
    seed_outcome(conn, tier='category_control', query_id=4)
    seed_outcome(conn, tier='value_incentives', query_id=3)
    seed_outcome(conn, tier='brand_direct', query_id=2)
    seed_outcome(conn, tier='catalog_accuracy', query_id=1)

    assert [t['tier'] for t in build(conn)['tiers']] == [
        'brand_direct', 'catalog_accuracy', 'value_incentives', 'category_control',
    ]


# ── header context ────────────────────────────────────────────────────────

def test_the_expected_nulls_notes_reach_the_header(conn):
    """Written before the run, so a zero reads as predicted rather than
    explained after the fact."""
    seed_outcome(conn)
    seed_study(conn, config={
        'category_control': {'enabled': True, 'expected_nulls': 'Near zero.'},
        'merchant': {'brand': 'Wiggle & Snug', 'domain': 'trueshopstore.com'},
    })
    study = build(conn)['study']

    assert study['syndicated_merchant'] == 'wiggle-and-snug'
    assert study['merchant']['brand'] == 'Wiggle & Snug'
    assert study['expected_nulls'] == {'category_control': 'Near zero.'}


def test_a_tier_that_could_not_be_built_reaches_the_header(conn):
    """A missing rate that renders as 0% is the report lying quietly."""
    seed_outcome(conn)
    seed_study(conn, config={
        'value_incentives': {'enabled': True, 'unavailable': '504 from TrueSync'},
    })
    assert build(conn)['study']['unavailable'] == {
        'value_incentives': '504 from TrueSync',
    }


def test_a_study_with_no_brand_carries_no_study_context(conn):
    seed_outcome(conn)
    seed_study(conn, merchant=None)
    assert build(conn)['study'] is None


# ── the validated agreement rate ──────────────────────────────────────────

def test_the_agreement_rate_is_none_until_someone_records_one(conn):
    """Never estimated, never defaulted to something plausible, never
    inferred from the extractor's own confidence."""
    seed_outcome(conn)
    assert build(conn)['extraction_validation'] is None


def test_a_recorded_agreement_rate_is_returned_verbatim(conn):
    seed_outcome(conn)
    conn.execute(text("""
        UPDATE soa_cycles SET extraction_validation = :v WHERE id = 1
    """), {"v": json.dumps({
        "sample_size": 40, "agreed": 37, "agreement_rate": 0.925,
        "validated_by": "elton", "validated_at": "2026-09-10",
    })})
    conn.commit()

    validation = build(conn)['extraction_validation']
    assert validation['agreement_rate'] == 0.925
    assert validation['sample_size'] == 40


# ── the drill-down ────────────────────────────────────────────────────────

def test_every_rate_traces_back_to_a_stored_answer(conn):
    run_id = seed_outcome(conn, answer='The Size 3 pack is $22.99.')
    rows = tier_accuracy.per_question_outcomes(conn, 1)

    assert len(rows) == 1
    assert rows[0]['run_id'] == run_id
    assert rows[0]['answer_excerpt'] == 'The Size 3 pack is $22.99.'
    assert rows[0]['expected_answer']['amount'] == '22.99'


def test_the_drill_down_can_be_filtered_to_one_tier(conn):
    seed_outcome(conn, tier='catalog_accuracy', query_id=1)
    seed_outcome(conn, tier='value_incentives', query_id=2)

    rows = tier_accuracy.per_question_outcomes(conn, 1, tier='value_incentives')
    assert [r['tier'] for r in rows] == ['value_incentives']


def test_a_stale_row_names_the_publication_it_matched(conn):
    """Staleness attributable to a specific past publish rather than a
    general accusation of being behind."""
    seed_outcome(conn, outcome='stale', matched_at='2026-08-15T00:00:00+00:00')
    (row,) = tier_accuracy.per_question_outcomes(conn, 1)
    assert row['matched_published_at'].startswith('2026-08-15')


def test_a_long_answer_is_excerpted_with_the_run_id_kept(conn):
    """The full transcript stays one existing endpoint away, keyed by the
    run_id the outcome row already carries."""
    seed_outcome(conn, answer='x' * 5000)
    (row,) = tier_accuracy.per_question_outcomes(conn, 1)
    assert len(row['answer_excerpt']) == tier_accuracy.ANSWER_EXCERPT_CHARS + 1
    assert row['run_id']


# ── secondary expectations, as their own column ───────────────────────────
#
# pack_count rides on the price question rather than being asked, exactly
# as gtin does. Neither can move the tier's headline accuracy — the
# question did not ask for either — so both are reported beside it with
# their own sample.

def _sec(kind, outcome):
    return [{"type": kind, "outcome": outcome, "reason": "because"}]


def secondary_of(section, tier_name, kind):
    tier = tier_of(section, tier_name)
    return next(s for s in tier["secondary"] if s["type"] == kind)


def test_pack_count_is_reported_as_its_own_column_within_the_tier(conn):
    seed_outcome(conn, outcome='exact', secondary=_sec('pack_count', 'exact'))
    seed_outcome(conn, outcome='exact', secondary=_sec('pack_count', 'exact'))
    seed_outcome(conn, outcome='exact', secondary=_sec('pack_count', 'wrong'))

    pack = secondary_of(build(conn), 'catalog_accuracy', 'pack_count')
    assert pack['label'] == 'Pack count'
    assert pack['accuracy'] == round(2 / 3, 4)
    assert pack['scored'] == 3


def test_a_secondary_carries_its_own_sample_count(conn):
    """Same rule as every other rate here: a rate over three samples and a
    rate over three hundred are not the same claim."""
    seed_outcome(conn, secondary=_sec('pack_count', 'exact'))
    seed_outcome(conn, secondary=_sec('pack_count', 'absent'))

    pack = secondary_of(build(conn), 'catalog_accuracy', 'pack_count')
    assert pack['samples'] == 2
    assert pack['scored'] == 1
    assert pack['accuracy'] == 1.0


def test_an_absent_secondary_stays_out_of_its_denominator_and_in_its_sample(conn):
    """Recording the absents is what gives this column a denominator at
    all — without them, "right nine times out of ten" and "volunteered
    nine times in a thousand" are the same number."""
    for _ in range(9):
        seed_outcome(conn, secondary=_sec('pack_count', 'absent'))
    seed_outcome(conn, secondary=_sec('pack_count', 'exact'))

    pack = secondary_of(build(conn), 'catalog_accuracy', 'pack_count')
    assert pack['accuracy'] == 1.0
    assert pack['scored'] == 1
    assert pack['samples'] == 10
    assert pack['counts']['absent'] == 9


def test_a_secondary_never_moves_the_tiers_headline_accuracy(conn):
    """The question asked for a price. A wrong count on a right price is
    a right price."""
    seed_outcome(conn, outcome='exact', secondary=_sec('pack_count', 'wrong'))
    seed_outcome(conn, outcome='exact', secondary=_sec('gtin', 'wrong'))

    tier = tier_of(build(conn), 'catalog_accuracy')
    assert tier['accuracy'] == 1.0
    assert tier['scored'] == 2


def test_gtin_and_pack_count_are_reported_separately(conn):
    seed_outcome(conn, secondary=[
        {"type": "gtin", "outcome": "absent", "reason": "r"},
        {"type": "pack_count", "outcome": "exact", "reason": "r"},
    ])
    section = build(conn)

    assert [s['type'] for s in tier_of(section, 'catalog_accuracy')['secondary']] == [
        'gtin', 'pack_count',
    ]
    assert secondary_of(section, 'catalog_accuracy', 'gtin')['accuracy'] is None
    assert secondary_of(section, 'catalog_accuracy', 'pack_count')['accuracy'] == 1.0


def test_a_tier_with_no_secondaries_reports_an_empty_list(conn):
    seed_outcome(conn, tier='value_incentives', outcome='exact')
    assert tier_of(build(conn), 'value_incentives')['secondary'] == []


# ── the stale row, end to end ─────────────────────────────────────────────
#
# Catalog accuracy's drill-down went unresponsive on a real cycle while
# the value tier's opened; the difference between them was two stale
# outcomes. These lock the service side of that path — the shapes the
# matched-prior-publish fields can actually arrive in, and what the
# browser is handed for each.

def test_a_stale_row_carries_everything_the_drill_down_renders(conn):
    seed_outcome(
        conn, outcome='stale', matched_at='2026-08-15T00:00:00+00:00',
        answer='It costs $15.99.',
    )
    (row,) = tier_accuracy.per_question_outcomes(conn, 1)

    assert row['outcome'] == 'stale'
    assert row['matched_published_at'].startswith('2026-08-15')
    for field in ('run_id', 'query_code', 'query_text', 'platform',
                  'run_number', 'outcome_reason', 'answer_excerpt'):
        assert row[field] is not None, field


def test_a_timestamp_reaches_the_browser_as_a_string_whatever_the_driver_gives(conn):
    """sqlite hands back a string and Postgres hands back a datetime. The
    browser must not be the place that difference first shows up."""
    seed_outcome(
        conn, outcome='stale',
        matched_at=datetime(2026, 8, 15, 14, 2, 11, tzinfo=timezone.utc),
    )
    (row,) = tier_accuracy.per_question_outcomes(conn, 1)
    assert isinstance(row['matched_published_at'], str)
    assert row['matched_published_at'].startswith('2026-08-15')


def test_a_stale_row_with_no_matched_publish_is_null_not_missing(conn):
    """The field is how a stale outcome is attributed to a specific past
    publish. Absent and null are the same to the renderer, but only one
    of them is a key it can read."""
    seed_outcome(conn, outcome='stale', matched_at=None)
    (row,) = tier_accuracy.per_question_outcomes(conn, 1)
    assert 'matched_published_at' in row
    assert row['matched_published_at'] is None


def test_an_unreadable_expected_answer_is_null_rather_than_an_exception(conn):
    """The column is JSON, and _json returns None on anything it cannot
    parse. A row that cannot be described is still a row that has to be
    listed — it is evidence that something is wrong."""
    seed_outcome(conn, outcome='stale')
    conn.execute(text(
        "UPDATE soa_expectation_outcomes SET expected_answer = 'not json'"
    ))
    conn.commit()
    (row,) = tier_accuracy.per_question_outcomes(conn, 1)
    assert row['expected_answer'] is None
    assert row['outcome'] == 'stale'


def test_a_tier_with_stale_rows_lists_them_all(conn):
    """The reported cycle: catalog accuracy with two stale outcomes among
    its exacts, filtered to that tier."""
    seed_outcome(conn, outcome='exact', query_id=1)
    seed_outcome(conn, outcome='stale', query_id=2,
                 matched_at='2026-08-15T00:00:00+00:00')
    seed_outcome(conn, outcome='stale', query_id=3,
                 matched_at='2026-07-02T00:00:00+00:00')
    seed_outcome(conn, tier='value_incentives', outcome='exact', query_id=4)

    rows = tier_accuracy.per_question_outcomes(conn, 1, tier='catalog_accuracy')
    assert [r['outcome'] for r in rows] == ['exact', 'stale', 'stale']
    assert all(r['tier'] == 'catalog_accuracy' for r in rows)


# ── the brand-direct split ────────────────────────────────────────────────
#
# Fixtures are the shape cycle 20260915-113207-wiggle-snug-full produced:
# 66 runs, 33 per surface, of which 2 cited the brand's own record.

BRAND_CYCLE = {
    'chatgpt': {
        'acknowledged_unknown': 14, 'misattributed': 11, 'echoed': 4,
        'grounded': 2, 'fabricated': 0, 'absent': 2,
    },
    'gemini': {
        'acknowledged_unknown': 12, 'fabricated': 6, 'echoed': 12,
        'misattributed': 2, 'grounded': 0, 'absent': 1,
    },
}


def seed_brand_cycle(conn):
    query_id = 100
    for platform, counts in BRAND_CYCLE.items():
        for outcome, n in counts.items():
            for _ in range(n):
                query_id += 1
                seed_outcome(
                    conn, tier='brand_direct', platform=platform,
                    outcome=outcome, query_id=query_id,
                    expected={"type": "brand_mention", "brand": "Wiggle & Snug",
                              "domain": "trueshopstore.com"},
                    source_attribution=(
                        'brand_domain' if outcome == 'grounded' else 'retailer'
                    ),
                )


def test_the_brand_tier_is_reported_as_the_split_and_not_as_an_accuracy(conn):
    seed_brand_cycle(conn)
    entry = tier_of(build(conn), 'brand_direct')

    assert entry['accuracy'] is None
    assert entry['staleness'] is None
    assert entry['wrong_rate'] is None
    assert [a['outcome'] for a in entry['assessments']] == [
        'grounded', 'echoed', 'misattributed', 'fabricated',
        'acknowledged_unknown',
    ]


def test_the_split_counts_every_assessed_run_and_no_others(conn):
    seed_brand_cycle(conn)
    entry = tier_of(build(conn), 'brand_direct')

    assert entry['samples'] == 66
    # The three that never named the brand stay out of the denominator,
    # exactly as absent stays out of accuracy elsewhere.
    assert entry['assessed'] == 63
    assert sum(a['count'] for a in entry['assessments']) == 63
    assert entry['counts']['absent'] == 3


def test_two_runs_in_sixty_six_read_the_record(conn):
    seed_brand_cycle(conn)
    entry = tier_of(build(conn), 'brand_direct')

    grounded = next(a for a in entry['assessments'] if a['outcome'] == 'grounded')
    assert grounded['count'] == 2
    assert entry['grounded_rate'] == round(2 / 63, 4)


def test_the_answers_that_invented_or_substituted_are_their_own_number(conn):
    """13 misattributed + 6 fabricated. Under the old scoring all 19 of
    these were `exact`."""
    seed_brand_cycle(conn)
    entry = tier_of(build(conn), 'brand_direct')
    assert entry['counts']['misattributed'] == 13
    assert entry['counts']['fabricated'] == 6
    assert entry['harmful_rate'] == round(19 / 63, 4)


def test_the_split_is_reported_per_surface(conn):
    """The two surfaces fail differently — ChatGPT substitutes another
    product, Gemini invents one — and a blended number says neither."""
    seed_brand_cycle(conn)
    surfaces = {s['platform']: s for s in tier_of(build(conn), 'brand_direct')['surfaces']}

    assert set(surfaces) == {'chatgpt', 'gemini'}
    chatgpt = {a['outcome']: a['count'] for a in surfaces['chatgpt']['assessments']}
    gemini = {a['outcome']: a['count'] for a in surfaces['gemini']['assessments']}
    assert chatgpt['grounded'] == 2 and gemini['grounded'] == 0
    assert chatgpt['misattributed'] == 11 and gemini['fabricated'] == 6
    assert 'visibility' not in surfaces['chatgpt']


def test_an_outcome_from_the_wrong_vocabulary_is_not_folded_in(conn):
    """A catalog outcome on a brand-direct row would land in a
    denominator that does not describe it."""
    seed_brand_cycle(conn)
    seed_outcome(conn, tier='brand_direct', outcome='stale', query_id=999)
    entry = tier_of(build(conn), 'brand_direct')
    assert entry['samples'] == 66
    assert 'stale' not in entry['counts']


# ── value survival, and what an assistant can guess ───────────────────────

POINTS_GUESSABLE = {"type": "points", "rule": {"kind": "per_dollar", "rate": "1.00"},
                    "program_name": "Member Rewards"}
POINTS_REAL = {"type": "points", "rule": {"kind": "per_dollar", "rate": "3"},
               "program_name": "Member Rewards"}
CODE = {"type": "code", "code": "SNUG3", "value_kind": "percent_off", "value": "15.0"}


def test_a_guessable_points_rule_stays_out_of_the_value_headline(conn):
    """One point per dollar is what almost every programme does. An
    assistant that says so has shown nothing about whether it read this
    record, and a headline it moves is measuring the industry."""
    seed_outcome(conn, tier='value_incentives', outcome='exact',
                 expected=POINTS_GUESSABLE, query_id=1)
    seed_outcome(conn, tier='value_incentives', outcome='wrong',
                 expected=CODE, query_id=2)

    section = build(conn)
    assert section['value_survival'] == 0.0
    assert section['value_survival_samples'] == 1
    # The tier's own accuracy, over everything, is unchanged beside it.
    assert section['value_survival_all'] == 0.5


def test_the_excluded_rows_are_reported_rather_than_dropped(conn):
    """Silently removing rows from a published rate is its own lie."""
    seed_outcome(conn, tier='value_incentives', outcome='exact',
                 expected=POINTS_GUESSABLE, query_id=1)
    seed_outcome(conn, tier='value_incentives', outcome='wrong',
                 expected=POINTS_GUESSABLE, query_id=2)
    seed_outcome(conn, tier='value_incentives', outcome='exact',
                 expected=CODE, query_id=3)

    low = build(conn)['low_information']
    assert low['scored'] == 2
    assert low['exact'] == 1
    assert low['rate'] == 0.5
    assert 'category default' in low['note']


def test_a_real_points_rate_is_not_excluded(conn):
    """Three points per dollar is this brand's, not the industry's."""
    seed_outcome(conn, tier='value_incentives', outcome='exact',
                 expected=POINTS_REAL, query_id=1)
    section = build(conn)
    assert section['value_survival'] == 1.0
    assert section['value_survival_samples'] == 1
    assert section['low_information'] is None


def test_the_exclusion_is_decided_by_what_we_published_not_by_the_answer(conn):
    """Both of these are the same expectation. One was answered right and
    one wrong, and both are excluded — otherwise the rule could be
    applied to results somebody disliked."""
    seed_outcome(conn, tier='value_incentives', outcome='exact',
                 expected=POINTS_GUESSABLE, query_id=1)
    seed_outcome(conn, tier='value_incentives', outcome='wrong',
                 expected=POINTS_GUESSABLE, query_id=2)
    section = build(conn)
    assert section['value_survival'] is None
    assert section['value_survival_samples'] == 0


# ── near-miss codes ───────────────────────────────────────────────────────

def test_a_near_miss_code_is_counted_apart_from_the_rest_of_wrong(conn):
    """The right code with the wrong terms: the code reached the
    assistant and its value did not."""
    seed_outcome(conn, tier='value_incentives', outcome='wrong',
                 expected=CODE, near_miss=True, query_id=1)
    seed_outcome(conn, tier='value_incentives', outcome='wrong',
                 expected=CODE, query_id=2)

    entry = tier_of(build(conn), 'value_incentives')
    assert entry['near_miss'] == 1
    # And still inside wrong. Moving it out would change a denominator to
    # make a number look better.
    assert entry['counts']['wrong'] == 2
    assert entry['wrong_rate'] == 1.0


def test_a_tier_with_no_near_misses_reports_zero_not_nothing(conn):
    seed_outcome(conn, tier='catalog_accuracy', outcome='wrong')
    assert tier_of(build(conn), 'catalog_accuracy')['near_miss'] == 0


# ── the guarantee the re-score rests on ───────────────────────────────────

def test_the_catalog_tier_is_untouched_by_any_of_this(conn):
    """The brand tier is re-scored in place on top of these changes.
    Catalog accuracy has to come out of that with the numbers it went in
    with, and it does because nothing above reads or writes its rows."""
    for outcome in ('exact', 'exact', 'exact', 'stale', 'wrong', 'absent'):
        seed_outcome(conn, tier='catalog_accuracy', outcome=outcome,
                     query_id=hash(outcome) % 50 + 1)
    seed_brand_cycle(conn)

    entry = tier_of(build(conn), 'catalog_accuracy')
    assert entry['counts'] == {
        'exact': 3, 'stale': 1, 'wrong': 1, 'absent': 1, 'unscoreable': 0,
    }
    assert entry['accuracy'] == 0.6
    assert entry['staleness'] == 0.2
    assert entry['scored'] == 5
    assert entry['samples'] == 6
