"""
2L-3: the console's one-line narratives, written by a model from the facts
the scorer already holds, and checked before anything is shown.

Decision (Elton, Oct 21): the demo's Answers rows read like "Sends the AMORE
shopper to Amazon at about $36.18. Amazon charged $47.99 that day ...", ours
read "stated 49.77; the page said 49.77". One model call per flagged answer
and per product row writes the line from the facts; every number and name in
the line is checked against those facts; the templates stay for everything
else, and for any line that fails.

  facts     load_cycle_facts(): per flagged answer (a wrong, stale or
            other-brand price, a fabricated or misattributed brand verdict,
            a fabricated citation or availability, a rival first pick on a
            brand-choice question) and per product row (the cycle's cached
            retailer-prices rows with the catalog tier's quotes), only what
            the scorer stored. Of the answer's text, only the spans the
            labeller labelled and the spans holding a quoted price: the
            model cannot be handed a fact the scorer did not keep.
  digest    facts_digest(): sha256 of the facts. A line is served only while
            its stored digest is the facts' digest now, so a rescore that
            changes a row's facts puts its template back until the line is
            rewritten.
  writer    LiveWriter calls OpenAI (SOA_NARRATIVE_MODEL, default the
            parser's small model, config.SOA_CODING_MODEL) twice on the same
            request. RecordedWriter replays scripts/record_narratives.py's
            recordings, keyed by the facts digest. Tests only ever replay.
  checks    check(): every dollar amount and every number in the line is in
            the facts; every retailer, agent and brand name too (a capitalised
            word inside a sentence must be one the facts hold); no banned
            word (the console's copy scan, apps/console/tools/audit.py, plus
            "AI", "model", semicolons and dashes); at most 220 characters.
            decide(): taken only when both calls write a line and both pass
            (the wording may differ, the first is kept). Otherwise dropped,
            and the console shows its template.
  storage   soa_narratives (migration c8e2f4a6b1d3), one row per cycle and
            subject, with the digest, model, time, each call's answer and
            usage. Written by the worker when a full loop's cycle completes
            (fullloop/coordinator.py) and by rescore_cycle.py --narratives.
  served    served(): {subject: line} for the cycle's lines whose digest is
            current. The API reads it for /answers, /overview and /true-value.

Both halves run only with SOA_NARRATIVES_ENABLED=1 (default off): off, the
worker writes nothing and the API serves `narrative: null` everywhere.

The model's settings: verbosity low, as the 2A-5 extractor (supply
truesync/fullloop/extract.py), and reasoning effort low (EFFORT says why it
is not the extractor's none). The client exposes no temperature;
determinism is measured (two recording runs), not assumed.

Sync copies to apps/api/soa_shared/ and apps/pipeline/soa_shared/ (it reads
claim_kinds and retailers, which packages/shared/soa_shared/ does not carry).
"""
import hashlib
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import inspect, text

from soa_shared import claim_kinds, surfaces
from soa_shared import unprompted
from soa_shared.expected_answers import normalize_domain, normalize_money
from soa_shared.retailers import KNOWN_RETAILERS, RETAILER_NAMES, retailer_name

FLAG = "SOA_NARRATIVES_ENABLED"
MODEL_ENV = "SOA_NARRATIVE_MODEL"
TABLE = "soa_narratives"
#: Two calls on the same request; a line is taken only when both pass.
CALLS = 2
MAX_CHARS = 220
#: Calls in flight at once while a cycle's lines are written.
MAX_WORKERS = 4
#: Reasoning effort. The 2A-5 extractor reads with none; writing from the
#: facts with none leaked the facts' field names ("first_pick", "merchant
#: brand") and wrote clauses the facts do not hold on the first-pick lines,
#: and low did not, at about the same tokens (measured on the FL13 fixture).
EFFORT = "low"

ANSWER = 'answer'
PRODUCT = 'product'

#: The console's agent names (console_read_models.AGENT_NAMES).
AGENT_NAMES = {
    'chatgpt': 'ChatGPT', 'gemini': 'Gemini', 'aimode': 'Google AI Mode',
    'perplexity': 'Perplexity', 'copilot': 'Copilot', 'claude': 'Claude',
}
#: How a line may write an agent: its name, and AI Mode for Google AI Mode.
AGENT_WORDS = ('Google AI Mode', 'AI Mode', 'ChatGPT', 'Gemini', 'Perplexity', 'Copilot', 'Claude')

VALUE_TIERS = ('catalog_accuracy', 'value_incentives')
BRAND_TIER = 'brand_direct'
FLAGGED_VALUE = ('wrong', 'stale')
FLAGGED_BRAND = ('fabricated', 'misattributed')
FLAGGED_FLAGS = ('fabricated_citation', 'fabricated_availability')
#: TV_CELL_RULE's order: the worst outcome among the runs that quoted a price.
CELL_ORDER = ('wrong', 'stale', 'partial', 'exact')
#: The scorer's outcomes in the console's words (console_read_models.VALUE_VERDICT).
VERDICT_WORDS = {'exact': 'right', 'wrong': 'wrong', 'stale': 'stale', 'partial': 'partial', 'absent': 'no price',
                 'unverifiable': 'could not be checked', 'unscoreable': 'not scored', 'missed': 'no price'}
#: Why an answer was flagged, in words with no number in them: the scorer's
#: rules (expectation_comparator, brand_direct_classifier, answer_flags).
MEANINGS = {
    'wrong_price': "The price the assistant gave is not the price the retailer charged.",
    'stale_price': "The price the assistant gave is an old price, not the one the retailer charged that day.",
    'other_brand_price': "The only price in the answer was for another brand's product, so it gave none for this one.",
    'brand_fabricated': "The answer stated something about the brand that the brand never published and no source backs.",
    'brand_misattributed': "The answer described another brand's product as if it were this brand's.",
    'fabricated_citation': "The answer cited a source that does not exist or does not say this.",
    'fabricated_availability': "The answer said where the product is sold, and that is not true.",
    'rival_first_pick': "On a question that let the assistant choose a brand, its first pick was another brand.",
}
CLAIM_KIND_WORDS = {claim_kinds.ATTRIBUTE: 'stated a fact about the brand',
                    claim_kinds.RECOMMENDATION_ONLY: 'only recommended the brand, stated no fact'}
