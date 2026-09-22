"""
Pipeline polling worker.

Railway runs this as a continuously running process. It polls soa_cycles
every 30 seconds for rows with status = 'planned' and executes each one
through PipelineOrchestrator.

The API (Vercel) writes status='planned' when a user launches a cycle in
the UI. This worker picks it up and runs it. The two services communicate
only through the database — no direct coupling.

Also polls soa_lite_requests (status='pending') for SoA Lite, the public
unauthenticated lead-gen flow: process_lite_requests resolves entities,
generates a fixed LITE_QUERY_COUNT-query study, and creates a cycle for it, which then
flows through the SAME planned-cycle poll/execute_cycle path as any other
cycle (prioritized — see get_next_planned_cycle). Once the cycle is
queued, process_lite_requests also runs the Agent Scan (scan/engine.py)
synchronously against the request's store_url and records the result on
soa_lite_scan_results — never delaying the cycle, and never able to fail
the lite request itself (see _run_lite_scan). _sweep_lite_completions
mirrors both the cycle's and the scan's terminal state back onto
soa_lite_requests.
"""
import os
import sys
import time
import json
import asyncio
import logging
from datetime import datetime, timedelta, timezone

# Add pipeline root to path so local modules resolve correctly
sys.path.insert(0, os.path.dirname(__file__))

from urllib.parse import urlparse

import lite_events
import ops_alert
from soa_shared.database import engine
from soa_shared.degraded_dimensions import (
    DEGRADED_REASON_ORCHESTRATION_FAILED,
    DEGRADED_REASON_TIMED_OUT,
    build_degraded_dimensions,
)
from soa_shared.scan_dimensions import SCORER_VERSION
from soa_shared.models.soa_models import (
    LITE_STATUS_COMPLETE,
    LITE_STATUS_FAILED,
    LITE_STATUS_GENERATING,
    LITE_STATUS_IDENTIFYING_COMPETITORS,
    LITE_STATUS_RUNNING,
)
from sqlalchemy import bindparam, text

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [worker] %(levelname)s %(message)s',
)
log = logging.getLogger(__name__)

POLL_INTERVAL = 30  # seconds when idle


def _env_int(name: str, default: int) -> int:
    """Never raises — an unset or unparseable env var falls back to the
    default, same discipline as scan/fetcher.py's own _env_int. A worker
    must never fail to boot over a typo in a tuning knob."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def get_next_planned_cycle():
    """
    Fetch the oldest planned cycle.
    Returns a Row with (cycle_code, study_type, platforms, runs_per_query,
    cycle_mode) or None.

    SoA Lite cycles (cycle_code prefix 'lite-') jump the queue ahead of
    everything else: they run in a couple minutes (1 platform,
    1 run/query, LITE_QUERY_COUNT queries, at LITE_QUERY_CONCURRENCY —
    see run_orchestrator.py) versus hours for a full client cycle, and a
    lead-gen visitor is waiting live on the result. Within each priority
    tier, oldest first.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT
              cycle_code,
              study_type,
              platforms,
              runs_per_query,
              cycle_mode
            FROM soa_cycles
            WHERE status = 'planned'
            ORDER BY (CASE WHEN cycle_code LIKE 'lite-%' THEN 0 ELSE 1 END), created_at ASC
            LIMIT 1
        """)).fetchone()
    return row


def mark_failed(cycle_code: str, error: str):
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE soa_cycles
            SET status = 'failed',
                notes = COALESCE(notes,'') || :suffix
            WHERE cycle_code = :code
        """), {
            "code":   cycle_code,
            "suffix": (
                f"\n[worker error "
                f"{datetime.now(timezone.utc).isoformat()}] {error}"
            ),
        })
    log.error(f"Marked {cycle_code} as failed: {error}")


async def execute_truecost_sweep(cycle_code: str):
    """
    cycle_mode='truecost' path — sweeps the cycle's scoped SKUs through the
    Deal Engine instead of running LLM queries. No soa_runs, no coder.
    """
    from sqlalchemy import text as _text
    from soa_shared.models.soa_models import SoaCycle
    from soa_shared.database import session_factory
    from sweep.truecost_sweep import run_truecost_sweep

    log.info(f"Starting truecost sweep for {cycle_code}")
    with session_factory() as session:
        cycle = session.query(SoaCycle).filter_by(cycle_code=cycle_code).first()
        cycle.status = "running"
        session.commit()

    summary = await run_truecost_sweep(cycle_code)

    with session_factory() as session:
        cycle = session.query(SoaCycle).filter_by(cycle_code=cycle_code).first()
        cycle.status = "complete"
        cycle.total_runs_planned = summary.total_planned
        cycle.completed_runs = summary.captured + summary.unavailable
        cycle.end_date = datetime.now(timezone.utc).date()
        session.commit()

    log.info(
        f"Truecost sweep done: {cycle_code} — "
        f"captured={summary.captured} unavailable={summary.unavailable} "
        f"skipped={summary.skipped_already_done} "
        f"({summary.sku_count} SKUs x {summary.tier_count} tiers)"
    )


async def execute_cycle(
    cycle_code: str,
    study_type: str,
    platforms: list,
    runs_per_query: int,
    cycle_mode: str = "query",
):
    if cycle_mode == "truecost":
        await execute_truecost_sweep(cycle_code)
        return

    from orchestrator.pipeline import PipelineOrchestrator
    log.info(f"Starting pipeline for {cycle_code} ({study_type})")
    log.info(f"Platforms: {platforms}")
    log.info(f"Runs per query: {runs_per_query}")
    orch = PipelineOrchestrator(
        cycle_code=cycle_code,
        study_type=study_type,
        platforms=platforms,
        runs_per_query=runs_per_query,
    )
    await orch.run_pipeline()
    log.info(f"Pipeline done: {cycle_code}")


def _mark_generation_failed(job_id: int, error: str):
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE soa_query_generation_jobs
            SET status = 'failed',
                error_message = :err,
                updated_at = NOW()
            WHERE id = :id
        """), {"id": job_id, "err": error[:1000]})
        conn.commit()


def _insert_generated_rows(
    rows: list,
    study_type: str,
    organization_id: int,
    created_by: str | None,
):
    """
    Bulk inserts validated generated rows into soa_queries with
    auto-generated query_codes. Uses _query_code_prefix logic.
    organization_id and created_by are taken from the generation job row
    so every inserted query is correctly scoped to the requesting org.
    """
    name = study_type
    for pfx in ('brand_', 'retailer_', 'sonic_', 'senso_'):
        if name.startswith(pfx):
            name = name[len(pfx):]
            break
    prefix = name.split('_')[0][:3].upper()

    with engine.connect() as conn:
        count_row = conn.execute(
            text("SELECT COUNT(*) FROM soa_queries WHERE study_type = :st"),
            {"st": study_type},
        ).fetchone()
        counter = count_row[0] or 0

        for row in rows:
            counter += 1
            query_code = f"{prefix}_{counter:03d}"
            # Collision check (global — query_code must be globally unique)
            while conn.execute(
                text("SELECT 1 FROM soa_queries WHERE query_code = :code"),
                {"code": query_code},
            ).fetchone():
                counter += 1
                query_code = f"{prefix}_{counter:03d}"

            conn.execute(text("""
                INSERT INTO soa_queries (
                    query_code, query_text, category, stage,
                    specificity, persona, study_type, study_pattern,
                    soa_focus, rationale, status,
                    organization_id, created_by,
                    tier, expected_answer, provenance, source_ref,
                    created_at
                ) VALUES (
                    :query_code, :query_text, :category, :stage,
                    :specificity, :persona, :study_type, :study_pattern,
                    :soa_focus, :rationale, :status,
                    :organization_id, :created_by,
                    :tier, :expected_answer, :provenance, :source_ref,
                    NOW()
                )
            """), {
                "query_code":      query_code,
                "query_text":      row['query_text'],
                "category":        row['category'],
                "stage":           row['stage'],
                "specificity":     row['specificity'],
                "persona":         row['persona'],
                "study_type":      study_type,
                "study_pattern":   row['study_pattern'],
                "soa_focus":       row.get('soa_focus'),
                "rationale":       row.get('rationale'),
                "status":          row['status'],
                "organization_id": organization_id,
                "created_by":      created_by,
                # NULL on every row from an ungrounded study, which is
                # every row this function wrote before the tiers existed.
                # json.dumps rather than the raw dict, the same
                # write-convention the JSON columns on the job row use.
                "tier":            row.get('tier'),
                "expected_answer": _as_json_column(row.get('expected_answer')),
                "provenance":      row.get('provenance'),
                "source_ref":      _as_json_column(row.get('source_ref')),
            })
        conn.commit()


def _as_json_column(value):
    """Python -> a JSON column. None stays None: a NULL expected_answer
    means "this question is not scored by Layer 2", which is not the same
    fact as an empty object and is read differently by the scorer."""
    return None if value is None else json.dumps(value)


def _job_json(value):
    """Job-row JSON column -> Python. Postgres' JSON type hands back a
    parsed object; sqlite (and any driver storing it as TEXT) hands back
    a string. Same defensive read soa_lite_requests.competitor_names
    already uses in _process_one_lite_request."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            log.warning(f"[generation] unreadable JSON on job row: {value[:200]!r}")
            return None
    return value


def _record_provenance(job_id: int, provenance: dict):
    """
    Never raises. Provenance is a report ABOUT a study that already
    exists; failing the job because the report could not be written would
    destroy the thing the report is about. Logged loudly and dropped.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE soa_query_generation_jobs
                SET provenance = :prov, updated_at = NOW()
                WHERE id = :id
            """), {"prov": json.dumps(provenance), "id": job_id})
            conn.commit()
    except Exception:
        log.exception(
            f"[generation] job {job_id}: could not record provenance — the "
            f"study itself is unaffected"
        )


def _delete_tier_questions(study_type: str, tiers: list) -> int:
    """
    Removes the questions of the named tiers for this study, so a rebuild
    replaces them rather than doubling them.

    Deletes, and does not soft-retire. A regenerated study is asked
    against the record as it is NOW, and leaving the old questions
    Retired alongside would leave a study whose report has two prices for
    one variant and no way to say which one it measured.

    Their soa_runs and soa_expectation_outcomes rows are left alone, on
    purpose: a past cycle's measurements are evidence of what was true
    then, and deleting them to tidy up a regeneration would destroy the
    history the whole feature exists to build.
    """
    if not tiers:
        return 0
    # An expanding bindparam rather than a dialect branch: SQLAlchemy
    # renders it as a plain IN list on both Postgres and sqlite, so the
    # tests run the same statement production does.
    statement = text("""
        DELETE FROM soa_queries
        WHERE study_type = :study_type
          AND tier IN :tiers
    """).bindparams(bindparam("tiers", expanding=True))

    with engine.connect() as conn:
        result = conn.execute(
            statement, {"study_type": study_type, "tiers": list(tiers)},
        )
        conn.commit()
        return result.rowcount or 0


