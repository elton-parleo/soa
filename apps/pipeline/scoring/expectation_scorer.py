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
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import text

from clients.truesync_catalog import TrueSyncCatalogClient, TrueSyncNotAuthorized
from parser.expectation_client import ExpectationClient
from parser.extraction_postprocess import apply_labels
from scoring import brand_direct_classifier as bdc
from scoring import expectation_comparator as cmp
from scoring import record_variants as rv
from scoring.retailer_reference import ReferenceSet
from soa_shared import expected_answers as ea
from soa_shared.database import engine

#: 2B: what a consumer surface returned instead of an answer. A RESULT, not
#: a failure: scored `absent`, counted in coverage, excluded from accuracy.
NO_ANSWER_STATUSES = ('no_ai_answer', 'sign_in_wall', 'blocked')

logger = logging.getLogger(__name__)


def _snapshot(client, study_type, merchant_slug, *, with_history):
    """
    The merchant's snapshot, read with the token of the customer the study
    belongs to (TrueSyncCatalogClient.for_study) unless a client was given.

    A REFUSAL is not degraded around (Step 1C, reversing the earlier
    choice). Without the catalog, the staleness lookup has no history, and
    a mismatch that is really `stale` — a value we once published — scores
    `wrong`. That silently changes outcomes rather than costing nuance, so
    TrueSyncNotAuthorized propagates and fails the cycle with the org or
    variable named (orchestrator/pipeline.py, Stage 2c). An OUTAGE still
    degrades: it is weather, and the snapshot says so.
    """
    if client is None:
        client = TrueSyncCatalogClient.for_study(study_type)
    return client.snapshot(merchant_slug, with_history=with_history)


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
        # None: each merchant is read with its study's customer's token.
        self._client = client
        self._by_merchant = {}
        # 2B: the snapshot itself, so the record's variants (rule 2) are
        # read off the same single catalog read as the history.
        self._snapshots = {}

    def record_variants(self, merchant_slug, study_type=None):
        if not merchant_slug:
            return []
        if merchant_slug not in self._by_merchant:
            self._load(merchant_slug, study_type)
        return rv.from_snapshot(self._snapshots.get(merchant_slug))

    def history_for(self, merchant_slug, study_type=None):
        return lambda variant_id: self.for_variant(merchant_slug, variant_id, study_type)

    def for_variant(self, merchant_slug, variant_id, study_type=None):
        if not merchant_slug or not variant_id:
            return None
        if merchant_slug not in self._by_merchant:
            self._load(merchant_slug, study_type)
        return self._by_merchant[merchant_slug].get(variant_id)

    def _load(self, merchant_slug, study_type):
        if merchant_slug not in self._by_merchant:
            snapshot = _snapshot(
                self._client, study_type, merchant_slug, with_history=True,
            )
            self._snapshots[merchant_slug] = snapshot
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
        self._client = client
        self._by_merchant = {}

    def for_merchant(self, merchant_slug, study_type=None):
        if not merchant_slug:
            return {}
        if merchant_slug not in self._by_merchant:
            snapshot = _snapshot(
                self._client, study_type, merchant_slug, with_history=False,
            )
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
                    # The merchant's own sites and listed retailers: a
                    # brand claim is grounded by a source at any of them.
                    'own_domains': list(snapshot.own_domains or []) or (
                        [snapshot.domain] if snapshot.domain else []),
                    'retailer_list': list(snapshot.retailer_list or []),
                    'program_name': snapshot.program_name,
                }
        return self._by_merchant[merchant_slug]


class TenantDomainsCache:
    """
    2D: every own domain of every merchant in the cycle's tenant, read once
    per scoring pass and cached on the cycle (by cycle id, for the life of
    the scorer), for the brand-direct classifier's grounded checks.

    W&S's store (trueshopstore.com) and its brand site (wiggleandsnug.com)
    are two supply merchants, so the store's own record lists only the
    store, and an answer grounded on wiggleandsnug.com scored `echoed` on
    the store's cycle (229, run 12979). The tenant is the brand's owner:
    a source at any of its merchants' sites is the brand's own.

    An outage degrades to the merchant's own list (the rule before 2D), and
    says so; a refusal raises, as every catalog read does.
    """

    def __init__(self, client: TrueSyncCatalogClient = None) -> None:
        self._client = client
        self._by_cycle = {}

    def for_cycle(self, cycle_id, study_type=None):
        if cycle_id in self._by_cycle:
            return self._by_cycle[cycle_id]
        client = self._client or TrueSyncCatalogClient.for_study(study_type)
        # Duck-typed, as HistoryCache's 2B methods are: a client without the
        # read (a test double) gives the rule before 2D, never an error.
        read = getattr(client, 'tenant_own_domains', None)
        domains, error = read() if read else ([], None)
        if error is not None:
            logger.warning("[expectation] tenant own domains for cycle %s: %s — brand-direct "
                           "grounding reads %s", cycle_id, error,
                           f"{domains} and the merchant's own" if domains else "the merchant's own only")
        self._by_cycle[cycle_id] = list(domains)
        return self._by_cycle[cycle_id]


