"""
Assembling a study that is grounded in a syndicated brand's catalog.

One function, build_syndicated_study, that composes the four tiers into
one list of rows plus the tier_config that records what was built. The
worker calls it and writes what comes back; every decision about what a
tier IS lives in catalog_tiers.py or query_generator.py, not here.

The composition itself is the thing worth reading:

  category_control   the study's OWN stage-count questions, tagged. Not
                     additive: the tier is a label on questions that were
                     going to exist anyway.
  brand_direct       +N AI-written questions with the catalog as context.
  catalog_accuracy   +N template questions over the sampled variants.
  value_incentives   +N template questions, one per mechanic.

So the tally the modal shows — "{stage total} AI-written + {catalog
count} from the catalog" — is exactly: stage total plus brand-direct on
the AI side (both are model output), catalog accuracy plus value on the
catalog side (both are templates over the record). The tier source tags
in the design mock say the same thing: "Written by AI from the catalog"
against brand-direct, "Built from the catalog, not by AI" against the
other two.

Degradation is the other thing worth reading. A study whose brand cannot
be read still gets generated — as the ungrounded study it would have been
with the toggle off — because failing a job that holds fifty good
questions over an unreachable third-party endpoint is a worse outcome
than a study with two tiers instead of four. What must never happen is
silence: an unavailable catalog is recorded on tier_config where the
report and the study page can both say so.
"""
import logging
from typing import Optional

from generation import catalog_tiers as ct
from generation.query_generator import (
    generate_and_review_study,
    generate_brand_direct,
)

logger = logging.getLogger(__name__)

TIERS = ['brand_direct', 'catalog_accuracy', 'value_incentives', 'category_control']


def normalize_tier_config(raw: Optional[dict]) -> dict:
    """
    Whatever the modal sent -> {tier: {enabled: bool, ...}} for all four.

    An absent tier is disabled, not defaulted on. The toggle is off for
    existing users, and a study that quietly acquired a tier nobody asked
    for would put questions in a report that nobody can account for.
    """
    raw = raw or {}
    out = {}
    for tier in TIERS:
        entry = raw.get(tier)
        if isinstance(entry, dict):
            out[tier] = {**entry, 'enabled': bool(entry.get('enabled'))}
        else:
            out[tier] = {'enabled': bool(entry)}
    return out


def _primary_category(allowed_categories) -> str:
    """
    The category stamped on catalog-built rows.

    Catalog questions are not written by a model and so cannot pick a
    category per question; they take the study's first allowed one, which
    is the study's own subject. 'General' is the fallback because it is
    the catch-all the constraints already define — never a guess at the
    brand's vertical, which would put a Baby Care study's rows under
    Skincare on the strength of a string match.
    """
    for category in allowed_categories or []:
        if category:
            return category
    return 'General'


def _primary_persona(personas) -> str:
    for persona in personas or []:
        if persona:
            return persona
    return 'Value-Conscious'