def _existing_questions(study_type: str) -> list:
    """
    The study's current questions, as {tier, query_text, persona}.

    Regeneration rebuilds some tiers and leaves the rest standing, so
    "the rest" have to be readable. Two callers need them: the persona
    stamped on rebuilt catalog rows has to match the persona the study
    already uses, and brand-direct has to know which questions the
    catalog tiers are asking so it does not ask them again in different
    words — and on a brand-direct-only regeneration those questions are
    not being rebuilt, so the database is the only place they exist.
    """
    with engine.connect() as conn:
        return [
            dict(row) for row in conn.execute(text("""
                SELECT tier, query_text, persona
                FROM soa_queries
                WHERE study_type = :study_type
            """), {"study_type": study_type}).mappings()
        ]


def _run_regeneration(
    job_id, study_type, syndicated_merchant, tier_config, regenerate,
    organization_id, created_by, api_key, **kwargs,
):
    """
    Rebuild only the named tiers of an existing study, from the catalog as
    it is now.

    The study's own stage-count questions are never touched: they exist
    with or without a brand, the control tier is a tag on them, and
    rewriting them is creating a different study rather than refreshing
    this one against a record.

    A failure leaves the study as it was. The delete and the rebuild are
    ordered rebuild-first for exactly that reason — a TrueSync outage
    between them would otherwise leave a study with its catalog questions
    gone and nothing in their place.
    """
    from clients.truesync_catalog import TrueSyncCatalogClient
    from generation import catalog_tiers as ct
    from generation.query_generator import generate_brand_direct
    from generation.syndicated_study import normalize_tier_config, _primary_category, _primary_persona

    tiers = list(regenerate.get("tiers") or [])
    config = normalize_tier_config(tier_config)
    category = _primary_category(kwargs.get("allowed_categories"))

    existing = _existing_questions(study_type)
    # The study's own rows, not a default: a rebuilt catalog question
    # that lands on a different persona from the rest of the study splits
    # one study into two populations in every report that segments by it.
    persona = _primary_persona(kwargs.get("personas"), existing)

    snapshot = TrueSyncCatalogClient().snapshot(
        syndicated_merchant, with_history=False,
    )
    if not snapshot.available:
        _mark_generation_failed(
            job_id,
            f"Could not read {syndicated_merchant}'s catalog: {snapshot.error}. "
            f"The study is unchanged.",
        )
        return

    CATALOG_TIERS = ("catalog_accuracy", "value_incentives")

    rows = []
    rebuilt_catalog = []
    if "catalog_accuracy" in tiers:
        built, report = ct.build_catalog_accuracy(
            snapshot, category=category, persona=persona,
            study_pattern=kwargs.get('study_pattern'),
        )
        rebuilt_catalog.extend(built)
        config["catalog_accuracy"].update(report)
    if "value_incentives" in tiers:
        built, report = ct.build_value_incentives(
            snapshot, category=category, persona=persona,
            study_pattern=kwargs.get('study_pattern'),
        )
        rebuilt_catalog.extend(built)
        config["value_incentives"].update(report)
    rows.extend(rebuilt_catalog)

    if "brand_direct" in tiers:
        # Every catalog question that will exist when this finishes: the
        # ones just rebuilt, plus the ones staying exactly where they
        # are. On a brand-direct-only regeneration — the common case,
        # and the one that fixes a study rather than replacing it — the
        # second set is all of them.
        catalog_texts = [row["query_text"] for row in rebuilt_catalog]
        catalog_texts += [
            row["query_text"] for row in existing
            if row.get("tier") in CATALOG_TIERS and row.get("tier") not in tiers
        ]
        built, report = generate_brand_direct(
            snapshot,
            study_name=kwargs.get("study_name"),
            description=kwargs.get("description"),
            stage_targets=kwargs.get("stage_targets") or {},
            allowed_categories=kwargs.get("allowed_categories") or [],
            study_pattern=kwargs.get("study_pattern"),
            api_key=api_key,
            count=config["brand_direct"].get("count"),
            personas=kwargs.get("personas"),
            catalog_texts=catalog_texts,
        )
        rows.extend(built)
        config["brand_direct"].update({
            "count": len(built),
            "requested": report.get("requested"),
            "shortfall": report.get("shortfall"),
            "brand_missing_drops": report.get("brand_missing_drops") or [],
            "intent_duplicate_drops": report.get("intent_duplicate_drops") or [],
        })

    for tier in tiers:
        if config.get(tier):
            config[tier]["expected_nulls"] = ct.expected_nulls(snapshot, tier)
    config["merchant"] = {
        "slug": snapshot.merchant_slug, "brand": snapshot.brand,
        "domain": snapshot.domain, "products": snapshot.product_count,
        "variants": snapshot.variant_count, "gtins": snapshot.gtin_count,
        "codes": snapshot.code_count, "read_at": snapshot.read_at,
    }
    # Consumed: the marker is gone from what gets written back, so a
    # worker restart cannot regenerate the same study twice.
    config.pop("regenerate", None)

    removed = _delete_tier_questions(study_type, tiers)
    _insert_generated_rows(rows, study_type, organization_id, created_by)

    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE soa_query_generation_jobs
            SET tier_config = :config, status = 'complete', updated_at = NOW()
            WHERE id = :id
        """), {"config": json.dumps(config), "id": job_id})
        conn.commit()

    log.info(
        "[generation] job %s regenerated %s for %r: %d removed, %d written",
        job_id, ", ".join(tiers), study_type, removed, len(rows),
    )


def _run_syndicated_generation(
    *, job_id, syndicated_merchant, tier_config, stage_targets, **kwargs,
):
    """
    The grounded path: read the brand's published catalog, then build the
    four tiers over it.

    The catalog read is not allowed to fail the job. TrueSync is a
    separate service on a separate deploy, and a study whose stage
    questions generated perfectly well should not be thrown away because
    a third-party endpoint was down for the thirty seconds this ran —
    build_syndicated_study records the unavailability on tier_config and
    generates the study's ungrounded form.

    with_history=False: expectations are written against the CURRENT
    record. Prior values are the scorer's business, read at scoring time,
    because history fetched now is a picture of the past as it looked
    before anything republished.
    """
    from clients.truesync_catalog import TrueSyncCatalogClient
    from generation.syndicated_study import build_syndicated_study

    snapshot = TrueSyncCatalogClient().snapshot(
        syndicated_merchant, with_history=False,
    )
    if not snapshot.available:
        log.warning(
            "[generation] job %s: catalog for %r unavailable (%s)",
            job_id, syndicated_merchant, snapshot.error,
        )

    rows, provenance, resolved = build_syndicated_study(
        snapshot=snapshot,
        tier_config=tier_config,
        stage_targets=stage_targets,
        **kwargs,
    )

    # The stage total is what the tally splits on, and it is knowable only
    # here — build_syndicated_study sees per-tier counts, not the brief.
    resolved.setdefault('category_control', {})['stage_total'] = sum(
        (stage_targets or {}).values()
    )
    return rows, provenance, resolved


def _run_briefed_generation(
    job_id, study_type, study_name, description, target_count,
    organization_id, created_by, study_pattern, retailer_names,
    allowed_categories, stage_targets, rotate_named_retailer,
    naming_rule_enabled, personas, specificity_mode, api_key,
    syndicated_merchant=None, tier_config=None,
):
    """
    Generation for a job carrying a study brief.

    The difference from the legacy path is not just extra prompt detail.
    This one enforces the per-stage distribution rather than requesting
    it, stamps study_pattern instead of letting the model pick per row,
    drops out-of-scope categories, removes exact duplicates and asks for
    targeted replacements, and then runs two advisory review passes whose
    findings are recorded for a human and applied to nothing.

    A shortfall is reported, not raised: the study still gets created
    with whatever was generated. Failing forty-seven good queries because
    three are missing is worse than saying three are missing, and the
    provenance record says it in a form someone can act on.
    """
    from generation.query_generator import generate_and_review_study
    from soa_shared.constants import QUERY_CATEGORIES, QUERY_STAGES

    # Falling back rather than failing: these are shaping inputs, and a
    # job that reached here has a study_pattern, so the brief is real
    # even if a field of it is absent.
    if not stage_targets:
        # Even split, remainder to the earliest stages — the same shape
        # the modal's Balanced preset produces.
        base, extra = divmod(target_count, len(QUERY_STAGES))
        stage_targets = {
            stage: base + (1 if i < extra else 0)
            for i, stage in enumerate(QUERY_STAGES)
        }
    if not allowed_categories:
        allowed_categories = list(QUERY_CATEGORIES)

    # No brand chosen -> the path this function has always taken, reached
    # by the same call with the same arguments. That identity is the
    # whole guarantee for existing users: an untoggled modal is not a
    # near-copy of today's behaviour, it is today's behaviour.
    resolved_tier_config = None
    try:
        if syndicated_merchant:
            rows, provenance, resolved_tier_config = _run_syndicated_generation(
                job_id=job_id,
                syndicated_merchant=syndicated_merchant,
                tier_config=tier_config,
                study_name=study_name,
                description=description,
                stage_targets=stage_targets,
                allowed_categories=allowed_categories,
                study_pattern=study_pattern,
                api_key=api_key,
                retailer_names=retailer_names,
                rotate_named_retailer=rotate_named_retailer,
                naming_rule_enabled=naming_rule_enabled,
                personas=personas,
                specificity_mode=specificity_mode,
            )
        else:
            rows, provenance = generate_and_review_study(
                study_name=study_name,
                description=description,
                stage_targets=stage_targets,
                allowed_categories=allowed_categories,
                study_pattern=study_pattern,
                api_key=api_key,
                retailer_names=retailer_names,
                rotate_named_retailer=rotate_named_retailer,
                naming_rule_enabled=naming_rule_enabled,
                personas=personas,
                specificity_mode=specificity_mode,
            )
    except Exception as e:
        log.exception(f"[generation] job {job_id} failed")
        _mark_generation_failed(job_id, str(e))
        return

    if not rows:
        # Same honest-failure discipline as the legacy path: a job that
        # produced nothing is 'failed', never 'complete' with 0 queries
        # for the frontend to render as an oddly empty study.
        _record_provenance(job_id, provenance)
        _mark_generation_failed(
            job_id, "Generation produced no usable queries.",
        )
        return

    try:
        _insert_generated_rows(rows, study_type, organization_id, created_by)

        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE soa_query_generation_jobs
                SET created_count = :cc,
                    tier_config = COALESCE(:tier_config, tier_config),
                    status = 'complete',
                    updated_at = NOW()
                WHERE id = :id
            """), {
                "cc": len(rows),
                # The RESOLVED config, replacing what the modal asked
                # for: it carries the sampled variant ids, the per-tier
                # counts actually built, the expected-nulls notes and any
                # tier that was asked for and could not be. Rewriting the
                # request with the result is the point — the request is
                # not evidence of what the study contains.
                "tier_config": _as_json_column(resolved_tier_config),
                "id": job_id,
            })
            conn.commit()
    except Exception as e:
        log.exception(f"[generation] job {job_id} failed during insert")
        _mark_generation_failed(job_id, str(e))
        return

    # After the status update, deliberately. A poll that sees 'complete'
    # and no provenance yet reads as "not recorded"; one that sees
    # provenance on a job still 'running' would be a record of something
    # unfinished.
    _record_provenance(job_id, provenance)

    shortfall = provenance.get('shortfall_by_stage') or {}
    log.info(
        f"[generation] job {job_id} complete: {len(rows)} queries"
        + (f" (short by stage: {shortfall})" if shortfall else "")
    )


