"""
Generates soa_queries rows via OpenAI based on a study name and description.
Validates each generated row against QUERY_CONSTRAINTS before returning.
Invalid rows are skipped and logged — partial success is acceptable for AI
generation (unlike CSV upload which is all-or-nothing).

Also generates SoA Lite studies (generate_lite_queries) — a fixed
LITE_QUERY_COUNT-query brand_vs_brand set, LITE_QUERIES_PER_STAGE per
QUERY_STAGES stage. Unlike the general path, partial success is NOT
acceptable there (see generate_lite_queries): a report built from a
lopsided stage distribution would be misleading, so a persistent
shortfall raises LiteGenerationError instead of returning whatever was
generated.

The general path (generate_general_queries, and generate_and_review_study
which wraps it) shares that distribution enforcement via
_fill_stage_buckets but reports a residual shortfall rather than raising,
and adds a caller-supplied category allow-list plus a stamped
study_pattern.

Removal discipline across this module: exact-match duplicates are the
ONLY thing removed automatically, and rows outside the category
allow-list are dropped — never relabelled — so a scope violation stays
visible. The two review passes (review_semantic_duplicates,
review_coherence) are advisory: they produce findings for a human and
change nothing, and they degrade to no findings rather than failing a
study that has already generated.
"""

import json
import logging
import re
from typing import Optional
from openai import OpenAI
from soa_shared.constants import QUERY_CONSTRAINTS, QUERY_STAGES
from soa_shared.scan_dimensions import LITE_QUERIES_PER_STAGE

log = logging.getLogger(__name__)

BATCH_SIZE = 10

# Targeted follow-up calls allowed inside one _fill_stage_buckets pass on
# the general path (lite uses 1 — see generate_lite_queries).
RETRY_BUDGET_GENERAL = 2

# Times generate_general_queries will go back for replacements after
# dedupe removes rows. Bounded because a study whose subject genuinely
# only supports forty distinct questions will never converge on fifty,
# and an unbounded loop turns that into an OpenAI bill instead of a
# reported shortfall.
REPLACEMENT_ROUNDS = 2

# QUERY_CONSTRAINTS fields the DB allows NULL for (soa_queries.<field>.
# nullable=True) — absent/None from a generated row means "unconstrained,"
# not invalid, same skip-when-None convention app/routers/studies.py::
# _validate_csv_row already applies. Every OTHER QUERY_CONSTRAINTS field
# is NOT NULL in the schema, so a new field added there defaults to
# strict (must match exactly) unless explicitly added here — deliberately
# not derived from the model automatically, so adding a new constrained
# field forces a conscious choice between "add it to the generation
# prompt" and "it's fine unconstrained," not a silent default either way.
#
# subscription_state: an opt-in, feature-flagged (config.
# ELIGIBILITY_CONDITIONING_ENABLED, default off) persona eligibility
# signal for subscribe-and-save studies — see soa_models.py's column
# comment ("Null = unconstrained") and constants.py's QUERY_
# SUBSCRIPTION_STATES docstring.
#
# It stays in this set even though _build_prompt now DOES ask for it
# (matching _build_lite_prompt), and the two facts are independent. The
# original regression — 100% of generally-generated rows rejected
# deterministically, not from LLM flakiness — was that the prompt never
# requested the field while the validator demanded it; membership in
# this set is what actually fixed it, by making an absent value valid
# rather than invalid. Asking for it in the prompt only raises how often
# a value is present. A model that omits it on some rows (or on all of
# them, if a future prompt revision drops the key again) must still
# produce valid rows, so the nullable treatment is the load-bearing half
# and is deliberately NOT conditional on the prompt wording.
_NULLABLE_CONSTRAINED_FIELDS = {'subscription_state'}


class LiteGenerationError(Exception):
    """Raised when generate_lite_queries cannot reach LITE_QUERIES_PER_STAGE
    valid queries for every stage even after the targeted shortfall retry."""


# Characters stripped off the END of a normalized query. Deliberately
# generous (terminal punctuation, quotes, dashes, ellipsis): "Which
# retailer has the best price?" and "Which retailer has the best price"
# are the same question, and a model asked for fifty questions in five
# batches will hand back both spellings.
_TRAILING_PUNCTUATION = '?!.,;:…-–—"\'’”)'


def _count_by_stage(rows: list) -> dict:
    counts: dict = {}
    for row in rows:
        stage = row.get('stage')
        counts[stage] = counts.get(stage, 0) + 1
    return counts


def normalize_query_text(value) -> str:
    """
    Canonical form used to decide whether two generated questions are
    the SAME question: lowercased, outer whitespace stripped, internal
    runs of whitespace collapsed to one space, trailing punctuation
    removed.

    This is a normalizer, not a similarity measure. It exists to make
    exact duplicates detectable despite cosmetic drift; questions that
    differ in wording are the semantic review pass's problem
    (review_semantic_duplicates), not this function's.
    """
    text = (value or '').strip().lower()
    text = re.sub(r'\s+', ' ', text)
    return text.rstrip(_TRAILING_PUNCTUATION + ' ')


def dedupe_exact(rows: list) -> tuple:
    """
    Removes exact duplicates from a list of validated rows, keeping the
    FIRST occurrence of each. Returns (survivors, dropped) — dropped
    holds the removed rows themselves (not just their text) so the
    caller can report exactly what was discarded.

    The key is the normalized query_text ALONE. This is load-bearing and
    the single most likely thing to be "helpfully" broadened later: it
    is tempting to key on (query_text, category, stage, ...) so that two
    rows only collide when they agree on everything. That would be
    exactly backwards. The observed failures included the SAME question
    text carrying two different stage labels — a composite key lets
    precisely those through, while still catching the harmless case
    where the model repeated itself verbatim in every field. A question
    asked twice is asked twice regardless of how it was labelled the
    second time.

    Exact-match removal is the only fully automatic drop in this module.
    Anything requiring judgement (near-duplicates, off-brief rows) is
    reported for a human, never silently applied.
    """
    seen = set()
    survivors = []
    dropped = []
    for row in rows:
        key = normalize_query_text(row.get('query_text'))
        if key in seen:
            dropped.append(row)
            continue
        seen.add(key)
        survivors.append(row)
    return survivors, dropped


def _build_prompt(
    study_name: str,
    description: str,
    batch_size: int,
    already_generated: list,
) -> str:
    constraints_text = "\n".join(
        f"- {field}: one of {', '.join(repr(v) for v in vals)}"
        for field, vals in QUERY_CONSTRAINTS.items()
    )

    # The FULL already_generated list, not a tail slice. BATCH_SIZE is 10,
    # so a 50-question study runs five batches: a 20-entry window meant
    # batch 5 could not see batches 1 and 2 at all, and the model
    # reproduced questions it had no way to know it had already written.
    # That is the confirmed cause of the duplicates observed roughly nine
    # rows apart — one batch's worth of drift. The avoid-text wording is
    # deliberately unchanged; only the slice is gone.
    avoid_text = ""
    if already_generated:
        avoid_text = (
            "\n\nDo NOT repeat or closely paraphrase these already-generated questions:\n"
            + "\n".join(f"- {q}" for q in already_generated)
        )

    return f"""Generate exactly {batch_size} distinct search-style questions for a brand/market research study called "{study_name}".

Study description: {description or 'No additional description provided.'}

Each question becomes one row in a database table. For EACH question provide ALL of these fields. Every field value MUST be one of the exact allowed values listed — do not invent new values:

{constraints_text}

Also provide:
- query_text: the actual question/prompt a user might type into an AI assistant or search engine
- soa_focus: 1-3 comma-separated metric names this query is designed to test (free text, e.g. "Mention Rate, RSI")
- rationale: one sentence explaining why this query is useful for the study (free text)

Respond with ONLY a JSON array of {batch_size} objects, each with keys:
query_text, category, stage, specificity, persona, study_pattern, status, subscription_state, soa_focus, rationale.
No markdown, no explanation, just the JSON array.{avoid_text}"""


