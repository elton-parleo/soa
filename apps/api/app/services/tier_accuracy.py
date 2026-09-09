"""
Tier segmentation for the Full Analysis report: Layer 1's visibility and
Layer 2's accuracy, per tier x surface, each with the sample count it
rests on.

Every number here is a count of stored rows. `accuracy` is
exact / (exact + stale + wrong) over soa_expectation_outcomes; `visibility`
is the pass-1 mention rate over soa_coded_mentions, restricted to the
runs of one tier's questions. Nothing is modelled, smoothed or imputed —
a rate the report cannot trace back to rows is a rate it should not
print.

Three rules the shapes here exist to enforce:

  A rate is never published without its sample count. A rate over four
  samples and a rate over four hundred are not the same claim, and a
  report that renders them identically invites them to be read as if
  they were.

  `absent` and `unscoreable` stay OUT of the accuracy denominator and
  visible in the counts. Neither is a claim: one is the assistant
  declining to address the quantity, the other is us failing to read the
  answer. Folding either in would move a rate for a reason that is not
  about accuracy.

  A tier that was asked for and could not be built reports as
  unavailable, not as zero. A missing rate that renders as 0% is the
  report lying quietly.

The run-over-run trend with TrueSync publish markers is phase 2 and is
NOT built here. What it needs is already stored — record_published_at and
matched_published_at on every outcome row, source_ref on every question —
so it needs no re-run when it comes.
"""
from sqlalchemy import text

# Display order, and the order the report renders them in: the tier a
# shopper's question sounds most like first, the control last.
TIER_ORDER = [
    'brand_direct', 'catalog_accuracy', 'value_incentives', 'category_control',
]

TIER_LABELS = {
    'brand_direct':     'Brand-direct',
    'catalog_accuracy': 'Catalog accuracy',
    'value_incentives': 'Value & incentives',
    'category_control': 'Category control',
}

SCORED_OUTCOMES = ('exact', 'stale', 'wrong')


def _rate(numerator: int, denominator: int):
    """A rate, or None when there is nothing to divide. None renders as
    "no sample"; 0.0 renders as "measured, and it was zero", and the two
    must never be confused."""
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def _empty_counts() -> dict:
    return {outcome: 0 for outcome in
            ('exact', 'stale', 'wrong', 'absent', 'unscoreable')}


def _summarise(counts: dict) -> dict:
    scored = sum(counts[o] for o in SCORED_OUTCOMES)
    total = sum(counts.values())
    return {
        'counts': dict(counts),
        # The denominator, stated. Every rate below is over `scored`
        # except `answered_rate`, which is over everything.
        'scored': scored,
        'samples': total,
        'accuracy': _rate(counts['exact'], scored),
        'staleness': _rate(counts['stale'], scored),
        'wrong_rate': _rate(counts['wrong'], scored),
        # How often the assistant addressed the quantity at all. Kept
        # beside accuracy rather than folded into it: an assistant that
        # is right whenever it answers but answers a third of the time is
        # a different result from one that answers everything.
        'answered_rate': _rate(scored, total - counts['unscoreable']),
        # Our own failure rate, published rather than hidden. A rising
        # unscoreable share is the signal that the extractor is
        # degrading, and it is only visible if it is printed.
        'unscoreable_rate': _rate(counts['unscoreable'], total),
    }


# ─── Layer 2: outcomes per tier x surface ──────────────────────────────────

def _outcome_rows(conn, cycle_id: int):
    return conn.execute(text("""
        SELECT tier, platform, outcome, COUNT(*) AS n
        FROM soa_expectation_outcomes
        WHERE cycle_id = :cycle_id
        GROUP BY tier, platform, outcome
    """), {"cycle_id": cycle_id}).fetchall()


def _source_rows(conn, cycle_id: int):
    return conn.execute(text("""
        SELECT tier, platform, source_attribution, COUNT(*) AS n
        FROM soa_expectation_outcomes
        WHERE cycle_id = :cycle_id
        GROUP BY tier, platform, source_attribution
    """), {"cycle_id": cycle_id}).fetchall()


# ─── Layer 1: visibility per tier x surface ────────────────────────────────