def process_generation_jobs():
    """
    Polls soa_query_generation_jobs for status='pending', processes one job
    per call (one at a time to avoid OpenAI rate limits and DB contention
    with cycle processing).
    """
    import os

    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, study_type, study_name, description, target_count,
                   organization_id, created_by,
                   study_pattern, retailer_names, allowed_categories,
                   stage_targets, rotate_named_retailer,
                   naming_rule_enabled, personas, specificity_mode,
                   syndicated_merchant, tier_config
            FROM soa_query_generation_jobs
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
        """)).fetchone()

        if not row:
            return

        (job_id, study_type, study_name, description, target_count,
         organization_id, created_by,
         study_pattern, retailer_names, allowed_categories,
         stage_targets, rotate_named_retailer,
         naming_rule_enabled, personas, specificity_mode,
         syndicated_merchant, tier_config) = row

        # Mark running
        conn.execute(text("""
            UPDATE soa_query_generation_jobs
            SET status = 'running', updated_at = NOW()
            WHERE id = :id
        """), {"id": job_id})
        conn.commit()

    log.info(
        f"[generation] Starting job {job_id} for '{study_type}' "
        f"({target_count} queries)"
    )

    from generation.query_generator import generate_query_batch, dedupe_exact, BATCH_SIZE

    api_key = os.environ.get("OPEN_AI_API_KEY")
    if not api_key:
        _mark_generation_failed(job_id, "OPEN_AI_API_KEY not set")
        return

    # study_pattern is the discriminator, not a convenience: it is NULL
    # exactly when the job was queued before the study brief existed (or
    # by a client that sends only name/description/target_count). Such a
    # job is generated the way it would have been the day it was queued —
    # a pending row must not be retroactively reinterpreted under rules
    # nobody agreed to when they submitted it. There is also no honest
    # default available: every study_pattern value changes the coding
    # rubric, so picking one on the job's behalf would silently decide
    # something the requester never said.
    # A regenerate request reuses this job row rather than creating a
    # second one (study_type is unique on this table), carrying its
    # marker inside tier_config — which the rebuild consumes by writing
    # the resolved config back without it.
    parsed_tier_config = _job_json(tier_config)
    regenerate = (parsed_tier_config or {}).get("regenerate")
    if regenerate and syndicated_merchant:
        _run_regeneration(
            job_id=job_id,
            study_type=study_type,
            syndicated_merchant=syndicated_merchant,
            tier_config=parsed_tier_config,
            regenerate=regenerate,
            organization_id=organization_id,
            created_by=created_by,
            api_key=api_key,
            study_name=study_name,
            description=description,
            study_pattern=study_pattern,
            allowed_categories=_job_json(allowed_categories),
            stage_targets=_job_json(stage_targets),
            personas=_job_json(personas),
        )
        return

    if study_pattern:
        _run_briefed_generation(
            job_id=job_id,
            study_type=study_type,
            study_name=study_name,
            description=description,
            target_count=target_count,
            organization_id=organization_id,
            created_by=created_by,
            study_pattern=study_pattern,
            retailer_names=_job_json(retailer_names),
            allowed_categories=_job_json(allowed_categories),
            stage_targets=_job_json(stage_targets),
            rotate_named_retailer=(
                True if rotate_named_retailer is None else bool(rotate_named_retailer)
            ),
            naming_rule_enabled=(
                True if naming_rule_enabled is None else bool(naming_rule_enabled)
            ),
            personas=_job_json(personas),
            specificity_mode=specificity_mode,
            api_key=api_key,
            syndicated_merchant=syndicated_merchant,
            tier_config=_job_json(tier_config),
        )
        return

    created_count = 0
    generated_texts = []
    # Every row already inserted, kept so exact-duplicate removal can span
    # batches. Duplicates are a CROSS-batch phenomenon here — the model
    # only ever sees one batch at a time — so deduping inside
    # generate_query_batch would catch almost none of them. This is the
    # accumulation point, so this is where it belongs.
    accepted_rows = []
    duplicate_drops = []
    # A batch that contributes nothing new after dedupe makes no progress
    # toward target_count, and the loop condition is created_count-based:
    # without this guard an unlucky study could spin on OpenAI forever.
    stalled_batches = 0

    try:
        while created_count < target_count:
            remaining = target_count - created_count
            batch_size = min(BATCH_SIZE, remaining)

            rows, det_reason = generate_query_batch(
                study_name=study_name,
                description=description,
                batch_size=batch_size,
                already_generated=generated_texts,
                api_key=api_key,
            )

            if det_reason:
                # Every row in this batch failed validation on the same
                # field(s) — a prompt/schema mismatch, not one-off model
                # noise. Retrying would reproduce the identical 100%
                # failure, so fail the job now instead of wasting a
                # second OpenAI call and eventually "completing" with 0
                # queries (see the created_count==0 guard below, which
                # this path skips entirely by returning early).
                log.error(f"[generation] job {job_id}: {det_reason}")
                _mark_generation_failed(job_id, det_reason)
                return

            if not rows:
                log.warning(
                    f"[generation] job {job_id}: batch returned 0 valid rows — retrying once"
                )
                rows, det_reason = generate_query_batch(
                    study_name=study_name,
                    description=description,
                    batch_size=batch_size,
                    already_generated=generated_texts,
                    api_key=api_key,
                )
                if det_reason:
                    log.error(f"[generation] job {job_id}: {det_reason}")
                    _mark_generation_failed(job_id, det_reason)
                    return
                if not rows:
                    log.error(
                        f"[generation] job {job_id}: second attempt also 0 rows — stopping early"
                    )
                    break

            # Dedupe the accumulated set, not this batch in isolation.
            # accepted_rows is already duplicate-free, so it survives
            # intact and everything after it is what this batch actually
            # contributes.
            # accepted_rows is duplicate-free by construction, so every
            # row dedupe_exact drops from the concatenation came from
            # this batch — either a repeat of an earlier batch or a
            # repeat within this one.
            survivors, batch_drops = dedupe_exact(accepted_rows + rows)
            new_rows = survivors[len(accepted_rows):]

            if batch_drops:
                duplicate_drops.extend(batch_drops)
                log.info(
                    f"[generation] job {job_id}: dropped {len(batch_drops)} "
                    f"exact duplicate(s) from this batch"
                )

            if not new_rows:
                stalled_batches += 1
                log.warning(
                    f"[generation] job {job_id}: batch was entirely duplicates "
                    f"({stalled_batches} in a row)"
                )
                if stalled_batches >= 2:
                    log.error(
                        f"[generation] job {job_id}: two consecutive all-duplicate "
                        f"batches — stopping early with {created_count} queries"
                    )
                    break
                continue

            stalled_batches = 0
            _insert_generated_rows(new_rows, study_type, organization_id, created_by)
            accepted_rows.extend(new_rows)
            created_count += len(new_rows)
            generated_texts.extend(r['query_text'] for r in new_rows)

            # Update progress incrementally
            with engine.connect() as conn:
                conn.execute(text("""
                    UPDATE soa_query_generation_jobs
                    SET created_count = :cc, updated_at = NOW()
                    WHERE id = :id
                """), {"cc": created_count, "id": job_id})
                conn.commit()

            log.info(f"[generation] job {job_id}: {created_count}/{target_count}")

        if created_count == 0:
            # Reached here only via the "stopping early" break above (no
            # deterministic reason, but two attempts still produced
            # nothing usable) — an honest failure, never a "complete: 0
            # queries" the frontend would otherwise render as a normal,
            # if oddly empty, study.
            _mark_generation_failed(
                job_id, "Generation produced no usable queries after retrying.",
            )
            return

        # Mark complete
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE soa_query_generation_jobs
                SET status = 'complete', updated_at = NOW()
                WHERE id = :id
            """), {"id": job_id})
            conn.commit()

        log.info(
            f"[generation] job {job_id} complete: {created_count} queries"
            + (
                f" ({len(duplicate_drops)} exact duplicate(s) dropped)"
                if duplicate_drops else ""
            )
        )

    except Exception as e:
        log.exception(f"[generation] job {job_id} failed")
        _mark_generation_failed(job_id, str(e))


LITE_CREATED_BY = "soa-lite"