def _validate_generated_row(row: dict) -> tuple:
    """
    Checks constrained fields against QUERY_CONSTRAINTS. A field in
    _NULLABLE_CONSTRAINED_FIELDS is skipped (no error) when absent — the
    DB itself treats it as valid, and not every generation prompt asks
    for it. Every other constrained field must still match exactly.

    Returns (cleaned_row, errors) — errors is a list of (field, message)
    tuples, empty if the row is valid.
    """
    errors = []

    query_text = (row.get('query_text') or '').strip()
    if not query_text:
        errors.append(('query_text', 'query_text is empty'))

    cleaned = {
        'query_text': query_text,
        'soa_focus':  row.get('soa_focus'),
        'rationale':  row.get('rationale'),
    }

    for field, allowed in QUERY_CONSTRAINTS.items():
        val = row.get(field)
        if val is None and field in _NULLABLE_CONSTRAINED_FIELDS:
            cleaned[field] = None
            continue
        if val not in allowed:
            errors.append(
                (field, f"{field}={val!r} not in allowed values")
            )
        cleaned[field] = val

    return cleaned, errors


def _deterministic_failure_reason(row_errors: list, total_rows: int) -> Optional[str]:
    """
    row_errors: one entry per row that failed validation (rows that
    passed aren't included), each a list of (field, message) tuples from
    _validate_generated_row.

    Returns a human-readable reason when EVERY row in the batch failed
    validation and they all share at least one common failing field —
    a deterministic prompt/schema mismatch (that field is never in the
    model's output at all), not per-row LLM noise, so retrying the exact
    same request would just reproduce the identical 100% failure. None
    otherwise (a real retry is worth attempting).
    """
    if not row_errors or len(row_errors) < total_rows:
        return None
    fields_per_row = [{field for field, _ in errors} for errors in row_errors]
    common_fields = set.intersection(*fields_per_row)
    if not common_fields:
        return None
    return (
        f"Every generated row failed validation on the same field(s): "
        f"{', '.join(sorted(common_fields))} — this looks like a prompt/schema "
        f"mismatch, not a one-off model error; retrying would not help."
    )


def _call_openai_for_json(
    prompt: str,
    api_key: str,
    temperature: float = 0.8,
) -> Optional[list]:
    """
    One OpenAI call, one JSON array out. Returns None when the response
    cannot be read as a list. Errors from the call itself still
    propagate — see the comment in the body.

    This is the raw call that _call_openai_and_validate wraps with
    soa_queries row validation. The review passes need the call without
    the validation: their output is groups and verdicts, not query rows,
    so putting it through _validate_generated_row would reject every item
    on fields that have no meaning for it. Sharing this layer keeps them
    on the same client, the same fence-stripping, and the same
    temperature parameter, which is what actually matters.
    """
    # A transport/API exception is deliberately NOT caught here. It used
    # to propagate out of _call_openai_and_validate and therefore out of
    # generate_lite_queries, and lite feeds the live public audit tool —
    # turning a raised error into an empty list would convert it into a
    # LiteGenerationError about a stage shortfall, which is a different
    # failure wearing the wrong name. The review passes catch it
    # themselves, because for them a failed call must degrade quietly.
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )

    content = (response.choices[0].message.content or '').strip()

    # Strip markdown code fences if the model added them
    if content.startswith('```'):
        content = content.split('\n', 1)[1]
        content = content.rsplit('```', 1)[0]

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        log.error(f"Failed to parse OpenAI response as JSON: {e}")
        log.error(f"Raw content: {content[:500]}")
        return None

    # Handle both raw array and {"questions": [...]} shapes
    if isinstance(parsed, dict):
        for key in ('questions', 'queries', 'items', 'data',
                    'groups', 'findings', 'results'):
            if key in parsed:
                parsed = parsed[key]
                break

    if not isinstance(parsed, list):
        log.error(f"Expected JSON array, got: {type(parsed)}")
        return None

    return parsed


def _call_openai_and_validate(
    prompt: str,
    api_key: str,
    temperature: float = 0.8,
    stamp: Optional[dict] = None,
) -> tuple:
    """
    Calls OpenAI with a fully-built prompt, parses the JSON response, and
    validates each row via _validate_generated_row.

    Returns (valid_rows, deterministic_failure_reason). valid_rows is a
    list of validated, cleaned row dicts (invalid rows are logged and
    skipped, never raised). deterministic_failure_reason is set (and
    valid_rows is []) only when every row in a non-empty batch failed
    validation on the same field — see _deterministic_failure_reason;
    None in every other case, including "nothing parsed at all" (that's
    LLM-response noise, still worth a caller's retry).

    temperature defaults to 0.8 — the value this helper has always sent,
    so every existing caller is unchanged. It is a parameter because the
    review passes (review_semantic_duplicates, review_coherence) reuse
    this same helper for classification rather than generation, and
    classification wants near-zero sampling: at 0.8 the same fifty rows
    get grouped differently on consecutive runs, which makes an advisory
    finding impossible for a human to act on or re-check.

    stamp, when given, is merged into every parsed row BEFORE
    _validate_generated_row sees it. That ordering is the point: a
    stamped field is still checked against QUERY_CONSTRAINTS like any
    other, so a caller cannot smuggle an out-of-range value in through
    the back door — it just stops being something the model gets to
    decide per row. Default None leaves every row exactly as parsed.
    """
    parsed = _call_openai_for_json(prompt, api_key, temperature)
    if parsed is None:
        return [], None

    valid_rows = []
    row_errors = []
    for row in parsed:
        if stamp and isinstance(row, dict):
            row = {**row, **stamp}
        cleaned, errors = _validate_generated_row(row)
        if errors:
            log.warning(f"Skipping invalid generated row: {errors} — row={row}")
            row_errors.append(errors)
            continue
        valid_rows.append(cleaned)

    if not valid_rows and parsed:
        reason = _deterministic_failure_reason(row_errors, len(parsed))
        if reason:
            log.error(f"Deterministic generation failure: {reason}")
            return [], reason

    return valid_rows, None