class ReferenceCache:
    """
    2B: one retailer-prices read per cycle, cached ON the cycle.

    soa_cycles.reference_prices holds the payload, reference_as_of its
    as_of. The first scoring of a cycle that has an attributed_to price
    reads supply once (as of the cycle's start: created_at, the moment the
    cycle existed — for a full-loop cycle that is after reference_done) and
    stores it; every later scoring, re-score and classify-only re-score of
    that cycle reads the stored copy, which is what makes a re-score
    reproducible.

    `stale` comes from the PREVIOUS cycle of the same study that has cached
    rows: supply serves only the newest reference run at or before as_of.
    """

    def __init__(self, client: TrueSyncCatalogClient = None, *, fetch: bool = True) -> None:
        self._client = client
        self._fetch = fetch
        self._by_cycle = {}

    def for_cycle(self, cycle_id, *, study_type=None, merchant_slug=None):
        if cycle_id in self._by_cycle:
            return self._by_cycle[cycle_id]
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT id, cycle_code, study_type, reference_prices, created_at, start_date "
                "FROM soa_cycles WHERE id = :id"
            ), {"id": cycle_id}).fetchone()
        if row is None:
            self._by_cycle[cycle_id] = None
            return None
        payload = _as_dict(row.reference_prices)
        if payload is None and self._fetch and merchant_slug:
            payload = self._read(row, study_type or row.study_type, merchant_slug)
        prior_code, prior_payload = self._prior(row)
        reference = ReferenceSet(payload, prior_payload=prior_payload,
                                 prior_cycle_code=prior_code) if payload else None
        self._by_cycle[cycle_id] = reference
        return reference

    def with_payload(self, cycle_id, payload):
        """2J-4: score this cycle against `payload` instead of its stored
        copy, for this cache's life (rescore_cycle --refresh-reference's
        plan, before anything is written). `stale` still reads the previous
        cycle's stored rows."""
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT id, cycle_code, study_type, start_date FROM soa_cycles WHERE id = :id"
            ), {"id": cycle_id}).fetchone()
        prior_code, prior_payload = self._prior(row)
        self._by_cycle[cycle_id] = ReferenceSet(payload, prior_payload=prior_payload,
                                                prior_cycle_code=prior_code) if payload else None
        return self._by_cycle[cycle_id]

    def _read(self, cycle, study_type, merchant_slug):
        as_of = _cycle_start(cycle)
        client = self._client or TrueSyncCatalogClient.for_study(study_type)
        payload, error = client.retailer_prices(merchant_slug, as_of=as_of)
        if error is not None:
            logger.warning("[expectation] no retailer-prices for %s as of %s (%s) — "
                           "attributed prices score unverifiable", merchant_slug, as_of, error)
            return None
        with engine.begin() as conn:
            conn.execute(text(
                "UPDATE soa_cycles SET reference_prices = :p, reference_as_of = :a WHERE id = :id"
            ), {"p": json.dumps(payload), "a": payload.get('as_of') or as_of, "id": cycle.id})
        return payload

    @staticmethod
    def _prior(cycle):
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT cycle_code, reference_prices FROM soa_cycles "
                "WHERE study_type = :st AND id <> :id AND reference_prices IS NOT NULL "
                "  AND (start_date < :sd OR (start_date = :sd AND id < :id)) "
                "ORDER BY start_date DESC, id DESC LIMIT 1"
            ), {"st": cycle.study_type, "id": cycle.id, "sd": cycle.start_date}).fetchone()
        if row is None:
            return None, None
        return row[0], _as_dict(row[1])


def _cycle_start(cycle) -> str:
    """ISO 8601 for the cycle's start: created_at when the row has it,
    else the end of its start_date (a date alone is a day, and a reference
    read made that day belongs to it)."""
    created = getattr(cycle, 'created_at', None)
    if created is not None:
        if isinstance(created, str):
            return created
        if created.tzinfo is None:
            from datetime import timezone
            created = created.replace(tzinfo=timezone.utc)
        return created.isoformat()
    return f"{cycle.start_date}T23:59:59+00:00"


def citation_checks_enabled() -> bool:
    return os.getenv('SOA_CITATION_CHECK_ENABLED', '1') == '1'