ISSUE_WORDS = {'product.wrong': 'quoted a wrong price', 'product.other_brand': "priced another brand's product",
               'product.left_out': 'gave no price', 'product.unverifiable': 'could not be checked',
               'product.right': 'quoted the right price', 'product.not_asked': 'not asked'}

#: The console's banned-word scan (parleohq/truesync console-demo,
#: apps/console/tools/audit.py BAN), verbatim, plus the house rules.
COPY_SCAN = (r"\b(spine|lands|landed|landing|stand[ -]up|sticker price|pegs?|pegged|vibes?|delve\w*|tapestry|"
             r"testament|beacon|realm|multifaceted|game[- ]changer|transformative|revolutionary|seamless\w*|"
             r"synerg\w*|paradigm|holistic|myriad|foster\w*|embark\w*|pivotal|unlock\w*|elevat\w*|empower\w*|"
             r"leverag\w*|landscape|journey|important to note|underscor\w*|in conclusion|my read on|thoughts\?)\b")
_BANNED = re.compile(COPY_SCAN, re.I)
#: and the facts' own vocabulary leaking into a line: a field name, "merchant",
#: "reader", "facts"
_HOUSE = re.compile(r"\bAI\b|\bmodels?\b|;|\u2014|\u2013|--|_|\bmerchants?\b|\breaders?\b|\bfacts?\b", re.I)

SYSTEM_PROMPT = """You write the one line a product console shows beside a shopping assistant's \
answer, or beside one product across many answers. You get the facts a scorer recorded and \
nothing else.

What the line says, in order: what the assistant said (its price, its pick, its claim), what was \
true (the retailer's price that day, the brand's own facts), and, when the facts give it, what that \
means for the shopper or the brand. For a product, lead with its issue: which assistants got the \
price wrong, what they quoted, and what the retailer charged. For a first pick, say which brand the \
assistant put first and where the brand came in the order the answer named them.

Rules:
- Use only the facts. Every price, number, retailer, assistant, brand and product you write must \
appear in the facts, written as the facts write it. Never round, convert or compute: no \
differences, no percentages, no counts the facts do not state.
- Be exact about who said what. Name an assistant only beside the quote or pick the facts give \
for that assistant, and a price only beside the retailer the facts give it for.
- Name the assistant (or assistants) and the retailer.
- One or two short sentences, at most 200 characters. Plain words.
- Never use a semicolon, an em dash or an en dash. Write a second sentence instead.
- Never write the word "AI" or the word "model". "Google AI Mode" is an assistant's name and may \
be written.
- Write prices with a dollar sign, as "$27.97", and dates as the facts write them.
- Do not mention the scorer, verdicts, runs or checks. Say what happened.
- The reader works for the brand (or store) the facts name. Call it by its name, and do not tell \
the reader what the assistant should have done.
- If the facts hold nothing specific to say (no price, no pick, no claim, only a verdict), return null.

Style examples, from other merchants:
- "Sends the AMORE shopper to Amazon at about $36.18. Amazon charged $47.99 that day and ran save \
40% on 1 when you buy 2, which the answer never mentions."
- "Calls Walmart the cheapest for a club-only diaper. Only a third-party seller lists it there, at \
$63.90. Costco sold it for $46.79."
- "Gets oralb.com's $169.99 right. Gives Best Buy $219.99 for a brush Best Buy sells at $169.99."
- "Only Gemini said Pure is being replaced by AMORE."
- "Huggies Little Movers first, Pampers Cruisers 360 second."

Return JSON: {"line": "<the line>"} or {"line": null}."""

SCHEMA = {
    "type": "object",
    "properties": {"line": {"type": ["string", "null"]}},
    "required": ["line"],
    "additionalProperties": False,
}


def enabled() -> bool:
    return os.getenv(FLAG, "0").strip() == "1"


def model_name() -> str:
    from soa_shared import config
    return (os.getenv(MODEL_ENV) or "").strip() or config.SOA_CODING_MODEL


def _json(value):
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _money(value) -> Optional[str]:
    m = normalize_money(value) if value not in (None, '') else None
    return None if m in (None, '0.00') else m


def _day(value) -> Optional[str]:
    """'2026-10-19T14:00:00+00:00' -> 'Oct 19'."""
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return f"{d.strftime('%b')} {d.day}"


def _gtin14(value) -> Optional[str]:
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return digits.zfill(14) if digits and len(digits) <= 14 else None


def _agent(platform: Optional[str]) -> str:
    a = surfaces.agent_of(platform or '') or platform or 'unknown'
    return AGENT_NAMES.get(a, a)


def _drop_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, [], {}, '')}


# ---------------------------------------------------------------------------
# The facts
# ---------------------------------------------------------------------------

@dataclass
class Merchant:
    name: Optional[str]
    kind: Optional[str]
    terms: Tuple[str, ...]

    def facts(self) -> dict:
        """{'brand': name} or {'store': name}: the facts name it by what it
        is, so no field name ("merchant", "reader") is there to repeat."""
        return {('store' if self.kind in ('seller', 'store', 'retailer') else 'brand'): self.name} if self.name else {}

    def is_ours(self, name: Optional[str]) -> bool:
        return bool(name) and bool(unprompted.names_any(name, self.terms))


def _reference_rows(reference: Optional[dict]) -> List[dict]:
    return [r for r in (reference or {}).get('prices') or [] if isinstance(r, dict) and r.get('role') != 'comparison']


def _ref_keys(row: dict) -> List[str]:
    """Every key a reference row is known by (True Value's aliases)."""
    keys = [_gtin14(row.get('gtin')), row.get('variant_ref'), row.get('sku'),
            f"sku:{row['sku']}" if row.get('sku') else None]
    return [str(k) for k in keys if k]