def generate_query_batch(
    study_name: str,
    description: str,
    batch_size: int,
    already_generated: list,
    api_key: str,
) -> tuple:
    """
    Calls OpenAI to generate one batch of queries.
    Returns (valid_rows, deterministic_failure_reason) — see
    _call_openai_and_validate. Invalid rows are skipped and logged, never
    raised; a non-None reason means every row failed for the same
    field(s) and the caller should not blindly retry.

    study_pattern is still a model output on THIS path — see the
    generate_general_queries docstring for why it should not be, and for
    the stamped alternative. Changing it here means adding a required
    argument, which means changing this function's call site in
    worker.py, which breaks an existing test's generate_query_batch mock
    signature (tests/test_process_generation_jobs.py::
    test_end_to_end_50_query_study_commits_50_rows_across_batches). The
    fix lives on the new path instead; this one is left alone
    deliberately, not by oversight.
    """
    prompt = _build_prompt(study_name, description, batch_size, already_generated)
    return _call_openai_and_validate(prompt, api_key)


# ─── Stage-distribution enforcement ───────────────────────────────────────

SHORTFALL_RAISE = 'raise'
SHORTFALL_REPORT = 'report'


def _fill_stage_buckets(
    targets: dict,
    build_prompt,
    api_key: str,
    retry_budget: int,
    on_shortfall: str,
    shortfall_message=None,
    accept_row=None,
    stamp: Optional[dict] = None,
    label: str = '',
) -> dict:
    """
    Asks the model for a per-stage distribution and keeps asking, with
    progressively narrower prompts, until every stage is filled or the
    retry budget runs out.

    Requesting a distribution in the prompt is not the same as getting
    one — the model over-delivers on some stages and under-delivers on
    others — so the counts are enforced here: validated rows are bucketed
    by stage, a bucket stops accepting rows once it hits its target
    (excess is discarded rather than silently rebalancing the study), and
    the remaining shortfall drives the next prompt.

    Arguments:
      targets       {stage: count} — what the caller wants per stage.
      build_prompt  callable(shortfall_mapping, accepted_rows) ->
                    prompt string. Called once with the full targets and
                    an empty accepted list, then once per retry with only
                    the stages still short and everything bucketed so
                    far. Retries need the accepted rows because the whole
                    point of a follow-up prompt is that it knows what the
                    earlier calls already produced. The caller owns the
                    prompt wording; this helper only owns the loop.
      retry_budget  how many TARGETED follow-up calls are allowed after
                    the initial one. Lite uses 1, the general path 2.
      on_shortfall  SHORTFALL_RAISE or SHORTFALL_REPORT. Raise is for
                    lite, where a lopsided distribution produces a
                    misleading public report and failing outright is the
                    honest answer. Report is for general studies, where
                    hard-failing after five batches would discard
                    forty-seven good queries to punish a shortfall of
                    three.
      shortfall_message  callable(shortfall) -> str, used only by RAISE,
                    so the caller keeps ownership of its own error text.
      accept_row    optional callable(row) -> Optional[str]. Returns a
                    rejection reason to drop the row, or None to keep it.
                    Runs AFTER validation and before bucketing.
      stamp         forwarded to _call_openai_and_validate.
      label         prefix for this helper's log lines, so the lite path
                    keeps the '[lite]' tag ops already grep for.

    Returns a dict: buckets, shortfall, rejected (list of (row, reason)),
    and calls (how many model calls were actually made).
    """
    buckets = {stage: [] for stage in targets}
    rejected = []
    calls = 0

    def _bucket(rows):
        for row in rows:
            if accept_row is not None:
                reason = accept_row(row)
                if reason:
                    rejected.append((row, reason))
                    continue
            stage = row.get('stage')
            bucket = buckets.get(stage)
            if bucket is not None and len(bucket) < targets[stage]:
                bucket.append(row)

    def _shortfall():
        return {
            stage: targets[stage] - len(bucket)
            for stage, bucket in buckets.items()
            if len(bucket) < targets[stage]
        }

    # _call_openai_and_validate's deterministic_failure_reason isn't
    # separately branched on here — each retry sends a DIFFERENT, narrower
    # targeted prompt rather than blindly repeating the same request, so
    # it isn't the "retrying would not help" case that reason exists to
    # short-circuit.
    def _accepted():
        return [row for stage in targets for row in buckets[stage]]

    rows, _reason = _call_openai_and_validate(
        build_prompt(dict(targets), []), api_key, stamp=stamp,
    )
    calls += 1
    _bucket(rows)

    attempts = 0
    while attempts < retry_budget:
        shortfall = _shortfall()
        if not shortfall:
            break
        attempts += 1
        log.warning(f"{label}stage shortfall after call {calls}: {shortfall} — retrying")
        rows, _reason = _call_openai_and_validate(
            build_prompt(shortfall, _accepted()), api_key, stamp=stamp,
        )
        calls += 1
        _bucket(rows)

    shortfall = _shortfall()
    if shortfall and on_shortfall == SHORTFALL_RAISE:
        raise LiteGenerationError(
            shortfall_message(shortfall) if shortfall_message
            else f"stage shortfall persists: {shortfall}"
        )

    return {
        'buckets':   buckets,
        'shortfall': shortfall,
        'rejected':  rejected,
        'calls':     calls,
    }


def _build_lite_prompt(
    brand_name: str,
    competitor_names: list,
    stage_counts: dict,
    already_generated: list,
) -> str:
    constraints_text = "\n".join(
        f"- {field}: one of {', '.join(repr(v) for v in vals)}"
        for field, vals in QUERY_CONSTRAINTS.items()
    )

    competitors_text = (
        ", ".join(competitor_names) if competitor_names else "no named competitors"
    )

    distribution_text = "\n".join(
        f"- {count} {stage!r} stage question(s)"
        for stage, count in stage_counts.items()
        if count > 0
    )
    total = sum(stage_counts.values())

    avoid_text = ""
    if already_generated:
        avoid_text = (
            "\n\nDo NOT repeat or closely paraphrase these already-generated questions:\n"
            + "\n".join(f"- {q}" for q in already_generated)
        )

    return f"""Generate exactly {total} search-style questions a real consumer would ask an AI shopping assistant when considering the brand "{brand_name}" and/or its competitors ({competitors_text}).

This is a brand_vs_brand comparison study. Distribute the {total} questions EXACTLY as follows:
{distribution_text}

Critical rule on naming brands: questions must NOT all name "{brand_name}" explicitly. For 'Awareness' and 'Research' stage questions, prefer CATEGORY-LEVEL phrasing — asking about the product category in general, where "{brand_name}" or a competitor SHOULD naturally come up in a good answer but is not named in the question itself (e.g. "What's the best stroller for a newborn?" rather than "Is {brand_name} good?"). 'Comparison' and 'Ready to Buy' stage questions MAY name "{brand_name}" and/or its competitors directly (e.g. head-to-head or which-to-buy questions).

Each question becomes one row in a database table. For EACH question provide ALL of these fields. Every field value MUST be one of the exact allowed values listed — do not invent new values:

{constraints_text}

For "category": choose the closest fit to what "{brand_name}" sells. Use 'General' only if no other category fits.
For "study_pattern": always 'brand_vs_brand'.
For "status": always 'Active'.

Also provide:
- query_text: the actual question/prompt a user might type into an AI assistant or search engine
- soa_focus: 1-3 comma-separated metric names this query is designed to test (free text, e.g. "Mention Rate, RSI")
- rationale: one sentence explaining why this query is useful for the study (free text)

Respond with ONLY a JSON array of {total} objects, each with keys:
query_text, category, stage, specificity, persona, study_pattern, status, subscription_state, soa_focus, rationale.
No markdown, no explanation, just the JSON array.{avoid_text}"""