def _mark_lite_failed(request_id: int, error: str):
    """
    Stage 14 (W3): never raises. This is the last-resort failure path —
    a worker that can crash while recording a crash is the same bug one
    level down — so any failure here (DB unreachable, etc.) is caught
    and logged at CRITICAL rather than propagating.
    """
    try:
        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE soa_lite_requests
                SET status = :status,
                    error_message = :err,
                    updated_at = NOW()
                WHERE id = :id
            """), {"status": LITE_STATUS_FAILED, "id": request_id, "err": error[:1000]})
            conn.commit()
        lite_events.emit_state(request_id, "failed")
        log.error(f"[lite] request {request_id} failed: {error}")
    except Exception:
        log.critical(
            f"[lite] request {request_id}: FAILED TO RECORD FAILURE (original error: {error!r}) — giving up",
            exc_info=True,
        )


def process_lite_requests():
    """
    Polls soa_lite_requests for status='pending', processes one row per
    call — same one-at-a-time, oldest-first semantics as
    process_generation_jobs (avoids OpenAI rate limits and DB contention
    with cycle processing).

    State machine: pending -> identifying_competitors -> generating ->
    running. The cycle this creates is picked up and executed by the
    existing planned-cycle poll unchanged (get_next_planned_cycle/
    execute_cycle) — running -> complete/failed is mirrored onto this row
    by _sweep_lite_completions once the cycle finishes, not written here.

    Stage 14 (W1): the ENTIRE per-request body — including the very
    first status write — runs inside one try/except, so ANY failure
    marks this row 'failed' via _mark_lite_failed (its own, fresh
    connection) rather than leaving it 'pending'. A row stuck 'pending'
    poisons every future poll: the SELECT below is oldest-first with no
    offset, so it re-picks the SAME row forever, permanently blocking
    every request submitted after it. This is exactly what happened
    when the 'identifying_competitors' status write (added ahead of
    the DB constraint that allowed it) landed outside this try block —
    see LITE_STATUSES in soa_shared/models/soa_models.py.
    """
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT id, token, brand_name, competitor_names, store_url
            FROM soa_lite_requests
            WHERE status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1
        """)).fetchone()

    if not row:
        return

    request_id, token, brand_name, competitor_names, store_url = row

    try:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE soa_lite_requests
                SET status = :status, updated_at = NOW()
                WHERE id = :id
            """), {"status": LITE_STATUS_IDENTIFYING_COMPETITORS, "id": request_id})

        lite_events.emit_state(request_id, "running")
        log.info(f"[lite] Starting request {request_id} for brand '{brand_name}'")

        # JSON columns normally come back already-decoded (psycopg2 parses
        # json/jsonb natively); defensively handle a driver that returns the
        # raw string instead, same idiom as cycles.py::_row_to_cycle.
        if isinstance(competitor_names, str):
            competitor_names = json.loads(competitor_names)
        manual_competitor_names = competitor_names or []
        token8 = token[:8]
        study_type = f"lite-{token8}"
        cycle_code = f"lite-{token8}"

        api_key = os.environ.get("OPEN_AI_API_KEY")
        if not api_key:
            raise RuntimeError("OPEN_AI_API_KEY not set")

        from soa_shared.database import session_factory
        from soa_shared.org_helpers import get_or_create_leadgen_org
        from soa_shared.entity_helpers import get_or_create_entity_by_slug
        from soa_shared.cycle_creation import create_cycle_with_comparison_set
        from generation.query_generator import generate_lite_queries
        from generation.competitor_generator import generate_competitors, select_competitors

        with session_factory() as session:
            org_id = get_or_create_leadgen_org(session)
            session.commit()

        # a2. Stage 13: auto-generate up to 5 competitors, topping up
        # whatever the visitor named manually. generate_competitors()
        # never raises (rule 4's never-throw philosophy extended here —
        # this is a lookup, not something that may block the run), so
        # this always proceeds to a well-defined competitor_names/
        # competitor_source pair, even on total API failure ([] in ->
        # 'manual' or 'none' out). Persisted in its own transaction,
        # BEFORE entity resolution/query generation/cycle queueing below
        # — so a crash partway through the rest of this function still
        # leaves the generated set on the row rather than losing it to a
        # future re-generation.
        lite_events.emit_log(request_id, lite_events.TASK_COMPETITORS, "identifying your closest rivals…")
        candidates = generate_competitors(brand_name, api_key, store_url=store_url)
        competitor_candidates, competitor_source = select_competitors(
            manual_competitor_names, candidates, brand_name,
        )
        # Logo feature, Part 2a: soa_lite_requests.competitor_names stays a
        # plain list of name strings (its existing, documented shape —
        # other readers of this column expect that) — domain rides
        # separately, on soa_entities.website_url, via entity resolution
        # below, where it's actually needed (BrandLogo's fallback chain).
        competitor_names = [c["name"] for c in competitor_candidates]

        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE soa_lite_requests
                SET competitor_names = :names,
                    competitor_source = :source,
                    status = :status,
                    updated_at = NOW()
                WHERE id = :id
            """), {
                "names":  json.dumps(competitor_names),
                "source": competitor_source,
                "status": LITE_STATUS_GENERATING,
                "id":     request_id,
            })

        log.info(
            f"[lite] request {request_id}: competitors={competitor_names} source={competitor_source}"
        )
        if competitor_names:
            lite_events.emit_done(
                request_id, lite_events.TASK_COMPETITORS,
                f"{len(competitor_names)} competitors found", chips=competitor_names,
            )
        else:
            lite_events.emit_done(
                request_id, lite_events.TASK_COMPETITORS,
                "Running solo — no close rivals identified",
            )

        # b. Resolve entities — upsert-by-slug so repeat submissions of the
        # same brand reuse the existing soa_entities row. Logo feature,
        # Part 2a: website_url is threaded through on creation — store_url
        # for the brand's own entity (already in scope from the request),
        # candidate.domain for each competitor (None when the model
        # wasn't confident, same honest-null discipline as everywhere
        # else) — this is what SoAIndex's logo avatars ultimately read
        # (public_lite.py joins soa_entities.website_url back in).
        with engine.begin() as conn:
            brand_entity_id = get_or_create_entity_by_slug(conn, brand_name, "brand", website_url=store_url)
            competitor_entity_ids = [
                get_or_create_entity_by_slug(conn, c["name"], "brand", website_url=c["domain"])
                for c in competitor_candidates
            ]
            conn.execute(text("""
                UPDATE soa_lite_requests
                SET brand_entity_id = :bid,
                    competitor_entity_ids = :cids,
                    updated_at = NOW()
                WHERE id = :id
            """), {
                "bid":  brand_entity_id,
                "cids": json.dumps(competitor_entity_ids),
                "id":   request_id,
            })

        # c. Generate the fixed LITE_QUERY_COUNT-query study and insert into soa_queries.
        # _insert_generated_rows' query_code prefixing (first 3 chars up to
        # the first underscore) naturally yields 'LIT' for study_type
        # 'lite-{token8}' — no lite-specific insert logic needed.
        lite_events.emit_log(request_id, lite_events.TASK_QUERIES, "writing your shopper questions…")
        rows = generate_lite_queries(brand_name, competitor_names, api_key)

        with engine.connect() as conn:
            conn.execute(text("""
                UPDATE soa_lite_requests
                SET study_type = :st, updated_at = NOW()
                WHERE id = :id
            """), {"st": study_type, "id": request_id})
            conn.commit()

        _insert_generated_rows(rows, study_type, org_id, LITE_CREATED_BY)

        # d. Create the cycle + comparison set (brand=M001 primary,
        # competitors M002.. competitor) via the helper shared with
        # apps/api/app/routers/cycles.py::create_cycle.
        comparison_set = [
            {"entity_id": brand_entity_id, "comparison_code": "M001", "role": "primary"},
        ] + [
            {"entity_id": eid, "comparison_code": f"M{i + 2:03d}", "role": "competitor"}
            for i, eid in enumerate(competitor_entity_ids)
        ]

        with engine.begin() as conn:
            cycle_id, _ = create_cycle_with_comparison_set(
                conn,
                cycle_code=cycle_code,
                study_type=study_type,
                study_pattern="brand_vs_brand",
                cycle_mode="query",
                truecost_tiers=None,
                total_runs_planned=len(rows),  # 1 platform x 1 run/query
                start_date=datetime.now(timezone.utc).date(),
                platforms=json.dumps(["chatgpt"]),
                runs_per_query=1,
                organization_id=org_id,
                created_by=LITE_CREATED_BY,
                notes=None,
                comparison_set=comparison_set,
            )

            conn.execute(text("""
                UPDATE soa_lite_requests
                SET cycle_id = :cid, status = :status, updated_at = NOW()
                WHERE id = :id
            """), {"cid": cycle_id, "status": LITE_STATUS_RUNNING, "id": request_id})

            # Created atomically with the running transition — not in a
            # separate transaction — so there is no window where this
            # lite request is 'running' but has no scan row for
            # _sweep_lite_completions to join against.
            # cycle_id (Phase 1's soa_cycle_scans linkage) is stamped here
            # too, not just backfilled once for pre-existing rows — every
            # lite-owned scan row going forward carries both FKs, which
            # is what lets Phase 3's cycle-scoring service key entirely
            # off cycle_id without a lite_request_id fallback.
            conn.execute(text("""
                INSERT INTO soa_lite_scan_results (lite_request_id, cycle_id, input_url, status, updated_at)
                VALUES (:rid, :cid, :url, 'running', NOW())
            """), {"rid": request_id, "cid": cycle_id, "url": store_url})

        log.info(f"[lite] request {request_id}: cycle {cycle_code} queued (id={cycle_id})")

        # Runs after the cycle is queued so a slow/unreachable store never
        # delays the LLM path. Isolated in its own try/except: a bug here
        # must never flip this already-queued request to 'failed' via the
        # except below, which is for entity/query/cycle failures only
        # (rule 7 — the scan never blocks the report).
        fetch_probe_url = None
        fetch_probe_kind = None
        try:
            fetch_probe_url, fetch_probe_kind = _run_lite_scan(request_id, store_url, api_key)
        except Exception as scan_error:
            log.exception(f"[lite] request {request_id}: scan orchestration failed unexpectedly")
            # Crawl-failure alerting: this except is exactly the shape
            # the signing-import crash took, and it stayed silent for a
            # deploy cycle. ops_alert never raises, so the isolation
            # this block exists to provide is unchanged.
            ops_alert.send_crawl_failure_alert(
                ops_alert.FAILURE_CLASS_ORCHESTRATION,
                request_id=request_id, token=token, store_url=store_url,
                error=f"{type(scan_error).__name__}: {scan_error}",
            )

        # Stage 16 (Part 4): a single out-of-band OpenAI call, isolated
        # exactly like the scan above — a bug here must never flip this
        # already-queued request to 'failed'. Independent of store_url
        # (asks about the brand generally, not the crawl), so it runs
        # unconditionally.
        try:
            _run_membership_probe(request_id, brand_name, store_url, api_key)
        except Exception:
            log.exception(f"[lite] request {request_id}: membership probe failed unexpectedly")

        # Part 5 (R1): same isolation as the membership probe above — a
        # bug here must never flip this already-queued request to
        # 'failed'. Independent of store_url/scan outcome (asks about
        # the brand generally), so it runs unconditionally.
        try:
            _run_revenue_probe(request_id, brand_name, store_url, api_key)
        except Exception:
            log.exception(f"[lite] request {request_id}: revenue probe failed unexpectedly")

        # Part 2 (P1): same isolation as the probes above. Unlike
        # membership/revenue (which ask about the brand generally),
        # this probe needs an actual URL to open — run_scan always
        # returns one once discovery got far enough (see engine.py's
        # _choose_fetch_probe_url ladder), so it's skipped only when
        # there was never a store_url to scan at all.
        if fetch_probe_url:
            try:
                _run_fetch_probe(request_id, fetch_probe_url, fetch_probe_kind, api_key)
            except Exception:
                log.exception(f"[lite] request {request_id}: fetch probe failed unexpectedly")

    except Exception as e:
        log.exception(f"[lite] request {request_id} failed")
        _mark_lite_failed(request_id, str(e))


# ─── Scan reuse: don't re-crawl a store we just read ─────────────────────
#
# Justfoodfordogs was audited six times in one week; Petco, Vans, Warby
# Parker, NAPA and AutoAccessoriesGarage twice each. Every repeat
# re-crawled the same store and got the same answer — a dozen fetches
# and, on a walled site, minutes of wall clock, spent re-establishing a
# fact we already had on file.
#
# Scoped deliberately narrowly:
#   - Same canonical host, not the same URL string. www/apex, http/https
#     and a trailing slash are the same store.
#   - Same SCORER_VERSION only. A row scored under an older rubric is
#     not this run's answer, and copying it would silently mix versions.
#   - status in ('complete','blocked') only. A 'failed' row is exactly
#     the case worth retrying — reusing one would make a transient
#     outage permanent for the whole window.
#   - Inside SCAN_REUSE_WINDOW_HOURS. Past that, the store may genuinely
#     have changed.
#
# Only the CRAWL is reused. The membership and revenue probes are cheap
# brand-level LLM calls that don't touch the store, and they still run.
SCAN_REUSE_WINDOW_HOURS = _env_int("SCAN_REUSE_WINDOW_HOURS", 72)
SCAN_REUSE_STATUSES = ("complete", "blocked")