def _visibility_rows(conn, cycle_id: int, primary_entity_id):
    """
    Pass-1 mention rate for the PRIMARY entity, split by the tier of the
    question that produced each run.

    Reads soa_coded_mentions unchanged — Layer 1 is not re-derived here
    and is not affected by any of this. The tier is a GROUP BY, which is
    the whole point of stamping it on the question.
    """
    if primary_entity_id is None:
        return []
    return conn.execute(text("""
        SELECT q.tier,
               r.platform,
               COUNT(*) AS runs,
               SUM(CASE WHEN m.mentioned THEN 1 ELSE 0 END) AS mentioned
        FROM soa_coded_mentions m
        JOIN soa_runs r ON r.id = m.run_id
        JOIN soa_queries q ON q.id = r.query_id
        WHERE r.cycle_id = :cycle_id
          AND m.entity_id = :entity_id
          AND q.tier IS NOT NULL
        GROUP BY q.tier, r.platform
    """), {"cycle_id": cycle_id, "entity_id": primary_entity_id}).fetchall()


# ─── Drill-down ────────────────────────────────────────────────────────────

def per_question_outcomes(conn, cycle_id: int, *, tier: str = None, limit: int = 500):
    """
    One row per scored (question x surface x sample), with the stored
    answer text.

    The answer comes from soa_runs.raw_response, which is where it has
    always lived — the outcome row keys on run_id precisely so this join
    exists and a second copy does not. Truncated for transport, with the
    run_id carried so the full transcript is one existing endpoint away.

    This is what "every rate must trace back to stored answers" means in
    practice: every number in the summary above is a count of these rows,
    and these rows can be read.
    """
    clause = "AND o.tier = :tier" if tier else ""
    rows = conn.execute(text(f"""
        SELECT o.run_id, o.query_id, o.tier, o.platform, o.outcome,
               o.outcome_reason, o.expected_answer, o.extraction,
               o.secondary_results, o.source_attribution, o.domain_cited,
               o.record_published_at, o.matched_published_at,
               q.query_code, q.query_text,
               r.run_number, r.raw_response
        FROM soa_expectation_outcomes o
        JOIN soa_queries q ON q.id = o.query_id
        JOIN soa_runs r ON r.id = o.run_id
        WHERE o.cycle_id = :cycle_id {clause}
        ORDER BY q.query_code, o.platform, r.run_number
        LIMIT :limit
    """), {"cycle_id": cycle_id, "tier": tier, "limit": limit}).mappings().all()

    return [
        {
            'run_id': row['run_id'],
            'query_code': row['query_code'],
            'query_text': row['query_text'],
            'tier': row['tier'],
            'platform': row['platform'],
            'run_number': row['run_number'],
            'outcome': row['outcome'],
            'outcome_reason': row['outcome_reason'],
            'expected_answer': _json(row['expected_answer']),
            'extraction': _json(row['extraction']),
            'secondary_results': _json(row['secondary_results']),
            'source_attribution': row['source_attribution'],
            'domain_cited': row['domain_cited'],
            'record_published_at': _iso(row['record_published_at']),
            'matched_published_at': _iso(row['matched_published_at']),
            'answer_excerpt': _excerpt(row['raw_response']),
        }
        for row in rows
    ]


ANSWER_EXCERPT_CHARS = 1200


def _excerpt(text_value):
    if not text_value:
        return None
    if len(text_value) <= ANSWER_EXCERPT_CHARS:
        return text_value
    return text_value[:ANSWER_EXCERPT_CHARS] + '…'


def _json(value):
    import json
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _iso(value):
    return None if value is None else str(value)


# ─── The section ───────────────────────────────────────────────────────────