def _source_keys(source_ref: Optional[dict]) -> List[str]:
    ref = source_ref or {}
    keys = [_gtin14(ref.get('gtin')), _gtin14(ref.get('variant_id')), ref.get('variant_id'), ref.get('variant_ref')]
    return [str(k) for k in keys if k]


def _reference_fact(row: Optional[dict], member: bool = False) -> Optional[dict]:
    if not row:
        return None
    domain = normalize_domain(row.get('retailer_domain'))
    if row.get('method') == 'none_by_design':
        return _drop_none({'retailer': retailer_name(domain), 'price': None, 'note': "sets no price, the brand's own site",
                           'date': _day(row.get('observed_at'))})
    if row.get('verifiable') is False:
        return _drop_none({'retailer': retailer_name(domain), 'note': 'could not be read',
                           'date': _day(row.get('observed_at'))})
    price = _money(row.get('member_price') if member else row.get('price'))
    if price is None:
        return None
    return _drop_none({'retailer': retailer_name(domain), 'price': price, 'date': _day(row.get('observed_at'))})


def _claim_fact(claim: dict) -> Optional[dict]:
    if not isinstance(claim, dict):
        return None
    stated = _money(claim.get('stated'))
    if stated is None:
        return None
    reference = claim.get('reference') or {}
    against = _money(reference.get('against') if reference else claim.get('against'))
    return _drop_none({
        'price_quoted': stated,
        'for_product': claim.get('product'),
        'for_variant': claim.get('variant_name') if claim.get('target') in ('swap', 'clash') else None,
        'judged_against': against,
        'judged_at': retailer_name(reference.get('retailer_domain')) if reference.get('retailer_domain') else None,
        'verdict': VERDICT_WORDS.get(claim.get('outcome'), claim.get('outcome')),
        'note': claim.get('reason') or claim.get('conflict'),
    })


def _spans(extraction: dict, claims: List[dict]) -> List[str]:
    """The answer's text the scorer kept: the labelled spans (span_labels)
    whose label is not none, and the spans holding a quoted price. At most
    four, 300 characters each."""
    stated = [str(c.get('stated')) for c in claims if isinstance(c, dict) and c.get('stated')]
    out = []
    for span in (extraction or {}).get('span_labels') or []:
        if isinstance(span, dict) and span.get('text') and span.get('label') not in (None, 'none'):
            out.append(str(span['text'])[:300])
    for span in (extraction or {}).get('spans') or []:
        body = str(span.get('text') or '') if isinstance(span, dict) else ''
        if body and any(s and s in body for s in stated) and body[:300] not in out:
            out.append(body[:300])
    return out[:4]


def why_flagged(tier: Optional[str], outcome: Optional[dict], first: Optional[str], brand_choice: bool,
                merchant: Merchant) -> List[str]:
    """The reasons an answer gets a line (empty: it keeps its template)."""
    o = outcome or {}
    raw, reason = o.get('outcome'), o.get('reason_code')
    why = []
    if tier in VALUE_TIERS and raw in FLAGGED_VALUE:
        why.append(f'{raw}_price')
    if raw == 'absent' and reason == 'other_brand':
        why.append('other_brand_price')
    if tier == BRAND_TIER and raw in FLAGGED_BRAND:
        why.append(f'brand_{raw}')
    for f in _json(o.get('flags')) or []:
        if isinstance(f, dict) and f.get('flag') in FLAGGED_FLAGS:
            why.append(f['flag'])
    if brand_choice and first and not merchant.is_ours(first):
        why.append('rival_first_pick')
    return why


def answer_facts(run: dict, outcome: Optional[dict], mentions: List[dict], merchant: Merchant,
                 index: Dict[tuple, dict]) -> Optional[dict]:
    """The facts for one answer, or None when it is not flagged. `run`
    carries its question (query_text, tier, source_ref); `index` is the
    cycle's reference rows by (domain, key)."""
    if run.get('answer_status') not in (None, surfaces.ANSWERED):
        return None
    named = [m['name'] for m in sorted(mentions, key=lambda m: m.get('position') or 99)]
    first = next((m['name'] for m in mentions if m.get('position') == 1), None)
    brand_choice = unprompted.is_brand_choice(run, merchant.terms)
    why = why_flagged(run.get('tier'), outcome, first, brand_choice, merchant)
    if not why:
        return None
    o = outcome or {}
    extraction = _json(o.get('extraction')) or {}
    expected = _json(o.get('expected_answer')) or {}
    claims = [c for c in _json(o.get('claim_results')) or [] if isinstance(c, dict)]
    flags = [f for f in _json(o.get('flags')) or [] if isinstance(f, dict) and f.get('flag') in FLAGGED_FLAGS]
    brand = run.get('tier') == BRAND_TIER
    reference = None
    if not brand and expected.get('type') in ('price', 'member_price'):
        domain = normalize_domain(expected.get('attributed_to'))
        row = next((index[(domain, k)] for k in _source_keys(_json(run.get('source_ref'))) if (domain, k) in index), None)
        reference = _reference_fact(row, member=expected.get('type') == 'member_price')
        if reference is None and _money(expected.get('amount')):
            reference = _drop_none({'retailer': retailer_name(domain) if domain else None,
                                    'price': _money(expected.get('amount'))})
    surface = run.get('surface') or surfaces.surface_of(run.get('platform') or '')
    rival = 'rival_first_pick' in why
    return _drop_none({
        'kind': ANSWER,
        'why': why,
        'meaning': [MEANINGS[w] for w in why if w in MEANINGS],
        'question': run.get('query_text'),
        'agent': _agent(run.get('platform')),
        'surface': surfaces.SURFACE_LABELS.get(surface, surface),
        **merchant.facts(),
        'agent_quoted': [f for f in (_claim_fact(c) for c in claims) if f],
        'retailer_price_that_day': reference,
        'verdict': None if brand else VERDICT_WORDS.get(o.get('outcome'), o.get('outcome')),
        'reason_code': o.get('reason_code'),
        'scorer_note': o.get('outcome_reason'),
        'brand_verdict': o.get('outcome') if brand else None,
        'claim_kind': CLAIM_KIND_WORDS.get(claim_kinds.claim_kind(extraction)) if brand else None,
        'first pick': first if rival or brand_choice else None,
        'named in order': named if rival or brand_choice else None,
        'flags': [_drop_none({'flag': f.get('flag'), 'detail': f.get('detail') or f.get('evidence')}) for f in flags],
        'answer_spans': _spans(extraction, claims),
    })