def _canonical_host(url: str | None) -> str | None:
    """The host two URLs have to share to be the same store: scheme
    stripped, leading 'www.' stripped, lowercased, no trailing dot or
    port. None for anything that isn't recognizably a hostname — which
    simply means no reuse, the safe direction. A subdomain is NOT
    folded in: shop.example.com is a different storefront from
    example.com and routinely has a different catalog."""
    if not url:
        return None
    try:
        value = url.strip()
        if "://" not in value:
            value = f"https://{value}"
        host = (urlparse(value).hostname or "").strip().lower().rstrip(".")
        # urlparse is happy to call free text a hostname. A host with no
        # dot or with whitespace in it could never match a real store's,
        # but returning it would put garbage in a log line and an event.
        if not host or "." not in host or any(c.isspace() for c in host):
            return None
        if host.startswith("www."):
            host = host[4:]
        return host or None
    except Exception:
        return None


def _find_reusable_scan(conn, store_url: str, request_id: int):
    """The most recent reusable scan row for this store, or None. Reads
    only — the caller does the copy. Never raises: any failure here
    degrades to "no reuse", which is just an ordinary crawl."""
    host = _canonical_host(store_url)
    if not host:
        return None
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=SCAN_REUSE_WINDOW_HOURS)
        rows = conn.execute(text("""
            SELECT id, input_url, status, total_score, integrity_capped,
                   dimensions, pages_fetched, fetch_probe, updated_at
            FROM soa_lite_scan_results
            WHERE status IN :statuses
              AND input_url IS NOT NULL
              AND updated_at > :cutoff
              AND lite_request_id IS DISTINCT FROM :rid
            ORDER BY updated_at DESC
            LIMIT 50
        """).bindparams(bindparam("statuses", expanding=True)),
            {"statuses": list(SCAN_REUSE_STATUSES), "cutoff": cutoff, "rid": request_id},
        ).fetchall()
    except Exception:
        log.exception(f"[lite] request {request_id}: reuse lookup failed — falling back to a fresh crawl")
        return None

    # Host matching happens here, not in SQL: input_url is stored as
    # given (scheme, www, sometimes a path), and normalizing it in SQL
    # across Postgres and SQLite would be a per-dialect string mess for
    # a 50-row scan.
    for row in rows:
        if _canonical_host(row[1]) != host:
            continue
        # The window is re-checked here, not left to the SQL predicate
        # alone: the SQL one narrows the scan on Postgres, but
        # updated_at comes back as text on SQLite and a text-vs-
        # timestamp comparison there is not the check it looks like.
        # This one reads the value the same way every other timestamp in
        # this worker is read.
        updated = _as_utc_datetime(row[8])
        if updated is None or updated < cutoff:
            continue
        dimensions = _decode_json_field(row[5], {}) or {}
        if dimensions.get("scorer_version") != SCORER_VERSION:
            continue
        # Never reuse a reuse: chaining would let one crawl's data
        # outlive its own window indefinitely.
        if dimensions.get("reused_from_scan_id"):
            continue
        return row
    return None


def _reuse_recent_scan(request_id: int, store_url: str) -> tuple | None:
    """Copies a recent scan of the same store onto this request's row
    and returns (fetch_probe_url, fetch_probe_kind) for the caller, or
    None when there was nothing to reuse (the ordinary path).

    The copied row is stamped with reused_from_scan_id/reused_at so the
    reuse is legible in the admin drawer and after the fact — this
    should never be something you have to infer from timing."""
    with engine.connect() as conn:
        source = _find_reusable_scan(conn, store_url, request_id)
    if source is None:
        return None

    (source_id, _source_url, status, total_score, integrity_capped,
     dimensions_raw, pages_fetched_raw, fetch_probe_raw, updated_at) = source

    dimensions = _decode_json_field(dimensions_raw, {}) or {}
    dimensions["reused_from_scan_id"] = source_id
    dimensions["reused_at"] = datetime.now(timezone.utc).isoformat()
    pages_fetched = _decode_json_field(pages_fetched_raw, []) or []
    fetch_probe = _decode_json_field(fetch_probe_raw, None)

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE soa_lite_scan_results
            SET status = :status,
                total_score = :total_score,
                integrity_capped = :integrity_capped,
                dimensions = :dimensions,
                pages_fetched = :pages_fetched,
                fetch_probe = :fetch_probe,
                error = NULL,
                updated_at = NOW()
            WHERE lite_request_id = :rid
        """), {
            "rid": request_id,
            "status": status,
            "total_score": total_score,
            "integrity_capped": bool(integrity_capped) if integrity_capped is not None else False,
            "dimensions": json.dumps(dimensions),
            "pages_fetched": json.dumps(pages_fetched),
            "fetch_probe": json.dumps(fetch_probe) if fetch_probe is not None else None,
        })

    host = _canonical_host(store_url)
    age_hours = _reuse_age_hours(updated_at)
    log.info(
        f"[lite] request {request_id}: reusing scan #{source_id} of {host} "
        f"({age_hours}h old, status={status}) — skipping the crawl"
    )
    lite_events.emit_done(
        request_id, lite_events.TASK_CRAWL,
        f"Reusing our read of {host} from {age_hours} hour{'' if age_hours == 1 else 's'} ago",
    )
    # The fetch probe was copied with the rest, so re-running it would
    # overwrite a good answer with a second OpenAI call for nothing.
    return None, None


def _reuse_age_hours(updated_at) -> int:
    """Whole hours since the reused scan ran, floored at 1 — "0 hours
    ago" reads as a bug, and the reuse window is measured in hours
    anyway. Never raises."""
    try:
        when = _as_utc_datetime(updated_at)
        if when is None:
            return 1
        delta = datetime.now(timezone.utc) - when
        return max(1, int(delta.total_seconds() // 3600))
    except Exception:
        return 1


def _run_lite_scan(request_id: int, store_url: str | None, api_key: str | None = None) -> tuple:
    """
    Runs the Agent Scan for this lite request and updates the
    soa_lite_scan_results row already created (status='running') in the
    same transaction that queued the cycle — see process_lite_requests.
    Returns (url, kind) the fetch probe (Part 2) should ask ChatGPT to
    open (result.fetch_probe_url/fetch_probe_kind — N4), or (None, None)
    when there was no scan to run at all.

    store_url is None -> 'skipped': guessing a domain server-side risks
    scanning the wrong store, which is worse than no scan at all. The
    API/widget owns collecting a real URL from the visitor.

    run_scan itself never raises (scan/engine.py) — it always returns a
    ScanResult with a terminal or 'skipped' status. What CAN still raise
    is getting there at all: `from scan.engine import run_scan` runs the
    whole scan/ package's import chain (fetcher -> signing -> ...) for
    the first time in this process, and a bug in module-level code
    anywhere in that chain (production outage, 2026-09-22 — see
    scan/signing.py's module docstring) raises before run_scan is even
    called. That path is now caught here too, so this function still
    only ever writes one final update to the scan row — 'failed' with
    an honest degraded-dims record, never leaving it 'running' forever.

    api_key (rescue session, Part 3c): threaded down to run_scan's
    last-resort LLM-assisted discovery tier ONLY — gates behind
    LLM_DISCOVERY_FALLBACK there; a missing/None key just means that
    one tier never fires, same as before this parameter existed.
    """
    if not store_url:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE soa_lite_scan_results
                SET status = 'skipped', updated_at = NOW()
                WHERE lite_request_id = :rid
            """), {"rid": request_id})
        log.info(f"[lite] request {request_id}: no store_url — audit skipped")
        lite_events.emit_done(
            request_id, lite_events.TASK_CRAWL,
            "No store URL was provided — audit skipped",
        )
        return None, None

    # Emitted BEFORE the import below, not after (production outage,
    # 2026-09-22): the incident this guards against was exactly an
    # import-time raise, which — when this log line came after the
    # import — meant a broken worker left NO crawl task event at all,
    # and the status page's progress UI sat on nothing rather than ever
    # resolving. Emitting first means the visitor always sees "reading
    # your store…" show up, whatever happens next.
    lite_events.emit_log(request_id, lite_events.TASK_CRAWL, f"reading {store_url}…")

    # Scan reuse: checked after the crawl task's event exists (so the
    # status page always shows the task, whichever way it resolves) and
    # before any network work. Isolated — a bug in reuse must never cost
    # this request its crawl, so anything unexpected falls through to
    # the ordinary path below.
    try:
        reused = _reuse_recent_scan(request_id, store_url)
        if reused is not None:
            return reused
    except Exception:
        log.exception(f"[lite] request {request_id}: scan reuse failed — crawling instead")

    try:
        from scan.engine import run_scan
        result = run_scan(store_url, api_key=api_key)
    except Exception as e:
        log.exception(f"[lite] request {request_id}: scan orchestration raised before completing — marking failed")
        degraded_dims = build_degraded_dimensions(DEGRADED_REASON_ORCHESTRATION_FAILED)
        degraded_dims["degraded_reason"] = "orchestration_failed"
        error_text = f"{type(e).__name__}: {e}"[:500]
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE soa_lite_scan_results
                SET status = 'failed',
                    dimensions = :dimensions,
                    pages_fetched = :pages_fetched,
                    error = :error,
                    updated_at = NOW()
                WHERE lite_request_id = :rid
            """), {
                "rid": request_id,
                "dimensions": json.dumps(degraded_dims),
                "pages_fetched": json.dumps([]),
                "error": error_text,
            })
        lite_events.emit_done(
            request_id, lite_events.TASK_CRAWL,
            "Couldn't read your store this run — see your report for details",
        )
        return None, None

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE soa_lite_scan_results
            SET status = :status,
                total_score = :total_score,
                integrity_capped = :integrity_capped,
                dimensions = :dimensions,
                pages_fetched = :pages_fetched,
                error = :error,
                updated_at = NOW()
            WHERE lite_request_id = :rid
        """), {
            "rid":               request_id,
            "status":            result.status,
            "total_score":       result.total_score,
            "integrity_capped":  result.integrity_capped,
            "dimensions":        json.dumps(result.dimensions),
            "pages_fetched":     json.dumps(result.pages_fetched),
            "error":             result.error,
        })

    log.info(f"[lite] request {request_id}: scan {result.status} (score={result.total_score})")
    _emit_crawl_retry_moments(request_id, result)
    _emit_llm_discovery_moment(request_id, result)
    lite_events.emit_done(request_id, lite_events.TASK_CRAWL, _crawl_done_text(result))
    return result.fetch_probe_url, result.fetch_probe_kind