def build_syndicated_study(
    *,
    snapshot,
    study_name: str,
    description: str,
    stage_targets: dict,
    allowed_categories: list,
    study_pattern: str,
    api_key: str,
    tier_config: dict,
    retailer_names=None,
    rotate_named_retailer: bool = True,
    naming_rule_enabled: bool = True,
    personas=None,
    specificity_mode=None,
    variant_cap: int = ct.DEFAULT_VARIANT_CAP,
) -> tuple:
    """
    Returns (rows, provenance, resolved_tier_config).

    `rows` is every question in study order — the stage-count questions
    first, then brand-direct, then the catalog tiers — in the shape
    worker.py's _insert_generated_rows writes.

    `provenance` is the existing generation provenance record, unchanged
    in shape, with a `tiers` section added. Nothing that read it before
    reads differently now.
    """
    config = normalize_tier_config(tier_config)
    category = _primary_category(allowed_categories)
    persona = _primary_persona(personas)

    generate_kwargs = {
        'study_name': study_name,
        'description': description,
        'allowed_categories': allowed_categories,
        'study_pattern': study_pattern,
        'api_key': api_key,
        'personas': personas,
    }
    if specificity_mode:
        generate_kwargs['specificity_mode'] = specificity_mode

    # ── The study's own questions ────────────────────────────────────
    #
    # Generated exactly as they are today, catalog or no catalog: the
    # brief's stage counts, retailer names and naming rule, unchanged.
    # This call is what the "untoggled modal produces byte-identical
    # payloads" guarantee rests on — with no tiers enabled, nothing below
    # runs and nothing above changed.
    rows, provenance = generate_and_review_study(
        stage_targets=stage_targets,
        retailer_names=retailer_names,
        rotate_named_retailer=rotate_named_retailer,
        naming_rule_enabled=naming_rule_enabled,
        **generate_kwargs,
    )

    if config['category_control']['enabled']:
        # A TAG, not a generation. These questions were going to exist;
        # the tier says what they are FOR — a floor showing what the
        # category returns when the brand is not named — and that is why
        # they are not additive to the count.
        for row in rows:
            row['tier'] = 'category_control'
            row['provenance'] = 'ai'
        config['category_control']['count'] = len(rows)
    else:
        config['category_control']['count'] = 0

    grounded = bool(snapshot and snapshot.available)
    if not grounded:
        reason = (snapshot.error if snapshot else 'no brand selected')
        for tier in ('brand_direct', 'catalog_accuracy', 'value_incentives'):
            if config[tier]['enabled']:
                # Recorded, never silent. A tier that was asked for and
                # could not be built is a fact the report has to be able
                # to state, or a missing rate reads as a zero rate.
                config[tier]['unavailable'] = reason
                config[tier]['count'] = 0
        provenance['tiers'] = config
        logger.warning(
            "[generation] catalog unavailable (%s) — the study is generated "
            "as its ungrounded form", reason,
        )
        return rows, provenance, config

    config['merchant'] = {
        'slug': snapshot.merchant_slug,
        'brand': snapshot.brand,
        'domain': snapshot.domain,
        'products': snapshot.product_count,
        'variants': snapshot.variant_count,
        'gtins': snapshot.gtin_count,
        'codes': snapshot.code_count,
        'program_name': snapshot.program_name,
        'tiers': [t.get('name') for t in snapshot.tiers],
        'read_at': snapshot.read_at,
    }

    # ── Brand-direct ─────────────────────────────────────────────────
    if config['brand_direct']['enabled']:
        brand_rows, brand_report = generate_brand_direct(
            snapshot,
            stage_targets=stage_targets,
            count=config['brand_direct'].get('count'),
            **generate_kwargs,
        )
        rows.extend(brand_rows)
        config['brand_direct'].update({
            'count': len(brand_rows),
            'requested': brand_report.get('requested'),
            'stage_targets': brand_report.get('stage_targets'),
        })

    # ── Catalog accuracy ─────────────────────────────────────────────
    if config['catalog_accuracy']['enabled']:
        accuracy_rows, accuracy_report = ct.build_catalog_accuracy(
            snapshot, category=category, persona=persona, cap=variant_cap,
        )
        rows.extend(accuracy_rows)
        config['catalog_accuracy'].update(accuracy_report)

    # ── Value & incentives ───────────────────────────────────────────
    if config['value_incentives']['enabled']:
        value_rows, value_report = ct.build_value_incentives(
            snapshot, category=category, persona=persona,
        )
        rows.extend(value_rows)
        config['value_incentives'].update(value_report)

    # ── Expected nulls, written BEFORE the run ───────────────────────
    #
    # So a zero in the report reads as predicted rather than explained
    # after the fact. A prediction recorded after seeing the result is
    # not a prediction.
    for tier in TIERS:
        if config[tier]['enabled']:
            config[tier]['expected_nulls'] = ct.expected_nulls(snapshot, tier)

    provenance['tiers'] = config
    return rows, provenance, config


# ─── The tally ─────────────────────────────────────────────────────────────

def tally(config: dict) -> dict:
    """
    {ai_written, from_catalog, total} for a resolved tier_config.

    The split is by who wrote the question, which is what the modal's
    label claims: brand-direct is a model writing with a catalog open, so
    it counts as AI-written; catalog accuracy and value are templates over
    the record, so they count as from-the-catalog. Category control is a
    tag on questions already counted in the stage total and adds nothing.

    Mirrored in apps/api/web/src/components/catalogTiers.js, which
    computes the same numbers before anything is generated.
    """
    config = normalize_tier_config(config)
    stage_total = config['category_control'].get('stage_total') or 0

    ai_written = stage_total + (
        config['brand_direct'].get('count') or 0
        if config['brand_direct']['enabled'] else 0
    )
    from_catalog = sum(
        config[tier].get('count') or 0
        for tier in ('catalog_accuracy', 'value_incentives')
        if config[tier]['enabled']
    )
    return {
        'ai_written': ai_written,
        'from_catalog': from_catalog,
        'total': ai_written + from_catalog,
    }