def cell_status(quotes: List[dict]) -> str:
    """TV_CELL_RULE over one retailer's quotes: the worst outcome among the
    runs that quoted a price, else missed."""
    quoted = [q['verdict'] for q in quotes if q.get('quoted') and q.get('verdict') in CELL_ORDER]
    if not quoted:
        return 'unverifiable' if any(q.get('verdict') == 'unverifiable' for q in quotes) else 'missed'
    return min(quoted, key=CELL_ORDER.index)


def issue_rule(quotes: List[dict]) -> Tuple[str, int, int]:
    """console_parity.product_issue's rule: (rule, n, runs)."""
    runs = len(quotes)
    if not runs:
        return 'product.not_asked', 0, 0
    counts = {
        'product.other_brand': sum(1 for q in quotes if q['verdict'] == 'absent' and q.get('reason_code') == 'other_brand'),
        'product.wrong': sum(1 for q in quotes if q['verdict'] in ('wrong', 'stale')),
        'product.left_out': sum(1 for q in quotes if q['verdict'] == 'absent' and q.get('reason_code') != 'other_brand'),
        'product.unverifiable': sum(1 for q in quotes if q['verdict'] == 'unverifiable'),
    }
    rule, n = max(counts.items(), key=lambda kv: kv[1])
    if n:
        return rule, n, runs
    return 'product.right', sum(1 for q in quotes if q['verdict'] == 'exact'), runs


def product_facts(reference: Optional[dict], catalog_runs: List[dict], merchant: Merchant) -> Dict[str, dict]:
    """{product key: facts} for each variant in the cycle's cached
    retailer-prices that a catalog question asked about. The key is True
    Value's row key (GTIN-14, else supply's variant_ref); `aliases` lists
    every key the row is known by."""
    groups: Dict[str, dict] = {}
    alias: Dict[str, str] = {}
    for row in _reference_rows(reference):
        key = _gtin14(row.get('gtin')) or row.get('variant_ref')
        if not key:
            continue
        g = groups.setdefault(key, {'label': row.get('variant_label') or key, 'rows': [], 'aliases': []})
        g['rows'].append(row)
        for a in _ref_keys(row):
            if a not in g['aliases']:
                g['aliases'].append(a)
            alias.setdefault(a, key)
    quotes: Dict[str, List[dict]] = {}
    for run in catalog_runs:
        key = next((alias[k] for k in _source_keys(_json(run.get('source_ref'))) if k in alias), None)
        if key is None or run.get('outcome') is None:
            continue
        expected = _json(run.get('expected_answer')) or {}
        claims = [c for c in _json(run.get('claim_results')) or [] if isinstance(c, dict)]
        asked = next((c for c in claims if c.get('target', 'asked') == 'asked' and _money(c.get('stated'))), None)
        other = next((c for c in claims if c.get('target') in ('swap', 'clash') and _money(c.get('stated'))), None)
        quote = asked or other
        quotes.setdefault(key, []).append(_drop_none({
            'agent': _agent(run.get('platform')),
            'asked_at': retailer_name(expected.get('attributed_to')) if expected.get('attributed_to') else None,
            'quoted': _money(quote.get('stated')) if quote else None,
            'for_variant': (other.get('variant_name') or other.get('product')) if quote is other and other else None,
            'verdict': run.get('outcome'),
            'reason_code': run.get('reason_code'),
        }))
    out = {}
    for key, g in groups.items():
        qs = quotes.get(key) or []
        if not qs:
            continue
        rule, n, runs = issue_rule(qs)
        prices: Dict[str, dict] = {}
        for row in g['rows']:
            if row.get('role') == 'own' and row.get('method') != 'none_by_design' and not _money(row.get('price')):
                continue
            fact = _reference_fact(row)
            if fact and fact.get('retailer'):
                prices[fact['retailer']] = _drop_none({'price': fact.get('price'), 'date': fact.get('date'),
                                                       'note': fact.get('note')})
        quoted: Dict[tuple, List[str]] = {}
        for q in qs:
            if q.get('quoted'):
                quoted.setdefault((q['verdict'], q.get('asked_at'), q['quoted'], q.get('for_variant')), []).append(q['agent'])

        def listed(verdicts):
            return [_drop_none({'retailer': at, 'quoted': price, 'for_variant': variant, 'agents': sorted(agents),
                                'retailer_charged': (prices.get(at) or {}).get('price') if verdict != 'exact' else None})
                    for (verdict, at, price, variant), agents in sorted(quoted.items(), key=lambda kv: (str(kv[0][1]), kv[0][2]))
                    if verdict in verdicts]
        asked_at = sorted({q.get('asked_at') for q in qs if q.get('asked_at')})
        out[key] = _drop_none({
            'kind': PRODUCT,
            'product': g['label'],
            **merchant.facts(),
            'agents_asked': len({q['agent'] for q in qs}),
            'answers': runs,
            'retailer_prices_that_day': prices,
            'wrong_quotes': listed(('wrong', 'stale', 'partial')),
            'right_quotes': listed(('exact',)),
            'gave_no_price': sorted({q['agent'] for q in qs if not q.get('quoted') and q.get('reason_code') != 'other_brand'}),
            'priced_another_brand': sorted({q['agent'] for q in qs if q.get('reason_code') == 'other_brand'}),
            'cell_status': {r: VERDICT_WORDS.get(cell_status([q for q in qs if q.get('asked_at') == r]), 'no price')
                            for r in asked_at},
            'issue': {'rule': rule, 'meaning': ISSUE_WORDS.get(rule, rule), 'answers': n, 'of': runs},
            'aliases': g['aliases'],
        })
    return out