SPECIFICITY_MATCH_TO_STAGE = 'match_to_stage'
SPECIFICITY_EVEN_SPLIT = 'even_split'

_SPECIFICITY_INSTRUCTIONS = {
    SPECIFICITY_MATCH_TO_STAGE: (
        "For \"specificity\": match it to where the question sits in the "
        "funnel — early-funnel questions are broad, and questions close to "
        "purchase are narrow and concrete."
    ),
    SPECIFICITY_EVEN_SPLIT: (
        "For \"specificity\": spread the questions roughly evenly across the "
        "allowed values, independently of stage."
    ),
}


def _build_general_prompt(
    study_name: str,
    description: str,
    stage_counts: dict,
    allowed_categories: list,
    study_pattern: str,
    already_generated: list,
    retailer_names: Optional[list] = None,
    naming_rule_enabled: bool = True,
    personas: Optional[list] = None,
    specificity_mode: str = SPECIFICITY_MATCH_TO_STAGE,
) -> str:
    """
    The general-study counterpart to _build_lite_prompt.

    Only allowed_categories is rendered into the constraints text, not
    the whole of QUERY_CATEGORIES. A study about prestige beauty has no
    business being offered 'Baby Care' as a choice, and the cheapest way
    to stop a category appearing in the output is to never put it in the
    prompt. The filter in generate_general_queries is the enforcement;
    this is the hint. personas narrows the same way when the caller
    supplied a list — but unlike category it is NOT enforced by a drop:
    a persona label outside the requested set is a mislabelled row, not a
    question about the wrong subject, and throwing away an otherwise good
    question over it costs more than it saves.

    study_pattern is stated, not asked for. It is a property of the
    study, not of each question, and a model that emits it per row will
    hand back a mix — which changes the coding rubric from query to query
    while every row still looks individually valid.

    retailer_names are the entities to name in question text. The list is
    presented in a ROTATED order per call (see generate_general_queries)
    rather than always in the caller's order: a model handed the same
    list every time tends to reach for the first name in it, which is how
    a study ends up naming one retailer in ten of eleven head-to-heads —
    and such a study cannot be reused with a different primary entity,
    which is the whole point of reuse across cycles.

    naming_rule_enabled generalises the rule already hardcoded in
    _build_lite_prompt: names appear only in Comparison and Ready to Buy
    questions, so an Awareness or Research mention has to be earned by
    the answer rather than prompted by the question.
    """
    constraint_values = dict(QUERY_CONSTRAINTS)
    constraint_values['category'] = list(allowed_categories)
    if personas:
        constraint_values['persona'] = list(personas)
    constraints_text = "\n".join(
        f"- {field}: one of {', '.join(repr(v) for v in vals)}"
        for field, vals in constraint_values.items()
        if field != 'study_pattern'
    )

    distribution_text = "\n".join(
        f"- {count} {stage!r} stage question(s)"
        for stage, count in stage_counts.items()
        if count > 0
    )
    total = sum(stage_counts.values())

    avoid_text = ""
    if already_generated:
        avoid_text = (
            "\n\nDo NOT repeat or closely paraphrase these already-generated questions:\n"
            + "\n".join(f"- {q}" for q in already_generated)
        )

    specificity_text = _SPECIFICITY_INSTRUCTIONS.get(
        specificity_mode, _SPECIFICITY_INSTRUCTIONS[SPECIFICITY_MATCH_TO_STAGE],
    )

    names = list(retailer_names or [])
    if names:
        naming_text = (
            f"\nThe retailers to name are: {', '.join(names)}. "
            f"Spread the mentions across all of them — do not lead with the "
            f"same one every time."
        )
        if naming_rule_enabled:
            naming_text += (
                f"\n\nCritical rule on naming: only 'Comparison' and 'Ready to Buy' "
                f"questions may name a retailer. 'Awareness' and 'Research' questions "
                f"must describe the shopper's need in category-level terms WITHOUT "
                f"naming any of them, so that a mention in a good answer is earned "
                f"rather than prompted by the question itself."
            )
    else:
        # An UNBRANDED study: no retailers to name anywhere. This is the
        # strictest form of a share-of-mentions measurement, not a
        # degraded one — nothing in the question can prompt a mention, so
        # every mention in an answer has been earned.
        #
        # Emitted regardless of naming_rule_enabled, which is the fix for
        # a real gap: the rule governs WHERE names may appear, so with no
        # names there is nothing for it to govern, and the old code left
        # the prompt completely silent about naming whenever the rule was
        # off. Silent means the model decides, and what it decides is to
        # invent retailers — the one thing an unbranded study must not
        # contain.
        #
        # The Comparison-stage sentence is the other half. 'Comparison'
        # normally means retailer-vs-retailer, and a model handed that
        # stage with no names to use will either invent some or produce
        # something shapeless. Saying what a comparison compares INSTEAD
        # is what keeps the stage meaningful.
        naming_text = (
            "\nThis is an UNBRANDED study. Do not name specific retailers or "
            "brands in any question, at any stage — not even as an example. "
            "Every question must describe the shopper's need in category-level "
            "terms, so that any retailer or brand a good answer mentions has "
            "been earned by the answer rather than prompted by the question."
            "\n\n'Comparison' stage questions must still genuinely compare — but "
            "they weigh PRODUCTS, product types and buying criteria against each "
            "other (formulation, price tier, ingredients, longevity, value, "
            "suitability for a need), never one retailer against another."
        )

    return f"""Generate exactly {total} distinct search-style questions for a brand/market research study called "{study_name}".

Study description: {description or 'No additional description provided.'}

Distribute the {total} questions EXACTLY as follows:
{distribution_text}

Each question becomes one row in a database table. For EACH question provide ALL of these fields. Every field value MUST be one of the exact allowed values listed — do not invent new values:

{constraints_text}

For "category": choose only from the values listed above. Every question must be about a subject that genuinely belongs to one of them — if a question would need a category outside that list, do not ask it.
For "status": always 'Active'.
{specificity_text}
{naming_text}

Also provide:
- query_text: the actual question/prompt a user might type into an AI assistant or search engine
- soa_focus: 1-3 comma-separated metric names this query is designed to test (free text, e.g. "Mention Rate, RSI")
- rationale: one sentence explaining why this query is useful for the study (free text)

Respond with ONLY a JSON array of {total} objects, each with keys:
query_text, category, stage, specificity, persona, status, subscription_state, soa_focus, rationale.
No markdown, no explanation, just the JSON array.{avoid_text}"""


