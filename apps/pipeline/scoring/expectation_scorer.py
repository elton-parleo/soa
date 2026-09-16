"""
Layer 2, end to end: extract, compare, classify, store.

One soa_runs row -> one soa_expectation_outcomes row, for runs whose
query carries a typed expectation. Layer 1 (soa_coded_mentions) is not
touched and runs on every tier regardless; the tier tag is what segments
it. This never re-derives mentioned/position/strength — there is nothing
here for those to drift from, by construction, exactly as pass 2 is
separated from pass 1.

The publication history comes from TrueSync at SCORING time, not from
what the study stored at generation time. That ordering is the point: a
history fetched when the question was written is a picture of the past as
it looked before anything republished, and staleness is precisely the
question of what has been published since.
"""
import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from clients.truesync_catalog import TrueSyncCatalogClient
from parser.expectation_client import ExpectationClient
from parser.extraction_postprocess import apply_labels
from scoring import expectation_comparator as cmp
from soa_shared import expected_answers as ea
from soa_shared.database import engine

logger = logging.getLogger(__name__)


@dataclass
class ScoreRunResult:
    run_id: int
    status: str  # success / skipped_no_expectation / skipped_no_answer / db_error
    outcome: Optional[str] = None
    error_message: Optional[str] = None


class HistoryCache:
    """
    One price-history read per merchant per batch, not per run.

    A hundred runs of one study all ground in one brand; reading its
    history a hundred times would be a hundred identical requests to a
    third-party service inside a scoring loop. Cached for the life of the
    batch and no longer — the next batch reads fresh, because what
    "prior" means changes every time anything republishes.
    """

    def __init__(self, client: TrueSyncCatalogClient = None) -> None:
        self._client = client or TrueSyncCatalogClient()
        self._by_merchant = {}

    def for_variant(self, merchant_slug, variant_id):
        if not merchant_slug or not variant_id:
            return None
        if merchant_slug not in self._by_merchant:
            snapshot = self._client.snapshot(merchant_slug, with_history=True)
            if not snapshot.available:
                logger.warning(
                    "[expectation] no price history for %s (%s) — a mismatch "
                    "will score wrong rather than stale",
                    merchant_slug, snapshot.error,
                )
            self._by_merchant[merchant_slug] = {
                vid: [
                    {
                        'published_at': point.published_at,
                        'list_price': point.list_price,
                        'member_price': point.member_price,
                        'member_tier_name': point.member_tier_name,
                    }
                    for point in points
                ]
                for vid, points in (snapshot.price_history or {}).items()
            }
        return self._by_merchant[merchant_slug].get(variant_id)


class BrandFactsCache:
    """
    What the record publishes about a brand, for the brand-direct
    classifier to check claims against.

    Same one-read-per-merchant-per-batch discipline as HistoryCache, and
    the same degradation: if the catalog cannot be read, the facts are
    empty and the classifier simply has less to contradict. It never
    guesses — a claim the record cannot speak to is reported as unsourced,
    never as disproved.
    """

    def __init__(self, client: TrueSyncCatalogClient = None) -> None:
        self._client = client or TrueSyncCatalogClient()
        self._by_merchant = {}

    def for_merchant(self, merchant_slug):
        if not merchant_slug:
            return {}
        if merchant_slug not in self._by_merchant:
            snapshot = self._client.snapshot(merchant_slug, with_history=False)
            if not snapshot.available:
                logger.warning(
                    "[expectation] no catalog for %s (%s) — brand claims can "
                    "only be checked for whether they were sourced",
                    merchant_slug, snapshot.error,
                )
                self._by_merchant[merchant_slug] = {}
            else:
                self._by_merchant[merchant_slug] = {
                    'brand': snapshot.brand,
                    'domain': snapshot.domain,
                    'tier_names': [
                        t.get('name') for t in (snapshot.tiers or []) if t.get('name')
                    ],
                    'product_titles': [p.title for p in (snapshot.products or [])],
                }
        return self._by_merchant[merchant_slug]