def facts_digest(facts: dict) -> str:
    body = json.dumps(facts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def merchant_of(conn, cycle: dict, reference: Optional[dict]) -> Merchant:
    """The cycle's merchant: its study's tier_config.merchant (brand name,
    the brand's terms) and the cached reference's kind."""
    job = conn.execute(text("SELECT tier_config, syndicated_merchant FROM soa_query_generation_jobs "
                            "WHERE study_type = :st ORDER BY id DESC"), {'st': cycle.get('study_type')}).fetchone() \
        if cycle.get('study_type') else None
    tier_config = (_json(job[0]) if job else None) or {}
    m = tier_config.get('merchant') or {}
    primary = conn.execute(text("""
        SELECT e.name, e.aliases FROM soa_cycle_entities ce JOIN soa_entities e ON e.id = ce.entity_id
        WHERE ce.cycle_id = :c AND ce.role = 'primary'
    """), {'c': cycle['id']}).fetchone()
    name = m.get('study_brand') or m.get('brand') or (primary[0] if primary else None) or (job[1] if job else None)
    terms = unprompted.brand_terms(primary[0] if primary else name, (_json(primary[1]) if primary else None) or [],
                                   m.get('product_names') or [])
    if name and name not in terms:
        terms = [name, *terms]
    kind = (reference or {}).get('kind') or m.get('kind') or m.get('merchant_kind')
    return Merchant(name=name, kind=kind, terms=tuple(terms))


def load_cycle_facts(conn, cycle_id: int) -> Dict[str, dict]:
    """{subject: facts} for one cycle: 'answer:run-<id>' per flagged answer,
    'product:<key>' per product row. Reads only what the scorer stored."""
    cycle = conn.execute(text("SELECT id, cycle_code, study_type, reference_prices FROM soa_cycles WHERE id = :c"),
                         {'c': cycle_id}).mappings().first()
    if cycle is None:
        return {}
    cycle = dict(cycle)
    reference = _json(cycle.get('reference_prices'))
    merchant = merchant_of(conn, cycle, reference)
    index: Dict[tuple, dict] = {}
    for row in _reference_rows(reference):
        domain = normalize_domain(row.get('retailer_domain'))
        for k in _ref_keys(row):
            if domain:
                index.setdefault((domain, k), row)
    runs = [dict(r) for r in conn.execute(text("""
        SELECT r.id, r.platform, r.surface, r.answer_status, q.query_text, q.tier, q.stage, q.source_ref
        FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
        WHERE r.cycle_id = :c ORDER BY r.id
    """), {'c': cycle_id}).mappings()]
    outcomes = {o['run_id']: dict(o) for o in conn.execute(text("""
        SELECT run_id, outcome, reason_code, outcome_reason, claim_results, expected_answer, extraction, flags
        FROM soa_expectation_outcomes WHERE cycle_id = :c
    """), {'c': cycle_id}).mappings()}
    mentions: Dict[int, List[dict]] = {}
    for m in conn.execute(text("""
        SELECT cm.run_id, e.name, cm.position FROM soa_coded_mentions cm
        JOIN soa_entities e ON e.id = cm.entity_id JOIN soa_runs r ON r.id = cm.run_id
        WHERE r.cycle_id = :c AND cm.mentioned = :yes
    """), {'c': cycle_id, 'yes': True}).mappings():
        mentions.setdefault(m['run_id'], []).append(dict(m))
    out: Dict[str, dict] = {}
    for run in runs:
        facts = answer_facts(run, outcomes.get(run['id']), mentions.get(run['id'], []), merchant, index)
        if facts:
            out[f"{ANSWER}:run-{run['id']}"] = facts
    catalog = [{**run, **{k: v for k, v in (outcomes.get(run['id']) or {}).items() if k != 'run_id'}}
               for run in runs if run.get('tier') == 'catalog_accuracy']
    for key, facts in product_facts(reference, catalog, merchant).items():
        out[f"{PRODUCT}:{key}"] = facts
    return out


# ---------------------------------------------------------------------------
# The prompt and the writers
# ---------------------------------------------------------------------------

def prompt(facts: dict) -> str:
    shown = {k: v for k, v in facts.items() if k != 'aliases'}
    return "Facts:\n" + json.dumps(shown, indent=1, ensure_ascii=False, sort_keys=True)


def request_digest(facts: dict, model: str) -> str:
    """What was asked: the model, the system prompt, the schema and the prompt."""
    body = json.dumps({"model": model, "effort": EFFORT, "system": SYSTEM_PROMPT, "schema": SCHEMA,
                       "prompt": prompt(facts)},
                      sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


@dataclass
class Answer:
    """What a writer returned: each call's raw JSON and usage."""
    raws: Tuple[str, ...]
    model: str
    usage: Tuple[dict, ...] = ()


class MissingRecording(LookupError):
    pass


Writer = Callable[[dict], Answer]


class LiveWriter:
    """CALLS OpenAI calls per subject, on the same request, with structured output."""

    def __init__(self, model: Optional[str] = None, client=None):
        self.model = model or model_name()
        self._client = client

    def client(self):
        if self._client is None:
            from openai import OpenAI

            from soa_shared import config
            if not config.OPEN_AI_API_KEY:
                raise RuntimeError("OPEN_AI_API_KEY is not set")
            self._client = OpenAI(api_key=config.OPEN_AI_API_KEY)
        return self._client

    def __call__(self, facts: dict) -> Answer:
        raws, usages = [], []
        for _ in range(CALLS):
            # verbosity low, as the 2A-5 extractor; effort EFFORT (see there)
            response = self.client().responses.create(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=[{"role": "user", "content": prompt(facts)}],
                reasoning={"effort": EFFORT},
                text={"verbosity": "low",
                      "format": {"type": "json_schema", "name": "narrative", "schema": SCHEMA, "strict": True}},
            )
            raws.append(response.output_text)
            usage = getattr(response, 'usage', None)
            usages.append({k: getattr(usage, k, None) for k in ('input_tokens', 'output_tokens', 'total_tokens')}
                          if usage else {})
        return Answer(raws=tuple(raws), model=self.model, usage=tuple(usages))


def record_command() -> str:
    return "python scripts/record_narratives.py --cycle fl13"


class RecordedWriter:
    """Replays scripts/record_narratives.py's recordings: one JSON file per
    facts digest, with its CALLS calls. A recording made from another
    request (the prompt, the schema or the facts changed) is refused."""

    def __init__(self, directory):
        self.directory = Path(directory)

    def __call__(self, facts: dict) -> Answer:
        digest = facts_digest(facts)
        path = self.directory / f"{digest}.json"
        if not path.exists():
            raise MissingRecording(f"no recorded response for facts {digest[:12]} in {self.directory}; "
                                   f"record with: {record_command()}")
        found = json.loads(path.read_text())
        if found.get('request_digest') != request_digest(facts, found.get('model')):
            raise MissingRecording(f"the recording of facts {digest[:12]} was made from a different request "
                                   f"(prompt or schema changed); re-record with: {record_command()}")
        calls = found.get('calls') or []
        if len(calls) != CALLS:
            raise MissingRecording(f"the recording of facts {digest[:12]} holds {len(calls)} call(s), not {CALLS}; "
                                   f"re-record with: {record_command()}")
        return Answer(raws=tuple(c['response'] for c in calls), model=found['model'],
                      usage=tuple(c.get('usage') or {} for c in calls))


def configured() -> Optional[Writer]:
    """The live writer when SOA_NARRATIVES_ENABLED=1, else None."""
    return LiveWriter() if enabled() else None


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

_AMOUNT = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)")
_NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)(?![\w])")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9&'\u2019.+]*")
_SENTENCE_END = re.compile(r"[.!?]\s+$")


