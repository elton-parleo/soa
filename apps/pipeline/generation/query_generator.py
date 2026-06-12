"""
Generates soa_queries rows via OpenAI based on a study name and description.
Validates each generated row against QUERY_CONSTRAINTS before returning.
Invalid rows are skipped and logged — partial success is acceptable for AI
generation (unlike CSV upload which is all-or-nothing).
"""

import json
import logging
from openai import OpenAI
from soa_shared.constants import QUERY_CONSTRAINTS

log = logging.getLogger(__name__)

BATCH_SIZE = 10


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
    Checks constrained fields against QUERY_CONSTRAINTS.
    Returns (cleaned_row, errors). errors is empty if the row is valid.
    """
    errors = []

    query_text = (row.get('query_text') or '').strip()
    if not query_text:
        errors.append('query_text is empty')

    cleaned = {
        'query_text': query_text,
        'soa_focus':  row.get('soa_focus'),
        'rationale':  row.get('rationale'),
    }

    for field, allowed in QUERY_CONSTRAINTS.items():
        val = row.get(field)
        if val not in allowed:
            errors.append(
                f"{field}={val!r} not in allowed values"
            )
        cleaned[field] = val

    return cleaned, errors


def generate_query_batch(
    study_name: str,
    description: str,
    batch_size: int,
    already_generated: list,
    api_key: str,
) -> list:
    """
    Calls OpenAI to generate one batch of queries.
    Returns a list of validated, cleaned row dicts.
    Invalid rows are skipped and logged — does not raise.
    """
    client = OpenAI(api_key=api_key)

    prompt = _build_prompt(study_name, description, batch_size, already_generated)

    response = client.chat.completions.create(
        model="gpt-4o-mini",
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
        return []

    # Handle both raw array and {"questions": [...]} shapes
    if isinstance(parsed, dict):
        for key in ('questions', 'queries', 'items', 'data'):
            if key in parsed:
                parsed = parsed[key]
                break

    if not isinstance(parsed, list):
        log.error(f"Expected JSON array, got: {type(parsed)}")
        return []

    valid_rows = []
    for row in parsed:
        cleaned, errors = _validate_generated_row(row)
        if errors:
            log.warning(f"Skipping invalid generated row: {errors} — row={row}")
            continue
        valid_rows.append(cleaned)

    return valid_rows