# ─── Full Analysis coexistence, Phase 2: standalone cycle crawls ──────────
#
# apps/api/app/routers/full_analysis.py::launch_crawl writes a 'pending'
# soa_lite_scan_results row keyed by cycle_id with NO lite_request_id
# (Phase 1's soa_cycle_scans linkage — cycle_id nullable, then
# lite_request_id relaxed to nullable too, see migration 8c31844a4171).
# This is the pipeline-side stage that actually runs those — same
# run_scan() engine _run_lite_scan already uses, just addressed by the
# scan row's own id instead of lite_request_id, since there is no lite
# request to key off for a standalone Full Analysis cycle. Never touches
# a lite-owned row (those are always claimed by _run_lite_scan instead,
# via process_lite_requests) — the WHERE clause below is scoped to
# lite_request_id IS NULL specifically so the two paths can never race
# on the same row.

def _run_cycle_scan(scan_id: int, store_url: str, api_key: str | None) -> None:
    """
    Runs the Agent Scan for one standalone (non-lite) cycle crawl and
    writes the result back onto its own soa_lite_scan_results row by id.
    run_scan() never raises (scan/engine.py) — always returns a
    ScanResult with a terminal or 'skipped' status. What CAN still raise
    is getting there at all (see _run_lite_scan's docstring — same
    scan/ import-chain risk, same fix here): process_cycle_crawls calls
    this with NO surrounding try/except, so leaving that path unguarded
    would crash the whole poll iteration instead of just failing one
    scan row.
    """
    try:
        from scan.engine import run_scan
        result = run_scan(store_url, api_key=api_key)
    except Exception as e:
        log.exception(f"[cycle-crawl] scan {scan_id}: orchestration raised before completing — marking failed")
        degraded_dims = build_degraded_dimensions(DEGRADED_REASON_ORCHESTRATION_FAILED)
        degraded_dims["degraded_reason"] = "orchestration_failed"
        error_text = f"{type(e).__name__}: {e}"[:500]
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE soa_lite_scan_results
                SET status = 'failed',
                    dimensions = :dimensions,
                    pages_fetched = :pages_fetched,
                    error = :error,
                    updated_at = NOW()
                WHERE id = :scan_id
            """), {
                "scan_id": scan_id,
                "dimensions": json.dumps(degraded_dims),
                "pages_fetched": json.dumps([]),
                "error": error_text,
            })
        return

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE soa_lite_scan_results
            SET status = :status,
                total_score = :total_score,
                integrity_capped = :integrity_capped,
                dimensions = :dimensions,
                pages_fetched = :pages_fetched,
                error = :error,
                updated_at = NOW()
            WHERE id = :scan_id
        """), {
            "scan_id":          scan_id,
            "status":           result.status,
            "total_score":      result.total_score,
            "integrity_capped": result.integrity_capped,
            "dimensions":       json.dumps(result.dimensions),
            "pages_fetched":    json.dumps(result.pages_fetched),
            "error":            result.error,
        })
    log.info(f"[cycle-crawl] scan {scan_id}: {result.status} (score={result.total_score})")


def _run_cycle_revenue_probe(scan_id: int, cycle_id: int, store_url: str, api_key: str) -> None:
    """
    Cycle-level counterpart to _run_revenue_probe: a standalone Full
    Analysis cycle's own scan row (lite_request_id NULL) never goes
    through process_lite_requests, so nothing ever populated its
    revenue_probe — the exposure widget's revenue seed would silently
    stay null for every non-continuation cycle forever. Same never-
    throw isolation as the lite probes (caller wraps this in its own
    try/except); the only new step is resolving a brand_name, since
    this path has no soa_lite_requests row to read one off.

    Continuation cycles skip this entirely (see process_cycle_crawls)
    — the audit's own scan row already has a revenue_probe, and
    app/routers/full_analysis.py falls back to reading it directly
    rather than paying for a second, redundant OpenAI call.
    """
    from generation.revenue_probe import probe_revenue

    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT e.name FROM soa_cycle_entities ce
            JOIN soa_entities e ON e.id = ce.entity_id
            WHERE ce.cycle_id = :cid AND ce.role = 'primary'
        """), {"cid": cycle_id}).fetchone()
    if not row:
        return
    brand_name = row[0]

    result = probe_revenue(brand_name, api_key, store_url=store_url)

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE soa_lite_scan_results SET revenue_probe = :probe, updated_at = NOW()
            WHERE id = :scan_id
        """), {"scan_id": scan_id, "probe": json.dumps(result)})

    log.info(f"[cycle-crawl] scan {scan_id}: revenue probe result={result['annual_revenue_usd']}")


def process_cycle_crawls() -> None:
    """
    Picks up one pending standalone cycle crawl per poll iteration —
    same "fetch the oldest, one at a time" discipline as
    get_next_planned_cycle, not a batch. Flips status to 'running'
    before the (slow) scan call so a second poll iteration during a
    long-running crawl never re-picks the same row.
    """
    api_key = os.environ.get("OPEN_AI_API_KEY")
    with engine.connect() as conn:
        row = conn.execute(text("""
            SELECT sr.id, sr.input_url, sr.cycle_id, c.source_lite_request_id
            FROM soa_lite_scan_results sr
            JOIN soa_cycles c ON c.id = sr.cycle_id
            WHERE sr.status = 'pending' AND sr.lite_request_id IS NULL AND sr.cycle_id IS NOT NULL
            ORDER BY sr.id
            LIMIT 1
        """)).fetchone()

    if not row:
        return

    scan_id, store_url, cycle_id, source_lite_request_id = row
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE soa_lite_scan_results SET status = 'running', updated_at = NOW()
            WHERE id = :scan_id
        """), {"scan_id": scan_id})

    if not store_url:
        with engine.begin() as conn:
            conn.execute(text("""
                UPDATE soa_lite_scan_results SET status = 'skipped', updated_at = NOW()
                WHERE id = :scan_id
            """), {"scan_id": scan_id})
        log.info(f"[cycle-crawl] scan {scan_id}: no store_url — skipped")
        return

    _run_cycle_scan(scan_id, store_url, api_key)

    # Revenue probe (exposure widget's seed): skipped for a continuation
    # cycle — the audit's own scan row already carries one, and
    # app/routers/full_analysis.py reads it directly rather than paying
    # for a second, redundant OpenAI call for the same brand. Isolated
    # exactly like every lite-side probe — a failure here must never
    # affect the crawl result already written above.
    if not source_lite_request_id and api_key:
        try:
            _run_cycle_revenue_probe(scan_id, cycle_id, store_url, api_key)
        except Exception:
            log.exception(f"[cycle-crawl] scan {scan_id}: revenue probe failed unexpectedly")


def _emit_crawl_retry_moments(request_id: int, result) -> None:
    """
    Mirrors the crawl's politeness-ladder retries into the console. A4
    (fetch resilience)'s per-page attempts/retry_after_seen data
    (scan/engine.py::_fetch_entry, carried on every result.pages_fetched
    row) already has this; fetcher.py's retry ladder itself has no
    request_id to narrate to and is a tight sleep/retry loop with no
    live callback hook, so this reconstructs the "interesting moments"
    from the finished scan result rather than streaming them mid-fetch.
    Bounded by MAX_PAGE_FETCHES (~12 pages/scan), so one line per
    retried page is never spammy.
    """
    for entry in result.pages_fetched or []:
        attempts = entry.get("attempts") or 1
        if attempts <= 1:
            continue
        retry_after = entry.get("retry_after_seen")
        cooloff = f", backed off {retry_after:.0f}s" if retry_after else ""
        outcome = "retry succeeded" if entry.get("status") == "fetched" else "still no luck"
        lite_events.emit_log(
            request_id, lite_events.TASK_CRAWL,
            f"{entry.get('url')} rate-limited us{cooloff} — {outcome}",
        )


def _emit_llm_discovery_moment(request_id: int, result) -> None:
    """
    Part 3c: the LLM-assisted discovery tier is deep inside the
    synchronous scan/discovery.py call this function already blocked on
    — there's no live callback to narrate from mid-scan, same
    constraint _emit_crawl_retry_moments documents above. Reconstructed
    here instead, from the finished sitemap_sampling trace's
    llm_discovery key (Part 4a) — present only when that tier actually
    ran (flag on, deterministic tiers all empty, site not blocked).
    """
    llm_trace = (result.dimensions or {}).get("sitemap_sampling", {}).get("llm_discovery")
    if not llm_trace:
        return
    lite_events.emit_log(
        request_id, lite_events.TASK_CRAWL,
        "asking ChatGPT where your product pages live…",
    )
    returned = llm_trace.get("urls_returned", 0)
    verified = llm_trace.get("urls_verified", 0)
    log.info(f"[lite] request {request_id}: LLM discovery returned {returned} URL(s), {verified} verified")


def _crawl_done_text(result) -> str:
    if result.status == 'complete':
        pages = len(result.pages_fetched or [])
        return f"{pages} pages read — catalog, loyalty, and protocol surfaces"
    if result.status == 'blocked':
        return "Your store blocked our reader — that itself is a finding"
    if result.status == 'failed':
        return "Couldn't finish reading your store this time"
    return "Audit did not complete"


def _run_membership_probe(request_id: int, brand_name: str, store_url: str | None, api_key: str):
    """
    Stage 16 (Part 4): runs the membership probe and writes its result
    onto the soa_lite_scan_results row already created (status='running'
    or later) when the cycle was queued — see process_lite_requests.

    probe_membership itself never raises (generation/membership_probe.py)
    — it always returns a well-defined {result, raw_evidence} dict, so
    this function only ever writes one update to the scan row.
    """
    from generation.membership_probe import probe_membership

    lite_events.emit_log(
        request_id, lite_events.TASK_PROBE_MEMBERSHIP,
        "asking whether a membership program exists…",
    )
    result = probe_membership(brand_name, api_key, store_url=store_url)

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE soa_lite_scan_results
            SET membership_probe = :probe, updated_at = NOW()
            WHERE lite_request_id = :rid
        """), {"rid": request_id, "probe": json.dumps(result)})

    log.info(f"[lite] request {request_id}: membership probe result={result['result']}")
    if result['result'] == 'yes':
        done_text = "Program found — Member Value will be scored"
    elif result['result'] == 'no':
        done_text = "No program found — scoring normalized"
    else:
        done_text = "Couldn't determine membership status"
    lite_events.emit_done(request_id, lite_events.TASK_PROBE_MEMBERSHIP, done_text)