def _strings(value) -> Iterable[str]:
    if isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _strings(v)
    elif value is not None:
        yield str(value)


def facts_text(facts: dict) -> str:
    return '\n'.join(_strings(facts))


def _numbers(text_: str) -> set:
    out = set()
    for m in _NUMBER.finditer(text_):
        raw = m.group(1).replace(',', '').rstrip('.')
        out.add(raw)
        if '.' in raw:
            out.add(normalize_money(raw) or raw)
    return out


def _amounts(facts: dict) -> set:
    out = set()
    for s in _strings(facts):
        for m in _NUMBER.finditer(s):
            amount = normalize_money(m.group(1).replace(',', ''))
            if amount:
                out.add(amount)
    return out


def _names_in(line: str) -> List[str]:
    """Retailer and agent names the line writes: a retailer by its display
    name or a capitalised alias ("Target", "Sam's Club"), or by its domain,
    and the agents. Case matters, so "the brand's target" names no retailer."""
    text_ = ' ' + line.replace('\u2019', "'") + ' '
    found = []
    candidates = set(RETAILER_NAMES.values()) | set(RETAILER_NAMES) | set(AGENT_WORDS) \
        | {a.title() for a in KNOWN_RETAILERS if '.' not in a}
    for name in sorted(candidates, key=len, reverse=True):
        if re.search(r'(?<![A-Za-z0-9])' + re.escape(name) + r'(?![A-Za-z0-9])', text_):
            if not any(name.lower() in f for f in found):
                found.append(name.lower())
    return found


def _pairs(value, owners=()) -> Iterable[Tuple[str, str]]:
    """(amount, owner) for every amount in the facts, its owners the
    retailer and agent names in the same dict or above it."""
    if isinstance(value, dict):
        here = list(owners)
        for k, v in value.items():
            if k in ('retailer', 'agent', 'judged_at', 'at') and isinstance(v, str):
                here.append(v)
            elif k == 'agents' and isinstance(v, list):
                here.extend(str(a) for a in v)
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                # a key that is itself a retailer's name owns what is under it
                yield from _pairs(v, here + ([k] if k in RETAILER_NAMES.values() else []))
            elif v is not None:
                for m in _NUMBER.finditer(str(v)):
                    amount = normalize_money(m.group(1).replace(',', ''))
                    if amount:
                        for o in here or ['']:
                            yield amount, o.lower()
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from _pairs(v, owners)


def _unpaired_amount(line: str, facts: dict) -> Optional[str]:
    """The first dollar amount whose sentence names none of the retailers or
    agents the facts tie it to (an amount the facts tie to nobody passes)."""
    owners: Dict[str, set] = {}
    for amount, owner in _pairs(facts):
        owners.setdefault(amount, set()).add(owner)
    for sentence in re.split(r"(?<=[.!?])\s+", line):
        lowered = sentence.lower().replace('\u2019', "'")
        for m in _AMOUNT.finditer(sentence):
            amount = normalize_money(m.group(1).replace(',', ''))
            tied = {o for o in owners.get(amount, set()) if o}
            if tied and not any(o in lowered for o in tied):
                return m.group(1)
    return None


_QUOTE_VERB = re.compile(r"\b(quot\w*|said|says|say|gave|gives|give|put|puts|priced|prices|told|tells|listed by)\b", re.I)
_TRUTH_VERB = re.compile(r"\b(charged|charges|charge|listed|lists|had|has|sold|sells|was|is|costs?|priced at)\b", re.I)
_CLAUSE = re.compile(r"(?<=[.!?])\s+|\s+but\s+|,?\s+while\s+|,?\s+whereas\s+|,?\s+when\s+|,\s+and\s+|,\s+so\s+", re.I)