class ExpectationScorer:

    def __init__(self, client: ExpectationClient = None,
                 history: HistoryCache = None,
                 brand_facts: BrandFactsCache = None,
                 labeler=None) -> None:
        self.client = client or ExpectationClient()
        self.history = history if history is not None else HistoryCache()
        self.brand_facts = (
            brand_facts if brand_facts is not None else BrandFactsCache()
        )
        # Step 1b. Constructed lazily so a test that does not pass one
        # gets no labelling call rather than a missing-API-key error at
        # import time; pass labeler=False to switch it off outright.
        if labeler is None:
            from parser.labeling_client import LabelingClient
            labeler = LabelingClient()
        self.labeler = labeler or None

    # ─── Reading ──────────────────────────────────────────────────────

    def _load_run(self, run_id: int):
        with engine.connect() as conn:
            return conn.execute(text("""
                SELECT r.id, r.cycle_id, r.query_id, r.platform, r.raw_response,
                       r.status,
                       q.tier, q.expected_answer, q.source_ref
                FROM soa_runs r
                JOIN soa_queries q ON q.id = r.query_id
                WHERE r.id = :run_id
            """), {"run_id": run_id}).fetchone()

    # ─── Writing ──────────────────────────────────────────────────────

    def _store(self, *, run, expectation, extraction, verdict, model):
        """
        One verdict per run. A re-score REPLACES the row rather than
        appending, so a rate cannot double-count a twice-scored run —
        which is also why the table carries a unique constraint on run_id
        rather than relying on this.
        """
        import json

        source_ref = _as_dict(run.source_ref) or {}
        payload = {
            "run_id": run.id,
            "query_id": run.query_id,
            "cycle_id": run.cycle_id,
            "platform": run.platform,
            "tier": run.tier,
            # A COPY of the expectation, not a join. Republishing rewrites
            # the question's expectation, and an outcome reading through
            # to the new one would silently restate what it compared
            # against.
            "expected_answer": json.dumps(expectation),
            "extraction": json.dumps(extraction),
            "outcome": verdict.outcome,
            "outcome_reason": verdict.reason,
            "domain_cited": verdict.domain_cited,
            "source_attribution": verdict.source_attribution,
            "secondary_results": (
                json.dumps(verdict.secondary) if verdict.secondary else None
            ),
            "record_published_at": source_ref.get('published_at'),
            "matched_published_at": verdict.matched_published_at,
            "near_miss": verdict.near_miss or None,
            "extraction_model": model,
        }

        with engine.connect() as conn:
            conn.execute(
                text("DELETE FROM soa_expectation_outcomes WHERE run_id = :run_id"),
                {"run_id": run.id},
            )
            conn.execute(text("""
                INSERT INTO soa_expectation_outcomes (
                    run_id, query_id, cycle_id, platform, tier,
                    expected_answer, extraction, outcome, outcome_reason,
                    domain_cited, source_attribution, secondary_results,
                    record_published_at, matched_published_at,
                    near_miss, extraction_model, scored_at
                ) VALUES (
                    :run_id, :query_id, :cycle_id, :platform, :tier,
                    :expected_answer, :extraction, :outcome, :outcome_reason,
                    :domain_cited, :source_attribution, :secondary_results,
                    :record_published_at, :matched_published_at,
                    :near_miss, :extraction_model, NOW()
                )
            """), payload)
            conn.commit()

    # ─── One run ──────────────────────────────────────────────────────

    async def score_run(self, run_id: int) -> ScoreRunResult:
        run = self._load_run(run_id)
        if run is None:
            return ScoreRunResult(run_id, 'skipped_no_run')

        expectation = _as_dict(run.expected_answer)
        if not ea.is_scoreable(expectation):
            # Not a failure. Category-control questions carry no
            # expectation deliberately, and so does every query written
            # before the tiers existed. Layer 1 has already run on them.
            return ScoreRunResult(run_id, 'skipped_no_expectation')

        if run.status != 'success' or not (run.raw_response or '').strip():
            # An answer that never arrived is not an assistant error. It
            # is recorded as unscoreable, with a row, so the run is
            # visible in the sample count rather than quietly missing
            # from a denominator.
            from parser.expectation_prompts import EMPTY_EXTRACTION
            extraction = {
                **EMPTY_EXTRACTION,
                'extraction_note': f"run status {run.status!r}, no answer text",
            }
            verdict = cmp.compare(expectation, extraction, tier=run.tier)
            try:
                self._store(run=run, expectation=expectation,
                            extraction=extraction, verdict=verdict, model=None)
            except Exception as exc:
                logger.exception("[expectation] run %s: could not store", run_id)
                return ScoreRunResult(run_id, 'db_error', error_message=str(exc))
            return ScoreRunResult(run_id, 'skipped_no_answer', outcome=verdict.outcome)

        source_ref = _as_dict(run.source_ref) or {}
        facts = self.brand_facts.for_merchant(
            source_ref.get('merchant_slug'),
        ) if self.brand_facts else {}

        # The study's merchant, for every tier. A price expectation
        # carries no brand, and without this fallback brand_mentioned was
        # computed with nothing to look for on every catalog and value
        # row in the study — which ea.names_brand answers True to.
        brand = (expectation.get('brand')
                 or source_ref.get('brand')
                 or facts.get('brand'))

        result = await self.client.extract(
            run.raw_response, brand=brand,
            # So the post-processor can tell the brand's own site from
            # another brand when the answer writes one as the other.
            brand_domain=(expectation.get('domain') or source_ref.get('domain')
                          or facts.get('domain')),
        )

        # Step 1b: what each transcribed span IS. A failed call leaves
        # every span unlabelled, which asserted_claims reads as no claims
        # — never as claims nobody classified.
        if self.labeler is not None:
            labels = await self.labeler.label(
                result.record, answer_text=run.raw_response,
            )
            result.record = apply_labels(
                result.record, labels.labels,
                answer_text=run.raw_response, brand=brand,
            )
            if labels.error:
                logger.warning(
                    "[expectation] run %s: labelling failed (%s) — spans are "
                    "recorded and unlabelled", run_id, labels.error,
                )

        history = self.history.for_variant(
            source_ref.get('merchant_slug'), source_ref.get('variant_id'),
        ) if self.history else None

        verdict = cmp.compare_with_secondary(
            expectation, result.record,
            history=history,
            source_ref=source_ref,
            brand_domain=expectation.get('domain') or source_ref.get('domain'),
            tier=run.tier,
            brand_facts=facts,
        )

        try:
            self._store(run=run, expectation=expectation,
                        extraction=result.record, verdict=verdict,
                        model=result.model)
        except Exception as exc:
            logger.exception("[expectation] run %s: could not store", run_id)
            return ScoreRunResult(run_id, 'db_error', error_message=str(exc))

        return ScoreRunResult(run_id, 'success', outcome=verdict.outcome)


def _as_dict(value):
    """JSON column -> Python. Postgres hands back a parsed object; sqlite
    (and any driver storing it as TEXT) hands back a string. Same
    defensive read worker.py's _job_json already uses."""
    import json

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


# ─── Which runs need scoring ───────────────────────────────────────────────

def scoreable_run_ids(cycle_id: int) -> list:
    """
    Every run in this cycle whose query carries a typed expectation.

    The filter is on expected_answer being non-null rather than on the
    tier: a category-control question has a tier and no expectation and
    must not be scored, and a hand-written question could have an
    expectation and no tier and should be.
    """
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT r.id
            FROM soa_runs r
            JOIN soa_queries q ON q.id = r.query_id
            WHERE r.cycle_id = :cycle_id
              AND q.expected_answer IS NOT NULL
            ORDER BY r.id
        """), {"cycle_id": cycle_id}).fetchall()
    return [row[0] for row in rows]