def generate_general_queries(
    study_name: str,
    description: str,
    stage_targets: dict,
    allowed_categories: list,
    study_pattern: str,
    api_key: str,
    retailer_names: Optional[list] = None,
    rotate_named_retailer: bool = True,
    naming_rule_enabled: bool = True,
    personas: Optional[list] = None,
    specificity_mode: str = SPECIFICITY_MATCH_TO_STAGE,
) -> tuple:
    """
    The general-study path: caller-supplied per-stage targets, a
    caller-supplied category allow-list, and a study_pattern stamped onto
    every row rather than chosen per row by the model.

    Returns (rows, report). It does NOT raise on shortfall, which is the
    substantive difference from generate_lite_queries. Lite is a fixed
    24-question public artifact where a lopsided distribution makes the
    report itself misleading, so failing is honest. A general study is
    fifty-odd questions built over several model calls; hard-failing
    because three Comparison rows are missing throws away forty-seven
    good queries to punish a shortfall a human can see and fix in a
    minute. So it reports.

    The report names, per stage, what was requested and what was
    delivered, plus every row dropped as an exact duplicate, every row
    dropped for an out-of-list category, and how many replacement rounds
    ran. Phase-three provenance is assembled on top of it.

    Three things are deliberately NOT done here:

    A row whose category falls outside allowed_categories is DROPPED, not
    relabelled. Rewriting it to the nearest allowed value is the cheap
    edit and it is the wrong one: it converts a visible scope violation
    into a clean-looking row, and the underlying problem — the generator
    drifted off the brief — disappears from the record. Dropping it
    leaves the drift visible in the report where someone can act on it.

    Exact duplicates are removed automatically; nothing else is. Rows
    that merely look similar are the semantic review pass's business, and
    that pass is advisory.

    Replacement generation is bounded at REPLACEMENT_ROUNDS. Each round
    re-enters validation, the category filter and dedupe, because a
    replacement can perfectly well collide with something already kept
    or wander out of scope itself.
    """
    stage_targets = {k: v for k, v in stage_targets.items() if v > 0}
    allowed = set(allowed_categories)

    kept: list = []
    duplicates: list = []
    category_drops: list = []
    seen_keys: set = set()

    def _accept(row):
        """Runs before a row is bucketed, so a rejected row never
        occupies a slot. Deduping AFTER bucketing looks equivalent and
        is not: a stage capped at two rows that receives the same
        question twice fills up on the duplicate pair and discards a
        third, unique, perfectly good row as overflow — then goes back to
        the model for a replacement it already had in hand."""
        if row.get('category') not in allowed:
            reason = (
                f"category {row.get('category')!r} is outside the study's "
                f"allowed categories"
            )
            category_drops.append({
                'query_text': row.get('query_text'),
                'category':   row.get('category'),
                'reason':     reason,
            })
            return reason
        key = normalize_query_text(row.get('query_text'))
        if key in seen_keys:
            duplicates.append(row)
            return "exact duplicate of a question already generated"
        seen_keys.add(key)
        return None

    names = list(retailer_names or [])
    prompt_calls = {'n': 0}

    def _rotated_names():
        """Presents the retailer list starting from a different name on
        each call. Asking the model to spread mentions is necessary and
        not sufficient — handed the same order every time it reaches for
        whatever is first, which is exactly how one retailer ended up
        named in ten of eleven head-to-heads. Rotating the ORDER costs
        nothing and does not depend on the model cooperating."""
        # `not names` guards the unbranded study: an empty list has
        # nothing to rotate, and `% len(names)` on it would raise
        # ZeroDivisionError on the very first prompt. Returning the empty
        # list unchanged is what makes rotation a no-op rather than a
        # crash, whatever rotate_named_retailer says.
        if not names or not rotate_named_retailer:
            return names
        offset = prompt_calls['n'] % len(names)
        return names[offset:] + names[:offset]

    def _build(shortfall, accepted_rows):
        # The avoid-list is the FULL keep-list, not just what this
        # helper pass has bucketed. A replacement round opens a fresh
        # pass, so its first prompt starts with an empty accepted list —
        # without kept, a replacement for a deduped row would be written
        # by a model that cannot see any of the rows it must not repeat,
        # which is how the duplicate got there in the first place.
        avoid = [row['query_text'] for row in kept]
        avoid += [row['query_text'] for row in accepted_rows]
        prompt = _build_general_prompt(
            study_name, description, shortfall, allowed_categories,
            study_pattern, avoid,
            retailer_names=_rotated_names(),
            naming_rule_enabled=naming_rule_enabled,
            personas=personas,
            specificity_mode=specificity_mode,
        )
        prompt_calls['n'] += 1
        return prompt

    stamp = {'study_pattern': study_pattern}

    calls = 0
    rounds = 0
    remaining = dict(stage_targets)

    while True:
        result = _fill_stage_buckets(
            targets=remaining,
            build_prompt=_build,
            api_key=api_key,
            retry_budget=RETRY_BUDGET_GENERAL,
            on_shortfall=SHORTFALL_REPORT,
            accept_row=_accept,
            stamp=stamp,
            label='[generation] ',
        )
        calls += result['calls']

        fresh = [
            row for stage in remaining for row in result['buckets'][stage]
        ]
        # _accept has already rejected anything colliding with seen_keys,
        # so this pass should find nothing. It stays as the belt to
        # _accept's braces: dedupe_exact is the module's definition of a
        # duplicate, and a future edit to _accept that stops matching it
        # should surface as a reported duplicate rather than as a
        # duplicate row in a study.
        survivors, dropped = dedupe_exact(kept + fresh)
        kept = survivors
        duplicates.extend(dropped)

        delivered = _count_by_stage(kept)
        remaining = {
            stage: target - delivered.get(stage, 0)
            for stage, target in stage_targets.items()
            if delivered.get(stage, 0) < target
        }

        if not remaining or rounds >= REPLACEMENT_ROUNDS:
            break
        rounds += 1
        log.info(
            f"[generation] replacement round {rounds}: still short {remaining}"
        )

    delivered = _count_by_stage(kept)
    report = {
        'requested_by_stage': dict(stage_targets),
        'delivered_by_stage': {
            stage: delivered.get(stage, 0) for stage in stage_targets
        },
        'shortfall_by_stage': {
            stage: target - delivered.get(stage, 0)
            for stage, target in stage_targets.items()
            if delivered.get(stage, 0) < target
        },
        'duplicates_dropped': duplicates,
        'category_drops': category_drops,
        'replacement_rounds': rounds,
        'generation_calls':   calls,
        'retailers_named':    names,
        'naming_rule_enabled': naming_rule_enabled,
        'specificity_mode':   specificity_mode,
    }
    return kept, report


