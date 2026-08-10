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
"""

import json
import logging
from typing import Optional
from openai import OpenAI
from soa_shared.constants import QUERY_CONSTRAINTS, QUERY_STAGES
from soa_shared.scan_dimensions import LITE_QUERIES_PER_STAGE

log = logging.getLogger(__name__)

BATCH_SIZE = 10

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
# SUBSCRIPTION_STATES docstring. The general generation prompt
# (_build_prompt) never asks for it — only curated/seeded studies and
# the SoA Lite prompt (_build_lite_prompt) populate it deliberately —
# so treating an absent value as invalid rejected 100% of every
# generally-generated row deterministically, not from any LLM flakiness.
_NULLABLE_CONSTRAINED_FIELDS = {'subscription_state'}


class LiteGenerationError(Exception):
    """Raised when generate_lite_queries cannot reach LITE_QUERIES_PER_STAGE
    valid queries for every stage even after the targeted shortfall retry."""


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

    avoid_text = ""
    if already_generated:
        avoid_text = (
            "\n\nDo NOT repeat or closely paraphrase these already-generated questions:\n"
            + "\n".join(f"- {q}" for q in already_generated[-20:])
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
query_text, category, stage, specificity, persona, study_pattern, status, soa_focus, rationale.
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


def _call_openai_and_validate(prompt: str, api_key: str) -> tuple:
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
    """
    client = OpenAI(api_key=api_key)

    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
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
        return [], None

    # Handle both raw array and {"questions": [...]} shapes
    if isinstance(parsed, dict):
        for key in ('questions', 'queries', 'items', 'data'):
            if key in parsed:
                parsed = parsed[key]
                break

    if not isinstance(parsed, list):
        log.error(f"Expected JSON array, got: {type(parsed)}")
        return [], None

    valid_rows = []
    row_errors = []
    for row in parsed:
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
    """
    prompt = _build_prompt(study_name, description, batch_size, already_generated)
    return _call_openai_and_validate(prompt, api_key)


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


def generate_lite_queries(
    brand_name: str,
    competitor_names: list,
    api_key: str,
) -> list:
    """
    Generates a fixed LITE_QUERY_COUNT-query SoA Lite study: exactly
    LITE_QUERIES_PER_STAGE queries per QUERY_STAGES stage (Stage 25:
    bumped from 3/stage to 6/stage — soa_shared.scan_dimensions is the
    one place this count is defined). The distribution is enforced here,
    not just requested in the prompt — validated rows are bucketed by
    stage, and if any stage is short after the first call, ONE targeted
    regeneration call asks only for the shortfall stages/counts. If still
    short after that retry, raises LiteGenerationError: a partial lite
    study (e.g. 5 Comparison questions instead of 6) would skew the
    resulting report, so it's better to fail the request outright.
    """
    buckets: dict = {stage: [] for stage in QUERY_STAGES}

    def _bucket(rows):
        for row in rows:
            stage = row.get('stage')
            bucket = buckets.get(stage)
            if bucket is not None and len(bucket) < LITE_QUERIES_PER_STAGE:
                bucket.append(row)

    def _already_generated():
        return [row['query_text'] for bucket in buckets.values() for row in bucket]

    def _shortfall():
        return {
            stage: LITE_QUERIES_PER_STAGE - len(bucket)
            for stage, bucket in buckets.items()
            if len(bucket) < LITE_QUERIES_PER_STAGE
        }

    # _call_openai_and_validate's deterministic_failure_reason isn't
    # separately branched on here — the lite prompt already asks for
    # every QUERY_CONSTRAINTS field explicitly (including
    # subscription_state), and the existing shortfall-retry below
    # already sends a DIFFERENT, narrower targeted prompt rather than
    # blindly repeating the same request, so it isn't the "retrying
    # would not help" case that reason exists to short-circuit.
    initial_counts = {stage: LITE_QUERIES_PER_STAGE for stage in QUERY_STAGES}
    prompt = _build_lite_prompt(brand_name, competitor_names, initial_counts, [])
    rows, _reason = _call_openai_and_validate(prompt, api_key)
    _bucket(rows)

    shortfall = _shortfall()
    if shortfall:
        log.warning(f"[lite] stage shortfall after first call: {shortfall} — retrying")
        retry_prompt = _build_lite_prompt(
            brand_name, competitor_names, shortfall, _already_generated(),
        )
        retry_rows, _reason = _call_openai_and_validate(retry_prompt, api_key)
        _bucket(retry_rows)

    shortfall = _shortfall()
    if shortfall:
        raise LiteGenerationError(
            f"Could not generate {LITE_QUERIES_PER_STAGE} valid queries for "
            f"stage(s) {list(shortfall.keys())} after retry — shortfall={shortfall}"
        )

    return [row for stage in QUERY_STAGES for row in buckets[stage]]
