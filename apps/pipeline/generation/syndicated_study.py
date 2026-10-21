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

2I-7: category control names no brand. A category-control question is the
floor, what the category returns when the brand is not named; one that
names it put the brand in the answer and measures nothing (FL12, Pampers:
13 of the first 25). So the stage writer is told the rule when the tier is
on, and every question it returns is checked with soa_shared/unprompted.py,
the rule the console's score counts by. A question that names the brand is
regenerated once; a replacement that still names it is dropped and
counted, so the tier can come in under the stage target rather than carry
a branded question (keep_brand_out).

2K-1 (E29): the comparison tier. With category control on, the study's
Comparison-stage questions are not category control: "Pampers vs Huggies
for newborns" is a brand-choice moment, and 2I-7 regenerated it away for
naming the brand. They are written as comparison questions (the brand and a
rival, asking which to choose; rivals from the merchant's competitor list
first, then a rival the writer names and declares), tagged `comparison`, and
checked with soa_shared/unprompted.is_comparison. One naming no rival is
regenerated once, then dropped and counted (keep_comparisons), as 2I-7 does
for category control.

Degradation is the other thing worth reading. A study whose brand cannot
be read still gets generated — as the ungrounded study it would have been
with the toggle off — because failing a job that holds fifty good
questions over an unreachable third-party endpoint is a worse outcome
than a study with two tiers instead of four. What must never happen is
silence: an unavailable catalog is recorded on tier_config where the
report and the study page can both say so.
"""
import logging
from collections import Counter
from typing import Optional

from soa_shared import unprompted
from soa_shared.constants import QUERY_PERSONAS

from generation import catalog_tiers as ct
from generation.query_generator import (
    COMPARISON_STAGE,
    generate_and_review_study,
    generate_brand_direct,
    generate_general_queries,
    normalize_query_text,
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


def _primary_persona(personas, rows=None) -> str:
    """
    The persona stamped on catalog-built rows. Always a QUERY_PERSONAS
    value, because soa_queries.persona is NOT NULL and carries a CHECK
    against that list — a builder that invents a label writes a row the
    database refuses, or worse, one it accepts and no report can segment.

    Three sources, in the order of how much they know:

    1. The brief, when the study named personas. That is the study
       saying who it is about, and nothing here should second-guess it.

    2. The study's OWN questions, when it did not. Personas are optional
       in the modal and most studies leave them empty, so this is the
       common path rather than the fallback. The model picked a persona
       per question from the same enum and picked it knowing the subject;
       the most frequent of those is what this study is about, arrived at
       from the study's own output rather than guessed.

    3. The first enum value, reachable only for a study with no
       questions at all.

    Step 2 is the fix for a real defect. This used to end at a hardcoded
    'Value-Conscious' — a valid enum value, from the beauty verticals,
    and the wrong one for every study outside them. The first real
    brand-mode study was Baby Care: its model-written questions were
    'Value-Conscious Parent' and its catalog-built questions were
    'Value-Conscious', so the two halves of one study segmented into two
    different populations and neither was complete.
    """
    for persona in personas or []:
        if persona in QUERY_PERSONAS:
            return persona
        if persona:
            logger.warning(
                "[generation] ignoring persona %r: not in QUERY_PERSONAS", persona,
            )

    # Counter preserves first-seen order among equal counts, so a tie
    # resolves to whichever persona the study asked about first rather
    # than to whatever the hash order happens to be that run.
    counts = Counter(
        row.get('persona') for row in rows or []
        if row.get('persona') in QUERY_PERSONAS
    )
    if counts:
        return counts.most_common(1)[0][0]

    return QUERY_PERSONAS[0]


def control_terms(snapshot) -> tuple:
    """(brand, product names, terms) the category-control rule is stated
    and checked with: the study's brand and its catalog's product names, as
    the console reads them back from tier_config.merchant (study_brand_terms
    adds the entity's aliases there)."""
    if not snapshot:
        return None, [], []
    brand = getattr(snapshot, 'study_brand', None) or getattr(snapshot, 'brand', None)
    names = [p.title for p in (snapshot.products if snapshot.available else []) if p.title]
    return brand, names, unprompted.brand_terms(brand, (), names)


def control_line(count: int, dropped: int, checked: bool) -> str:
    """The tier's one line, as the preview and the generation status show it."""
    if not checked:
        return f"{count} question{'' if count == 1 else 's'}, not checked: no brand to check against"
    line = f"{count} question{'' if count == 1 else 's'}, none naming the brand"
    if dropped:
        line += f" ({dropped} dropped for naming it)"
    return line


def keep_brand_out(rows: list, terms: list, regenerate) -> tuple:
    """
    The category-control check. Returns (kept rows, report).

    Every row is checked with unprompted.is_unprompted. The ones that name
    the brand are handed to `regenerate(stage_counts, avoid_texts)` ONCE,
    for as many questions per stage as failed; each replacement is checked
    the same way and against the rows already kept (an exact duplicate is
    no replacement). What still names the brand is dropped and counted: a
    question that names the brand is not a category-control question, so
    the tier comes in short rather than carry it.

    With no terms there is nothing to check against, and every row is kept.
    """
    if not terms:
        return list(rows), {'checked_against': [], 'branded_regenerated': 0, 'branded_dropped': []}
    kept = [r for r in rows if unprompted.is_unprompted(r, terms)]
    branded = [r for r in rows if not unprompted.is_unprompted(r, terms)]
    report = {
        'checked_against': list(terms),
        'branded_regenerated': len(branded),
        'branded_found': [{'query_text': r.get('query_text'), 'stage': r.get('stage'),
                           'names': unprompted.names_any(r.get('query_text'), terms)} for r in branded],
        'branded_dropped': [],
    }
    if not branded:
        return kept, report

    stages = dict(Counter(r.get('stage') for r in branded))
    try:
        fresh = regenerate(stages, [r.get('query_text') for r in rows]) or []
    except Exception as exc:  # noqa: BLE001 - a failed regeneration drops the branded rows, never the study
        logger.warning("[generation] category-control regeneration failed: %s", exc)
        report['regeneration_error'] = type(exc).__name__
        fresh = []

    # at most as many per stage as failed, in the writer's order; a
    # replacement that names the brand or repeats a kept question fills nothing
    seen = {normalize_query_text(r.get('query_text')) for r in kept}
    room = dict(stages)
    replacements, still = [], []
    for row in fresh:
        key = normalize_query_text(row.get('query_text'))
        if room.get(row.get('stage'), 0) <= 0 or key in seen:
            continue
        if not unprompted.is_unprompted(row, terms):
            still.append(row)
            continue
        seen.add(key)
        room[row.get('stage')] -= 1
        replacements.append(row)
    # each replacement takes a branded question's place, in study order;
    # a branded question with no replacement of its stage is dropped
    pending = {}
    for r in replacements:
        pending.setdefault(r.get('stage'), []).append(r)
    out, dropped = [], []
    for r in rows:
        if unprompted.is_unprompted(r, terms):
            out.append(r)
        elif pending.get(r.get('stage')):
            out.append(pending[r.get('stage')].pop(0))
        else:
            dropped.append(r)
    report['replaced'] = len(replacements)
    report['branded_dropped'] = [{'query_text': r.get('query_text'), 'stage': r.get('stage'),
                                  'names': unprompted.names_any(r.get('query_text'), terms)} for r in dropped]
    report['replacements_naming_the_brand'] = [
        {'query_text': r.get('query_text'), 'stage': r.get('stage'),
         'names': unprompted.names_any(r.get('query_text'), terms)} for r in still]
    return out, report


def comparison_line(count: int, dropped: int) -> str:
    """The comparison tier's one line, as the preview and the generation status show it."""
    line = f"{count} question{'' if count == 1 else 's'}, each naming the brand and a rival"
    if dropped:
        line += f" ({dropped} dropped for naming no rival)"
    return line


def admissible_rival(name, brand_terms: list) -> bool:
    """A rival the writer declared counts when it is a name, is not one of
    the brand's own terms (or a line of it), and is not a retailer: a store
    is not a brand to choose against (soa_shared/retailers.py)."""
    from soa_shared.retailers import retailers_named
    from soa_shared.expected_answers import names_brand, normalize_brand_text
    key = normalize_brand_text(name) if isinstance(name, str) else ''
    if not key:
        return False
    if any(key == normalize_brand_text(t) or names_brand(name, t) for t in brand_terms):
        return False
    return not retailers_named(name)


def _passes(row: dict, terms: list, rivals: list) -> tuple:
    """(is a comparison, the rival terms it was checked against): the
    listed rivals, plus the one the writer declared when admissible."""
    declared = row.get('rival')
    checked = list(rivals) + ([declared] if admissible_rival(declared, terms) and declared not in rivals else [])
    return unprompted.is_comparison(row, terms, checked), checked


def keep_comparisons(rows: list, terms: list, rivals: list, regenerate) -> tuple:
    """
    The comparison check (2K-1). Returns (kept rows, report).

    Every Comparison-stage row is checked with unprompted.is_comparison
    against the brand's terms and the rivals (the listed competitors, plus
    the rival the writer declared, when it is a brand and not the merchant
    or a retailer). Those that fail are handed to `regenerate(n, avoid_texts)`
    ONCE; each replacement is checked the same way and against the rows
    already kept. What still names no rival is dropped and counted, so the
    tier can come in under the stage target rather than carry a question
    that is not a comparison.
    """
    def named(row, checked):
        return unprompted.names_any(row.get('query_text'), checked)

    kept, failed, rivals_named = [], [], Counter()
    passed = set()
    for r in rows:
        ok, checked = _passes(r, terms, rivals)
        if ok:
            kept.append(r)
            passed.add(id(r))
            rivals_named.update(named(r, [c for c in checked if c not in terms]))
        else:
            failed.append(r)
    report = {'checked_against': {'brand': list(terms), 'rivals': list(rivals)},
              'regenerated': len(failed), 'replaced': 0, 'dropped': [],
              'found': [{'query_text': r.get('query_text'), 'rival': r.get('rival')} for r in failed]}
    if failed:
        try:
            fresh = regenerate(len(failed), [r.get('query_text') for r in rows]) or []
        except Exception as exc:  # noqa: BLE001 - a failed regeneration drops the rows, never the study
            logger.warning("[generation] comparison regeneration failed: %s", exc)
            report['regeneration_error'] = type(exc).__name__
            fresh = []
        seen = {normalize_query_text(r.get('query_text')) for r in kept}
        replacements = []
        for row in fresh:
            key = normalize_query_text(row.get('query_text'))
            if len(replacements) >= len(failed) or key in seen:
                continue
            ok, checked = _passes(row, terms, rivals)
            if not ok:
                continue
            seen.add(key)
            replacements.append(row)
            rivals_named.update(named(row, [c for c in checked if c not in terms]))
        # each replacement takes a failed question's place, in study order
        out, pending = [], list(replacements)
        for r in rows:
            if id(r) in passed:
                out.append(r)
            elif pending:
                out.append(pending.pop(0))
            else:
                report['dropped'].append({'query_text': r.get('query_text'), 'rival': r.get('rival')})
        kept = out
        report['replaced'] = len(replacements)
    report['rivals_named'] = sorted(rivals_named.items(), key=lambda kv: (-kv[1], kv[0]))
    return kept, report


def _stage_order(rows: list) -> list:
    """The study's rows in stage order (QUERY_STAGES), stable within a stage."""
    from soa_shared.constants import QUERY_STAGES
    rank = {s: i for i, s in enumerate(QUERY_STAGES)}
    return sorted(rows, key=lambda r: rank.get(r.get('stage'), len(rank)))


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
    rivals=None,
) -> tuple:
    """
    Returns (rows, provenance, resolved_tier_config).

    rivals: the merchant's competitor names (2K-1), the comparison tier's
    first choice of rival; the worker reads them (worker.merchant_rivals).

    `rows` is every question in study order — the stage-count questions
    first, then brand-direct, then the catalog tiers — in the shape
    worker.py's _insert_generated_rows writes.

    `provenance` is the existing generation provenance record, unchanged
    in shape, with a `tiers` section added. Nothing that read it before
    reads differently now.
    """
    config = normalize_tier_config(tier_config)
    category = _primary_category(allowed_categories)
    # 2K-1: the merchant's timezone the wizard set, kept on the merchant block
    # this rebuilds below (soa_shared/local_time.merchant_timezone reads it)
    zone = ((tier_config or {}).get('merchant') or {}).get('timezone') if isinstance(tier_config, dict) else None
    if zone:
        config['merchant'] = {'timezone': zone}

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

    # 2I-7: with the control tier on, the stage writer is told the
    # category-control rule, and its questions are checked after. Off, the
    # call below is the one this code made before the tiers existed.
    control_on = config['category_control']['enabled']
    brand, product_names, terms = control_terms(snapshot) if control_on else (None, [], [])
    control = {'brand': brand, 'product_names': product_names} if control_on and brand else None
    # 2K-1: with the control tier on and a brand to name, the Comparison
    # stage is the comparison tier: the brand and a rival
    rivals = [r for r in (rivals or []) if admissible_rival(r, terms)] if control else []
    comparison_on = bool(control and (stage_targets or {}).get(COMPARISON_STAGE))
    comparison = {'brand': brand, 'rivals': rivals} if comparison_on else None

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
        **({'category_control': control} if control else {}),
        **({'comparison': comparison} if comparison else {}),
    )

    # After the generation call, not before: with no personas in the
    # brief this reads the study's own questions to find out who the
    # study is about, and there were no questions to read until now.
    persona = _primary_persona(personas, rows)

    if config['category_control']['enabled']:
        # A TAG, not a generation. These questions were going to exist;
        # the tier says what they are FOR — a floor showing what the
        # category returns when the brand is not named — and that is why
        # they are not additive to the count.
        #
        # 2I-7: tagged only once checked. One that names the brand is
        # regenerated once and then dropped (keep_brand_out).
        def regenerate(stages, avoid):
            fresh, _report = generate_general_queries(
                stage_targets=stages,
                retailer_names=retailer_names,
                rotate_named_retailer=rotate_named_retailer,
                naming_rule_enabled=naming_rule_enabled,
                category_control=control,
                avoid_texts=avoid,
                **generate_kwargs,
            )
            return fresh

        compared = [r for r in rows if comparison_on and r.get('stage') == COMPARISON_STAGE]
        rows = [r for r in rows if not (comparison_on and r.get('stage') == COMPARISON_STAGE)]
        requested = len(rows)
        rows, check = keep_brand_out(rows, terms, regenerate)
        for row in rows:
            row['tier'] = 'category_control'
            row['provenance'] = 'ai'
        if comparison_on:
            def regenerate_comparisons(n, avoid):
                fresh, _report = generate_general_queries(
                    stage_targets={COMPARISON_STAGE: n},
                    retailer_names=retailer_names,
                    rotate_named_retailer=rotate_named_retailer,
                    naming_rule_enabled=naming_rule_enabled,
                    category_control=control,
                    comparison=comparison,
                    avoid_texts=avoid,
                    **generate_kwargs,
                )
                return fresh

            asked = len(compared)
            compared, ccheck = keep_comparisons(compared, terms, rivals, regenerate_comparisons)
            for row in compared:
                row['tier'] = 'comparison'
                row['provenance'] = 'ai'
                row.pop('rival', None)
            cdropped = len(ccheck['dropped'])
            config['comparison'] = {**ccheck, 'enabled': True, 'count': len(compared), 'generated': asked,
                                    'dropped': cdropped, 'rivals': rivals,
                                    'line': comparison_line(len(compared), cdropped)}
            provenance['comparison_check'] = {k: ccheck[k] for k in ccheck if k != 'checked_against'}
            rows = _stage_order(rows + compared)
        dropped = len(check['branded_dropped'])
        controls = sum(1 for r in rows if r.get('tier') == 'category_control')
        config['category_control'].update(check)
        config['category_control'].update({
            'count': controls,
            'generated': requested,
            'dropped': dropped,
            'line': control_line(controls, dropped, bool(terms)),
        })
        provenance['category_control_check'] = {k: check[k] for k in check if k != 'checked_against'}
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
        # 2B: which mode the study was generated in, and from what record.
        'kind': getattr(snapshot, 'merchant_kind', None),
        'hosting': getattr(snapshot, 'hosting', None),
        'own_domain': getattr(snapshot, 'own_domain', None),
        'retailer_list': list(getattr(snapshot, 'retailer_list', None) or []),
        'study_brand': getattr(snapshot, 'study_brand', None) or snapshot.brand,
        'record_error': getattr(snapshot, 'record_error', None),
        # 2I-7: the brand's product names, the terms beside its name that
        # the console's unprompted rule reads back (soa_shared/unprompted.py)
        'product_names': [p.title for p in snapshot.products if p.title],
        **({'timezone': zone} if zone else {}),
    }

    # ── The catalog tiers, BUILT FIRST ───────────────────────────────
    #
    # Built before brand-direct and appended after it, so the study's
    # question order is unchanged (stage, then brand-direct, then
    # catalog) while brand-direct gets to see them.
    #
    # It has to see them. These are templates over the record and they
    # are the questions with a published number behind them; a
    # brand-direct question that asks the same thing in different words
    # measures that number twice and scores the second copy against a
    # brand_mention expectation, which is not what it measured. Building
    # them first is what makes the catalog tier the authority on its own
    # questions and brand-direct the tier that has to work around them.
    catalog_rows = []

    if config['catalog_accuracy']['enabled']:
        accuracy_rows, accuracy_report = ct.build_catalog_accuracy(
            snapshot, category=category, persona=persona,
            study_pattern=study_pattern, cap=variant_cap,
        )
        catalog_rows.extend(accuracy_rows)
        config['catalog_accuracy'].update(accuracy_report)

    if config['value_incentives']['enabled']:
        value_rows, value_report = ct.build_value_incentives(
            snapshot, category=category, persona=persona,
            study_pattern=study_pattern,
        )
        catalog_rows.extend(value_rows)
        config['value_incentives'].update(value_report)

    # ── Brand-direct ─────────────────────────────────────────────────
    if config['brand_direct']['enabled']:
        brand_rows, brand_report = generate_brand_direct(
            snapshot,
            stage_targets=stage_targets,
            count=config['brand_direct'].get('count'),
            catalog_texts=[row['query_text'] for row in catalog_rows],
            **generate_kwargs,
        )
        # 2B: a question may name a retailer only from the record's list.
        # The generator is told so; this is the check that it listened.
        retailer_drops = []
        if ct.is_external(snapshot):
            kept = []
            for row in brand_rows:
                outside = ct.retailers_outside_list(row.get('query_text'), snapshot)
                if outside:
                    retailer_drops.append({'query_text': row.get('query_text'),
                                           'retailers': outside})
                else:
                    kept.append(row)
            brand_rows = kept
        rows.extend(brand_rows)
        config['brand_direct'].update({
            'retailer_not_in_list_drops': retailer_drops,
            'count': len(brand_rows),
            'requested': brand_report.get('requested'),
            'shortfall': brand_report.get('shortfall'),
            'stage_targets': brand_report.get('stage_targets'),
            'brand_missing_drops': brand_report.get('brand_missing_drops') or [],
            'intent_duplicate_drops': brand_report.get('intent_duplicate_drops') or [],
        })

    rows.extend(catalog_rows)

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