def _run_revenue_probe(request_id: int, brand_name: str, store_url: str | None, api_key: str):
    """
    Part 5 (R1): runs the revenue probe and writes its result onto the
    soa_lite_scan_results row already created (status='running' or
    later) when the cycle was queued — same row/pattern as
    _run_membership_probe above.

    probe_revenue itself never raises (generation/revenue_probe.py) — it
    always returns a well-defined {annual_revenue_usd, basis, quote}
    dict, so this function only ever writes one update to the scan row.
    """
    from generation.revenue_probe import probe_revenue

    lite_events.emit_log(request_id, lite_events.TASK_PROBE_REVENUE, "estimating annual revenue…")
    result = probe_revenue(brand_name, api_key, store_url=store_url)

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE soa_lite_scan_results
            SET revenue_probe = :probe, updated_at = NOW()
            WHERE lite_request_id = :rid
        """), {"rid": request_id, "probe": json.dumps(result)})

    log.info(f"[lite] request {request_id}: revenue probe result={result['annual_revenue_usd']}")
    if result.get('annual_revenue_usd'):
        done_text = f"~${result['annual_revenue_usd']:,.0f}/yr estimated"
    else:
        done_text = "Couldn't estimate revenue"
    lite_events.emit_done(request_id, lite_events.TASK_PROBE_REVENUE, done_text)


def _run_fetch_probe(request_id: int, probe_url: str, probe_kind: str | None, api_key: str):
    """
    Part 2 (P1), kind-aware (N4): runs the fetch probe and writes its
    result onto the soa_lite_scan_results row already created when the
    cycle was queued — same row/pattern as _run_membership_probe/
    _run_revenue_probe above.

    probe_fetch itself never raises (generation/fetch_probe.py) — it
    always returns a well-defined {outcome, url, kind, price, quote,
    note} dict, so this function only ever writes one update to the
    scan row.
    """
    from generation.fetch_probe import probe_fetch

    log.info(f"[lite] request {request_id}: asking ChatGPT to open one of your product pages…")
    lite_events.emit_log(
        request_id, lite_events.TASK_PROBE_FETCH,
        "asking ChatGPT to open one of your product pages…",
    )
    result = probe_fetch(probe_url, api_key, kind=probe_kind)

    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE soa_lite_scan_results
            SET fetch_probe = :probe, updated_at = NOW()
            WHERE lite_request_id = :rid
        """), {"rid": request_id, "probe": json.dumps(result)})

    log.info(f"[lite] request {request_id}: fetch probe result={result['outcome']}")
    kind_phrase = "your homepage" if probe_kind == "store_root" else "your product page"
    outcome = result.get('outcome')
    if outcome == 'quoted_price':
        done_text = f"ChatGPT opened {kind_phrase} and quoted a price"
    elif outcome == 'opened_no_price':
        done_text = f"ChatGPT opened {kind_phrase} fine"
    elif outcome == 'could_not_access':
        done_text = f"ChatGPT couldn't access {kind_phrase} either"
    else:
        done_text = "Inconclusive"
    lite_events.emit_done(request_id, lite_events.TASK_PROBE_FETCH, done_text)


SCAN_TERMINAL_STATUSES = ("complete", "blocked", "failed", "skipped")
SCAN_TIMEOUT_MINUTES = 10


def _decode_json_field(value, default):
    """Same defensive str-vs-already-decoded idiom as competitor_names
    handling in process_lite_requests above."""
    if isinstance(value, str):
        return json.loads(value) if value else default
    return value if value is not None else default


def _terminal_run_state(cycle_status: str, scan_status: str, degraded_reason: str | None) -> str:
    """
    Part 1 (E1): maps the sweep's final (cycle_status, scan_status,
    degraded_reason) onto the run-manifest's kind=state terminal value
    — drives the status page's chip and terminal banner (P4). A failed
    cycle always wins (nothing about the crawl matters if the pipeline
    itself never finished); otherwise a no-product-pages-found scan or
    a blocked/failed scan gets its own state so the status page can
    show the SAME hotfix-3/5 honest banner the report already shows —
    a normal or skipped (no store_url) scan is just 'done', since rule
    7 means the scan never blocks completion.
    """
    if cycle_status != 'complete':
        return 'failed'
    if degraded_reason == 'no_product_pages_found':
        return 'no-product-pages'
    if scan_status in ('blocked', 'failed'):
        return 'degraded-blocked'
    return 'done'


def _as_utc_datetime(value):
    """Normalizes soa_lite_scan_results.updated_at across dialects — a real
    datetime from Postgres, or the ISO string the SQLite NOW() UDF returns
    in tests (see test_process_lite_requests.py::db)."""
    if value is None:
        return None
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _sweep_lite_completions():
    """
    Lite rows in status='running' become 'complete'/'failed' only once
    BOTH their cycle and their scan have reached a terminal state. The
    existing planned-cycle poll executes the cycle unchanged; the scan
    runs synchronously inside process_lite_requests, so by the time the
    cycle finishes the scan row is normally already terminal too — this
    join is a guard, not a wait loop.

    The one case that needs active recovery: the scan row is still
    'running' because the worker died mid-scan (see
    process_lite_requests -> _run_lite_scan). A lite request must never
    be stuck 'running' forever because of the scan (rule 7), so a scan
    row stuck 'running' for >= SCAN_TIMEOUT_MINUTES is force-marked
    'failed' here before the completion check proceeds.

    Stage 14 (W2): the SELECT is read-only, run once; each matched
    row's transition then gets its own connection/transaction AND its
    own try/except, so one bad row (a constraint violation, or any
    other DB error) can't roll back or block every other row's
    completion in the same sweep pass — it's simply logged and retried
    on the next pass.
    """
    now = datetime.now(timezone.utc)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT lr.id, lr.cycle_id, c.status, sr.id, sr.status, sr.updated_at, sr.dimensions
            FROM soa_lite_requests lr
            JOIN soa_cycles c ON c.id = lr.cycle_id
            JOIN soa_lite_scan_results sr ON sr.lite_request_id = lr.id
            WHERE lr.status = 'running'
              AND c.status IN ('complete', 'failed')
        """)).fetchall()

    for lite_id, cycle_id, cycle_status, scan_id, scan_status, scan_updated_at, dimensions_raw in rows:
        try:
            final_scan_status = scan_status
            watchdog_fired = False
            with engine.begin() as conn:
                if scan_status not in SCAN_TERMINAL_STATUSES:
                    scan_age = _as_utc_datetime(scan_updated_at)
                    stuck = scan_age is not None and (now - scan_age) >= timedelta(minutes=SCAN_TIMEOUT_MINUTES)
                    if not stuck:
                        continue  # scan legitimately still running — check again next pass

                    # error stays the existing 'scan timed out' text for
                    # this path specifically — dimensions/pages_fetched
                    # are the additive part (same honest, fully-v4-shaped
                    # degraded dims an ordinary blocked/failed scan
                    # already gets) so the report renders through the
                    # normal pillars machinery instead of an empty {}.
                    timed_out_dims = build_degraded_dimensions(DEGRADED_REASON_TIMED_OUT)
                    timed_out_dims["degraded_reason"] = "timed_out"
                    conn.execute(text("""
                        UPDATE soa_lite_scan_results
                        SET status = 'failed', error = 'scan timed out',
                            dimensions = :dimensions, pages_fetched = :pages_fetched,
                            updated_at = NOW()
                        WHERE id = :id
                    """), {
                        "id": scan_id,
                        "dimensions": json.dumps(timed_out_dims),
                        "pages_fetched": json.dumps([]),
                    })
                    final_scan_status = 'failed'
                    watchdog_fired = True

                if cycle_status == 'complete':
                    conn.execute(text("""
                        UPDATE soa_lite_requests
                        SET status = :status, updated_at = NOW()
                        WHERE id = :id
                    """), {"status": LITE_STATUS_COMPLETE, "id": lite_id})
                else:
                    conn.execute(text("""
                        UPDATE soa_lite_requests
                        SET status = :status,
                            error_message = 'Cycle failed during execution.',
                            updated_at = NOW()
                        WHERE id = :id
                    """), {"status": LITE_STATUS_FAILED, "id": lite_id})

            if watchdog_fired:
                # Crawl-failure alerting: a scan the watchdog had to
                # force-fail means the worker died or hung mid-crawl —
                # the other failure worth waking up for. Rate-limited to
                # one per class per window, so a broken deploy timing
                # out every request sends one email, not hundreds.
                ops_alert.send_crawl_failure_alert(
                    ops_alert.FAILURE_CLASS_WATCHDOG,
                    request_id=lite_id, token=_lite_token(lite_id),
                    store_url=_lite_store_url(lite_id),
                    error=f"scan #{scan_id} sat in 'running' for >= {SCAN_TIMEOUT_MINUTES} minutes",
                )
                # The crawl task's own event may still be sitting on
                # "reading…" if the worker died (or hung) mid-scan —
                # close it out so the status page's progress UI never
                # waits on a task that will now never finish.
                lite_events.emit_done(
                    lite_id, lite_events.TASK_CRAWL,
                    "Your store read took too long and was stopped — see your report for details",
                )

            degraded_reason = _decode_json_field(dimensions_raw, {}).get('degraded_reason')
            state = _terminal_run_state(cycle_status, final_scan_status, degraded_reason)
            lite_events.emit_state(lite_id, state)
            if state != 'failed':
                # Part 3: isolated exactly like the probes in
                # process_lite_requests — a bug or API failure here must
                # never prevent the state transition already committed
                # above, or the "Your report" done event that follows.
                try:
                    _run_pillar_headlines(lite_id, cycle_id, scan_id, dimensions_raw)
                except Exception:
                    log.exception(f"[lite] request {lite_id}: pillar headline generation failed unexpectedly")

                lite_events.emit_done(
                    lite_id, lite_events.TASK_REPORT,
                    "Three pillars, ranked fixes, private link",
                )
        except Exception:
            log.exception(f"[lite] request {lite_id}: completion sweep failed for this row — will retry next pass")

    # Isolated in its own try/except: a bug or outage in email delivery
    # must never prevent the completion-transition logic above (rule 7
    # in spirit — nothing about notifying the visitor may block the
    # pipeline's own state machine).
    try:
        _send_pending_report_emails()
    except Exception:
        log.exception("[lite] report-ready email sweep failed unexpectedly")


def _lite_token(lite_request_id: int) -> str | None:
    """The request's public token, for an ops alert's body — the one
    handle that identifies a run across the logs, the admin page and
    the visitor's own link. Its own connection and its own try/except:
    this is called from a failure path, and a lookup that raises there
    would turn a handled failure into an unhandled one."""
    return _lite_column(lite_request_id, "token")


def _lite_store_url(lite_request_id: int) -> str | None:
    return _lite_column(lite_request_id, "store_url")


def _lite_column(lite_request_id: int, column: str) -> str | None:
    # column is never caller-supplied — both call sites above pass a
    # literal — so the interpolation below has no untrusted input.
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(f"SELECT {column} FROM soa_lite_requests WHERE id = :id"),
                {"id": lite_request_id},
            ).fetchone()
        return row[0] if row else None
    except Exception:
        log.exception(f"[lite] request {lite_request_id}: could not read {column} for an ops alert")
        return None


def _fetch_visibility_metrics(conn, cycle_id: int) -> dict:
    """Part 3: lean visibility facts for pillar-headline generation —
    reads the SAME soa_metrics_results table apps/api's
    _fetch_metrics_rows (app/routers/public_lite.py) reads: already-
    computed, already-stored metrics, no re-derivation of the scoring
    formula. Scoped to the primary entity's overall-slice numbers plus
    its share-of-mentions rank across the full comparison set — the
    same rank apps/api's frontend computes client-side as
    shareOfMentionsRank (LiteFullReportV4.jsx), reimplemented here in
    SQL since the worker has no JS runtime to share it with."""
    rows = conn.execute(text("""
        SELECT ce.role, mr.soa_pct, mr.mention_rate, mr.rsi_score
        FROM soa_metrics_results mr
        JOIN soa_cycle_entities ce ON ce.cycle_id = mr.cycle_id AND ce.entity_id = mr.entity_id
        WHERE mr.cycle_id = :cid AND mr.slice_type = 'overall'
    """), {"cid": cycle_id}).fetchall()

    if not rows:
        return {"som_pct": None, "mention_rate": None, "rsi_score": None, "rank_line": None}

    ranked = sorted(rows, key=lambda r: -(r[1] or 0))
    primary_row = next((r for r in rows if r[0] == 'primary'), None)
    rank_line = None
    if primary_row is not None:
        idx = next(i for i, r in enumerate(ranked) if r[0] == 'primary')
        n = idx + 1
        suffix = 'st' if n == 1 else 'nd' if n == 2 else 'rd' if n == 3 else 'th'
        rank_line = f"{n}{suffix} of {len(ranked)} in the competitor set"

    return {
        "som_pct": primary_row[1] if primary_row else None,
        "mention_rate": primary_row[2] if primary_row else None,
        "rsi_score": primary_row[3] if primary_row else None,
        "rank_line": rank_line,
    }


def _run_pillar_headlines(lite_id: int, cycle_id: int, scan_id: int, dimensions_raw) -> None:
    """
    Part 3: one OpenAI call per audit, generating the three pillar
    headlines from the run's own facts (generation/pillar_headlines.py)
    and storing them as an additive sibling key on soa_lite_scan_
    results.dimensions — same "no migration" pattern as offers/
    product_image_url (scan/offer_feed.py). The report renders from
    this stored value and never regenerates it (3b) — this sweep is the
    ONLY place generated_headlines is ever written, and it only ever
    runs once per request (this function only fires on the lite
    request's single running -> complete/failed transition).
    """
    api_key = os.environ.get("OPEN_AI_API_KEY")
    if not api_key:
        return

    from generation.pillar_headlines import generate_pillar_headlines

    dims = _decode_json_field(dimensions_raw, {})

    lite_events.emit_log(lite_id, lite_events.TASK_REPORT, "writing your pillar summaries…")

    with engine.connect() as conn:
        visibility_metrics = _fetch_visibility_metrics(conn, cycle_id)

    headlines = generate_pillar_headlines(dims, visibility_metrics, api_key)

    dims["generated_headlines"] = headlines
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE soa_lite_scan_results
            SET dimensions = :dimensions, updated_at = NOW()
            WHERE id = :id
        """), {"dimensions": json.dumps(dims), "id": scan_id})