def _retailer_spans(clause: str) -> List[Tuple[int, str]]:
    """(end offset, display name) of every retailer the clause names."""
    out = []
    names = {v: v for v in RETAILER_NAMES.values()}
    names.update({d: RETAILER_NAMES[d] for d in RETAILER_NAMES})
    for written, display in names.items():
        for m in re.finditer(r'(?<![A-Za-z0-9])' + re.escape(written) + r'(?![A-Za-z0-9])', clause, re.I if '.' in written else 0):
            out.append((m.end(), display))
    return sorted(out)


def _agents_in(clause: str) -> List[str]:
    found = []
    for a in AGENT_WORDS:
        if re.search(r'(?<![A-Za-z])' + re.escape(a) + r'(?![A-Za-z])', clause):
            name = 'Google AI Mode' if a == 'AI Mode' else a
            if name not in found:
                found.append(name)
    return found


def _said_and_true(facts: dict) -> Tuple[set, Dict[str, str]]:
    """({(agent, retailer or None, amount)} the facts say was quoted, {retailer: price that day})."""
    said, true = set(), {}
    if facts.get('kind') == PRODUCT:
        for r, v in (facts.get('retailer_prices_that_day') or {}).items():
            if v.get('price'):
                true[r] = v['price']
        for q in (facts.get('wrong_quotes') or []) + (facts.get('right_quotes') or []):
            for a in q.get('agents') or []:
                said.add((a, q.get('retailer'), q.get('quoted')))
    else:
        ref = facts.get('retailer_price_that_day') or {}
        if ref.get('retailer') and ref.get('price'):
            true[ref['retailer']] = ref['price']
        for q in facts.get('agent_quoted') or []:
            said.add((facts.get('agent'), q.get('judged_at') or ref.get('retailer'), q.get('price_quoted')))
    return said, true


def _who_said_what(line: str, facts: dict) -> Optional[str]:
    """In a clause naming agents and a quoting verb, every named agent quoted
    each amount (at the retailer named before it, if one is). In a clause
    naming a retailer and a verb like charged, the amount is that retailer's
    price that day. None when every such clause agrees with the facts."""
    said, true = _said_and_true(facts)
    for clause in _CLAUSE.split(line):
        amounts = [(m.start(), normalize_money(m.group(1).replace(',', ''))) for m in _AMOUNT.finditer(clause)]
        if not amounts:
            continue
        agents = _agents_in(clause)
        retailers = _retailer_spans(clause)
        for pos, amount in amounts:
            before = [name for end, name in retailers if end <= pos]
            at = before[-1] if before else None
            if agents and _QUOTE_VERB.search(clause):
                for a in agents:
                    if not any(sa == a and sp == amount and (at is None or sr in (None, at)) for sa, sr, sp in said):
                        return f"{a} ${amount}" + (f" at {at}" if at else '')
            elif at and _TRUTH_VERB.search(clause[clause.rfind(at, 0, pos) if at in clause else 0:pos]):
                if at in true and true[at] != amount:
                    return f"{at} charged ${amount}"
    return None


def check(line: Optional[str], facts: dict) -> Optional[str]:
    """None when the line passes every check, else the first failure."""
    if line is None or not str(line).strip():
        return 'no_line'
    line = str(line).strip()
    if len(line) > MAX_CHARS:
        return f'too_long:{len(line)}'
    scrubbed = line
    for agent in AGENT_WORDS:
        scrubbed = scrubbed.replace(agent, ' ')
    m = _HOUSE.search(scrubbed) or _BANNED.search(scrubbed)
    if m:
        return f'banned:{m.group(0)}'
    known = facts_text(facts)
    known_lower = known.lower().replace('’', "'")
    amounts = _amounts(facts)
    for m in _AMOUNT.finditer(line):
        amount = normalize_money(m.group(1).replace(',', ''))
        if amount not in amounts:
            return f'amount_not_in_facts:${m.group(1)}'
    numbers = _numbers(known)
    for m in _NUMBER.finditer(line):
        raw = m.group(1).replace(',', '').rstrip('.')
        if raw not in numbers and (normalize_money(raw) if '.' in raw else raw) not in numbers:
            return f'number_not_in_facts:{raw}'
    unpaired = _unpaired_amount(line, facts)
    if unpaired:
        return f'unpaired_amount:${unpaired}'
    misread = _who_said_what(line, facts)
    if misread:
        return f'who_said_what:{misread}'
    named = _agents_in(line)
    if facts.get('kind') == ANSWER and facts.get('agent') and facts['agent'] not in named:
        return f"agent_not_named:{facts['agent']}"
    if facts.get('kind') == PRODUCT and not named:
        return 'agent_not_named'
    for name in _names_in(line):
        if name not in known_lower:
            # a retailer the facts hold by its domain, or the reverse
            domain = KNOWN_RETAILERS.get(name) or (name if name in RETAILER_NAMES else None)
            display = RETAILER_NAMES.get(domain or '', '').lower()
            if not ((domain and domain in known_lower) or (display and display in known_lower)):
                return f'name_not_in_facts:{name}'
    # a capitalised word inside a sentence is a name: it must be one the facts hold
    words = list(_WORD.finditer(line))
    for i, m in enumerate(words):
        word = re.sub(r"['\u2019]s?\.?$|\.$", '', m.group(0)) or m.group(0)
        if not word[0].isupper():
            continue
        start = m.start()
        sentence_start = start == 0 or bool(_SENTENCE_END.search(line[:start])) or line[:start].rstrip().endswith(('"', ':'))
        if sentence_start:
            continue
        if word.lower() not in known_lower:
            return f'name_not_in_facts:{word}'
    return None