def classify(run, expectation, extraction, *, history=None, brand_facts=None,
             references=None, domain_checker=None, tenant_domains=None) -> cmp.Verdict:
    """
    The deterministic half, for one run whose extraction already exists.

    Used by the live scorer after extraction, and by a classify-only
    re-score over the STORED extraction — the same function, so the two
    cannot disagree. No model call; the network calls it can make are the
    catalog and retailer-prices reads (cached per batch / on the cycle)
    and the citation check (cached 24 hours).
    """
    source_ref = _as_dict(run.source_ref) or {}
    merchant = source_ref.get('merchant_slug')
    facts = brand_facts.for_merchant(merchant, study_type=run.study_type) \
        if brand_facts else {}
    # 2D: the tenant's own domains ride on the facts. Two readers: the
    # brand-direct classifier (brand_direct_classifier.ours), where a refused
    # token raises as every catalog read does, and since 2E every tier's
    # source_split (expectation_comparator._decorate), a report field that
    # degrades to the merchant's own list rather than fail a price outcome
    if tenant_domains is not None and bdc.is_brand_direct(getattr(run, 'tier', None), expectation):
        facts = {**facts, 'tenant_own_domains': tenant_domains.for_cycle(
            run.cycle_id, study_type=run.study_type)}
    elif tenant_domains is not None:
        try:
            facts = {**facts, 'tenant_own_domains': tenant_domains.for_cycle(run.cycle_id, study_type=run.study_type)}
        except TrueSyncNotAuthorized:
            pass

    answer_status = getattr(run, 'answer_status', None)
    if answer_status in NO_ANSWER_STATUSES:
        return cmp.Verdict(
            outcome=cmp.ABSENT,
            reason=f"the surface showed no answer ({answer_status}); counted in "
                   f"coverage, outside accuracy",
        )

    # Duck-typed: a history cache without the 2B methods (an older caller,
    # a test double) simply gets no rule 2, never an error.
    record_variants = (history.record_variants(merchant, run.study_type)
                       if hasattr(history, 'record_variants') else None)
    history_for = (history.history_for(merchant, run.study_type)
                   if hasattr(history, 'history_for') else None)
    reference = None
    if expectation.get('attributed_to') and references is not None:
        reference = references.for_cycle(run.cycle_id, study_type=run.study_type,
                                         merchant_slug=merchant)
    dead = {}
    if domain_checker is not None:
        from scoring import answer_flags as af
        for domain in af.cited_domains(extraction.get('sources_cited')):
            check = domain_checker.check(domain)
            if check.fabricated:
                dead[domain] = check.as_dict()

    return cmp.compare_with_secondary(
        expectation, extraction,
        history=history.for_variant(merchant, source_ref.get('variant_id'),
                                    study_type=run.study_type) if history else None,
        source_ref=source_ref,
        brand_domain=expectation.get('domain') or source_ref.get('domain'),
        tier=run.tier,
        brand_facts=facts,
        record_variants=record_variants,
        history_for=history_for,
        reference=reference,
        retrieved_sources=_as_dict(getattr(run, 'retrieved_sources', None)),
        dead_domains=dead,
        grounding=_as_dict(getattr(run, 'grounding', None)),
    )