def _sweep_full_cycle_pillar_headlines() -> None:
    """
    Full-cycle counterpart to _run_pillar_headlines above — Part A
    (pillar-headline generation extended to Full Analysis, previously
    lite-only). A SWEEP, not a single state-transition trigger, because
    a full cycle's query-execution pipeline (soa_cycles.status=
    'complete', PipelineOrchestrator's own runner/coding/metrics stages)
    and its crawl (soa_lite_scan_results.status='complete', driven by
    process_cycle_crawls above) are two independently-timed async
    processes with no single event to hook — this checks both are done,
    once per poll pass, for whichever cycle needs it next.

    Written into the SAME soa_lite_scan_results.dimensions JSON blob the
    lite path already uses (an additive sibling key), on THAT cycle's
    own scan row (found by cycle_id, latest row wins — the same
    ORDER BY id DESC LIMIT 1 discipline cycle_scoring_full.py::
    build_full_cycle_report already reads with). No new storage or
    schema was needed for the Full Analysis report to pick this up —
    that function already reads dimensions_raw from exactly this row.

    One cycle per pass (same "don't hog the loop" discipline as
    process_cycle_crawls/get_next_planned_cycle) — skips any cycle that
    already has generated_headlines (idempotent; "has this JSON key"
    isn't portably expressible in SQL across Postgres/SQLite, so this
    filters in Python, same idiom as decode_json_field elsewhere in this
    file) and any scan row owned by a lite_request (that's _run_pillar_
    headlines' own exclusive path, keyed on the lite request's
    completion, not this sweep's).
    """
    api_key = os.environ.get("OPEN_AI_API_KEY")
    if not api_key:
        return

    from generation.pillar_headlines import generate_pillar_headlines

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT s.cycle_id, s.id, s.dimensions
            FROM soa_lite_scan_results s
            JOIN soa_cycles c ON c.id = s.cycle_id
            WHERE s.lite_request_id IS NULL
              AND s.cycle_id IS NOT NULL
              AND s.status = 'complete'
              AND c.status = 'complete'
              AND c.cycle_mode = 'query'
              AND s.id = (
                  SELECT MAX(s2.id) FROM soa_lite_scan_results s2 WHERE s2.cycle_id = s.cycle_id
              )
            ORDER BY s.cycle_id
        """)).fetchall()

    for cycle_id, scan_id, dimensions_raw in rows:
        dims = _decode_json_field(dimensions_raw, {})
        if "generated_headlines" in dims:
            continue

        try:
            with engine.connect() as conn:
                visibility_metrics = _fetch_visibility_metrics(conn, cycle_id)

            headlines = generate_pillar_headlines(dims, visibility_metrics, api_key)

            dims["generated_headlines"] = headlines
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE soa_lite_scan_results
                    SET dimensions = :dimensions, updated_at = NOW()
                    WHERE id = :id
                """), {"dimensions": json.dumps(dims), "id": scan_id})
        except Exception:
            log.exception(f"[cycle] cycle_id={cycle_id}: pillar headline generation failed unexpectedly")

        # One per pass, regardless of success/failure above — the next
        # poll pass picks up whatever's next.
        break


# Single source for the report-ready email's link — same variable
# name/intent as the frontend's PUBLIC_AUDIT_BASE_URL
# (apps/api/web/src/lite/publicUrls.js).
#
# Cutover: the canonical audit address is https://parleo.io/audit, so
# the fallback below now names it. The ENVIRONMENT VARIABLE STILL
# WINS — if PUBLIC_AUDIT_BASE_URL is set on Railway it overrides this
# entirely, so updating this literal is a safety net, not the fix.
# Setting the variable is the fix, and it is listed for the deploy.
#
# audit.parleo.io keeps working for links already in inboxes:
# apps/api/vercel.json 308s every path on that host to the matching
# parleo.io/audit path, query string included, so an old
# /r/{token}?src=email link still lands on the right report with its
# attribution intact.
PUBLIC_AUDIT_BASE_URL = os.environ.get("PUBLIC_AUDIT_BASE_URL", "https://parleo.io/audit").rstrip("/")


def _send_pending_report_emails():
    """
    Stage 12 (E3): sends the "your report is ready" email for every
    completed lite request that has an email on file but hasn't been
    sent yet. Runs on EVERY sweep pass (not just the completion
    transition above), so it naturally covers both orderings — email
    set before completion, or after — and retries a transient send
    failure on the next pass rather than losing it. Never raises: a
    send failure is logged and simply left for the next pass to retry.

    Stage 14 (W2): the SELECT is read-only, run once; each row's send
    attempt (already isolated) and its report_email_sent_at write
    (newly isolated here, its own connection/transaction) can no longer
    take down or roll back any other row in the same pass.
    """
    from email_sender import get_email_sender

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT id, token, email, brand_name
            FROM soa_lite_requests
            WHERE status = 'complete'
              AND email IS NOT NULL
              AND report_email_sent_at IS NULL
        """)).fetchall()

    if not rows:
        return

    sender = get_email_sender()
    for lite_id, token, email, brand_name in rows:
        # ?src=email: analytics attribution (docs/analytics.md) — the
        # frontend's captureSrcParam() reads and strips this on load.
        report_url = f"{PUBLIC_AUDIT_BASE_URL}/r/{token}?src=email"
        try:
            sent = sender.send_report_ready(email, report_url, brand_name)
        except Exception:
            log.exception(f"[lite] request {lite_id}: unexpected error sending report-ready email")
            sent = False

        if not sent:
            log.warning(
                f"[lite] request {lite_id}: report-ready email send failed — will retry next sweep pass"
            )
            continue

        try:
            with engine.begin() as conn:
                conn.execute(text("""
                    UPDATE soa_lite_requests
                    SET report_email_sent_at = NOW()
                    WHERE id = :id
                """), {"id": lite_id})
        except Exception:
            log.exception(
                f"[lite] request {lite_id}: failed to record report_email_sent_at — will retry next sweep pass"
            )


def main():
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    log.info("SoA Pipeline Worker started")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    while True:
        try:
            row = get_next_planned_cycle()

            if row:
                cycle_code     = row[0]
                study_type     = row[1]
                platforms      = row[2]
                runs_per_query = row[3]
                cycle_mode     = row[4] or "query"

                # Fallback for pre-migration cycles with NULL columns
                if cycle_mode != "truecost" and not platforms:
                    log.warning(
                        f"{cycle_code}: platforms is NULL — using default [chatgpt, gemini]"
                    )
                    platforms = ['chatgpt', 'gemini']

                if cycle_mode != "truecost" and not runs_per_query:
                    log.warning(
                        f"{cycle_code}: runs_per_query is NULL — using default 5"
                    )
                    runs_per_query = 5

                log.info(f"Dequeued: {cycle_code} (cycle_mode={cycle_mode})")
                try:
                    asyncio.run(
                        execute_cycle(cycle_code, study_type, platforms, runs_per_query, cycle_mode)
                    )
                except Exception as e:
                    log.exception(f"Cycle {cycle_code} failed: {e}")
                    mark_failed(cycle_code, str(e))
            else:
                log.debug("Queue empty.")

            # Poll generation jobs in same loop iteration — isolated try/except
            # so a generation failure never crashes cycle processing
            try:
                process_generation_jobs()
            except Exception:
                log.exception("[generation] poll iteration failed")

            # Same isolation for SoA Lite: claiming a pending request, and
            # sweeping running requests whose cycle has finished.
            try:
                process_lite_requests()
            except Exception:
                log.exception("[lite] poll iteration failed")

            try:
                _sweep_lite_completions()
            except Exception:
                log.exception("[lite] completion sweep failed")

            # Full Analysis coexistence, Phase 2: standalone cycle crawls —
            # same isolation as every other stage above, so a crawl failure
            # never blocks cycle/lite processing on later loop iterations.
            try:
                process_cycle_crawls()
            except Exception:
                log.exception("[cycle-crawl] poll iteration failed")

            # Part A: pillar-headline generation extended to Full
            # Analysis — same isolation as every other sweep above.
            try:
                _sweep_full_cycle_pillar_headlines()
            except Exception:
                log.exception("[cycle] pillar headline sweep failed")

            if not row:
                time.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            log.info("Worker stopped.")
            break
        except Exception as e:
            log.exception(f"Unexpected worker error: {e}")
            time.sleep(10)


if __name__ == "__main__":
    main()