def parse(raw: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(line, error) from one call's raw JSON."""
    try:
        body = json.loads(raw or '')
    except ValueError:
        return None, 'malformed'
    if not isinstance(body, dict) or 'line' not in body:
        return None, 'malformed'
    line = body.get('line')
    return (line.strip() if isinstance(line, str) and line.strip() else None), None


def decide(answer: Answer, facts: dict) -> dict:
    """Both calls must write a line and both must pass. The first is kept."""
    calls = []
    for raw, usage in zip(answer.raws, list(answer.usage) + [{}] * (len(answer.raws) - len(answer.usage))):
        line, error = parse(raw)
        calls.append({'response': raw, 'usage': usage, 'line': line,
                      'check': error or (check(line, facts) if line is not None else 'no_line')})
    lines = [c['line'] for c in calls]
    if len(calls) == CALLS and all(c['check'] is None for c in calls):
        return {'status': 'accepted', 'line': lines[0], 'reason': None, 'calls': calls}
    if all(line is None for line in lines) and all(c['check'] == 'no_line' for c in calls):
        return {'status': 'null', 'line': None, 'reason': 'no_line', 'calls': calls}
    failed = [c['check'] for c in calls if c['check'] not in (None, 'no_line')]
    # a line beside a null: the two calls disagree on whether there is anything to say
    reason = failed[0] if failed else 'calls_disagree:null'
    return {'status': 'dropped', 'line': None, 'reason': reason, 'calls': calls}


# ---------------------------------------------------------------------------
# Storage and the read
# ---------------------------------------------------------------------------

def table_exists(conn) -> bool:
    return inspect(conn).has_table(TABLE)


def stored(conn, cycle_id: int) -> Dict[str, dict]:
    if not table_exists(conn):
        return {}
    return {r['subject']: dict(r) for r in conn.execute(text(
        f"SELECT subject, facts_digest, line, status, reason, model, written_at FROM {TABLE} WHERE cycle_id = :c"),
        {'c': cycle_id}).mappings()}


def store(conn, cycle_id: int, subject: str, digest: str, decision: dict, model: str) -> None:
    conn.execute(text(f"DELETE FROM {TABLE} WHERE cycle_id = :c AND subject = :s"), {'c': cycle_id, 's': subject})
    calls = [{k: c.get(k) for k in ('response', 'usage', 'check')} for c in decision['calls']]
    conn.execute(text(f"""
        INSERT INTO {TABLE} (cycle_id, subject, facts_digest, line, status, reason, model, calls, written_at)
        VALUES (:c, :s, :d, :line, :status, :reason, :model, :calls, :at)
    """), {'c': cycle_id, 's': subject, 'd': digest, 'line': decision['line'], 'status': decision['status'],
           'reason': decision['reason'], 'model': model, 'calls': json.dumps(calls),
           'at': datetime.now(timezone.utc)})


def served(conn, cycle_id: int) -> Dict[str, str]:
    """{subject: line} for the cycle's accepted lines whose digest is the
    facts' digest now. Empty with the flag off or the table missing."""
    if not enabled():
        return {}
    rows = stored(conn, cycle_id)
    if not rows:
        return {}
    facts = load_cycle_facts(conn, cycle_id)
    out = {}
    for subject, f in facts.items():
        row = rows.get(subject)
        if row and row['status'] == 'accepted' and row['line'] and row['facts_digest'] == facts_digest(f):
            out[subject] = row['line']
            for a in f.get('aliases') or []:
                out.setdefault(f"{PRODUCT}:{a}", row['line'])
    return out


def answer_line(lines: Dict[str, str], answer_id: Optional[str]) -> Optional[str]:
    return lines.get(f"{ANSWER}:{answer_id}") if answer_id else None


def product_line(lines: Dict[str, str], *keys) -> Optional[str]:
    for k in keys:
        if k and f"{PRODUCT}:{k}" in lines:
            return lines[f"{PRODUCT}:{k}"]
    return None


def write_cycle(engine, cycle_id: int, writer: Writer, *, dry_run: bool = False, force: bool = False,
                max_workers: int = MAX_WORKERS, log: Callable[[str], None] = lambda s: None) -> List[dict]:
    """Write the cycle's lines: each subject's facts, two calls, the checks,
    and (unless dry_run) the row. Without force, a subject whose stored row
    has the current digest is skipped. Returns one report per subject:
    {subject, facts, digest, status, line, reason, calls, model}."""
    with engine.connect() as conn:
        facts = load_cycle_facts(conn, cycle_id)
        have = {} if force else stored(conn, cycle_id)
    todo = [(s, f) for s, f in facts.items()
            if force or (have.get(s) or {}).get('facts_digest') != facts_digest(f)]
    log(f"narratives: {len(facts)} subjects, {len(todo)} to write"
        f"{' (dry run, nothing stored)' if dry_run else ''}")

    def one(item):
        subject, f = item
        try:
            answer = writer(f)
        except MissingRecording:
            raise
        except Exception as exc:  # noqa: BLE001 - a failed call is a dropped line, never a crash
            return {'subject': subject, 'facts': f, 'digest': facts_digest(f), 'status': 'dropped', 'line': None,
                    'reason': f'model_error:{type(exc).__name__}', 'calls': [], 'model': getattr(writer, 'model', None)}
        decision = decide(answer, f)
        return {'subject': subject, 'facts': f, 'digest': facts_digest(f), 'model': answer.model, **decision}

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        reports = list(pool.map(one, todo))
    if not dry_run:
        with engine.begin() as conn:
            if not table_exists(conn):
                raise RuntimeError(f"{TABLE} is missing (migration c8e2f4a6b1d3 not applied)")
            for r in reports:
                if r['calls'] or r['status'] != 'dropped':
                    store(conn, cycle_id, r['subject'], r['digest'], r, r['model'] or model_name())
    return reports


def usage_totals(reports: List[dict]) -> dict:
    calls = [c for r in reports for c in r.get('calls') or []]
    tokens_in = [int((c.get('usage') or {}).get('input_tokens') or 0) for c in calls]
    tokens_out = [int((c.get('usage') or {}).get('output_tokens') or 0) for c in calls]
    return {'subjects': len(reports), 'calls': len(calls), 'input_tokens': sum(tokens_in),
            'output_tokens': sum(tokens_out),
            'max_input_tokens': max(tokens_in, default=0), 'max_output_tokens': max(tokens_out, default=0)}