class ExpectationScorer:

    def __init__(self, client: ExpectationClient = None,
                 history: HistoryCache = None,
                 brand_facts: BrandFactsCache = None,
                 labeler=None, references: ReferenceCache = None,
                 domain_checker=None, tenant_domains: TenantDomainsCache = None) -> None:
        self.client = client or ExpectationClient()
        self.history = history if history is not None else HistoryCache()
        self.brand_facts = (
            brand_facts if brand_facts is not None else BrandFactsCache()
        )
        # 2B. The retailer-prices reference shares the history cache's
        # catalog client (and so its token); the citation check is on
        # unless SOA_CITATION_CHECK_ENABLED=0.
        self.references = references if references is not None else ReferenceCache(
            getattr(self.history, '_client', None))
        # 2D: the tenant's own domains, once per cycle, same client
        self.tenant_domains = tenant_domains if tenant_domains is not None else TenantDomainsCache(
            getattr(self.history, '_client', None))
        if domain_checker is None and citation_checks_enabled():
            from scoring.citation_check import DbDomainCheckStore, DomainChecker
            domain_checker = DomainChecker(store=DbDomainCheckStore())
        self.domain_checker = domain_checker or None
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
                       r.status, r.retrieved_sources, r.grounding, r.surface, r.answer_status,
                       q.tier, q.expected_answer, q.source_ref, q.study_type
                FROM soa_runs r
                JOIN soa_queries q ON q.id = r.query_id
                WHERE r.id = :run_id
            """), {"run_id": run_id}).fetchone()

    # ─── Writing ──────────────────────────────────────────────────────

    def _attribute_truth(self, run, source_ref):
        """2N-1: an attribute question's brand truth from the cycle's
        reference (its cached retailer-prices, read once per cycle as a
        price claim's is), or None. Every other run: None, and no read."""
        from soa_shared import attribute_accuracy as aa

        if source_ref.get('intent') != aa.ATTRIBUTE_INTENT or self.references is None:
            return None
        reference = self.references.for_cycle(run.cycle_id, study_type=getattr(run, 'study_type', None),
                                              merchant_slug=source_ref.get('merchant_slug'))
        return aa.truth_for(aa.truth_index(getattr(reference, 'payload', None)), source_ref)

    def _store(self, *, run, expectation, extraction, verdict, model):
        """
        One verdict per run. A re-score REPLACES the row rather than
        appending, so a rate cannot double-count a twice-scored run —
        which is also why the table carries a unique constraint on run_id
        rather than relying on this.
        """
        source_ref = _as_dict(run.source_ref) or {}
        extraction = code_attribute(source_ref, extraction, getattr(run, 'raw_response', None),
                                    truth=self._attribute_truth(run, source_ref))
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
            "flags": json.dumps(verdict.flags) if verdict.flags else None,
            "claim_results": json.dumps(verdict.claims) if verdict.claims else None,
            "source_split": json.dumps(verdict.source_split) if verdict.source_split else None,
            "reason_code": verdict.reason_code,
            "surface": getattr(run, 'surface', None),
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
                    near_miss, extraction_model, flags, claim_results,
                    source_split, reason_code, surface, scored_at
                ) VALUES (
                    :run_id, :query_id, :cycle_id, :platform, :tier,
                    :expected_answer, :extraction, :outcome, :outcome_reason,
                    :domain_cited, :source_attribution, :secondary_results,
                    :record_published_at, :matched_published_at,
                    :near_miss, :extraction_model, :flags, :claim_results,
                    :source_split, :reason_code, :surface, NOW()
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

        if getattr(run, 'answer_status', None) in NO_ANSWER_STATUSES:
            # A consumer surface's wall or empty answer: a result, scored
            # absent, never sent to the extractor (there is nothing to read).
            from parser.expectation_prompts import EMPTY_EXTRACTION
            extraction = {**EMPTY_EXTRACTION, 'extraction_confident': True,
                          'extraction_note': f"surface returned {run.answer_status}"}
            verdict = classify(run, expectation, extraction)
            try:
                self._store(run=run, expectation=expectation,
                            extraction=extraction, verdict=verdict, model=None)
            except Exception as exc:
                logger.exception("[expectation] run %s: could not store", run_id)
                return ScoreRunResult(run_id, 'db_error', error_message=str(exc))
            return ScoreRunResult(run_id, 'skipped_no_answer', outcome=verdict.outcome)

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
            source_ref.get('merchant_slug'), study_type=run.study_type,
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

        verdict = classify(
            run, expectation, result.record, history=self.history,
            brand_facts=self.brand_facts, references=self.references,
            domain_checker=self.domain_checker, tenant_domains=self.tenant_domains,
        )

        try:
            self._store(run=run, expectation=expectation,
                        extraction=result.record, verdict=verdict,
                        model=result.model)
        except Exception as exc:
            logger.exception("[expectation] run %s: could not store", run_id)
            return ScoreRunResult(run_id, 'db_error', error_message=str(exc))

        return ScoreRunResult(run_id, 'success', outcome=verdict.outcome)


def code_attribute(source_ref: dict, extraction: dict, answer: str, truth: dict = None) -> dict:
    """
    2M-1: on an attribute question's run (source_ref.intent 'attribute'), the
    weight range the answer states for the asked size, deterministically
    (soa_shared/attribute_accuracy.weight_from_answer), as the extraction's
    `weight_range` / `weight_evidence` (None when it states none). Every
    other run's extraction is returned as it is. No model.

    2N-1: and the brand truth it is judged against, the cycle's (`truth`,
    {truth, source} from the cycle's reference, attribute_accuracy.truth_for),
    as `weight_truth` / `weight_truth_source`. None when the cycle's
    reference has none for the variant: never the study's copy.
    """
    from soa_shared import attribute_accuracy as aa

    if (source_ref or {}).get('intent') != aa.ATTRIBUTE_INTENT or not isinstance(extraction, dict):
        return extraction
    judged = {'weight_truth': (truth or {}).get('truth'), 'weight_truth_source': (truth or {}).get('source')}
    if answer is None and 'weight_range' in extraction:
        return {**extraction, **judged}  # no answer text to read: the stored coding stands
    stated, evidence = aa.weight_from_answer(answer, source_ref.get('size'))
    return {**extraction, 'weight_range': stated, 'weight_evidence': evidence, **judged}


def _as_dict(value):
    """JSON column -> Python. Postgres hands back a parsed object; sqlite
    (and any driver storing it as TEXT) hands back a string. Same
    defensive read worker.py's _job_json already uses."""
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