def build_tier_accuracy(conn, cycle_id: int, *, primary_entity_id=None,
                        study_type: str = None):
    """
    The tier section of the Full Analysis report, or None when this cycle
    has no tiered questions at all.

    None, not an empty section: a study generated without a syndicated
    brand has nothing to say here, and rendering an empty accuracy panel
    on it would invite the reader to conclude something about a
    measurement that was never taken.
    """
    outcome_rows = _outcome_rows(conn, cycle_id)
    visibility_rows = _visibility_rows(conn, cycle_id, primary_entity_id)
    if not outcome_rows and not visibility_rows:
        return None

    tiers = {}

    def tier_entry(tier):
        if tier not in tiers:
            tiers[tier] = {
                'tier': tier,
                'label': TIER_LABELS.get(tier, tier),
                'counts': _empty_counts(),
                'surfaces': {},
                'visibility': {'runs': 0, 'mentioned': 0},
                'source_attribution': {},
            }
        return tiers[tier]

    def surface_entry(tier, platform):
        entry = tier_entry(tier)
        if platform not in entry['surfaces']:
            entry['surfaces'][platform] = {
                'platform': platform,
                'counts': _empty_counts(),
                'visibility': {'runs': 0, 'mentioned': 0},
            }
        return entry['surfaces'][platform]

    for row in outcome_rows:
        tier, platform, outcome, n = row[0], row[1], row[2], row[3]
        tier_entry(tier)['counts'][outcome] += n
        surface_entry(tier, platform)['counts'][outcome] += n

    for row in _source_rows(conn, cycle_id):
        tier, _platform, attribution, n = row[0], row[1], row[2], row[3]
        bucket = tier_entry(tier)['source_attribution']
        key = attribution or 'none'
        bucket[key] = bucket.get(key, 0) + n

    for row in visibility_rows:
        tier, platform, runs, mentioned = row[0], row[1], row[2], row[3] or 0
        entry = tier_entry(tier)
        entry['visibility']['runs'] += runs
        entry['visibility']['mentioned'] += mentioned
        surface = surface_entry(tier, platform)
        surface['visibility']['runs'] += runs
        surface['visibility']['mentioned'] += mentioned

    def finish_visibility(block):
        block['rate'] = _rate(block['mentioned'], block['runs'])
        return block

    ordered = []
    for tier in TIER_ORDER + sorted(set(tiers) - set(TIER_ORDER)):
        entry = tiers.get(tier)
        if entry is None:
            continue
        entry.update(_summarise(entry['counts']))
        finish_visibility(entry['visibility'])
        surfaces = []
        for surface in sorted(entry['surfaces'].values(), key=lambda s: s['platform']):
            surface.update(_summarise(surface['counts']))
            finish_visibility(surface['visibility'])
            surfaces.append(surface)
        entry['surfaces'] = surfaces
        ordered.append(entry)

    value_tier = next(
        (t for t in ordered if t['tier'] == 'value_incentives'), None,
    )

    return {
        'tiers': ordered,
        # The headline the brief asks for by name. Deliberately the value
        # tier's exact rate and not an average across tiers: "did the
        # member price, the code and the points survive into the answer"
        # is a question about the value tier, and blending catalog prices
        # into it would answer a different one.
        'value_survival': value_tier['accuracy'] if value_tier else None,
        'value_survival_samples': value_tier['scored'] if value_tier else 0,
        'study': _study_context(conn, study_type),
        'extraction_validation': _extraction_validation(conn, cycle_id),
    }


# ─── Header context: expected nulls and the validated agreement rate ───────

def _study_context(conn, study_type: str):
    """
    What the study SAID it expected before the run: the brand it is
    grounded in, and the per-tier expected-nulls notes.

    Rendered in the report header so a zero is attributable. A prediction
    read after the result is not a prediction, which is why these are
    written at generation time and only read here.
    """
    if not study_type:
        return None

    row = conn.execute(text("""
        SELECT syndicated_merchant, tier_config
        FROM soa_query_generation_jobs
        WHERE study_type = :study_type
    """), {"study_type": study_type}).fetchone()
    if row is None or not row[0]:
        return None

    config = _json(row[1]) or {}
    return {
        'syndicated_merchant': row[0],
        'merchant': config.get('merchant'),
        'expected_nulls': {
            tier: entry.get('expected_nulls')
            for tier, entry in config.items()
            if isinstance(entry, dict) and entry.get('expected_nulls')
        },
        'unavailable': {
            tier: entry.get('unavailable')
            for tier, entry in config.items()
            if isinstance(entry, dict) and entry.get('unavailable')
        },
        'tier_counts': {
            tier: entry.get('count')
            for tier, entry in config.items()
            if isinstance(entry, dict) and entry.get('count') is not None
        },
    }


def _extraction_validation(conn, cycle_id: int):
    """
    The hand-checked agreement rate for this cycle's extractor, or None.

    None until a human records one, and the report says "not validated"
    rather than printing a number. It is never estimated, never defaulted
    to something plausible, and never inferred from the extractor's own
    confidence — a validated agreement rate that nobody validated is the
    single most damaging number this system could print.
    """
    row = conn.execute(text("""
        SELECT extraction_validation FROM soa_cycles WHERE id = :cycle_id
    """), {"cycle_id": cycle_id}).fetchone()
    return _json(row[0]) if row else None