def generate_and_review_study(
    study_name: str,
    description: str,
    stage_targets: dict,
    allowed_categories: list,
    study_pattern: str,
    api_key: str,
    retailer_names: Optional[list] = None,
    rotate_named_retailer: bool = True,
    naming_rule_enabled: bool = True,
    personas: Optional[list] = None,
    specificity_mode: str = SPECIFICITY_MATCH_TO_STAGE,
) -> tuple:
    """
    The whole general path in one call: generate, then review, then
    account for what happened. Returns (rows, provenance).

    The ordering is the reason this is a function rather than three calls
    at the call site. Both review passes run on the rows that SURVIVED
    exact dedupe — reviewing the pre-dedupe set would report every
    removed duplicate a second time as a semantic one, burying the
    findings that need a human under the ones already handled.

    rows is exactly what generate_general_queries returned: the reviews
    are advisory and remove nothing. A caller that persists rows should
    persist these and surface the provenance alongside them.
    """
    rows, report = generate_general_queries(
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

    semantic_groups = review_semantic_duplicates(rows, api_key)
    coherence_findings = review_coherence(
        rows, study_name, description, allowed_categories, api_key,
    )

    provenance = build_provenance_record(
        rows, report, semantic_groups, coherence_findings,
    )
    return rows, provenance


# ─── Review passes ────────────────────────────────────────────────────────
#
# Both are ADVISORY. Exact-match dedupe is the only fully automatic
# removal in this module; everything below produces findings for a human
# to look at and produces no side effects at all. That line is
# deliberate: a semantic judgement or a scope judgement made by a model
# at generation time, applied silently, is indistinguishable afterwards
# from the generator having simply written fewer questions.
#
# Both run at REVIEW_TEMPERATURE. These are classification tasks, not
# generation: at the generation default of 0.8 the same fifty rows get
# grouped differently on consecutive runs, and an advisory finding a
# reviewer cannot reproduce is worse than none.
#
# Both degrade to empty findings on any malformed or unreadable model
# output. A review pass that fails must never block study creation —
# it is a second opinion, and the study is already generated by the time
# it runs.

REVIEW_TEMPERATURE = 0

COHERENCE_OK = 'ok'
COHERENCE_LABEL_MISMATCH = 'label_mismatch'
COHERENCE_OUT_OF_SCOPE = 'out_of_scope'
_COHERENCE_VERDICTS = {
    COHERENCE_OK, COHERENCE_LABEL_MISMATCH, COHERENCE_OUT_OF_SCOPE,
}


def _numbered_questions(rows: list) -> str:
    return "\n".join(
        f"{i + 1}. {row.get('query_text', '')}" for i, row in enumerate(rows)
    )


def _build_semantic_duplicate_prompt(rows: list) -> str:
    return f"""Below is a numbered list of questions from a single market research study.

{_numbered_questions(rows)}

Find GROUPS of questions that are REDUNDANT — the same question asked twice in different words.

The test for a group is deletion. A set of questions is a group only if DELETING ANY ONE OF THEM would lose no information the remaining members do not already cover. If removing a question would cost the study an answer it would not otherwise get, that question does not belong in the group.

Group them. Do NOT compare every possible pair; work by reading the list and collecting the ones that belong together.

These are NOT redundancy, and none of them is a reason to group:
- A shared topic. Twenty questions about prestige beauty are twenty questions.
- A shared category. Everything filed under Skincare is not one question.
- A shared retailer. "Mentions Sephora" is not a redundancy.
- A shared question shape. "What is the best X for Y?" asked about six different products is six questions.

Two checks on your own reason text, before you return a group:
- If the reason needs the word "different" or "distinct" to describe the members, they are not redundant. You have found a topic cluster. Do not return it.
- If the reason has to join several subjects with "or" — selection, pricing, promotions or loyalty — you are describing a theme that spans several questions, not one question asked twice. Do not return it.

Output that must NEVER be produced, both real and both wrong:
- "These are all distinct prestige beauty topic questions about different products, ingredients, routines, or use cases." — this says the members are distinct. Distinct questions are not duplicates.
- "These all ask about Sephora vs Ulta prestige skincare selection, pricing, promotions, or loyalty value" — four subjects joined by "or" is a topic cluster.

A correct group looks like this: one question asking whether Sephora's loyalty program makes prestige skincare cheaper, and another asking whether joining Sephora's rewards program lowers what you pay for prestige skincare. Same question, same answer, different words. Delete either one and nothing is lost.

Genuine groups are small — two questions, occasionally three. If you find yourself collecting seven or twenty questions into one group, you have switched from finding duplicates to sorting by topic. Stop and discard that group.

Returning an empty array is a perfectly good answer, and the expected one for a well-formed study. Do not manufacture groups to appear thorough.

Return ONLY a JSON array. Each element is one group:
- members: array of the question numbers in this group (at least 2)
- keep: the ONE question number in this group that best represents it
- reason: one short sentence saying what makes them redundant

No markdown, no explanation, just the JSON array."""


# ─── Guards on the semantic duplicate pass ───────────────────────────────
#
# These run in code, after the model responds, and none of them depends on
# the model cooperating. That is the point. The failure they exist for was
# a model that grouped 46 of 52 queries into five "duplicate" groups and
# wrote, as its own justification for the largest of them, "These are all
# distinct prestige beauty topic questions about different products,
# ingredients, routines, or use cases." It asserted the members were
# distinct and recommended deleting 21 of 22 in the same breath. A prompt
# change alone cannot be trusted against a model willing to write that.

# Genuine redundancy is two questions, occasionally three. Twenty-two is
# not a duplicate group by any reading.
MAX_DUPLICATE_GROUP_SIZE = 3

# Words that, in a reason for grouping, deny the grouping. Substring
# match, case-insensitive, deliberately crude — "differently" and
# "differences" carry the same signal and should also be caught. The
# false positive this admits ("indifferent") does not occur in this
# vocabulary, and catching a real one matters more than dodging it.
_REDUNDANCY_DENYING_WORDS = ('different', 'distinct')

DISCARD_OVERSIZED = 'oversized'
DISCARD_MIXED_LABELS = 'mixed_labels'
DISCARD_REASON_DENIES_REDUNDANCY = 'reason_denies_redundancy'


def _duplicate_group_discard_reasons(finding: dict, rows: list) -> list:
    """
    Every guard a group trips, or [] if it survives. Returns all of them
    rather than the first, because a group that is both oversized AND
    self-contradicting says something different about the pass than one
    that is merely large.
    """
    tripped = []
    members = finding.get('members') or []

    if len(members) > MAX_DUPLICATE_GROUP_SIZE:
        tripped.append(DISCARD_OVERSIZED)

    # Two questions filed under different categories are almost never the
    # same question, and the same holds for funnel stage: an Awareness
    # question and a Research question are asked by different shoppers at
    # different moments even when the words overlap. The failing group
    # one mixed Skincare, Makeup and Fragrance across Awareness and
    # Research, and this guard alone would have caught it.
    categories = {rows[i].get('category') for i in members if i < len(rows)}
    stages = {rows[i].get('stage') for i in members if i < len(rows)}
    if len(categories) > 1 or len(stages) > 1:
        tripped.append(DISCARD_MIXED_LABELS)

    reason = (finding.get('reason') or '').lower()
    if any(word in reason for word in _REDUNDANCY_DENYING_WORDS):
        tripped.append(DISCARD_REASON_DENIES_REDUNDANCY)

    return tripped


def _apply_duplicate_group_guards(findings: list, rows: list) -> tuple:
    """
    Splits candidate groups into (kept, discarded).

    An oversized group is DISCARDED, never truncated to its first three
    members. The model's ordering carries no signal about which members
    are the real pair, so truncation would invent a finding out of an
    arbitrary slice — and the observed failure had two genuine pairs
    buried inside a nine-member group, which truncation would have
    replaced with three unrelated queries wearing a duplicate label.
    Discarding loses those pairs; fabricating a different finding is
    worse, and the count recorded in provenance is what makes the loss
    visible.
    """
    kept, discarded = [], []
    for finding in findings:
        tripped = _duplicate_group_discard_reasons(finding, rows)
        if not tripped:
            kept.append(finding)
            continue
        record = {
            'size': len(finding.get('members') or []),
            'guards': tripped,
            'reason': finding.get('reason', ''),
        }
        discarded.append(record)
        log.warning(
            f"[review] discarded a semantic duplicate group of "
            f"{record['size']} on {', '.join(tripped)} — reason was: "
            f"{record['reason']!r}"
        )
    return kept, discarded


class DuplicateReviewFindings(list):
    """
    The kept findings, carrying what the guards threw away.

    A plain list subclass rather than a (findings, discards) tuple
    deliberately: review_semantic_duplicates' return type is part of an
    existing contract — callers compare it to [], take len() of it and
    index into it, and generate_and_review_study's own tests patch the
    function with a two-argument stand-in that returns a bare list.
    Widening the signature or the return type would break those. A list
    that is still a list, with an extra attribute the composition reads
    through getattr, changes nothing for any existing caller and lets a
    mocked plain [] report zero discards truthfully.
    """
    def __init__(self, findings=(), discarded=()):
        super().__init__(findings)
        self.discarded = list(discarded)

    @property
    def discarded_count(self):
        return len(self.discarded)


def review_semantic_duplicates(rows: list, api_key: str) -> list:
    """
    Advisory review of the rows that survived exact dedupe: which of them
    are the same question written twice?

    The model is asked to GROUP, not to compare pairs. Across fifty items
    that is the difference between a task models do reliably and one they
    do not: exhaustive pairwise comparison is 1,225 judgements, and a
    model asked for it produces a plausible-looking list that is mostly
    noise. Grouping is one pass over the list.

    The case this exists for looks like two questions asking for the best
    prestige vitamin C serum, one phrased for brightening dull skin and
    one for brightening and uneven tone. Different surface text, so exact
    matching cannot see it; overlapping vocabulary, so string similarity
    calls it ambiguous either way.

    What the model returns is then put through _apply_duplicate_group_guards
    before anyone sees it — a size cap, a same-category/same-stage check
    and a self-contradiction check on the reason text. The prompt asks for
    redundancy; the guards are what make the answer trustworthy when it
    does not. Discarded groups never reach the review panel, and their
    count reaches provenance so a study where this pass misbehaved reads
    differently from one that genuinely had nothing to report.

    Returns findings ONLY. Never mutates rows, never drops a QUERY —
    "discard" here means discarding a model finding, not a question.
    Returns [] if there is nothing to review or the model output cannot
    be read.
    """
    if len(rows) < 2:
        return DuplicateReviewFindings()

    parsed = _safe_review_call(
        _build_semantic_duplicate_prompt(rows), api_key, "semantic duplicate",
    )
    if not parsed:
        return DuplicateReviewFindings()

    findings = []
    for group in parsed:
        if not isinstance(group, dict):
            continue
        members = _valid_indexes(group.get('members'), len(rows))
        if len(members) < 2:
            continue
        keep = _valid_indexes([group.get('keep')], len(rows))
        # A recommendation outside its own group is not a
        # recommendation; fall back to the first member rather than
        # discarding an otherwise usable finding.
        keep_index = keep[0] if keep and keep[0] in members else members[0]
        findings.append({
            'members':      members,
            'member_texts': [rows[i].get('query_text') for i in members],
            'keep':         keep_index,
            'keep_text':    rows[keep_index].get('query_text'),
            'reason':       str(group.get('reason') or '').strip(),
        })

    kept, discarded = _apply_duplicate_group_guards(findings, rows)
    if discarded:
        log.warning(
            f"[review] semantic duplicate pass: kept {len(kept)} group(s), "
            f"discarded {len(discarded)}"
        )
    return DuplicateReviewFindings(kept, discarded)


def _build_coherence_prompt(
    rows: list,
    study_name: str,
    description: str,
    allowed_categories: list,
) -> str:
    categories_text = ", ".join(repr(c) for c in allowed_categories)
    return f"""You are reviewing the questions in a market research study for coherence with the study's own brief.

Study name: {study_name}
Study description: {description or 'No additional description provided.'}
Allowed categories: {categories_text}

Here are the questions, each with the category it was labelled with:

{chr(10).join(
    f"{i + 1}. [{row.get('category')}] {row.get('query_text', '')}"
    for i, row in enumerate(rows)
)}

Classify EACH question into exactly ONE of these three verdicts:

- "ok": the question fits the study's stated subject, and its label is right.

- "label_mismatch": the question's SUBJECT genuinely belongs to this study, but a field on it carries the wrong value. Name the field and the corrected value.

- "out_of_scope": the question's SUBJECT does not belong to this study at all.

The distinction between the last two is the whole point of this review, and the tempting answer is usually the wrong one. Ask first whether the question's subject belongs in this study. Only if it does may you call a wrong label a label_mismatch.

Worked example. A study of prestige beauty products contains "Where can I get the best price on a Dyson Airwrap?", labelled category 'Skincare'. The cheap answer is label_mismatch with a corrected category of 'Haircare', after which the row looks clean. That answer is wrong. A hair-styling appliance is not a prestige beauty product, so the question does not belong in this study whatever it is labelled; the real defect is that the generator drifted off the brief, and relabelling it hides that. The correct verdict is out_of_scope.

So: when a question's subject sits outside the study's stated scope, it is out_of_scope even if some allowed category label would technically fit it.

Return ONLY a JSON array with one element per question:
- index: the question number
- verdict: "ok", "label_mismatch" or "out_of_scope"
- field: for label_mismatch only, the name of the field that is wrong
- proposed_value: for label_mismatch only, the corrected value for that field
- reason: for out_of_scope only, one short sentence on why the subject does not belong

No markdown, no explanation, just the JSON array."""


def review_coherence(
    rows: list,
    study_name: str,
    description: str,
    allowed_categories: list,
    api_key: str,
) -> list:
    """
    Advisory review of each row against the study's own brief: does this
    question belong in this study, and is it labelled correctly?

    Returns one finding per row the model classified as something other
    than ok. Never mutates rows and never applies a proposed correction —
    a label_mismatch is a suggestion for a human, and an out_of_scope row
    is a signal that the generator drifted, which is worth seeing rather
    than tidying away.

    Returns [] if there is nothing to review or the model output cannot
    be read.
    """
    if not rows:
        return []

    parsed = _safe_review_call(
        _build_coherence_prompt(rows, study_name, description, allowed_categories),
        api_key,
        "coherence",
    )
    if not parsed:
        return []

    findings = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        indexes = _valid_indexes([item.get('index')], len(rows))
        if not indexes:
            continue
        index = indexes[0]
        verdict = item.get('verdict')
        if verdict not in _COHERENCE_VERDICTS or verdict == COHERENCE_OK:
            continue
        finding = {
            'index':      index,
            'query_text': rows[index].get('query_text'),
            'category':   rows[index].get('category'),
            'verdict':    verdict,
            'reason':     str(item.get('reason') or '').strip(),
        }
        if verdict == COHERENCE_LABEL_MISMATCH:
            finding['field'] = item.get('field')
            finding['proposed_value'] = item.get('proposed_value')
        findings.append(finding)
    return findings


def _safe_review_call(prompt: str, api_key: str, label: str) -> Optional[list]:
    """
    Runs a review prompt at REVIEW_TEMPERATURE and swallows every
    failure, returning None. A review pass is a second opinion on a study
    that already exists; letting it raise would mean a flaky OpenAI call
    could fail a study creation that had otherwise completely succeeded.
    """
    try:
        return _call_openai_for_json(prompt, api_key, temperature=REVIEW_TEMPERATURE)
    except Exception as e:
        log.error(f"{label} review failed, degrading to no findings: {e}")
        return None


def _valid_indexes(values, length: int) -> list:
    """
    Converts the model's 1-based question numbers into 0-based row
    indexes, discarding anything out of range or not a number. Order is
    preserved and repeats are collapsed.

    The model is given a 1-based list because that is what a human
    reading the same list sees, and the findings are for humans. Nothing
    downstream should have to know that, so the conversion happens here
    and findings carry ordinary row indexes.
    """
    if not isinstance(values, (list, tuple)):
        return []
    seen = set()
    out = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        index = number - 1
        if index < 0 or index >= length or index in seen:
            continue
        seen.add(index)
        out.append(index)
    return out


def build_provenance_record(
    rows: list,
    report: dict,
    semantic_groups: Optional[list] = None,
    coherence_findings: Optional[list] = None,
    discarded_duplicate_groups: Optional[list] = None,
) -> dict:
    """
    Everything that happened to a generated study, in one structure: what
    was asked for, what was delivered, what was removed automatically and
    what was merely flagged.

    The automatic/advisory split is the reason this exists. Exact
    duplicates are gone by the time anyone sees the study, so the record
    names them and their text. Semantic groups, coherence findings and
    category drops are judgements — the first two applied to nothing at
    all, the third having dropped a row rather than quietly rewriting it
    — and a reviewer needs to be able to tell those apart at a glance.
    """
    # Read the carried discards BEFORE normalising, and normalise on
    # `is None` rather than truthiness. A DuplicateReviewFindings that
    # kept nothing is an empty list and therefore falsy, so `or []` would
    # swap it for a bare list and throw the discards away — in exactly
    # the case they matter most, where every group the model returned was
    # thrown out and the count is the only thing distinguishing that from
    # a clean study.
    if discarded_duplicate_groups is None:
        discarded_duplicate_groups = list(getattr(semantic_groups, 'discarded', None) or [])
    semantic_groups = semantic_groups if semantic_groups is not None else []
    coherence_findings = coherence_findings if coherence_findings is not None else []

    by_outcome: dict = {
        COHERENCE_LABEL_MISMATCH: [],
        COHERENCE_OUT_OF_SCOPE: [],
    }
    for finding in coherence_findings:
        by_outcome.setdefault(finding.get('verdict'), []).append(finding)

    duplicates = report.get('duplicates_dropped') or []

    return {
        'rows_generated':      len(rows),
        'requested_by_stage':  report.get('requested_by_stage', {}),
        'delivered_by_stage':  report.get('delivered_by_stage', {}),
        'shortfall_by_stage':  report.get('shortfall_by_stage', {}),
        'replacement_rounds':  report.get('replacement_rounds', 0),
        'generation_calls':    report.get('generation_calls', 0),

        # Echoed from the brief. A record of what happened is not much
        # use without a record of what was asked for — reading "one
        # retailer named in ten of eleven" only means something next to
        # the list of retailers that were supposed to be spread across
        # them, and next to whether rotation was even switched on.
        'retailers_named':     report.get('retailers_named', []),
        'naming_rule_enabled': report.get('naming_rule_enabled'),
        'specificity_mode':    report.get('specificity_mode'),

        # Automatic — these rows are not in the study.
        'exact_duplicates_dropped': [
            {'query_text': row.get('query_text'), 'stage': row.get('stage')}
            for row in duplicates
        ],
        'category_drops': report.get('category_drops', []),

        # Advisory — nothing was applied.
        'semantic_duplicate_groups': list(semantic_groups),

        # Groups the guards threw out before a human could see them.
        # Recorded because the alternative is indistinguishable from a
        # clean study: a pass that returned five topic clusters and a
        # pass that correctly found nothing both surface zero findings,
        # and only this number tells them apart after the fact.
        'semantic_groups_discarded': len(discarded_duplicate_groups),
        'semantic_group_discards': discarded_duplicate_groups,
        'coherence_findings_by_outcome': {
            COHERENCE_LABEL_MISMATCH: by_outcome.get(COHERENCE_LABEL_MISMATCH, []),
            COHERENCE_OUT_OF_SCOPE:   by_outcome.get(COHERENCE_OUT_OF_SCOPE, []),
        },
        'coherence_ok_count': len(rows) - len(coherence_findings),
    }


def generate_lite_queries(
    brand_name: str,
    competitor_names: list,
    api_key: str,
) -> list:
    """
    Generates a fixed LITE_QUERY_COUNT-query SoA Lite study: exactly
    LITE_QUERIES_PER_STAGE queries per QUERY_STAGES stage (Stage 25:
    bumped from 3/stage to 6/stage — soa_shared.scan_dimensions is the
    one place this count is defined). The distribution is enforced, not
    just requested in the prompt — see _fill_stage_buckets, which this
    shares with the general path: validated rows are bucketed by stage,
    and if any stage is short after the first call, ONE targeted
    regeneration call (retry_budget=1) asks only for the shortfall
    stages/counts. If still short after that retry, SHORTFALL_RAISE
    raises LiteGenerationError with the message this function supplies: a
    partial lite study (e.g. 5 Comparison questions instead of 6) would
    skew the resulting report, so it's better to fail the request
    outright. The general path passes SHORTFALL_REPORT for the opposite
    reason — see generate_general_queries.
    """
    targets = {stage: LITE_QUERIES_PER_STAGE for stage in QUERY_STAGES}

    def _build(shortfall, accepted_rows):
        return _build_lite_prompt(
            brand_name,
            competitor_names,
            shortfall,
            [row['query_text'] for row in accepted_rows],
        )

    def _message(shortfall):
        return (
            f"Could not generate {LITE_QUERIES_PER_STAGE} valid queries for "
            f"stage(s) {list(shortfall.keys())} after retry — shortfall={shortfall}"
        )

    result = _fill_stage_buckets(
        targets=targets,
        build_prompt=_build,
        api_key=api_key,
        retry_budget=1,
        on_shortfall=SHORTFALL_RAISE,
        shortfall_message=_message,
        label='[lite] ',
    )

    buckets = result['buckets']
    return [row for stage in QUERY_STAGES for row in buckets[stage]]
