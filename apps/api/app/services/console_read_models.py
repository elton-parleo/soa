"""
2B §6: soa's results in the console's shapes.

The console (parleohq/truesync console-demo apps/console/src/data/types.ts
and studio.ts) is the product UI from 2C-0 on. These builders turn soa's
stored rows into its types, with every mapping written down here and in
docs/console-read-models.md. Where a console type cannot hold what soa
knows, the payload carries the extra field BESIDE the typed one rather than
bending it, and says so in `divergences` — the same rule supply's Command
Center payloads follow.

2I-8: counts are shown for every agent together by default, as the console
demo shows them: each read keyed by surface leads with `all` (soa_shared/
surfaces.py ALL, every run in the cycle), its default, and keeps each
surface's own entry beside it, unchanged, for the console's surface filter.
The score pools surfaces by score, not by count (console_score.py).

Pure functions over rows (the loaders at the bottom do the SQL), so each
mapping is tested without a database.
"""
import json
import re
from collections import Counter
from decimal import Decimal
from typing import Dict, Iterable, List, Optional

from sqlalchemy import text

from soa_shared import attribute_accuracy, claim_kinds, local_time, per_unit, retired_lines, surfaces, unprompted
from soa_shared import promo_pass_through as ppt
from soa_shared import severity
from soa_shared.expected_answers import UNVERIFIED
from soa_shared.expected_answers import names_brand as ea_names_brand

from app.services import console_claims

# ─── vocabularies ──────────────────────────────────────────────────────────

AGENT_NAMES = {
    'chatgpt': 'ChatGPT', 'gemini': 'Gemini', 'aimode': 'Google AI Mode',
    'perplexity': 'Perplexity', 'copilot': 'Copilot', 'claude': 'Claude',
}

#: Value outcomes -> Check.verdict / Answer.verdict. Explicit, not lossy:
#: the console's four values where they mean the same thing, and soa's
#: other outcomes passed through VERBATIM (with a tone) for 2C-0 to render.
VALUE_VERDICT = {
    'exact': 'right', 'wrong': 'wrong', 'absent': 'missed', 'partial': 'partial',
    'stale': 'stale', 'unverifiable': 'unverifiable', 'unscoreable': 'unscoreable',
    # 2N-1: a per-unit quote, outside scored and outside wrong (soa_shared/per_unit.py)
    'per_unit': 'per_unit',
}
VERDICT_TONE = {
    'right': 'ok', 'wrong': 'bad', 'missed': 'warn', 'partial': 'warn',
    'stale': 'warn', 'unverifiable': 'neu', 'unscoreable': 'neu', 'per_unit': 'neu',
}
BRAND_TONE = {
    'grounded': 'ok', 'echoed': 'neu', 'misattributed': 'bad', 'fabricated': 'bad',
    'acknowledged_unknown': 'warn', 'absent': 'warn', 'unscoreable': 'neu',
    # 2O-5: facts not on the pages read, nothing contradicts them (stored unscoreable, reason unverified)
    'unverified': 'neu',
}
#: Segment.mark per claim outcome. The console labels `miss` "left out";
#: soa uses it for a claim that landed near the reference but not on it.
MARK = {'exact': 'ok', 'wrong': 'wrong', 'partial': 'miss', 'stale': 'miss'}
#: TvCell.status, extended by `unverifiable`. A stale quote is wrong today;
#: the raw outcome rides beside it in `outcome`.
TV_STATUS = {'exact': 'exact', 'wrong': 'wrong', 'partial': 'partial', 'absent': 'missed',
             'stale': 'wrong', 'unverifiable': 'unverifiable', 'unscoreable': 'none', 'per_unit': 'per_unit'}
#: 2N-1: the console's words for a per-unit quote's cell and check.
PER_UNIT_LABEL = per_unit.NOTE


def read_outcome(outcome: Optional[str], reason_code: Optional[str]) -> Optional[str]:
    """The run's outcome as the console reads it: a run stored unscoreable for a
    per-unit quote (reason per_unit, the scorer's 2N-1 rule) reads per_unit;
    2O-5: a brand-direct run stored unscoreable for facts the index does not
    hold and nothing contradicts (reason unverified) reads unverified."""
    if outcome == 'unscoreable' and reason_code == per_unit.PER_UNIT:
        return per_unit.PER_UNIT
    if outcome == 'unscoreable' and reason_code == UNVERIFIED:
        return UNVERIFIED
    return outcome
#: StudyCell.s per outcome (value and brand vocabularies).
CELL_TONE = {
    'exact': 'ok', 'grounded': 'ok', 'wrong': 'bad', 'fabricated': 'bad', 'misattributed': 'bad',
    'partial': 'warn', 'stale': 'warn', 'echoed': 'warn', 'acknowledged_unknown': 'warn',
    'absent': 'neu', 'unverifiable': 'neu', 'unscoreable': 'neu', 'unverified': 'neu',
}
#: Worst first, for picking one outcome to stand for several runs.
SEVERITY = ['wrong', 'fabricated', 'misattributed', 'stale', 'partial', 'acknowledged_unknown',
            'absent', 'echoed', 'unverifiable', 'unverified', 'unscoreable', 'exact', 'grounded']
TIER_LABELS = {'brand_direct': 'Brand-direct', 'catalog_accuracy': 'Catalog accuracy',
               'value_incentives': 'Value & incentives', 'category_control': 'Category control',
               'comparison': 'Comparison'}

ANSWER_DIVERGENCES = [
    "Answer.verdict is not a console field: it carries the value outcome mapped exact->right, "
    "wrong->wrong, absent->missed, partial->partial; stale, unverifiable and unscoreable pass "
    "through verbatim with `tone`. Brand-direct rows leave it null and carry `brand_verdict`.",
    "Check.verdict uses the same mapping, so it can hold stale / unverifiable / unscoreable, "
    "which the console's union does not have yet (2C-0).",
    "Answer.agent can be 'claude', which the console's AgentId does not have yet (2C-0 adds it).",
    "Segment.mark 'miss' marks a partial or stale claim; the console labels miss 'left out'.",
    "Extra fields beside the typed ones: platform, answer_status, tier, verdict, tone, "
    "brand_verdict, flags, flag_details, cycle, reason (the outcome's rule code), variant_id, "
    "gtin, retailer (the True Value cell the answer is judged in).",
    "Check.reason (2C) is the classifier's rule code (other_brand, not_our_product, "
    "variant_clash, product_inferred, variant_swap); Check.note is prose only.",
    "Answer.surface (api | grounded_api | consumer_ui) and Answer.collector are typed from 2C.",
]


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def compact(d: dict, optional: Iterable[str]) -> dict:
    """Drop the OPTIONAL typed fields that are None: TypeScript's
    `field?: string` admits an absent field, not a null one."""
    return {k: v for k, v in d.items() if not (k in optional and v is None)}


def money(value, currency='USD') -> str:
    if value in (None, ''):
        return '—'
    return f"${value}" if (currency or 'USD') == 'USD' else f"{value} {currency}"


def worst(outcomes: Iterable[str]) -> Optional[str]:
    counts = Counter(o for o in outcomes if o)
    if not counts:
        return None
    top = max(counts.values())
    tied = [o for o, n in counts.items() if n == top]
    return min(tied, key=lambda o: SEVERITY.index(o) if o in SEVERITY else len(SEVERITY))


# ─── Answer ────────────────────────────────────────────────────────────────

def _and(names: List[str]) -> str:
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' and ' + names[-1]


def catalog_verdict(intent: str, source_ref: dict, extraction: Optional[dict], answer: Optional[str], *,
                    attribute: Optional[dict] = None, deals: Optional[dict] = None,
                    expectation: Optional[dict] = None) -> dict:
    """
    2N-1: a catalog-built brand-direct answer's own verdict (never the
    brand-claim rule's): {verdict, line, severity, tone}.

      where_to_buy    coverage: the stores it sends the shopper to (the
                      routing coding) against the brand's retailer list.
                      covered (two or more listed), partial, no_store.
      cheapest_place  deal pass-through: whether it named a deal live for
                      the SKU that day (`deals`, the cycle's cached rows').
                      named_deal, missed_deal, no_deal_live.
      attribute       the weight range (attribute_accuracy.answer_attribute).
      retired         2Q-2 (B2): whether it named the successor. grounded
                      (named it, unflagged), no_successor (2T-4: High, "did not
                      name AMORE, its successor"); a line with no successor,
                      or an answer with no text, is not judged. Still sold is
                      not coded (RETIRED_STILL_SOLD_NOTE, 2L-2). The successor
                      is the question's expectation's (catalog_tiers.
                      build_retired_line_questions), named by its terms.
    """
    ref = source_ref or {}
    if intent == claim_kinds.ATTRIBUTE_INTENT:
        v = (attribute or {}).get('verdict')
        return {'verdict': v, 'line': (attribute or {}).get('line'),
                'severity': {'match': 'ok', 'mismatch': 'high', 'absent': 'low'}.get(v, 'low'),
                'tone': {'match': 'ok', 'mismatch': 'bad', 'absent': 'bad'}.get(v, 'neu')}
    if intent == claim_kinds.RETIRED:
        retired, expected = ref.get('retired_line') or {}, expectation or {}
        line, successor = retired.get('line') or 'the line', retired.get('successor') or expected.get('successor') or {}
        if not successor or not (answer or '').strip():
            return {'verdict': None, 'line': f"asked about {line}, which the brand retired. Whether the answer called it "
                                             f"still sold is not coded", 'severity': 'low', 'tone': 'neu'}
        # 2Q-2 (B2): FL15's retired-line question read every answer High and red, the four that named AMORE too
        label = successor.get('label') or successor.get('line') or 'the successor'
        still = f"Whether it called {line} still sold is not coded"
        terms = successor.get('terms') or retired_lines.terms(successor.get('product_name') or label,
                                                              expected.get('brand') or ref.get('brand'))
        if retired_lines.names(answer, terms):
            return {'verdict': 'grounded', 'line': f"named {label}, its successor. {still}", 'severity': 'ok', 'tone': 'ok'}
        # 2T-4 (2): High, the successor not named on the direct question (soa_shared/severity.py)
        return {'verdict': 'no_successor', 'line': f"did not name {label}, its successor. {still}",
                'severity': 'high', 'tone': 'bad'}
    stores = stores_in_order(extraction)
    if stores is None:
        return {'verdict': None, 'line': None, 'severity': 'low', 'tone': 'neu'}
    names = [st['name'] for st in stores]
    if intent == claim_kinds.CHEAPEST_PLACE:
        live = ppt.live_for(deals, ref)
        where = f"named {names[0]} as the cheapest place" if names else 'named no store'
        if not live:
            return {'verdict': 'no_deal_live', 'line': f"{where}, with no deal live for this SKU that day",
                    'severity': 'low', 'tone': 'neu'}
        named = ppt.judge(answer, live)['named']
        if named:
            deal = next(d for d in live if ppt.deal_id(d) in named)
            return {'verdict': 'named_deal', 'line': f"named the {ppt.short(deal)} live that day",
                    'severity': 'ok', 'tone': 'ok'}
        return {'verdict': 'missed_deal', 'line': f"{where} and named none of the deals live that day "
                                                  f"({_and([ppt.short(d) for d in live])})",
                'severity': 'medium', 'tone': 'bad'}
    listed = set(ref.get('retailer_list') or [])
    on = [st for st in stores if st.get('domain') and (not listed or st['domain'] in listed)]
    if not stores:
        return {'verdict': 'no_store', 'line': 'named no store', 'severity': 'medium', 'tone': 'bad'}
    covered = len({st['domain'] for st in on}) >= 2
    return {'verdict': 'covered' if covered else 'partial',
            'line': f"named {_and(names)}, {len(on)} of the brand's retailers",
            'severity': 'ok' if covered else 'low', 'tone': 'ok' if covered else 'neu'}


# ─── 2T-5: the Answers tabs and the rule-built summary ──────────────────────

#: The demo's four tabs (Answer.queryType there). Tier stays its own field.
ACCURACY, VALUE, CATEGORY, BRAND_DIRECT = 'Accuracy', 'Value', 'Category', 'Brand-direct'
ANSWER_KINDS = (ACCURACY, VALUE, CATEGORY, BRAND_DIRECT)
#: catalog-built brand-direct intents that ask where to buy or what it costs
VALUE_INTENTS = ('where_to_buy', 'cheapest_place')
ORDINALS = {2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth', 6: 'sixth', 7: 'seventh', 8: 'eighth', 9: 'ninth'}
#: A flagged answer whose verdict carried no line of its own reads its rule's (never "Not scored").
RULE_LINES = {
    severity.WRONG_PRICE: 'quoted a price the page did not show',
    severity.WRONG_FACT: '{brand_s} facts stated wrong',
    severity.FABRICATED: 'cited a source or a store that does not hold up',
    severity.RETIRED_CURRENT: 'called a retired line current',
    severity.NO_SUCCESSOR: 'did not name the successor of a retired line',
    severity.CLUB_ELSEWHERE: 'sent a club-only line to a store that is not a club',
    severity.MISSED_DEAL: 'named none of the deals live that day',
    severity.FEWER_RETAILERS: "named fewer than two of the brand's retailers",
    severity.NO_WEIGHT: 'gave no weight range',
    severity.PARTIAL_PRICE: 'quoted a price near the page, not on it',
    severity.COULD_NOT_FIND: 'said it could not find the product',
}


def answer_kind(tier: Optional[str], intent: Optional[str]) -> str:
    """2T-5 (A4): Accuracy (weight, count and size questions), Value (where to buy, the cheapest place, the
    price at a retailer), Category (category control and comparison), Brand-direct (the rest asked by name)."""
    if tier in ('category_control', 'comparison'):
        return CATEGORY
    if tier in severity.VALUE_TIERS or intent in VALUE_INTENTS:
        return VALUE
    if intent == claim_kinds.ATTRIBUTE_INTENT:
        return ACCURACY
    return BRAND_DIRECT


def _brand_first(mentions: List[dict], ours: Optional[str], answer_status: Optional[str]) -> Optional[bool]:
    """Whether the brand came first, for the comparison rule; None when it cannot be said. 2T-5 (A5): an
    answer that never came back (AI Mode returned nothing) or whose coding ranked no brand has no rival
    first, so it is not "left out where it should be first". A coding whose lowest position is 2 or more
    had another brand first (build_visibility's rule)."""
    if not ours or answer_status not in (None, surfaces.ANSWERED):
        return None
    if not any(m.get('position') is not None for m in mentions):
        return None
    return any(m.get('position') == 1 and m.get('role') == 'primary' for m in mentions)


def ranking_line(mentions: List[dict], ours: Optional[str]) -> str:
    """2T-5 (A5): a comparison answer that left the brand out of first place, from the coded ranking:
    "Huggies first, Pampers second", "Huggies first, Pampers not named"."""
    brand = ours or 'the brand'
    top = next((m['name'] for m in mentions if m.get('position') == 1 and m.get('role') != 'primary'), None)
    mine = next((m for m in mentions if m.get('role') == 'primary'), None)
    lead = f"{top} first" if top else 'Another brand first'
    if mine is None:
        return f"{lead}, {brand} not named"
    pos = mine.get('position')
    return f"{lead}, {brand} {ORDINALS.get(pos, f'{pos}th') if pos and pos > 1 else 'named'}"


def rule_summary(rule: Optional[str], ours: Optional[str]) -> Optional[str]:
    line = RULE_LINES.get(rule)
    return line.format(brand_s=f"{ours}'s" if ours else "the brand's") if line else None


#: 2C: the classifier's reason codes (scoring/expectation_comparator.py
#: REASON_*), carried in Check.reason and Answer.reason. A code soa adds
#: later passes through verbatim; the console renders an unknown one neutral.
#: 2K-1: the Answers chip per claim_kind
CLAIM_KIND_LABELS = {claim_kinds.ATTRIBUTE: 'Stated a fact', claim_kinds.RECOMMENDATION_ONLY: 'Recommendation only'}

REASON_CODES = ('other_brand', 'not_our_product', 'variant_clash', 'product_inferred', 'variant_swap',
                # 2K-1: a price attributed to the brand's own page, which sets none
                'brand_sets_no_price')


def _reason_code(value) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _describe(expectation: dict) -> str:
    if not expectation:
        return '—'
    try:
        from soa_shared.expected_answers import describe
        return describe(expectation) or '—'
    except Exception:  # an expectation the vocabulary cannot describe
        return '—'


def _claim_text(claim) -> str:
    stated = claim.get('stated')
    product = claim.get('product')
    return f"{money(stated)} for {product}" if product else money(stated)


def _live(claim, expectation) -> str:
    reference = claim.get('reference') or {}
    against = reference.get('against') if reference else claim.get('against')
    if against is None and claim.get('target') == 'asked' and not reference:
        against = expectation.get('amount')
    if reference and reference.get('method') == NOT_PRICED_METHOD:
        # 2K-1: read, and sets no price by design: not unreadable
        return f"no price set at {reference.get('retailer_domain') or 'the brand site'}, the brand's own site"
    if reference and not reference.get('verifiable', True):
        return f"unverifiable: {reference.get('unverifiable_reason') or 'page unreadable'}"
    where = f" at {reference.get('retailer_domain')}" if reference.get('retailer_domain') else ''
    return f"{money(against, expectation.get('currency'))}{where}"


#: 2L-1 (B1): a check row's reference is never $0.00. An answer that gave no
#: price (no claim, or only a claim about something else) is judged against
#: the True Value cell it is asked in: the cycle's cached reference row for
#: the variant at the retailer the question names, its price and its basis
#: (`live_basis`, as TvCell's). A cycle scored before this read its question's
#: stored amount instead, which a page not read when the study was generated
#: stored as 0.00 (FL13); the read applies to stored cycles, nothing stored is
#: rewritten. With no reference and no amount the row says "—".
def _is_zero(value) -> bool:
    try:
        from soa_shared.expected_answers import normalize_money
    except Exception:  # pragma: no cover
        return False
    return normalize_money(value) == '0.00'


def reference_index(reference: Optional[dict]) -> Dict[tuple, dict]:
    """(domain, variant key) -> the cycle's cached reference row, keyed as
    True Value keys its rows (GTIN-14, variant_ref, sku, sku:<sku>)."""
    out: Dict[tuple, dict] = {}
    for row in (reference or {}).get('prices') or []:
        if not isinstance(row, dict) or row.get('role') == 'comparison':
            continue
        domain = _domain_key(row.get('retailer_domain'))
        for key in (_gtin14(row.get('gtin')), row.get('variant_ref'), row.get('sku'),
                    f"sku:{row['sku']}" if row.get('sku') else None):
            if domain and key:
                out.setdefault((domain, str(key)), row)
    return out


def cell_reference(index: Optional[Dict[tuple, dict]], expectation: dict, source_ref: Optional[dict]) -> Optional[dict]:
    """The reference row of the True Value cell an answer is asked in, or None."""
    domain = _domain_key(expectation.get('attributed_to'))
    if not index or not domain:
        return None
    ref = source_ref or {}
    for key in (_gtin14(ref.get('gtin')), _gtin14(ref.get('variant_id')), ref.get('variant_id'), ref.get('variant_ref')):
        if key and (domain, str(key)) in index:
            return index[(domain, str(key))]
    return None


def _reference_check(expectation: dict, row: Optional[dict]) -> tuple:
    """(live, live_basis) for a check whose answer quoted no price for the
    variant asked about: the cell's reference, else the question's own
    amount, never 0.00."""
    if row is not None:
        member = expectation.get('type') == 'member_price'
        against = row.get('member_price') if member else row.get('price')
        live = _live({'reference': {**row, 'against': None if _is_zero(against) else against}},
                     {**expectation, 'currency': row.get('currency') or expectation.get('currency')})
        return (live, 'reference_read') if not live.startswith('—') else ('—', None)
    amount = expectation.get('amount')
    if amount and not _is_zero(amount):
        return money(amount, expectation.get('currency')), \
            'question' if expectation.get('attributed_to') else 'record'
    return None, None


def segments(answer_text: str, spans, claims) -> List[List[dict]]:
    """
    paragraphs: Segment[][] from the stored spans, verbatim.

    Each stored span is found in the answer in order; the text between spans
    is an unmarked segment; a blank line starts a new paragraph. A span
    carrying a claim gets the claim's mark and `ann` = the claim's 1-based
    index in `checks`. With no stored spans (an extraction from before the
    segmenter), the paragraphs are the answer's own, unmarked.
    """
    text_ = answer_text or ''
    pieces: List[tuple] = []
    pos = 0
    for span in spans or []:
        body = span.get('text') if isinstance(span, dict) else None
        if not body:
            continue
        idx = text_.find(body, pos)
        if idx < 0:
            continue
        if idx > pos:
            pieces.append((text_[pos:idx], None, None))
        mark, ann = None, None
        for i, claim in enumerate(claims or [], start=1):
            stated = str(claim.get('stated') or '')
            if stated and (stated in body) and claim.get('outcome') in MARK:
                mark, ann = MARK[claim['outcome']], i
                break
        pieces.append((body, mark, ann))
        pos = idx + len(body)
    if pos < len(text_):
        pieces.append((text_[pos:], None, None))

    # Whitespace between two spans rides on the segment before it rather
    # than becoming a segment of its own; the text stays verbatim.
    merged: List[tuple] = []
    for body, mark, ann in pieces:
        if merged and mark is None and not body.strip() and '\n\n' not in body:
            prev = merged[-1]
            merged[-1] = (prev[0] + body, prev[1], prev[2])
        else:
            merged.append((body, mark, ann))

    paragraphs: List[List[dict]] = [[]]
    for body, mark, ann in merged:
        parts = body.split('\n\n')
        for k, part in enumerate(parts):
            if k > 0:
                paragraphs.append([])
            if not part.strip('\n'):
                continue
            seg = {'t': part.strip('\n') if k > 0 or not paragraphs[-1] else part}
            if mark:
                seg['mark'] = mark
                seg['ann'] = ann
            paragraphs[-1].append(seg)
    return [p for p in paragraphs if p]


def sibling_name(claim: dict, variant_names: Optional[Dict[str, str]] = None) -> str:
    """2C-2c: the record's name for the sibling a swap claim priced, else the
    answer's own words for it."""
    return (variant_names or {}).get(claim.get('variant_id')) or claim.get('product') or claim.get('variant_id') or 'another variant'


def _swap_check(claim: dict, expectation: dict, variant_names: Optional[Dict[str, str]]) -> tuple:
    """(verdict outcome, judged-against text, note, reason code) for a claim
    about a sibling (swap) or a variant the record lacks (clash). One rule,
    the question's, as True Value and the Overview read it: a row scored
    before b3c5a29 keeps the sibling's own verdict in `outcome` and the
    question's in `question_outcome`; after it `outcome` is the question's.
    It is judged against the variant asked about, never the sibling."""
    outcome = claim.get('question_outcome') or claim.get('outcome')
    amount = expectation.get('amount')
    against = money(amount, expectation.get('currency')) if amount else _live(claim, expectation)
    if claim.get('target') == 'swap':
        return outcome, against, f"priced {sibling_name(claim, variant_names)} instead", 'variant_swap'
    return outcome, against, claim.get('reason') or 'a size or pack the record does not have', \
        _reason_code(claim.get('reason_code')) or 'variant_clash'


def build_answer(run: dict, query: dict, outcome: Optional[dict], mentions: List[dict],
                 *, runs_per_query: Optional[int], cycle_code: str,
                 variant_names: Optional[Dict[str, str]] = None, features: Optional[List[str]] = None,
                 references: Optional[Dict[tuple, dict]] = None, truths: Optional[dict] = None,
                 deals: Optional[dict] = None, ours: Optional[str] = None,
                 club_keys: Optional[set] = None) -> dict:
    """features (2K-3): the merchant's catalog feature terms for claim_kind
    (app/services/console_claims.py); None reads 2K-1's rule. references
    (2L-1): the cycle's reference_index, for the reference of a check whose
    answer gave no price. truths (2N-1): the cycle's brand truths
    (attribute_accuracy.truth_index), for an accuracy answer; deals the
    deals live that day (its cached rows'), for a cheapest-place answer.
    2T-4 (2): the severity is soa_shared/severity.classify's, of the
    answer's verdict; `ours` the primary entity (a comparison answer with a
    rival first), `club_keys` the feed's club-only variants' keys
    (console_brand_overview.club_lines), when the reader has the feed."""
    platform = run['platform']
    agent = surfaces.agent_of(platform) or platform
    extraction = _json((outcome or {}).get('extraction')) or {}
    expectation = _json((outcome or {}).get('expected_answer')) or {}
    claims = _json((outcome or {}).get('claim_results')) or []
    flags = _json((outcome or {}).get('flags')) or []
    tier = query.get('tier')
    brand = tier == 'brand_direct'
    raw = read_outcome((outcome or {}).get('outcome'), (outcome or {}).get('reason_code'))
    answer_outcome = raw   # 2T-4: `raw` is reused below for each claim's outcome; severity reads the answer's

    verdict = None if brand or raw is None else VALUE_VERDICT.get(raw, raw)
    # 2N-1: a catalog-built brand-direct question is judged by its own verdict, not the brand-claim rule
    intent = claim_kinds.catalog_intent(_json(query.get('source_ref'))) if brand else None
    kind = console_claims.claim_kind(extraction, features) if brand and not intent and outcome is not None else None
    brand_verdict = raw if brand and not intent else None
    checks = []
    if not brand and outcome is not None:
        priced = expectation.get('type') in ('price', 'member_price')
        cell = cell_reference(references, expectation, _json(query.get('source_ref'))) if priced else None
        for claim in claims:
            if claim.get('target') in ('swap', 'clash'):
                raw, live, note, reason = _swap_check(claim, expectation, variant_names)
            else:
                raw, live, note, reason = claim.get('outcome'), _live(claim, expectation), \
                    claim.get('reason') or claim.get('conflict'), _reason_code(claim.get('reason_code'))
            basis = 'reference_read' if claim.get('reference') else 'record' if claim.get('against') else None
            if priced and (live.startswith('—') or _is_zero(live.split(' ')[0].lstrip('$'))):
                # 2L-1: no reference on the claim (another product's price,
                # one the scorer had no row for): the cell's, never $0.00
                live, basis = _reference_check(expectation, cell)
                live = live or '—'
            mapped = VALUE_VERDICT.get(raw, raw)
            # 2C: the rule that decided the claim is `reason` (a code from
            # REASON_CODES); `note` keeps the prose. 2C-2c: a swap or clash
            # claim carries the question's verdict against the asked variant.
            checks.append(compact({'claim': _claim_text(claim), 'agent': AGENT_NAMES.get(agent, agent),
                                   'live': live, 'live_basis': basis, 'verdict': mapped, 'note': note, 'reason': reason,
                                   'tone': VERDICT_TONE.get(mapped, 'neu'),
                                   'target': claim.get('target')}, ('note', 'reason', 'target', 'live_basis')))
        if not claims:
            # 2L-1: an answer that gave no price is judged against the cell's
            # reference whether or not it quoted one. 2C-2c: an expectation
            # with no amount (a code, points) says what it expected, not a dash
            live, basis = _reference_check(expectation, cell) if priced else (None, None)
            if live is None:
                live = '—' if priced and expectation.get('attributed_to') else (
                    money(expectation.get('amount'), expectation.get('currency'))
                    if expectation.get('amount') and not _is_zero(expectation.get('amount')) else
                    '—' if priced else _describe(expectation))
            checks.append(compact({'claim': '—', 'agent': AGENT_NAMES.get(agent, agent),
                                   'live': live, 'live_basis': basis,
                                   'verdict': verdict, 'note': outcome.get('outcome_reason'),
                                   'reason': _reason_code(outcome.get('reason_code')),
                                   'tone': VERDICT_TONE.get(verdict, 'neu')}, ('note', 'reason', 'live_basis')))

    # 2C: which True Value cell this answer is judged in (variant x retailer),
    # so the console's drawer can show the reference price behind the verdict.
    source_ref = _json(query.get('source_ref')) or {}
    # 2M-1: an attribute question's answer, judged against the brand truth:
    # its own one-liner and drawer facts, and claim_kind attribute when it
    # stated a range (soa_shared/attribute_accuracy.py)
    attribute = attribute_accuracy.answer_attribute(source_ref, extraction, run.get('raw_response'),
                                                    truths=truths) if outcome is not None else None
    if attribute is not None and attribute['stated'] is not None:
        kind = claim_kinds.ATTRIBUTE
    own = catalog_verdict(intent, source_ref, extraction, run.get('raw_response'), attribute=attribute,
                          deals=deals, expectation=expectation) if intent and outcome is not None else None
    if intent == claim_kinds.RETIRED and own is not None:
        # 2Q-2 (B2): where a retired line is sold is its "still sold" clause, which is not
        # coded (2L-2): the store check never flags it, nor makes it High
        flags = [f for f in flags if f.get('flag') != 'fabricated_availability']
    named = [m['name'] for m in sorted(mentions, key=lambda m: m.get('position') or 99)]
    first = next((m['name'] for m in mentions if m.get('position') == 1), '')
    # 2T-4 (2): one severity, of the verdict (soa_shared/severity.py). A flag no longer overrides it:
    # a store off a brand's feed is unverified, never High (2T-4 (1)), whatever a row stored before says
    keys = {k for k in (_gtin14(source_ref.get('gtin')), _gtin14(source_ref.get('variant_id')),
                        source_ref.get('variant_id'), source_ref.get('sku'), source_ref.get('variant_ref')) if k}
    stores = stores_in_order(extraction) if club_keys and keys & set(club_keys) else None
    own_domain = _domain_key(source_ref.get('own_domain'))
    listed = [d for d in source_ref.get('retailer_list') or [] if _domain_key(d) != own_domain]
    graded = severity.classify(
        tier=tier, outcome=answer_outcome, reason_code=(outcome or {}).get('reason_code'), flags=flags,
        merchant_kind=source_ref.get('merchant_kind'), intent=intent, intent_verdict=(own or {}).get('verdict'),
        listed=len(listed) if source_ref.get('retailer_list') is not None else None,
        club_only=stores is not None, first_store_club=(stores[0].get('domain') in severity.CLUB_DOMAINS)
        if stores else None,
        brand_in_question=bool(ours) and ea_names_brand(query.get('query_text') or '', ours),
        brand_first=_brand_first(mentions, ours, run.get('answer_status')))
    if own is not None:
        own = {**own, 'severity': graded['severity']}
    summary = (own or {}).get('line') or (outcome or {}).get('outcome_reason') or (
        f"No answer ({run.get('answer_status')})" if run.get('answer_status') not in (None, 'answered')
        else 'Not scored')
    # 2T-5 (A5): a flagged answer's summary is never "Not scored". A comparison answer that put a rival
    # first reads the coded ranking; any other with no line of its own reads its rule's
    if graded['rule'] == severity.BRAND_NOT_FIRST:
        summary = ranking_line(mentions, ours)
    elif severity.is_flagged(graded['severity']) and summary == 'Not scored':
        summary = rule_summary(graded['rule'], ours) or summary
    return compact({
        'id': f"run-{run['id']}",
        'agent': agent,
        'query': query.get('query_text'),
        'queryType': TIER_LABELS.get(tier) or query.get('stage') or '',
        'runAt': _iso(run.get('run_at')),
        'runs': f"run {run.get('run_number')} of {runs_per_query}" if runs_per_query else None,
        'severity': graded['severity'],
        'summary': summary,
        'paragraphs': segments(run.get('raw_response'), extraction.get('spans'), claims),
        'named': named,
        'first': first,
        'checks': checks,
        # ── beside the typed fields ──
        'cycle': cycle_code,
        'platform': platform,
        'surface': run.get('surface') or surfaces.surface_of(platform),
        'collector': run.get('collector') or surfaces.collector_of(platform),
        'answer_status': run.get('answer_status'),
        'tier': tier,
        # 2T-5 (A4): the demo's tab, Accuracy, Value, Category or Brand-direct
        'kind': answer_kind(tier, source_ref.get('intent') or intent),
        # 2K-3: the study's question code (the drawer's "Q13") and its stage
        'query_code': query.get('query_code'),
        'stage': query.get('stage'),
        # 2G: what the question expected (price, member_price, code, points,
        # brand_mention), so a reader can count price claims apart from the rest
        'expected_type': expectation.get('type') or (_json(query.get('query_expected')) or {}).get('type'),
        'reason': _reason_code((outcome or {}).get('reason_code')),
        'verdict': verdict,
        'tone': own['tone'] if own else BRAND_TONE.get(raw, 'neu') if brand else VERDICT_TONE.get(verdict, 'neu'),
        # 2N-1: a catalog-built question's own verdict (catalog_verdict)
        'intent_verdict': (own or {}).get('verdict'),
        'brand_verdict': brand_verdict,
        # 2K-1 (A9): a brand-direct answer's kind, the Answers list's chip: it
        # stated an attribute, or only recommended the brand (soa_shared/claim_kinds.py)
        'claim_kind': kind,
        'claim_kind_label': CLAIM_KIND_LABELS.get(kind),
        'flags': [f.get('flag') for f in flags],
        'flag_details': flags,
        # 2T-4 (2): the rule the severity came from, and a page we could not check (our gap, never flagged)
        'severity_rule': graded['rule'],
        'could_not_check': (outcome or {}).get('outcome_reason') if graded['could_not_check'] else None,
        'variant_id': source_ref.get('variant_id'),
        'gtin': source_ref.get('gtin'),
        'retailer': expectation.get('attributed_to') or source_ref.get('own_domain') or source_ref.get('domain'),
        # 2M-1: the brand-direct intent (2L-4's where_to_buy / cheapest_place, 2M-1's
        # attribute), the Answers list's Accuracy chip; and the attribute verdict.
        # 2N-1: a retired line's question reads 'retired' (claim_kinds.catalog_intent)
        'intent': source_ref.get('intent') or intent,
        'attribute': None if attribute is None else {k: v for k, v in attribute.items() if k != 'line'},
        # 2O-3: the claim that decided a brand-direct verdict, and its facts against the brand's fact index
        'brand_claim': brand_claim_evidence(extraction) if brand_verdict else None,
    }, ('runs', 'reason', 'variant_id', 'gtin', 'retailer', 'expected_type', 'claim_kind', 'claim_kind_label',
        'intent', 'attribute', 'intent_verdict', 'brand_claim', 'could_not_check'))


def brand_claim_evidence(extraction: Optional[dict]) -> Optional[dict]:
    """2O-3: the drawer's evidence for a brand-direct verdict the version-3
    coder decided (extraction.brand_claim, scoring/brand_claim_verdict.py):
    {span, kind, facts_found, facts_missing, facts_unchecked, spans, index}.
    `span` is the claim that decided ("fabricated: '2-9 lbs' is not on
    pampers.com's Swaddlers page" is the row's summary); None when no span
    decided (no_checkable_fact, acknowledged_unknown) or the row predates it.
    2O-4: and `sentences`, every claim sentence judged, in answer order, each
    {text, kind, verdict, facts_found, facts_missing, facts_unchecked,
    decided}, so the drawer lists them all, not only the one that decided.
    2O-5: and `facts_unverified` beside each, on a row coder 5 decided. 2P-1 (B4): and `evidence`,
    what the brand states instead of each contradicted fact."""
    claim = (extraction or {}).get('brand_claim') if isinstance(extraction, dict) else None
    if not isinstance(claim, dict):
        return None
    spans = [s for s in claim.get('spans') or [] if isinstance(s, dict)]
    at = claim.get('decided_by')
    span = spans[at] if isinstance(at, int) and 0 <= at < len(spans) else {}
    out = {'span': span.get('text'), 'kind': span.get('kind'),
           'facts_found': span.get('facts_found') or [], 'facts_missing': span.get('facts_missing') or [],
           'facts_unchecked': span.get('facts_unchecked') or [], 'spans': len(spans),
           'index': claim.get('index'),
           'sentences': [{'text': s.get('text'), 'kind': s.get('kind'), 'verdict': s.get('verdict'),
                          'facts_found': s.get('facts_found') or [], 'facts_missing': s.get('facts_missing') or [],
                          'facts_unchecked': s.get('facts_unchecked') or [], 'decided': i == at,
                          # 2P-1 (B4): what the brand states instead of each contradicted fact
                          # ("pampers.com's chart says under 10 lb"), the scorer's words since coder 6
                          'evidence': [f['evidence'] for f in s.get('facts_missing') or []
                                       if isinstance(f, dict) and f.get('evidence')],
                          **({'facts_unverified': s['facts_unverified']} if 'facts_unverified' in s else {})}
                         for i, s in enumerate(spans)]}
    if 'facts_unverified' in span:
        # 2O-5 (coder 5): facts_missing are the contradicted (slot, claimed, published),
        # facts_unverified those not on the pages read that nothing contradicts
        out['facts_unverified'] = span['facts_unverified']
    return out


# ─── Answers summary (2C) ──────────────────────────────────────────────────

#: Outcomes an accuracy is taken over (soa_shared/surface_accuracy.py SCORED).
#: absent, unscoreable and unverifiable are counted and stay outside it.
SUMMARY_SCORED = ('exact', 'partial', 'stale', 'wrong')
SUMMARY_FLAGS = ('fabricated_citation', 'fabricated_availability', 'variant_swap')


def _summary_cell(rows: List[dict]) -> dict:
    counts: Counter = Counter()
    flags: Counter = Counter()
    other_brand = 0
    answered = 0
    for r in rows:
        # 2C-2b: one rule for every Overview count: a run is answered only
        # when it says so (an errored run has no answer_status).
        if r.get('answer_status') == surfaces.ANSWERED:
            answered += 1
        outcome = r.get('outcome')
        counts[outcome or 'not_scored'] += 1
        if outcome == 'absent' and r.get('reason_code') == 'other_brand':
            other_brand += 1
        for f in _json(r.get('flags')) or []:
            name = f.get('flag') if isinstance(f, dict) else f
            if name:
                flags[name] += 1
    scored = sum(counts.get(o, 0) for o in SUMMARY_SCORED)
    return {
        'runs': len(rows),
        'answered': answered,
        'counts': dict(counts),
        'scored': scored,
        'accuracy': round(counts.get('exact', 0) / scored, 4) if scored else None,
        'unverifiable': counts.get('unverifiable', 0),
        'answered_with_other_brand': other_brand,
        'flags': {name: flags.get(name, 0) for name in SUMMARY_FLAGS},
    }


def _surface_key(row: dict) -> str:
    return row.get('surface') or surfaces.surface_of(row.get('platform')) or 'unlabelled'


def _ordered_surfaces(keys) -> List[str]:
    keys = set(keys)
    return [s for s in surfaces.SURFACE_KINDS if s in keys] + sorted(k for k in keys if k not in surfaces.SURFACE_KINDS)


def build_answers_summary(rows: List[dict], *, cycle_code: str) -> dict:
    """
    /api/console/answers/summary: per tier and per surface, every outcome
    counted, `unverifiable` on its own, and `answered_with_other_brand` (an
    absent whose reason is other_brand: the answer priced another brand's
    product in place of ours). One row per run; a run with no outcome
    counts as `not_scored`.

    2I-8: every list begins with `all` ("All agents"), every run whatever its
    surface, as the console demo counts them: counts summed over the
    surfaces, accuracy exact over scored on those sums, `unverifiable` still
    outside it. Each surface's own entry follows, as before, for the
    console's surface filter. `surfaces` is per surface across the value
    tiers; brand-direct, whose outcomes are not a price verdict, is only in
    `tiers`.

    rows: [{tier, surface, platform, answer_status, outcome, reason_code, flags, intent}]

    2N-1: brand-direct's cells count the AI-written questions' answers only,
    the ones the brand-claim rule judges. A catalog-built question's answers
    (`intent`, claim_kinds.catalog_intent) carry their own verdict and are
    outside those counts; each cell says how many there were (`catalog_built`,
    present when the study asked one).
    """
    by_tier: Dict[str, List[dict]] = {}
    catalog_built: List[dict] = []
    for r in rows:
        if r.get('tier') == 'brand_direct' and r.get('intent'):
            catalog_built.append(r)
            continue
        by_tier.setdefault(r.get('tier') or 'untiered', []).append(r)
    tier_order = [t for t in TIER_LABELS if t in by_tier] + sorted(t for t in by_tier if t not in TIER_LABELS)

    def per_surface(subset: List[dict]) -> List[dict]:
        grouped: Dict[str, List[dict]] = {surfaces.ALL: subset}
        for r in subset:
            grouped.setdefault(_surface_key(r), []).append(r)
        return [{'surface': k, 'label': surfaces.SURFACE_LABELS.get(k, k), **_summary_cell(grouped[k])}
                for k in surfaces.with_all(_ordered_surfaces(set(grouped) - {surfaces.ALL}))]

    value_rows = [r for r in rows if r.get('tier') != 'brand_direct']
    every: Dict[str, List[dict]] = {surfaces.ALL: rows}
    for r in rows:
        every.setdefault(_surface_key(r), []).append(r)
    body = {
        'cycle': cycle_code,
        # 2C-2c: per surface over every tier, by the run-count rule (runs the
        # cycle executed, answers that say answered): what the Answers strip counts
        'all_tiers': [{'surface': k, 'label': surfaces.SURFACE_LABELS.get(k, k), 'runs': len(every[k]),
                       'answered': sum(1 for r in every[k] if r.get('answer_status') == surfaces.ANSWERED)}
                      for k in surfaces.with_all(_ordered_surfaces(set(every) - {surfaces.ALL}))],
        'surfaces': per_surface(value_rows),
        'tiers': [{'tier': t, 'label': TIER_LABELS.get(t, t), 'surfaces': per_surface(by_tier[t])}
                  for t in tier_order],
    }
    for t in body['tiers'] if catalog_built else []:   # absent on a study with none, as before
        if t['tier'] == 'brand_direct':
            for cell in t['surfaces']:
                cell['catalog_built'] = sum(1 for r in catalog_built
                                            if cell['surface'] == surfaces.ALL or _surface_key(r) == cell['surface'])
    return body


def load_answers_summary(conn, cycle: dict) -> dict:
    rows = [dict(r) for r in conn.execute(text("""
        SELECT r.id AS run_id, r.platform, COALESCE(r.surface, o.surface) AS surface,
               r.answer_status, q.tier, q.source_ref, o.outcome, o.reason_code, o.flags
        FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
        LEFT JOIN soa_expectation_outcomes o ON o.run_id = r.id
        WHERE r.cycle_id = :c
    """), {'c': cycle['id']}).mappings()]
    for r in rows:   # 2N-1
        r['intent'] = claim_kinds.catalog_intent(_json(r.pop('source_ref')))
    unpriced = brand_sets_no_price_runs(conn, cycle)
    return build_answers_summary([not_priced(r, unpriced) for r in rows], cycle_code=cycle['cycle_code'])


# ─── TrueValue ─────────────────────────────────────────────────────────────

def _retailer_name(domain):
    names = {'target.com': 'Target', 'walmart.com': 'Walmart', 'amazon.com': 'Amazon',
             'costco.com': 'Costco', 'kroger.com': 'Kroger', 'cvs.com': 'CVS',
             'walgreens.com': 'Walgreens', 'samsclub.com': "Sam's Club", 'chewy.com': 'Chewy',
             'petco.com': 'Petco', 'petsmart.com': 'PetSmart'}
    return names.get(domain, domain)


def _gtin14(value) -> Optional[str]:
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return digits.zfill(14) if digits and len(digits) <= 14 else None


#: 2C-2: what one True Value cell says when several runs priced it. The runs
#: that quoted a price decide: the worst of their scored outcomes (wrong,
#: then stale, then partial, then exact). A run that priced another brand's
#: product (an absent) or quoted nothing is left out of that. When no run
#: quoted a price the cell is left out (`missed`). The quote shown is the
#: deciding run's. Unverifiable stays its own status, never right or wrong.
TV_CELL_RULE = (
    "A cell is the worst outcome among the runs that quoted a price for it (wrong, then stale, then "
    "partial, then exact). When no run quoted a price, it is left out. The quote shown is that run's.")
TV_SCORED = ('wrong', 'stale', 'partial', 'exact')


def aggregate_cell(runs: List[dict]) -> tuple:
    """(outcome, stated) for one cell's runs, by TV_CELL_RULE. (None, None)
    when no run asked."""
    if not runs:
        return None, None
    quoting = [r for r in runs if r.get('stated') not in (None, '')]
    scored = [r for r in quoting if r.get('outcome') in TV_SCORED]
    if scored:
        outcome = min((r['outcome'] for r in scored), key=TV_SCORED.index)
        stated = Counter(str(r['stated']) for r in scored if r['outcome'] == outcome).most_common(1)[0][0]
        return outcome, stated
    if any(r.get('outcome') == 'unverifiable' for r in quoting):
        return 'unverifiable', Counter(str(r['stated']) for r in quoting
                                       if r.get('outcome') == 'unverifiable').most_common(1)[0][0]
    if any(r.get('outcome') == per_unit.PER_UNIT for r in quoting):   # 2N-1: quoted, per diaper
        return per_unit.PER_UNIT, Counter(str(r['stated']) for r in quoting
                                          if r.get('outcome') == per_unit.PER_UNIT).most_common(1)[0][0]
    return 'absent', None


def _surface_order(keys) -> List[str]:
    return sorted(set(keys), key=lambda s: (-_SURFACE_RANK.get(s, 0), s))


def deciding_swap(claims: List[dict], outcome: Optional[str]) -> Optional[dict]:
    """2C-2b: the sibling-variant (or clash) claim that decided a run with no
    claim about the variant asked. A row scored after b3c5a29 carries the
    question's verdict in the claim's own `outcome`; a row scored before it
    (cycle 229) keeps the sibling's verdict there (`exact` for the Trial
    Pack's own price) and the question's in `question_outcome`. Either way
    the quote is the claim's `stated`, so a swap run never reads "no price"."""
    swaps = [c for c in claims or [] if c.get('target') in ('swap', 'clash') and c.get('stated') not in (None, '')]
    return (next((c for c in swaps if (c.get('question_outcome') or c.get('outcome')) == outcome), None)
            or (swaps[0] if swaps else None))


def clash_named(claim: Optional[dict], reason_code: Optional[str]) -> Optional[str]:
    """2R-2 (B5): the product words a quote named ("Pampers ZZZ Size 3,
    116-count") when the price check judged it wrong for naming a variant
    the record does not have (reason variant_clash) and not for its pack
    count (pack_conflict's), else None."""
    if reason_code != 'variant_clash' or not claim or pack_conflict(claim) is not None:
        return None
    return str(claim.get('product') or '').strip() or None


def pack_conflict(claim: Optional[dict]) -> Optional[int]:
    """2Q-1 (B4): the pack count a quote was for, when the price check moved
    it off the asked variant for that count (the claim's `conflict`, "pack
    count 58", scoring/record_variants.conflicts), else None."""
    m = re.match(r'pack count (\d+)', str((claim or {}).get('conflict') or ''))
    return int(m.group(1)) if m else None


def other_pack(reads: Optional[List[dict]], variant: dict, domain: Optional[str]) -> Optional[dict]:
    """2N-1: {price, pack, text} when supply's newest read of the variant's
    page at `domain` found the page's pack is not the variant's (its
    `pack_differs` finding): "other pack ($49.77 for 56 ct)". None otherwise."""
    want = _domain_key(domain)
    hits = [r for r in reads or [] if _domain_key(r.get('retailer_domain')) == want
            and reference_matches(r, variant) and any(f.get('finding') == 'pack_differs' for f in r.get('findings') or [])]
    if not hits:
        return None
    row = max(hits, key=lambda r: str(r.get('observed_at') or ''))
    finding = next(f for f in row.get('findings') or [] if f.get('finding') == 'pack_differs')
    numbers = [n for n in (finding.get('detail') or {}).get('page_numbers') or [] if str(n).strip()]
    pack = f"{numbers[0]} ct" if numbers else (str(finding.get('observed')) if finding.get('observed') else None)
    seen = next((f.get('observed') for f in row.get('findings') or [] if f.get('finding') == 'price_observed'), None)
    price = row.get('price') or seen
    if not price:
        return None
    shown = money(price, row.get('currency') or 'USD')
    return {'price': shown, 'pack': pack, 'text': f"other pack ({shown} for {pack})" if pack else f"other pack ({shown})"}


def _newest_read(reads: Optional[List[dict]], variant: dict) -> Optional[dict]:
    """2C-2a: the newest readable reference read of a record variant (its
    page stated a price), or None when no read of it exists."""
    hits = [r for r in reads or [] if r.get('verifiable') and r.get('price') not in (None, '')
            and reference_matches(r, {'variant_id': variant.get('variant_id'), 'gtin': variant.get('gtin')})]
    return max(hits, key=lambda r: str(r.get('observed_at') or '')) if hits else None


#: 2J-4: supply 2J-1 serves a brand's own page that sets no price as
#: `method: none_by_design` (`verifiable: false`, "brand site, no price
#: set"). The cell's `live` says the page was read and prices nothing, not
#: that it could not be read. (2J-4 left its answers unverifiable; 2K-1 does
#: not score them: BRAND_SETS_NO_PRICE below.)
NOT_PRICED_METHOD = 'none_by_design'
NOT_PRICED = 'not priced'

#: 2K-1: and a catalog-tier price claim attributed to that page is not
#: scored. The scorer says so from 2K-1 on (scoring/retailer_reference.py:
#: `unscoreable`, reason code `brand_sets_no_price`); a cycle scored before
#: stored `unverifiable`, and these read models re-read it so, from the
#: cycle's cached reference: an unverifiable catalog run whose claim was
#: judged against a none_by_design row (the claim's `reference.method`), or
#: whose question is attributed to a page the cached reference serves as
#: none_by_design for its variant. Outside every accuracy and outside the
#: "could not be checked" count; the quote is still shown.
BRAND_SETS_NO_PRICE = 'brand_sets_no_price'
#: 2K-3: two sentences (house rule: no semicolons). The scorer
#: (scoring/retailer_reference.py) still stores 2K-1's wording on a claim it
#: scores; _house_note rewrites that at read time, nothing stored changes.
BRAND_SETS_NO_PRICE_NOTE = "The brand's site sets no price. The agent priced it anyway."
LEGACY_NOTES = {"the brand's site sets no price; the agent priced it anyway": BRAND_SETS_NO_PRICE_NOTE}


def _house_note(row: dict) -> dict:
    """The row with a stored note in 2K-1's wording read in the house's
    (LEGACY_NOTES): its outcome_reason and its claims' reasons."""
    if row.get('outcome_reason') in LEGACY_NOTES:
        row['outcome_reason'] = LEGACY_NOTES[row['outcome_reason']]
    raw = row.get('claim_results')
    if raw is not None and any(n in str(raw) for n in LEGACY_NOTES):
        claims = _json(raw) or []
        for c in claims:
            if isinstance(c, dict) and c.get('reason') in LEGACY_NOTES:
                c['reason'] = LEGACY_NOTES[c['reason']]
        row['claim_results'] = claims
    return row


def _not_priced_pages(reference: Optional[dict]) -> set:
    """(domain, variant key) of every none_by_design row of the brand's own."""
    out = set()
    for row in (reference or {}).get('prices') or []:
        if row.get('method') != NOT_PRICED_METHOD or row.get('role') not in (None, 'own'):
            continue
        domain = _domain_key(row.get('retailer_domain'))
        for key in (_gtin14(row.get('gtin')), row.get('variant_ref'),
                    f"sku:{row['sku']}" if row.get('sku') else None, row.get('sku')):
            if key:
                out.add((domain, str(key)))
    return out


def _domain_key(value) -> Optional[str]:
    from soa_shared.expected_answers import normalize_domain
    return normalize_domain(value)


def is_brand_sets_no_price(outcome: dict, *, expected=None, source_ref=None, pages: Optional[set] = None) -> bool:
    """Whether a stored catalog-tier outcome row is a price the brand's own
    page sets none for (BRAND_SETS_NO_PRICE)."""
    if outcome.get('reason_code') == BRAND_SETS_NO_PRICE:
        return True
    if outcome.get('outcome') != 'unverifiable':
        return False
    claims = _json(outcome.get('claim_results')) or []
    if any((c.get('reference') or {}).get('method') == NOT_PRICED_METHOD for c in claims if isinstance(c, dict)):
        return True
    expected = _json(expected if expected is not None else outcome.get('expected_answer')) or {}
    ref = _json(source_ref) or {}
    domain = _domain_key(expected.get('attributed_to'))
    if not domain or not pages:
        return False
    keys = {str(k) for k in (_gtin14(ref.get('gtin')), _gtin14(ref.get('variant_id')), ref.get('variant_id'),
                             ref.get('variant_ref')) if k}
    return any((domain, k) in pages for k in keys)


def brand_sets_no_price_runs(conn, cycle: dict) -> set:
    """The cycle's catalog-tier runs whose price the brand's own page sets
    none for. One read of the outcomes; the cycle row's cached reference."""
    reference = cycle.get('reference_prices') if 'reference_prices' in cycle else conn.execute(text(
        "SELECT reference_prices FROM soa_cycles WHERE id = :c"), {'c': cycle['id']}).scalar()
    pages = _not_priced_pages(_json(reference))
    out = set()
    for r in conn.execute(text("""
        SELECT o.run_id, o.outcome, o.reason_code, o.claim_results, o.expected_answer, q.source_ref
        FROM soa_expectation_outcomes o JOIN soa_queries q ON q.id = o.query_id
        WHERE o.cycle_id = :c AND o.tier = 'catalog_accuracy'
          AND (o.outcome = 'unverifiable' OR o.reason_code = :code)
    """), {'c': cycle['id'], 'code': BRAND_SETS_NO_PRICE}).mappings():
        row = dict(r)
        if is_brand_sets_no_price(row, source_ref=row.get('source_ref'), pages=pages):
            out.add(row['run_id'])
    return out


def not_priced(row: dict, runs: set, key: str = 'run_id') -> dict:
    """The row with its outcome re-read as the brand's own page setting no
    price, when it is one of `runs`; else as it is (2K-3: a stored note in
    the house wording, _house_note). Its claims too."""
    if row.get(key) not in runs:
        return _house_note(row)
    row['outcome'] = 'unscoreable'
    row['reason_code'] = BRAND_SETS_NO_PRICE
    if 'outcome_reason' in row:
        row['outcome_reason'] = BRAND_SETS_NO_PRICE_NOTE
    if row.get('claim_results') is not None:
        claims = _json(row['claim_results']) or []
        for c in claims:
            if isinstance(c, dict) and c.get('target', 'asked') == 'asked' and c.get('outcome') in ('unverifiable', 'unscoreable'):
                c.update(outcome='unscoreable', reason_code=BRAND_SETS_NO_PRICE, reason=BRAND_SETS_NO_PRICE_NOTE)
        row['claim_results'] = claims
    return row


def feed_sku_rows(feed: Optional[dict], catalog: Optional[dict]) -> List[dict]:
    """2K-3: the merchant's own codes as the Catalog screen joins them:
    supply's feed rows (an external merchant: sku, gtin14, variant_key),
    then the published catalog's variants (a hosted one: variant_id
    `sku:<sku>`, gtin), for build_true_value's `feed_rows`."""
    rows = [r for r in (feed or {}).get('rows') or [] if isinstance(r, dict)]
    for listing in (catalog or {}).get('listings') or []:
        for v in listing.get('variants') or []:
            rows.append({'sku': v.get('sku'), 'gtin': v.get('gtin'), 'variant_key': v.get('variant_id')})
    return rows


#: 2T-4 (3): a cell's second line, the page read after the one its runs were judged against
T_TV_LATER = 'page read later: {live}, {day}'
#: 2T-4 (3): the fields of a read that make it the same read
_READ_KEYS = ('price', 'verifiable', 'observed_at', 'method')


def judged_read(claim: Optional[dict], outcome: Optional[str], reason: Optional[str] = None) -> Optional[dict]:
    """
    2T-4 (3): the read a run was judged against: its deciding claim's
    `reference` (the scorer's ReferenceRow: price, verifiable, read status,
    source, method, observed_at), or, for a run stored unverifiable with no
    claim carrying one ("no reference row for this page"), an unreadable
    read with the scorer's reason. None when the run carries no read (scored
    against the record, or before the scorer stored one): the cell's own
    reference is then the read.
    """
    reference = (claim or {}).get('reference') if isinstance(claim, dict) else None
    if isinstance(reference, dict) and reference:
        return {k: reference.get(k) for k in ('price', 'currency', 'verifiable', 'unverifiable_reason', 'read_status',
                                             'reference_source', 'method', 'observed_at', 'url')}
    if outcome == 'unverifiable':
        return {'price': None, 'verifiable': False, 'unverifiable_reason': reason, 'observed_at': None}
    return None


def _same_read(a: Optional[dict], b: Optional[dict]) -> bool:
    if a is None or b is None:
        return a is b
    pa, pb = a.get('price'), b.get('price')
    same_price = pa == pb or (pa not in (None, '') and pb not in (None, '') and _money_eq(pa, pb))
    return same_price and bool(a.get('verifiable', True)) == bool(b.get('verifiable', True)) and \
        (a.get('observed_at') is None or b.get('observed_at') is None or
         str(a.get('observed_at'))[:19] == str(b.get('observed_at'))[:19])


def _money_eq(a, b) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.005
    except (TypeError, ValueError):
        return str(a) == str(b)


def _judged_of(runs: List[dict]) -> Optional[dict]:
    """The read a cell's runs were judged against: the one most of them carry (they share the cycle's
    cached read), the newest on a tie; None when none carries one."""
    reads = [r['judged'] for r in runs if isinstance(r.get('judged'), dict)]
    if not reads:
        return None
    counts = Counter(json.dumps({k: rd.get(k) for k in _READ_KEYS}, sort_keys=True, default=str) for rd in reads)
    top = max(counts.values())
    tied = [rd for rd in reads if counts[json.dumps({k: rd.get(k) for k in _READ_KEYS}, sort_keys=True, default=str)] == top]
    return max(tied, key=lambda rd: str(rd.get('observed_at') or ''))


def build_true_value(reference: Optional[dict], scored: List[dict], *, own_domain: Optional[str],
                     record_variants: List[dict], reads: Optional[List[dict]] = None,
                     feed_rows: Optional[List[dict]] = None, brands: Optional[Dict[str, str]] = None) -> dict:
    """
    TrueValue: rows = variants; cells = TvCell {quoted, live, status}.

    2L-2: a retired variant's row carries `retired` (retired_view): from the
    feed's row when it has one, else from the retailer-prices row, whose
    successor is labelled with its own brand (`brands`: variant_id -> the
    catalog listing's brand) taken off its name.

    `live` is the 2A reference (supply's retailer-prices row cached on the
    cycle). With no reference cached (a cycle scored against the record),
    2C-2a: `live` is the newest readable reference read of the variant's
    page when `reads` (supply's /reference rows) has one, else the record's
    price, and `live_basis` says which ('reference_read' | 'record').

    2C-2: `by_surface` has each surface's cell, and `quotes` every run's
    quote with its agent and surface. TV_CELL_RULE decides each. `by_agent`
    is prices exact / scored per agent, per surface. 2I-8: the typed
    quoted/status are the cell on `surface`, which is `all`: TV_CELL_RULE
    over every agent's quotes, as the console demo counts them; `by_surface`
    and `by_agent` begin with `all`, each surface's own beside it.

    2C-2a: the columns are the record's retailers when it has two or more
    (`column_kind: 'retailer'`), else the agents (`column_kind: 'agent'`):
    with one retailer every agent would collapse into one worst-wins cell.
    Agent columns are per surface (`columns_by_surface`); each row keeps its
    one-retailer cell in `retailer_cells` for readers that want the product.

    scored: [{variant_id, gtin, retailer, outcome, stated, surface, agent,
    run, swap_product}], one per scored run of a price question.

    2K-3: each row carries `gtin` (None without one) and `feed_sku`, the
    merchant's own code from its feed: the reference read's `sku`, a record
    variant keyed `sku:<sku>`, or `feed_rows` (supply's feed rows, or the
    hosted catalog's variants, as the Catalog screen joins them) matched on
    the row's aliases. A row with no GTIN serves that code as its `sku` in
    place of supply's reference (`feed_sku:<n>`); a GTIN row's `sku` stays
    its GTIN, the key the console joins an answer to its row by.
    """
    rows_by_key: Dict[str, dict] = {}
    alias: Dict[str, str] = {}
    feed_sku: Dict[str, str] = {}
    retired: Dict[str, dict] = {}
    columns: List[str] = []
    live: Dict[tuple, dict] = {}

    for row in (reference or {}).get('prices') or []:
        domain = row.get('retailer_domain')
        key = _gtin14(row.get('gtin')) or row.get('variant_ref')
        # 2J-2: and sku:<sku>, supply's key for a variant with no GTIN, which
        # a question asked about it carries as its variant_id; its read's
        # variant_ref is feed_sku:<n>, so without it the quotes found no row
        for a in (key, row.get('variant_ref'), row.get('variant_label'), row.get('sku'),
                  f"sku:{row['sku']}" if row.get('sku') else None):
            if a:
                alias.setdefault(str(a), key)
        if domain and domain not in columns:
            columns.append(domain)
        rows_by_key.setdefault(key, {'product': row.get('variant_label') or key, 'sku': row.get('gtin') or key,
                                     'gtin': _gtin14(row.get('gtin'))})
        if row.get('sku'):
            feed_sku.setdefault(key, str(row['sku']))
        if row.get('status') == 'retired':   # 2L-2: supply's retailer-prices row says so
            succ = row.get('successor') or {}
            retired.setdefault(key, retired_view('retired', row.get('successor'),
                                                 (brands or {}).get(str(succ.get('variant_id')))))
        live[(key, domain)] = {**row, 'live_basis': 'reference_read'}

    if not reference:
        if own_domain:
            columns.append(own_domain)
        for v in record_variants:
            key = v['variant_id']
            for a in (key, _gtin14(v.get('gtin'))):
                if a:
                    alias.setdefault(str(a), key)
            rows_by_key.setdefault(key, {'product': v.get('label') or key, 'sku': v.get('gtin') or key,
                                         'gtin': _gtin14(v.get('gtin'))})
            if str(key).startswith('sku:'):
                feed_sku.setdefault(key, str(key)[len('sku:'):])
            read = _newest_read(reads, v)
            live[(key, own_domain)] = (
                {'price': read.get('price'), 'verifiable': True, 'currency': read.get('currency') or v.get('currency'),
                 'reference_source': read.get('reference_source'), 'method': read.get('method'),
                 'observed_at': read.get('observed_at'), 'live_basis': 'reference_read', 'url': read.get('url')}
                if read else
                {'price': v.get('list_price'), 'verifiable': True, 'currency': v.get('currency'),
                 'reference_source': 'record', 'observed_at': v.get('published_at'), 'live_basis': 'record'})

    feed_retired_by = feed_retired([f for f in feed_rows or [] if isinstance(f, dict)])
    for f in feed_rows or []:
        code = f.get('sku') or (str(f['variant_key'])[len('sku:'):] if str(f.get('variant_key') or '').startswith('sku:')
                                else None)
        if not code:
            continue
        for a in (_gtin14(f.get('gtin14') or f.get('gtin')), f.get('variant_key'), f"sku:{code}", code,
                  f.get('variant_label')):
            if a and str(a) in alias:
                feed_sku.setdefault(alias[str(a)], str(code))
                if code in feed_retired_by:   # the feed's row knows its brand: it wins
                    retired[alias[str(a)]] = feed_retired_by[code]
                break
    for key, meta in rows_by_key.items():
        meta['feed_sku'] = feed_sku.get(key)
        meta['retired'] = retired.get(key)
        if not meta['gtin'] and meta['feed_sku']:
            meta['sku'] = meta['feed_sku']

    grouped: Dict[tuple, List[dict]] = {}
    for item in scored:
        key = next((alias[str(a)] for a in (item.get('variant_id'), _gtin14(item.get('gtin'))) if a and str(a) in alias), None)
        if key is None:
            continue
        domain = item.get('retailer') or own_domain
        grouped.setdefault((key, domain), []).append(item)

    surface_of_run = lambda i: i.get('surface') or 'unlabelled'  # noqa: E731
    surface_list = _surface_order(surface_of_run(i) for runs in grouped.values() for i in runs)
    # 2I-8: the typed fields read every agent together (`all`), each
    # surface's own cell beside it
    keys = surfaces.with_all(surface_list)
    default = keys[0] if keys else None

    def cell_for(runs, ref):
        # 2T-4 (3): the verdict is the read the runs were judged against, never a later one
        ref = _judged_of(runs) or ref
        outcome, stated = aggregate_cell(runs)
        if ref is not None and ref.get('method') == NOT_PRICED_METHOD:
            # 2K-1: the brand's own page sets no price: its quotes are not scored
            status = 'none'
        elif ref is not None and not ref.get('verifiable', True) and runs:
            status = 'unverifiable'
        else:
            status = TV_STATUS.get(outcome, 'none') if outcome else 'none'
        return {'quoted': money(stated) if stated else '—', 'status': status, 'outcome': outcome, 'runs': len(runs)}

    def live_of(read):
        if read is None:
            return '—'
        if read.get('method') == NOT_PRICED_METHOD:
            return NOT_PRICED
        if not read.get('verifiable', True):
            return 'unverifiable'
        return money(read.get('price'), read.get('currency') or 'USD')

    def full_cell(runs, ref, surfaces_here):
        # 2T-4 (3): one read per cell. The price and the verdict are the read the runs were judged against;
        # a later read of the same page is a second line (`later`), never the price beside that verdict
        judged = _judged_of(runs)
        later = None
        if judged is not None and ref is not None and not _same_read(judged, ref) and ref.get('observed_at') and \
                (not judged.get('observed_at') or str(ref['observed_at']) > str(judged['observed_at'])):
            later = {'live': live_of(ref), 'observed_at': ref.get('observed_at'),
                     'text': T_TV_LATER.format(live=live_of(ref) if live_of(ref) != 'unverifiable' else
                                               'could not be read', day=_short_day(ref.get('observed_at')))}
        if judged is not None:
            ref = {**(ref or {}), **{k: v for k, v in judged.items() if k != 'currency' or v}}
        live_text = live_of(ref)
        by_surface = {s: cell_for([r for r in runs if surfaces.on_surface(surface_of_run(r), s)], ref)
                      for s in surfaces.with_all(surfaces_here)
                      if any(surfaces.on_surface(surface_of_run(r), s) for r in runs)}
        top = by_surface.get(default) or cell_for([], ref)
        return {
            'quoted': top['quoted'], 'live': live_text, 'status': top['status'],
            # beside the typed fields
            'outcome': top['outcome'], 'runs': top['runs'],
            # 2C: where `live` came from, so "honest fetch" and "hosted render"
            # are told apart; 'record' when no reference was read.
            'reference_source': (None if ref is None else
                                 ref.get('reference_source') or ('record' if not reference else None)),
            'method': None if ref is None else ref.get('method'),
            'observed_at': None if ref is None else ref.get('observed_at'),
            'live_basis': None if ref is None else ref.get('live_basis'),
            # 2C-2: every surface's cell, and every run's quote
            'surface': default if top['runs'] else None,
            **({'later': later} if later else {}),
            'by_surface': by_surface,
            'quotes': [{'agent': r.get('agent'), 'surface': surface_of_run(r), 'outcome': r.get('outcome'),
                        'stated': None if r.get('stated') in (None, '') else str(r['stated']),
                        'run': r.get('run'), **({'swap_product': r['swap_product']} if r.get('swap_product') else {}),
                        **({'swap_variant': r['swap_variant']} if r.get('swap_variant') else {}),
                        **({'pack': r['pack']} if r.get('pack') else {}),
                        **({'clash': r['clash']} if r.get('clash') else {})}
                       for r in runs],
        }

    by_agent_runs = len(columns) < 2
    agents_on: Dict[str, List[str]] = {}
    if by_agent_runs:
        for runs in grouped.values():
            for r in runs:
                agents_on.setdefault(surface_of_run(r), [])
                a = r.get('agent') or 'unknown'
                if a not in agents_on[surface_of_run(r)]:
                    agents_on[surface_of_run(r)].append(a)
        order = list(AGENT_NAMES)
        for s in agents_on:
            agents_on[s].sort(key=lambda a: (order.index(a) if a in order else 99, a))
    agent_columns = sorted({a for xs in agents_on.values() for a in xs},
                           key=lambda a: (list(AGENT_NAMES).index(a) if a in AGENT_NAMES else 99, a))
    domain = columns[0] if columns else own_domain

    rows = []
    for key, meta in rows_by_key.items():
        retailer_cells = {d: full_cell(grouped.get((key, d), []), live.get((key, d)), surface_list) for d in columns}
        for d, cell in retailer_cells.items():
            # 2N-1: a page priced for another pack is no price to check against
            pack = other_pack(reads, {'variant_id': key, 'gtin': meta['gtin']}, d) if cell['status'] == 'unverifiable' else None
            if pack:
                cell['other_pack'] = pack
        if by_agent_runs and agent_columns:
            runs = grouped.get((key, domain), [])
            cells = {a: full_cell([r for r in runs if (r.get('agent') or 'unknown') == a], live.get((key, domain)),
                                  [s for s in surface_list if a in agents_on.get(s, [])])
                     for a in agent_columns}
            rows.append({'product': meta['product'], 'sku': meta['sku'], 'cells': cells, 'retailer_cells': retailer_cells,
                         'variant_id': key, 'gtin': meta['gtin'], 'feed_sku': meta['feed_sku'],
                         **({'retired': meta['retired']} if meta['retired'] else {})})
        else:
            rows.append({'product': meta['product'], 'sku': meta['sku'], 'cells': retailer_cells, 'variant_id': key,
                         'gtin': meta['gtin'], 'feed_sku': meta['feed_sku'],
                         **({'retired': meta['retired']} if meta['retired'] else {})})

    by_agent: Dict[str, Dict[str, dict]] = {}
    for item in scored:
        a = item.get('agent') or 'unknown'
        for s in (surface_of_run(item), surfaces.ALL):
            c = by_agent.setdefault(s, {}).setdefault(a, {'exact': 0, 'scored': 0, 'wrong': 0, 'stale': 0,
                                                           'partial': 0, 'unverifiable': 0, 'left_out': 0,
                                                           'other_brand': 0})
            o = item.get('outcome')
            if o in TV_SCORED:
                c['scored'] += 1
                if o in c:
                    c[o] += 1
            elif o == 'unverifiable':
                c['unverifiable'] += 1
            elif o == 'absent':
                c['left_out'] += 1
                if item.get('reason_code') == 'other_brand':
                    c['other_brand'] += 1
    order = list(AGENT_NAMES)
    if surfaces.ALL in by_agent:
        by_agent[surfaces.ALL] = dict(sorted(by_agent[surfaces.ALL].items(),
                                             key=lambda kv: (order.index(kv[0]) if kv[0] in order else 99, kv[0])))
    agents_on[surfaces.ALL] = agent_columns

    retailer_columns = [{'id': d, 'name': _retailer_name(d), 'you': d == own_domain} for d in columns]
    agent_col = lambda a: {'id': a, 'name': AGENT_NAMES.get(a, a), 'kind': 'agent', 'retailer': domain,  # noqa: E731
                           'retailer_name': _retailer_name(domain) if domain else None}
    agent_kind = by_agent_runs and bool(agent_columns)
    return {
        'columns': ([agent_col(a) for a in agents_on.get(default, agent_columns)] if agent_kind else retailer_columns),
        'rows': rows,
        'programs': [],
        'as_of': (reference or {}).get('as_of'),
        # 2C-2
        'surface': default,
        'surfaces': [{'surface': s, 'label': surfaces.SURFACE_LABELS.get(s, s)} for s in keys],
        'by_agent': {s: by_agent.get(s, {}) for s in keys},
        'cell_rule': TV_CELL_RULE,
        # 2C-2a
        'column_kind': 'agent' if agent_kind else 'retailer',
        'columns_by_surface': ({s: [agent_col(a) for a in agents_on.get(s, [])] for s in keys} if agent_kind
                               else {s: retailer_columns for s in keys}),
        'retailer_columns': retailer_columns,
        'divergences': [
            "TvCell.status is extended by 'unverifiable' (the page blocked both reference sources).",
            "A stale quote has status 'wrong' (it is wrong today); `outcome` carries 'stale'.",
            "`programs` is empty unless `merchant` is given (2C-2): then the merchant's programs.",
            "Each cell carries reference_source (honest_fetch | hosted_render | record), method and "
            "observed_at beside the typed fields (2C), and live_basis (2C-2a).",
            "2C-2: TvCell.quoted / status are the cell on `surface`; `by_surface` has each surface's and "
            "`quotes` every run's. TV_CELL_RULE decides a cell. 2I-8: `surface` is `all`, every agent's "
            "quotes together, as the demo counts them; each surface's cell is beside it in `by_surface`.",
            "2C-2a: with one retailer in the record the columns are agents (column_kind 'agent', per surface "
            "in columns_by_surface, `all` with every agent); the one-retailer cell rides beside as retailer_cells.",
        ],
    }


# ─── Programs (2C) ─────────────────────────────────────────────────────────

def _program_terms(inc: dict) -> str:
    parts = []
    cur = inc.get('currency') or 'USD'
    if inc.get('member_price'):
        parts.append(f"{money(inc['member_price'], cur)} member price")
    if inc.get('discount_percent'):
        parts.append(f"{inc['discount_percent'].rstrip('0').rstrip('.')}% off")
    if inc.get('discount_amount'):
        parts.append(f"{money(inc['discount_amount'], cur)} off")
    if inc.get('points'):
        parts.append(f"{inc['points']} points")
    if inc.get('points_multiplier'):
        parts.append(f"{inc['points_multiplier'].rstrip('0').rstrip('.')}x points")
    if inc.get('code'):
        parts.append(f"code {inc['code']}")
    scope = inc.get('applies_to_category') or (f"{len(inc['applies_to_gtins'])} GTINs" if inc.get('applies_to_gtins')
                                                 else inc.get('applies_to'))
    if scope:
        parts.append(f"on {scope}")
    if inc.get('valid_until'):
        parts.append(f"until {str(inc['valid_until'])[:10]}")
    return ', '.join(parts) or (inc.get('mechanic') or '').replace('_', ' ')


def _norm_code(value) -> Optional[str]:
    return str(value).strip().upper() or None if value else None


def _norm_tier(value) -> Optional[str]:
    from soa_shared.expected_answers import normalize_tier_name
    return normalize_tier_name(value)


def _program_matches(inc: dict, expected: dict, source_ref: Optional[dict] = None) -> bool:
    """2C-2a: a value & incentives answer is about a program when the
    question's offer id is one of the program's (codes and points carry it
    from the record), or its code matches, or its tier name matches, folded
    the way the scorer folds it (soa_shared.expected_answers): the generator
    wrote both from the record, so these are the same identifiers, never a
    display name."""
    offer = (source_ref or {}).get('offer_id')
    if offer and offer in (inc.get('offer_ids') or []):
        return True
    if inc.get('code') and expected.get('code'):
        return _norm_code(expected['code']) == _norm_code(inc['code'])
    if inc.get('tier_name') and expected.get('tier_name'):
        return _norm_tier(expected['tier_name']) == _norm_tier(inc['tier_name'])
    return False


def record_programs(record: Optional[dict]) -> List[dict]:
    """2C-2a: the programs in the record (supply's /incentives, what the
    generator read): one per loyalty tier with the member prices the record
    states for it, one per promo code, one per points rule set. Each carries
    the identifiers the generator wrote into its questions (tier name, code,
    offer ids)."""
    program = (record or {}).get('program_name')
    tiers: Dict[str, dict] = {}
    codes: Dict[str, dict] = {}
    points: Dict[str, dict] = {}
    for listing in (record or {}).get('listings') or []:
        for v in listing.get('variants') or []:
            stated = [(mp.get('tier_name'), mp.get('price')) for mp in v.get('member_prices') or []]
            stated.append((v.get('entitled_tier_name'), v.get('entitled_member_price')))
            for tier, price in stated:
                if tier and _num(price) is not None:
                    t = tiers.setdefault(_norm_tier(tier), {'tier_name': tier, 'prices': {}})
                    t['prices'][v.get('variant_id')] = min(_num(price), t['prices'].get(v.get('variant_id'), _num(price)))
        for inc in listing.get('incentives') or []:
            code = inc.get('promo_code') or inc.get('code')
            if code:
                c = codes.setdefault(_norm_code(code), {'code': code, 'offer_ids': set(), 'incentive': inc})
                if inc.get('offer_id'):
                    c['offer_ids'].add(inc['offer_id'])
            elif inc.get('mechanic') in ('points_earn', 'points') and inc.get('offer_id'):
                name = inc.get('program_name') or program or 'Points'
                points.setdefault(name, set()).add(inc['offer_id'])
            if inc.get('tier_name') and inc.get('eligibility_kind') == 'tier':
                tiers.setdefault(_norm_tier(inc['tier_name']), {'tier_name': inc['tier_name'], 'prices': {}})
    out = []
    for t in tiers.values():
        vals = sorted(t['prices'].values())
        terms = (f"{t['tier_name']} price on {len(vals)} {'variant' if len(vals) == 1 else 'variants'}, "
                 + (money(f'{vals[0]:.2f}') if vals[0] == vals[-1] else f"{money(f'{vals[0]:.2f}')} to {money(f'{vals[-1]:.2f}')}")
                 if vals else f"{t['tier_name']} discount, stated without a price")
        out.append({'name': f"{program} {t['tier_name']}" if program else t['tier_name'], 'tier_name': t['tier_name'],
                    'terms': terms, 'mechanic': 'member_price', 'offer_ids': [], 'source': 'record'})
    for c in codes.values():
        inc, value = c['incentive'], c['incentive'].get('value') or {}
        bits = [f"{str(value['discount_percent']).rstrip('0').rstrip('.')}% off" if value.get('discount_percent') else None,
                f"{money(value['discount_amount'])} off" if value.get('discount_amount') else None,
                'new customers' if inc.get('eligibility_kind') == 'new_customer' else None]
        out.append({'name': c['code'], 'code': c['code'], 'terms': ', '.join(b for b in bits if b) or f"code {c['code']}",
                    'mechanic': inc.get('mechanic'), 'offer_ids': sorted(c['offer_ids']), 'source': 'record',
                    'valid_until': inc.get('valid_until')})
    for name, ids in points.items():
        out.append({'name': f"{name} points", 'terms': f"points on {len(ids)} {'offer' if len(ids) == 1 else 'offers'}",
                    'mechanic': 'points', 'offer_ids': sorted(ids), 'source': 'record'})
    return out


def _program_agents(scored: List[dict]) -> Dict[str, dict]:
    """2C-2: per surface, the agents that answered a scored question about a
    program and the ones that got every such answer right; 2C-2a: and the
    scored answers and exact ones. 2I-8: `all` first, every agent."""
    out: Dict[str, dict] = {surfaces.ALL: {'agents': {}}} if scored else {}
    for o in scored:
        s = o.get('surface') or surfaces.surface_of(o.get('platform')) or 'unlabelled'
        a = surfaces.agent_of(o.get('platform')) or o.get('platform') or 'unknown'
        for key in (surfaces.ALL, s):
            out.setdefault(key, {'agents': {}})['agents'].setdefault(a, []).append(o.get('outcome'))
    for entry in out.values():
        per = entry.pop('agents')
        entry['asked'] = sorted(per)
        entry['right'] = sorted(a for a, outs in per.items() if all(x == 'exact' for x in outs))
        entry['scored'] = sum(len(outs) for outs in per.values())
        entry['exact'] = sum(1 for outs in per.values() for x in outs if x == 'exact')
    return out


def build_programs(incentives: List[dict], value_outcomes: List[dict], *, record: Optional[dict] = None) -> List[dict]:
    """
    TrueValue.programs. 2C-2a: the record's programs first (record_programs:
    the generator's source, so its questions join on the same identifiers),
    then each owned incentive the record does not already have. 2C-2:
    `agentsRight` is "quoted right by N of M agents" over every agent (2I-8:
    `all`; before, the highest-fidelity surface that asked about the program), where an agent is right when every
    scored answer it gave about the program was exact (scored excludes
    absent, unscoreable and unverifiable); `by_surface` beside has every
    surface's agents and answers. A program no question asked about says so
    rather than showing 0.

    value_outcomes: [{outcome, expected_answer, platform, surface,
    source_ref}] for tier value_incentives.
    """
    programs = record_programs(record)
    have_codes = {_norm_code(p.get('code')) for p in programs if p.get('code')}
    have_tiers = {_norm_tier(p.get('tier_name')) for p in programs if p.get('tier_name')}
    for inc in incentives or []:
        if (inc.get('code') and _norm_code(inc['code']) in have_codes) or \
                (inc.get('tier_name') and _norm_tier(inc['tier_name']) in have_tiers):
            continue
        programs.append({**inc, 'name': inc.get('name') or inc.get('tier_name') or inc.get('code') or (inc.get('mechanic') or 'Program'),
                         'terms': _program_terms(inc), 'offer_ids': [], 'source': 'owned_incentive'})
    out = []
    for prog in programs:
        about = [o for o in value_outcomes
                 if _program_matches(prog, _json(o.get('expected_answer')) or {}, _json(o.get('source_ref')) or {})]
        scored = [o for o in about if o.get('outcome') in SUMMARY_SCORED]
        right = sum(1 for o in scored if o.get('outcome') == 'exact')
        per = _program_agents(scored)
        top = _surface_order(per)[0] if per else None
        if not about:
            agents_right, tone = 'not asked this cycle', 'neu'
        elif not scored:
            agents_right, tone = f"{len(about)} asked, none scored", 'neu'
        else:
            n, m = len(per[top]['right']), len(per[top]['asked'])
            agents_right = f"quoted right by {n} of {m} {'agent' if m == 1 else 'agents'}"
            tone = 'ok' if n == m else 'bad' if n == 0 else 'warn'
        out.append({
            'name': prog['name'], 'terms': prog['terms'], 'agentsRight': agents_right, 'tone': tone,
            # beside the typed fields
            'mechanic': prog.get('mechanic'), 'code': prog.get('code'), 'tier_name': prog.get('tier_name'),
            'valid_until': prog.get('valid_until'), 'asked': len(about), 'scored': len(scored), 'right': right,
            'surface': top, 'by_surface': per, 'source': prog.get('source'), 'offer_ids': prog.get('offer_ids') or [],
        })
    return out


# ─── Setup > Catalog (2C) ──────────────────────────────────────────────────

#: The 2A-1 warning soa adds to supply's feed preview (supply's validate has
#: not read the pages; the full loop's record-vs-page findings have).
MULTIPACK_SUGGESTED = 'multipack_suggested'


def _gtin14_or(value) -> Optional[str]:
    return _gtin14(value) or (str(value) if value else None)


def annotate_feed_preview(preview: dict, reference: Optional[dict], *, reference_error: Optional[str] = None) -> dict:
    """
    supply's feed preview with one more warning per row: the latest
    reference read of one of the row's pages showed a count-shaped number
    (`pack_differs`) while the row gives pack_count and no multipack. When
    a page number is a whole multiple of pack_count, the multiple is the
    suggested multipack. A row that was `ready` becomes `warning`; the
    summary's counts follow. Nothing here can make a row an error.
    """
    preview = dict(preview or {})
    findings = {}
    for row in (reference or {}).get('rows') or []:
        key = _gtin14_or(row.get('gtin'))
        for f in row.get('findings') or []:
            if f.get('finding') == 'pack_differs':
                findings.setdefault(key, []).append({**f, 'retailer_domain': row.get('retailer_domain'),
                                                     'url': row.get('url')})
    rows = []
    for row in preview.get('rows') or []:
        row = dict(row)
        messages = list(row.get('messages') or [])
        pack = row.get('pack_count')
        hits = findings.get(_gtin14_or(row.get('gtin'))) or []
        if hits and pack and not row.get('multipack'):
            page_numbers = sorted({int(n) for f in hits for n in ((f.get('detail') or {}).get('page_numbers') or [])
                                   if str(n).isdigit()})
            multiples = [n // int(pack) for n in page_numbers if n > int(pack) and n % int(pack) == 0]
            where = hits[0].get('retailer_domain') or 'a page'
            shown = ', '.join(str(n) for n in page_numbers) or hits[0].get('observed') or 'a count'
            text_ = (f"page shows a count but multipack is empty: {where} shows {shown}, the row says "
                     f"pack_count {pack}")
            if multiples:
                text_ += f", and multipack {multiples[0]} would explain it"
            messages.append({'code': MULTIPACK_SUGGESTED, 'severity': 'warning', 'field': 'multipack',
                             'message': text_, 'source': 'soa', 'suggested': multiples[0] if multiples else None})
            if row.get('status') == 'ready':
                row['status'] = 'warning'
        row['messages'] = messages
        rows.append(row)
    preview['rows'] = rows
    summary = dict(preview.get('summary') or {})
    if rows:
        statuses = [r.get('status') for r in rows]
        summary.update(ready=statuses.count('ready'), warning=statuses.count('warning'),
                       error=statuses.count('error'))
    preview['summary'] = summary
    preview['reference_checked'] = reference is not None
    if reference_error:
        preview['reference_error'] = reference_error
    return preview


# ─── Retired (2L-2) ────────────────────────────────────────────────────────

def retired_view(status: Optional[str], successor: Optional[dict], brand: Optional[str] = None) -> Optional[dict]:
    """2L-2: a retired variant's `retired`, the console's "Retired → AMORE"
    chip and successor link: {successor: {variant_id, sku, product_name,
    label} | None}. None for an active variant (or one from before 2L-2)."""
    if status != 'retired':
        return None
    if not successor:
        return {'successor': None}
    name = successor.get('product_name') or successor.get('title')
    return {'successor': {'variant_id': successor.get('variant_id'), 'sku': successor.get('sku'),
                          'product_name': name, 'label': retired_lines.label(name, brand)}}


def feed_retired(rows: List[dict]) -> Dict[str, dict]:
    """retired_view for each retired row of supply's /feed (lifecycle and
    successor_variant_key, on a retired row only), keyed by its variant_key,
    sku and gtin14; the successor is the row whose variant_key it names."""
    by_key = {r.get('variant_key') or r.get('gtin14'): r for r in rows if r.get('variant_key') or r.get('gtin14')}
    out: Dict[str, dict] = {}
    for r in rows:
        if r.get('lifecycle') != 'retired':
            continue
        succ = by_key.get(r.get('successor_variant_key')) if r.get('successor_variant_key') else None
        view = retired_view('retired', {'variant_id': r.get('successor_variant_key'), 'sku': succ.get('sku'),
                                        'product_name': succ.get('product_name'), 'title': succ.get('variant_label')}
                            if succ else None, r.get('brand_name'))
        for k in (r.get('variant_key'), r.get('sku'), r.get('gtin14')):
            if k:
                out[str(k)] = view
    return out


def catalog_brands(catalog: Optional[dict]) -> Dict[str, str]:
    """variant_id -> its listing's brand, from supply's catalog."""
    return {str(v.get('variant_id')): listing.get('brand') for listing in (catalog or {}).get('listings') or []
            for v in listing.get('variants') or [] if listing.get('brand') and v.get('variant_id')}


def build_catalog(merchant: str, *, feed: Optional[dict], history: List[dict], hosted_catalog: Optional[dict]) -> dict:
    """GET /api/console/catalog: one shape for both kinds of merchant.
    `source` is 'feed' (an external merchant's committed feed), 'hosted'
    (a Parleo-hosted merchant: read-only, from the store config) or 'none'
    (an external merchant with no feed committed yet)."""
    if hosted_catalog is not None:
        # supply's GET /merchants/{slug}/catalog: listings, each with its
        # published variants (variant_id, title, size, count, list_price, gtin).
        rows = []
        for listing in hosted_catalog.get('listings') or []:
            for v in listing.get('variants') or []:
                vid = str(v.get('variant_id') or '')
                rows.append({'gtin': v.get('gtin'), 'variant_id': v.get('variant_id'),
                             # 2K-3: the merchant's own code, as a feed row carries it
                             'sku': v.get('sku') or (vid[len('sku:'):] if vid.startswith('sku:') else None),
                             'listing_id': listing.get('listing_id'),
                             'product_name': listing.get('title'), 'brand_name': listing.get('brand'),
                             'variant_label': v.get('title'), 'size': v.get('size'), 'pack_count': v.get('count'),
                             'multipack': None, 'price': v.get('list_price'), 'currency': v.get('currency'),
                             'published_at': _iso(listing.get('published_at')), 'product_url': listing.get('product_url'),
                             # 2L-2: on a retired variant only
                             **({'retired': retired_view(v.get('status'), v.get('successor'), listing.get('brand'))}
                                if v.get('status') == 'retired' else {})})
        return {'merchant': merchant, 'source': 'hosted', 'read_only': True,
                'note': 'Hosted on Parleo: this catalog comes from the store config. Edit it there. No feed upload applies.',
                'version': None, 'rows': rows, 'versions': []}
    if feed is None:
        return {'merchant': merchant, 'source': 'none', 'read_only': False,
                'note': 'No feed committed yet. Download the template, fill it in and upload it here.',
                'version': None, 'rows': [], 'versions': history or []}
    rows = [dict(r) for r in feed.get('rows') or []]
    # 2L-2: supply's rows as given, plus `retired` on a retired one
    retired = feed_retired(rows)
    for r in rows:
        view = retired.get(str(r.get('variant_key') or r.get('sku') or r.get('gtin14') or ''))
        if view:
            r['retired'] = view
    return {'merchant': merchant, 'source': 'feed', 'read_only': False, 'note': None,
            'version': feed.get('version'), 'rows': rows, 'versions': history or []}


# ─── TrueSync matrix (2C) ──────────────────────────────────────────────────
#
# The Command Center matrix, assembled server-side from what the soa web
# app's MerchantCommandCenter.jsx reads in the browser (supply has no single
# endpoint for it): channels, publications, the published catalog, one
# verifications read per channel, and the merchant's provenance mix. The
# cell rules are verificationModel.js's (docs/verification-semantics.md):
# publish state, drift, acceptance and last verified are four separate
# things, and a record older than the cell's latest publish counts for
# nothing.

#: publication.status -> the console's CellState.
TS_CELL = {'published': 'published', 'compiled': 'compiled', 'validated': 'compiled',
           'compiled_not_published': 'compiled', 'withdrawn': 'compiled', 'failed': 'blocked'}
#: ExpressivenessFlag.severity -> ValidatorLine.verdict.
TS_VALIDATOR = {'dropped': 'dropped', 'approximated': 'approx', 'checkout_scope': 'info', 'info': 'info'}
#: Manufacturer Center acceptance (supply truesync/channels/manufacturer_center/diagnostics.py).
MC_STATES = ('approved', 'pending', 'disapproved', 'not_found', 'unavailable')
TS_DIVERGENCES = [
    "Assembled by soa from supply's channels, publications, catalog, per-channel verifications and "
    "provenance; supply has no single Command Center payload.",
    "Products are the published catalog's listings: a listing never published is not a row (the web "
    "app's schema-org spine has the same limit).",
    "TsCell.s: published, compiled (compiled, validated, withdrawn), blocked (failed), not_published "
    "(no publication), na (a channel this tenant is not connected to, with connected: false beside).",
    "TsCell.d comes from the newest fetch_probe at or after the publish only: drift when it has "
    "findings, none when it has none, unverified otherwise (and on every acceptance channel).",
    "acceptance (merchant_center from gmc_diagnostics, manufacturer_center from mc_acceptance) and "
    "origin ('parleo' | 'gmc_sync', manufacturer_center only) ride beside the typed cell.",
    "provenance per product is the merchant's mix when it is all one source; mixed, a listing with a "
    "publication is 'published' and the rest 'scrape' (provenance_basis says which).",
    "ValidatorLine.verdict: validation errors are 'conflict'; expressiveness dropped -> dropped, "
    "approximated -> approx, checkout_scope and info -> info; a valid record with no flags is one 'ok'.",
]


def _ts(value) -> str:
    return _iso(value) or ''


def _newest(rows, key='created_at'):
    rows = [r for r in rows if r]
    return max(rows, key=lambda r: (_ts(r.get(key)), r.get('id') or 0)) if rows else None


def _validator(publication: Optional[dict]) -> List[dict]:
    if not publication:
        return []
    lines = []
    validation = publication.get('validation') or {}
    for err in validation.get('errors') or []:
        lines.append({'field': 'record', 'verdict': 'conflict', 'note': str(err)})
    for flag in publication.get('expressiveness') or []:
        lines.append({'field': flag.get('field') or '', 'verdict': TS_VALIDATOR.get(flag.get('severity'), 'info'),
                      'note': flag.get('note') or ''})
    if not lines and validation.get('ok', True):
        lines.append({'field': 'record', 'verdict': 'ok', 'note': f"valid against {publication.get('spec_version') or 'the spec'}"})
    return lines


def _acceptance(channel: str, records: List[dict]) -> tuple:
    """(acceptance, origin) from the newest acceptance record."""
    if channel == 'manufacturer_center':
        rec = _newest([r for r in records if r.get('method') == 'mc_acceptance'])
        if rec is None:
            return None, None
        drift = rec.get('drift') or {}
        state = drift.get('acceptance') if drift.get('acceptance') in MC_STATES else 'unavailable'
        return state, drift.get('origin')
    if channel == 'merchant_center':
        rec = _newest([r for r in records if r.get('method') == 'gmc_diagnostics'])
        if rec is None:
            return None, None
        drift = rec.get('drift') or {}
        if drift.get('httpStatus') == 404:
            return 'not_found', None
        if drift.get('approved') is True:
            return 'approved', None
        return ('disapproved' if drift.get('issues') else 'pending'), None
    return None, None


def build_truesync(merchant: str, *, channels: List[dict], publications: List[dict], catalog: dict,
                   verifications: Dict[str, dict], provenance: Optional[dict]) -> dict:
    channel_list = [c for c in channels or [] if c.get('is_active', True)]
    listings = catalog.get('listings') or []
    listing_ids = {l.get('listing_id') for l in listings}
    # 2R-2a: a brand's held rows are feed records (record_ref "feed:<slug>:…", no listing); the
    # catalog lists each record as a listing whose product_id is that record_ref
    by_record = {l.get('product_id'): l.get('listing_id') for l in listings
                 if str(l.get('product_id') or '').startswith('feed:')}
    pubs: Dict[tuple, dict] = {}
    for pub in publications or []:
        lid = pub.get('listing_id') if pub.get('listing_id') in listing_ids else by_record.get(pub.get('record_ref'))
        if lid is None:
            continue
        key = (lid, pub.get('channel_slug'))
        best = pubs.get(key)
        if best is None or (_ts(pub.get('compiled_at')), pub.get('id') or 0) > (_ts(best.get('compiled_at')), best.get('id') or 0):
            pubs[key] = pub
    records: Dict[tuple, List[dict]] = {}
    for channel, envelope in (verifications or {}).items():
        for entry in (envelope or {}).get('listings') or []:
            for v in entry.get('verifications') or []:
                records.setdefault((entry.get('listing_id'), v.get('channel_slug') or channel), []).append(v)

    mix = (provenance or {}).get('listings') or {}
    scraped, published_n = mix.get('scrape', 0) or 0, mix.get('published', 0) or 0

    products, last_verified = [], ''
    for listing in listings:
        lid = listing.get('listing_id')
        variants = listing.get('variants') or []
        gtins = [v.get('gtin') for v in variants if v.get('gtin')]
        cells, validator, payload = {}, {}, {}
        any_pub = False
        for ch in channel_list:
            slug = ch['slug']
            pub = pubs.get((lid, slug))
            any_pub = any_pub or pub is not None
            published_at = _ts((pub or {}).get('published_at') or (pub or {}).get('compiled_at'))
            fresh = [r for r in records.get((lid, slug), []) if _ts(r.get('created_at')) >= published_at]
            probe = _newest([r for r in fresh if r.get('method') in ('fetch_probe', 'live_fetch')])
            findings = ((probe or {}).get('drift') or {}).get('findings')
            probe_ok = probe is not None and ((probe.get('drift') or {}).get('outcome') in (None, 'ok', 'drift')) \
                and isinstance(findings, list)
            drift = ('drift' if findings else 'none') if probe_ok else 'unverified'
            acceptance, origin = _acceptance(slug, fresh if pub else records.get((lid, slug), []))
            newest = _newest(fresh)
            if newest and _ts(newest.get('created_at')) > last_verified:
                last_verified = _ts(newest.get('created_at'))
            connected = ch.get('connected')
            if connected is False:
                state, note = 'na', 'not connected'
            elif pub is None:
                state, note = 'not_published', None
            else:
                state = TS_CELL.get(pub.get('status'), 'compiled')
                note = 'withdrawn' if pub.get('status') == 'withdrawn' else pub.get('error') or \
                    ('. '.join((pub.get('validation') or {}).get('errors') or []) or None)   # 2K-3: no semicolons
            cell = compact({'s': state, 'd': drift, 'n': len(findings) if probe_ok and findings else None,
                            'at': _ts(newest.get('created_at')) if newest else None, 'note': note,
                            # beside the typed fields
                            'publication_id': (pub or {}).get('id'), 'status': (pub or {}).get('status'),
                            'published_at': (pub or {}).get('published_at'), 'acceptance': acceptance,
                            'origin': origin, 'connected': connected,
                            'external_ref': (pub or {}).get('external_ref')},
                           ('n', 'at', 'note'))
            cells[slug] = cell
            validator[slug] = _validator(pub)
            if pub is not None:
                payload[slug] = json.dumps(pub.get('payload'), indent=2, ensure_ascii=False)
        if scraped and not published_n:
            provenance_of, basis = 'scrape', 'merchant'
        elif published_n and not scraped:
            provenance_of, basis = 'published', 'merchant'
        else:
            provenance_of, basis = ('published' if any_pub else 'scrape'), ('publication' if (scraped or published_n) else 'unknown')
        products.append({
            'sku': str(listing.get('product_id') or lid), 'name': listing.get('title') or f"Listing {lid}",
            'sub': ' · '.join(x for x in (listing.get('brand'), f"{len(variants)} variants") if x),
            'variants': f"{len(variants)} variants", **({'gtin': gtins[0]} if gtins else {}),
            'cells': cells, 'validator': validator, 'payload': payload,
            # beside the typed fields
            'listing_id': lid, 'product_url': listing.get('product_url'), 'published_at': _iso(listing.get('published_at')),
            'variant_ids': [v.get('variant_id') for v in variants if v.get('variant_id')], 'gtins': gtins,
            'provenance': provenance_of, 'provenance_basis': basis,
        })
    return {
        'merchant': merchant,
        'channels': [compact({'id': c['slug'], 'name': c.get('name') or c['slug'], 'short': c.get('name') or c['slug'],
                              'spec': c.get('spec_version') or '',
                              # beside the typed fields
                              'verification_surface': c.get('verification_surface'),
                              'extension_status': c.get('extension_status'), 'connected': c.get('connected'),
                              'depth_label': c.get('depth_label')}, ()) for c in channel_list],
        'products': products,
        'lastVerified': last_verified or None,
        'provenance': {'merchant_source': (provenance or {}).get('merchant_source'), 'listings': mix},
        'divergences': TS_DIVERGENCES,
    }


# ─── Accessibility ─────────────────────────────────────────────────────────

def access_measured(request: dict) -> bool:
    """An identity whose probe was never configured is not measured, which
    is not a problem: it never counts as one."""
    if request.get('measured') is not None:
        return bool(request['measured'])
    return not str(request.get('result') or '').startswith('not measured')


def access_problems(requests: Iterable[dict]) -> List[dict]:
    """The measured requests that did not get through."""
    return [r for r in requests or [] if access_measured(r) and not r.get('ok')]


def group_identities(requests: Iterable[dict]) -> List[dict]:
    """2K-4 (B4): access requests by display name, each named once.
    Two tokens can share one (Googlebot and its Google-Extended sibling
    both read "Googlebot"), and "Googlebot, Googlebot, bingbot" counted the
    name twice. [{identity, tokens, label}] in first-seen order; label is
    "Googlebot (2 tokens)" for a name with more than one."""
    groups: Dict[str, int] = {}
    for r in requests or []:
        name = r.get('identity') or '?'
        groups[name] = groups.get(name, 0) + 1
    return [{'identity': name, 'tokens': n, 'label': name if n == 1 else f"{name} ({n} tokens)"}
            for name, n in groups.items()]


def accessibility_from_supply(payload: Optional[dict]) -> dict:
    """
    supply's GET /merchants/{slug}/access, already Accessibility-shaped,
    with `claude` added to the agent vocabulary as vendor 'claude' (supply
    sends 'other' because the console's AgentId has no claude; 2C-0 adds it).
    """
    payload = payload or {}
    access = dict(payload.get('accessibility') or {})
    requests = []
    for row in access.get('requests') or []:
        row = dict(row)
        if row.get('agent') == 'claude':
            row['vendor'] = 'claude'
        requests.append(row)
    if access:
        access['requests'] = requests
        # 2K-4 (B4): the identities that did not get through, each display name once
        access['problem_identities'] = group_identities(access_problems(requests))
    divergences = [d for d in payload.get('divergences') or [] if "no 'claude'" not in d]
    divergences.append("AccessRow.vendor can be 'claude' (vendor 'claude', agent 'claude'); "
                       "the console adds it to AgentId in 2C-0.")
    return {**access, 'merchant': payload.get('merchant'), 'access_run': payload.get('access_run'),
            'divergences': divergences}


# ─── Studies ───────────────────────────────────────────────────────────────

#: 2I-8: `all` (every surface's runs together) ranks above every surface.
_SURFACE_RANK = {surfaces.ALL: 4, 'consumer_ui': 3, 'grounded_api': 2, 'api': 1}


def build_study_rows(queries: List[dict], runs: List[dict], outcomes: Dict[int, dict],
                     picks: Dict[int, str], primary_named: Dict[int, bool]) -> List[dict]:
    """
    StudyRow[] per question, StudyCell per agent.

    Two surfaces can belong to one agent (chatgpt and chatgpt_api are both
    ChatGPT). `cells` is keyed by AgentId as the console expects, holding
    the higher-fidelity surface (consumer_ui > grounded_api > api);
    `cells_by_platform` beside it keeps every surface, so nothing is lost.
    A cell's `s` is the most common outcome across the question's runs on
    that surface, ties going to the worse one; its text, pick and prices
    come from run 1.
    """
    by_q_platform: Dict[tuple, List[dict]] = {}
    for run in runs:
        by_q_platform.setdefault((run['query_id'], run['platform']), []).append(run)

    rows = []
    for query in queries:
        by_platform = {}
        for (qid, platform), qruns in by_q_platform.items():
            if qid != query['id']:
                continue
            qruns = sorted(qruns, key=lambda r: r['run_number'])
            first = qruns[0]
            outcome = worst((outcomes.get(r['id']) or {}).get('outcome') for r in qruns)
            claims = _json((outcomes.get(first['id']) or {}).get('claim_results')) or []
            cell = compact({
                's': CELL_TONE.get(outcome, 'neu') if outcome else
                     ('neu' if first.get('answer_status') else 'na'),
                'pick': picks.get(first['id']),
                'named': primary_named.get(first['id']),
                'at': _iso(first.get('run_at')),
                'text': (first.get('raw_response') or '')[:280] or None,
                'prices': [money(c.get('stated')) for c in claims if c.get('stated')] or None,
                'note': (outcomes.get(first['id']) or {}).get('outcome_reason'),
                # beside the typed fields
                'platform': platform,
                'surface': first.get('surface') or surfaces.surface_of(platform),
                'outcome': outcome,
                'runs': len(qruns),
            }, ('named', 'at', 'text', 'prices', 'note'))
            by_platform[platform] = cell
        cells = {}
        for platform, cell in sorted(by_platform.items(),
                                     key=lambda kv: _SURFACE_RANK.get(kv[1]['surface'], 0)):
            cells[surfaces.agent_of(platform) or platform] = cell
        rows.append({'id': query['query_code'], 'q': query['query_text'],
                     'type': TIER_LABELS.get(query.get('tier')) or query.get('stage') or '',
                     'cells': cells, 'cells_by_platform': by_platform})
    return rows


# ─── Operator section (studio.ts) ──────────────────────────────────────────

STAGE_TO_STUDIO = {'Awareness': 'Awareness', 'Research': 'Research', 'Comparison': 'Comparison',
                   'Ready to Buy': 'Ready to buy'}
ENTITY_TYPE_TO_STUDIO = {'retailer': 'retailer', 'brand': 'brand', 'cpg': 'cpg',
                         'service': 'group', 'aggregate': 'group'}
RUN_STATUS = {'planned': 'queued', 'running': 'running', 'complete': 'complete', 'failed': 'failed'}


def _domain(url) -> Optional[str]:
    if not url:
        return None
    host = str(url).split('//', 1)[-1].split('/', 1)[0].lower()
    return host[4:] if host.startswith('www.') else host


def build_entity(row: dict) -> dict:
    return compact({
        'id': row.get('slug') or str(row['id']), 'name': row['name'],
        'type': ENTITY_TYPE_TO_STUDIO.get(row.get('entity_type'), row.get('entity_type')),
        'domain': _domain(row.get('website_url')), 'category': row.get('category'),
        'aliases': _json(row.get('aliases')) or [],
        # beside the typed fields
        'soa_id': row['id'], 'soa_entity_type': row.get('entity_type'),
    }, ('domain', 'category'))


def build_prompt(row: dict, brand: Optional[str], terms: Iterable[str] = ()) -> dict:
    """terms: study_brand_terms (2I-7); `brand` alone when none are read."""
    terms = list(terms) or unprompted.brand_terms(brand)
    return compact({
        'id': row['query_code'], 'text': row['query_text'],
        'stage': STAGE_TO_STUDIO.get(row.get('stage'), row.get('stage')),
        'branded': bool(unprompted.names_any(row['query_text'], terms)),
        'persona': row.get('persona'),
        # soa's provenance vocabulary, which is not the console's source
        'source': {'catalog': 'csv', 'ai_from_catalog': 'ai', 'ai': 'ai'}.get(row.get('provenance'), 'ai'),
        'provenance': row.get('provenance'), 'tier': row.get('tier'),
    }, ('persona',))


#: 2C-2c: the tiers whose questions name the brand (a stage question and
#: category control do not). 2I-7: a category-control or stage question
#: whose text names the brand counts as branded too (soa_shared/unprompted.py).
BRANDED_TIERS = ('brand_direct', 'catalog_accuracy', 'value_incentives')


def study_status(cycles: List[dict]) -> str:
    """2C-2c: Draft with no cycle, Active while a cycle is planned or
    running, Done otherwise. Generation's own state rides beside."""
    if not cycles:
        return 'draft'
    if any(c.get('status') in ('planned', 'running') for c in cycles):
        return 'active'
    return 'done'


def prompt_counts(prompts: List[dict], terms: Iterable[str] = ()) -> dict:
    """Branded: the questions in a tier that names the brand, and (2I-7) any
    other whose text names it; unbranded: the rest, the unprompted ones the
    score counts. The study's question count, the one the Overview uses too.
    2K-1: a comparison question names the brand, so it is branded; a study
    that has any also says how many (`comparison`), the brand-choice
    questions beside the unbranded ones."""
    branded = sum(1 for p in prompts if p.get('tier') in BRANDED_TIERS
                  or not unprompted.is_unprompted({'tier': p.get('tier'), 'query_text': p.get('text')}, terms))
    out = {'branded': branded, 'unbranded': len(prompts) - branded, 'prompts': len(prompts)}
    comparison = sum(1 for p in prompts if p.get('tier') == COMPARISON)
    if comparison:
        out['comparison'] = comparison
    return out


def build_study(job: dict, prompts: List[dict], cycles: List[dict], entities: List[dict]) -> dict:
    latest = cycles[0] if cycles else {}
    platforms = _json(latest.get('platforms')) or []
    primary = next((e for e in entities if e.get('role') == 'primary'), None)
    tier_config = _json(job.get('tier_config')) or {}
    merchant = (tier_config or {}).get('merchant') or {}
    return compact({
        'id': job['study_type'], 'name': job['study_name'],
        'entity': (primary or {}).get('slug') or job.get('syndicated_merchant') or '',
        'pattern': job.get('study_pattern') or latest.get('study_pattern'),
        'category': (_json(job.get('allowed_categories')) or [''])[0] or '',
        'rivals': [e.get('slug') for e in entities if e.get('role') != 'primary'],
        'retailers': merchant.get('retailer_list') or (_json(job.get('retailer_names')) or []),
        'agents': sorted({surfaces.agent_of(p) or p for p in platforms}),
        'runsPerPrompt': latest.get('runs_per_query'),
        'cadence': 'once',
        'prompts': prompts,
        'shelfReads': [], 'crawl': False,
        'status': study_status(cycles),
        'created': _iso(job.get('created_at')) or '', 'lastRun': _iso(latest.get('start_date')),
        'owner': job.get('created_by') or '',
        # beside the typed fields
        'platforms': platforms, 'generation_status': job.get('status'),
        # 2K-1: the merchant's local time, for the study's display date ("the Oct 19 study");
        # `created` stays UTC
        'created_at_local': local_time.local_iso(job.get('created_at'), study_timezone(tier_config)),
        # 2L-1: archived studies are listed only with ?archived=1
        'archived': job.get('archived_at') is not None, 'archived_at': _iso(job.get('archived_at')),
        'timezone': study_timezone(tier_config),
        # 2K-3: the last run's day in the merchant's zone, beside lastRun (UTC)
        'last_run_local': cycle_dates(latest, study_timezone(tier_config))['start_date_local'] if latest else None,
    }, ('lastRun', 'last_run_local'))


#: 2L-1 (B3): a full loop is running until its request is scored, failed or
#: reads-only done (soa_full_loop_requests.status), or while a cycle runs.
LOOP_RUNNING = ('reference_pending', 'reference_done', 'cycle_planned', 'scoring')


def running_loops(conn, study_type: str) -> Optional[str]:
    """What runs for the study, in words, or None: a full-loop request in
    flight, else a running cycle."""
    request = conn.execute(text(
        "SELECT id, status FROM soa_full_loop_requests WHERE study_type = :st AND status IN ("
        + ", ".join(f"'{s}'" for s in LOOP_RUNNING) + ") ORDER BY id DESC"), {'st': study_type}).mappings().first()
    if request:
        return f"request {request['id']}, {request['status'].replace('_', ' ')}"
    cycle = conn.execute(text("SELECT cycle_code FROM soa_cycles WHERE study_type = :st AND status = 'running' "
                              "ORDER BY id DESC"), {'st': study_type}).scalar()
    return f"cycle {cycle}" if cycle else None


def run_identity(cycle: dict, ran_platforms: List[str]) -> dict:
    """2I: the cycle's resolved surface ids, runs per question and study.
    The ids are what ran (soa_runs.platform), in registry order; before any
    run, what the cycle stored resolved (soa_cycles.surfaces, 2D), else its
    platforms resolved today. A pre-2D cycle stored an alias and ran it
    under another id (229: "gemini" ran as gemini_grounded), so what ran is
    the only reliable answer once there are runs."""
    order = {s.id: i for i, s in enumerate(surfaces.SURFACES)}
    ids = sorted({p for p in ran_platforms if p}, key=lambda p: (order.get(p, len(order)), p))
    if not ids:
        stored = _json(cycle.get('surfaces'))
        if isinstance(stored, dict) and stored:
            ids = list(stored)
        else:
            try:
                ids = surfaces.resolve_platforms(_json(cycle.get('platforms')) or [])
            except surfaces.UnknownSurface:
                ids = list(_json(cycle.get('platforms')) or [])
    return {'surface_ids': ids, 'runs_per_question': cycle.get('runs_per_query'), 'study_id': cycle.get('study_type')}


def study_timezone(tier_config) -> str:
    """2K-1: the study's merchant's IANA zone (tier_config.merchant.timezone),
    else SOA_DEFAULT_TIMEZONE, else America/Los_Angeles (soa_shared/local_time.py)."""
    return local_time.merchant_timezone(_json(tier_config))


def study_timezones(conn, study_types: Iterable[str]) -> Dict[str, str]:
    """{study_type: its zone}, from each study's newest generation job."""
    out: Dict[str, str] = {}
    for st in sorted({s for s in study_types if s}):
        config = conn.execute(text(
            "SELECT tier_config FROM soa_query_generation_jobs WHERE study_type = :st ORDER BY id DESC LIMIT 1"),
            {'st': st}).scalar()
        out[st] = study_timezone(config)
    return out


def study_dates(job: Optional[dict]) -> dict:
    """2K-4 (B2): the study's own date, for "The Oct 20 study": its
    generation job's created_at (UTC) and the same moment in the merchant's
    zone (`created_at_local`), with the zone. A study generated 23:10 PDT on
    Oct 20 is the Oct 20 study, whenever its cycle ran."""
    if not job:
        return {'created_at': None, 'created_at_local': None, 'timezone': None}
    zone = study_timezone(job.get('tier_config'))
    return {'created_at': _iso(job.get('created_at')), 'created_at_local': local_time.local_iso(job.get('created_at'), zone),
            'timezone': zone}


def load_study_block(conn, study_type: Optional[str]) -> Optional[dict]:
    """2K-4 (B2): {id, name, created_at, created_at_local, timezone} of a
    study, from its newest generation job; None without one."""
    if not study_type:
        return None
    job = conn.execute(text("SELECT study_type, study_name, created_at, tier_config FROM soa_query_generation_jobs "
                            "WHERE study_type = :st ORDER BY id DESC LIMIT 1"), {'st': study_type}).mappings().first()
    if job is None:
        return None
    return {'id': job['study_type'], 'name': job['study_name'] or job['study_type'], **study_dates(dict(job))}


def study_identity(conn, cycle: Optional[dict]) -> dict:
    """2K-4 (B1): {'study', 'questions': {query_code: tier}} of a cycle's
    study, what soa_shared/cycle_compare compares first."""
    if not cycle:
        return {'study': None, 'questions': {}}
    questions = {r['query_code']: r['tier'] for r in conn.execute(text(
        "SELECT query_code, tier FROM soa_queries WHERE study_type = :st"), {'st': cycle.get('study_type')}).mappings()}
    return {'study': cycle.get('study_type'), 'questions': questions}


def cycle_dates(cycle: dict, tz: Optional[str] = None) -> dict:
    """2K-3 (B5): beside a cycle's UTC `start_date`, the day it started in
    the merchant's zone (`start_date_local`: its created_at there, as a
    date), the moment (`created_at_local`) and the zone. Nothing stored
    changes. A cycle created 04:26 UTC on Oct 20 in Los Angeles started on
    Oct 19. None when the cycle carries no created_at."""
    zone = tz or local_time.default_timezone()
    day = local_time.local_date(cycle.get('created_at'), zone)
    return {'start_date_local': day.isoformat() if day else None,
            'created_at_local': local_time.local_iso(cycle.get('created_at'), zone), 'timezone': zone}


#: 2T-7 (2): a cycle in copy, by its start day in the merchant's zone
CYCLE_LABEL = {'name': 'the {day} cycle', 'since': 'Since {day}', 'vs': 'vs {day}'}


def cycle_label(cycle: Optional[dict], tz: Optional[str] = None) -> Optional[dict]:
    """2T-7 (2): the one label every "since / vs / against" string reads for a cycle: {code, day, name, since,
    vs}. `day` is the cycle's start day in the merchant's zone (cycle_dates), else its UTC start date: "Oct 23",
    "the Oct 23 cycle", "Since Oct 23", "vs Oct 23". With no date at all, the code stands in (name is the code).
    The code stays the cycle's identifier wherever one is served."""
    if not cycle:
        return None
    code = cycle.get('cycle_code')
    iso = cycle_dates(cycle, tz).get('start_date_local') or _iso(cycle.get('start_date'))
    try:
        from datetime import date as _date
        d = _date.fromisoformat((iso or '')[:10])
        day = f"{d.strftime('%b')} {d.day}"
    except ValueError:
        return {'code': code, 'day': None, 'name': code, 'since': f'Since {code}', 'vs': f'vs {code}'}
    return {'code': code, 'day': day, **{k: v.format(day=day) for k, v in CYCLE_LABEL.items()}}


def cycle_label_of(conn, cycle: Optional[dict]) -> Optional[dict]:
    """cycle_label in the zone of the cycle's study (study_timezones)."""
    if not cycle:
        return None
    zone = study_timezones(conn, [cycle.get('study_type')]).get(cycle.get('study_type')) if cycle.get('study_type') \
        else None
    return cycle_label(cycle, zone)


def cycle_name(conn, cycle: Optional[dict]) -> Optional[str]:
    """"the Oct 23 cycle" (cycle_label's name), None for no cycle."""
    return (cycle_label_of(conn, cycle) or {}).get('name')


def build_run(cycle: dict, collected: int, usable: int, tz: Optional[str] = None) -> dict:
    """tz (2K-1): the study's merchant's zone, for `created_at_local`."""
    platforms = _json(cycle.get('platforms')) or []
    started, finished = cycle.get('created_at') or cycle.get('start_date'), cycle.get('end_date')
    return compact({
        'id': cycle['cycle_code'], 'study': cycle['study_type'],
        'started': _iso(started), 'finished': _iso(finished),
        'status': RUN_STATUS.get(cycle['status'], cycle['status']),
        'planned': cycle.get('total_runs_planned') or 0, 'collected': collected, 'usable': usable,
        'agents': sorted({surfaces.agent_of(p) or p for p in platforms}),
        'elapsed': '', 'note': cycle.get('notes'),
        # beside the typed fields
        'platforms': platforms,
        'surfaces': sorted({surfaces.surface_of(p) for p in platforms if surfaces.surface_of(p)}),
        'full_loop_run_id': cycle.get('full_loop_run_id'),
        # 2K-1: beside the UTC stamp, in the merchant's local time; 2K-3: and the local start day
        **cycle_dates(cycle, tz),
    }, ('finished', 'note'))


# ─── Visibility (2C-1) ─────────────────────────────────────────────────────
#
# Who the answers name and who they name first, every agent together (2I-8:
# `all`, the default) and per surface, from the coding
# already stored per answer. Two codings exist and both are read as stored:
#
#   Layer 1  soa_coded_mentions: one row per run x the cycle's entities
#            (ours as `primary`, the comparison set), `mentioned` and
#            `position`, the ordinal of the entity's first mention among the
#            entities named (parser/prompts.py POSITION RULES).
#   Layer 2  the extraction's other_brands_named: every other brand the
#            answer names, with presented_as. It has NO order field.
#
# Nothing is re-read from the answer text and no model is called.

#: The stage questions a study opens with carry no tier: the unprompted ones.
#: 2I-7: so do category-control questions (the same questions, tagged), less
#: any that names the brand (soa_shared/unprompted.py). A row's `tier` stays
#: its tier; its `unprompted` says whether it counts as unprompted.
VIS_UNPROMPTED = 'unprompted'
#: 2K-1: the comparison tier (it names the brand and a rival) and the set the
#: first-pick reads count over when a cycle asked one: unprompted plus it
#: (soa_shared/unprompted.is_brand_choice). A row's `brand_choice` says
#: whether it is in that set.
COMPARISON = 'comparison'
VIS_BRAND_CHOICE = 'brand_choice'
VIS_BRAND_CHOICE_LABEL = 'Category and comparison'
VIS_TIER_LABELS = {VIS_UNPROMPTED: 'Unprompted', **TIER_LABELS}
VIS_TIER_ORDER = (VIS_UNPROMPTED, 'category_control', COMPARISON, 'brand_direct', 'catalog_accuracy', 'value_incentives')
#: An other_brands_named entry named only as where the information came from
#: (a cited site, a publisher) is not a brand put to the shopper.
VIS_SOURCE_PRESENTED = ('source',)
VIS_SOURCE_RELATIONS = ('citation_only',)
#: 2G: how many brands outside the comparison set the ranking names per surface.
VIS_UNTRACKED_KEEP = 10
VIS_FIRST_PICK_RULE = (
    "First pick is the first brand the answer names, as coded when it was scored. The coding ranks every "
    "brand named, so when the comparison set's first brand sits second or later, another brand came first, "
    "and the brands the answer named outside the set decide which, by where each first appears. When no "
    "coding names that brand (a brand-choice answer's coding carries no list of other brands), nobody gets the pick.")
VISIBILITY_DIVERGENCES = [
    "2I-8: Visibility counts every agent together, as the demo does. RankRow.named and RankRow.first "
    "are the counts on `ranking.surface`, which is `all` (every answered run, whatever its surface), "
    "and `ranking.denom` is its answered runs; each surface is beside it under `surfaces`, `all` first, "
    "each with its per-agent split, for the console's surface filter.",
    "byQuestion is one row per run, not one per question with a first pick per agent "
    "(Tenant.visibility): an agent can have two surfaces, and a question has several runs.",
    "Brands outside the comparison set come from other_brands_named and are rolled up by name: a "
    "name that starts with a comparison-set brand (or alias) is that brand ('Huggies Snug & Dry' is "
    "Huggies), and a name that starts with another named brand is that brand. Sources "
    "(presented_as 'source', relation 'citation_only') are left out and counted in `sources_left_out`.",
    "RankRow.series is not sent: a sparkline needs two or more cycles, which the console reads itself.",
    "An answer whose first brand neither coding names has `first: null` and `first_basis: 'uncoded'`, "
    "counted per surface and agent in `ranking.first_uncoded` / `agent_first_uncoded`.",
]


def _brand_key(name) -> str:
    from soa_shared.expected_answers import normalize_brand_text
    return normalize_brand_text(name)


def _starts_with(tokens: tuple, prefix: tuple) -> bool:
    return bool(prefix) and tokens[:len(prefix)] == prefix


#: 2N-1: the words around a company's name that are not its name ("The Honest Company" is "Honest").
_COMPANY_WORDS = re.compile(r"^(?:the)\s+|\s+(?:company|co\.?|inc\.?|corporation|corp\.?|brands?)$", re.I)
#: The generic words a product name ends with, not its line ("Baby Dry Diapers" is "Baby Dry").
_LINE_TAIL = re.compile(r"(?:\s+(?:diapers?|nappies|pants|wipes|training pants|underwear|overnights?|"
                        r"size\s*\S+|\d+\s*(?:ct|count)))+$", re.I)


def entity_aliases(name: Optional[str]) -> List[str]:
    """2N-1: a comparison-set brand's name as answers write it without its
    company words: "The Honest Company" -> ["Honest"]."""
    short = _COMPANY_WORDS.sub('', _COMPANY_WORDS.sub('', (name or '').strip())).strip()
    return [short] if short and short.lower() != (name or '').strip().lower() else []


def line_aliases(product_names: Iterable[str], brand: Optional[str]) -> List[str]:
    """2N-1: the merchant's line names from its catalog's product names, the
    brand and the generic tail taken off: "Pampers Swaddlers Diapers" ->
    "Swaddlers", "Pampers Baby Dry" -> "Baby Dry". A sub-line is the brand's,
    never a brand of its own."""
    out = []
    for name in product_names or []:
        line = _LINE_TAIL.sub('', retired_lines.line_name(name, brand)).strip(' ,-')
        if line and _brand_key(line) and _brand_key(line) != _brand_key(brand) and line not in out:
            out.append(line)
    return out


class _Brands:
    """The cycle's brand vocabulary: the comparison set (with aliases) first,
    then every other brand Layer 2 coded, rolled up by name. 2N-1: each
    brand also by its name without company words ("Honest"), ours by its
    catalog's line names (`lines`: "Swaddlers", "Baby Dry", "Cruisers")."""

    def __init__(self, entities: List[dict], layer2_names: Iterable[str], lines: Iterable[str] = ()):
        self.known = []   # (tokens, display, you), longest first
        self.aliases: Dict[str, List[str]] = {}
        for e in entities:
            names = [e['name'], *(_json(e.get('aliases')) or []), *entity_aliases(e['name']),
                     *(list(lines) if e.get('role') == 'primary' else [])]
            self.aliases[e['name']] = names
            for n in names:
                toks = tuple(_brand_key(n).split())
                if toks:
                    self.known.append((toks, e['name'], e.get('role') == 'primary'))
        self.known.sort(key=lambda k: -len(k[0]))
        spellings: Dict[str, Counter] = {}
        for n in layer2_names:
            key = _brand_key(n)
            if key and self._entity(tuple(key.split())) is None:
                spellings.setdefault(key, Counter())[n] += 1
        # The shortest other name a name starts with is its root.
        keys = sorted(spellings, key=lambda k: (len(k.split()), k))
        self.root: Dict[str, str] = {}
        for key in keys:
            toks = tuple(key.split())
            parent = next((r for r in keys if r != key and len(r.split()) < len(toks)
                           and _starts_with(toks, tuple(r.split()))), None)
            self.root[key] = self.root.get(parent, parent) if parent else key
        self.display = {key: spellings[key].most_common(1)[0][0] for key in keys}

    def _entity(self, toks: tuple):
        return next(((d, you) for k, d, you in self.known if _starts_with(toks, k)), None)

    def resolve(self, name: str) -> Optional[tuple]:
        """(display name, you) for a name as written; None when it is empty."""
        key = _brand_key(name)
        if not key:
            return None
        hit = self._entity(tuple(key.split()))
        if hit:
            return hit
        root = self.root.get(key, key)
        return self.display.get(root, name), False


def _span_hit(spans: List[dict], names: Iterable[str]) -> Optional[tuple]:
    """(span index, offset) of the earliest stored span naming any of `names`."""
    best = None
    wanted = [f" {_brand_key(n)} " for n in names if _brand_key(n)]
    for i, span in enumerate(spans or []):
        hay = f" {_brand_key(span.get('text'))} "
        for w in wanted:
            at = hay.find(w)
            if at >= 0 and (best is None or (i, at) < best):
                best = (i, at)
    return best


def _visibility_run(layer1: List[dict], extraction: dict, brands: _Brands) -> tuple:
    """(named [{name, you}], first {name, you} | None, basis, sources left out) for one run."""
    named: Dict[str, dict] = {}

    def add(name, you):
        named.setdefault(name, {'name': name, 'you': bool(you)})

    coded = sorted(layer1, key=lambda m: (m.get('position') is None, m.get('position') or 0))
    for m in coded:
        add(m['name'], m.get('role') == 'primary')
    from soa_shared import retailers as af
    others, sources = [], 0
    for entry in (extraction or {}).get('other_brands_named') or []:
        if not isinstance(entry, dict) or not entry.get('name'):
            continue
        if entry.get('presented_as') in VIS_SOURCE_PRESENTED or entry.get('relation') in VIS_SOURCE_RELATIONS:
            sources += 1
            continue
        if af.is_store_name(entry['name']):
            continue   # 2N-1: a retailer is no brand (it is in the routing table)
        hit = brands.resolve(entry['name'])
        if hit:
            others.append((entry['name'], *hit))
            add(hit[0], hit[1])

    positioned = [m for m in coded if m.get('position') is not None]
    if positioned and positioned[0]['position'] == 1:
        top = positioned[0]
        return list(named.values()), {'name': top['name'], 'you': top.get('role') == 'primary'}, 'layer1_position', sources
    # Layer 1 counts every brand the answer names, so a lowest position of 2
    # or more means a brand outside the comparison set came first: only
    # Layer 2 can say which. A Layer 1 brand is a candidate only when Layer 1
    # coded no position at all.
    candidates = [] if positioned else \
        [(brands.aliases.get(m['name'], [m['name']]), m['name'], m.get('role') == 'primary') for m in coded]
    candidates += [([written], display, you) for written, display, you in others]
    if not candidates:
        return list(named.values()), None, ('uncoded' if positioned else None), sources
    spans = (extraction or {}).get('spans') or []
    located = [(hit, i, display, you) for i, (names, display, you) in enumerate(candidates)
               for hit in [_span_hit(spans, names)] if hit is not None]
    if located:
        _, _, display, you = min(located)
        return list(named.values()), {'name': display, 'you': you}, 'span_position', sources
    _, display, you = candidates[0]
    return list(named.values()), {'name': display, 'you': you}, 'coded_order', sources


#: 2T-5 (V3): words that put a named product outside a diaper category (wipes, training and swim pants,
#: overnight pants), as written in the answers: such a product is never "named but not tracked"
OUTSIDE_CATEGORY_WORDS = ('wipe', 'wipes', 'training pants', 'training pant', 'pull ups', 'pullups', 'easy ups',
                          'goodnites', 'ninjamas', 'underjams', 'little swimmers', 'splashers', 'swim pants')


def is_outside_category(name: Optional[str]) -> bool:
    """A one-word term matches inside a word ("WaterWipes"), a longer one as whole words."""
    key = f" {_brand_key((name or '').replace('-', ' '))} "
    for w in OUTSIDE_CATEGORY_WORDS:
        w = _brand_key(w)
        if (' ' in w and f" {w} " in key) or (' ' not in w and any(w in tok for tok in key.split())):
            return True
    return False


def _brand_entries(extraction: Optional[dict]):
    from soa_shared import retailers as af
    for entry in (extraction or {}).get('other_brands_named') or []:
        if not isinstance(entry, dict) or not entry.get('name') or af.is_store_name(entry['name']):
            continue
        if entry.get('presented_as') in VIS_SOURCE_PRESENTED or entry.get('relation') in VIS_SOURCE_RELATIONS:
            continue
        yield entry


def named_products(extraction: Optional[dict], brands: '_Brands') -> List[dict]:
    """2T-5 (V1): the products an answer named, in its coding's order: each Layer 2 name longer than the
    brand it resolves to ("Huggies Little Movers" is Huggies'), with that brand."""
    out = []
    for entry in _brand_entries(extraction):
        hit = brands.resolve(entry['name'])
        if hit and len(_brand_key(entry['name']).split()) > len(_brand_key(hit[0]).split()) and \
                not is_outside_category(entry['name']):
            out.append({'name': entry['name'], 'brand': hit[0], 'you': bool(hit[1])})
    return out


def outside_category(extraction: Optional[dict], brands: '_Brands') -> List[dict]:
    """2T-5 (V3): the names an answer coded outside the category, each once, with whether it is ours."""
    seen = {}
    for entry in _brand_entries(extraction):
        if is_outside_category(entry['name']):
            hit = brands.resolve(entry['name'])
            seen.setdefault(entry['name'], {'name': entry['name'], 'you': bool(hit and hit[1])})
    return list(seen.values())


def _agent_counts(rows: List[dict], surface: str) -> dict:
    """{agent: rows}; on `all`, agents in the demo's column order (AGENT_NAMES)."""
    counts = dict(Counter(r['agent'] for r in rows))
    if surface != surfaces.ALL:
        return counts
    order = list(AGENT_NAMES)
    return dict(sorted(counts.items(), key=lambda kv: (order.index(kv[0]) if kv[0] in order else 99, kv[0])))


def build_visibility(cycle_code: str, *, runs: List[dict], entities: List[dict], mentions: List[dict],
                     extractions: Dict[int, dict], terms: Iterable[str] = (), retired: Iterable[dict] = (),
                     retired_by: Optional[str] = None, cycle_name: Optional[str] = None, answer_texts: Optional[Dict[int, str]] = None,
                     merchant: Optional[dict] = None, lines: Iterable[str] = (), kind: Optional[str] = None) -> dict:
    """
    GET /api/console/visibility. `runs` carry their question (query_text,
    query_code, tier, stage); `mentions` are Layer 1's mentioned rows with
    the entity's name and cycle role; `extractions` are the stored Layer 2
    extractions by run id.
    terms: the brand's terms (load_brand_terms). 2I-7: each row says
    whether its question is unprompted (soa_shared/unprompted.py), which the
    score and the Overview count over.
    retired, retired_by, answer_texts: 2L-2, the study's retired lines
    (tier_config.merchant.retired), who retired them (the brand's domain)
    and each run's answer text by run id; with any line, the body carries
    `retired_named` (build_retired_named), else not at all. A run's
    `source_ref` (its question's) says which retired line a brand-direct
    question asked about.
    merchant: 2L-4, the cycle's merchant as routing_merchant reads it ({kind,
    retailers, own_domains, reads, brand, retailers_source}); a brand with a
    where-to-buy or cheapest-place question gets `routing` (build_routing),
    anything else none at all.
    lines, kind: 2N-1, the merchant's line names (line_aliases), which name
    it, and its kind. For a brand the ranking opens on the brand-choice
    answers (category control and comparison: `ranking.brand_choice`,
    `ranking.default_tier`); the every-question ranking stays the typed
    fields, the chip beside it.
    """
    from soa_shared import retailers as af
    layer2 = [e.get('name') for x in extractions.values() for e in ((x or {}).get('other_brands_named') or [])
              if isinstance(e, dict) and e.get('name') and not af.is_store_name(e.get('name'))
              and e.get('presented_as') not in VIS_SOURCE_PRESENTED and e.get('relation') not in VIS_SOURCE_RELATIONS]
    brands = _Brands(entities, layer2, lines)
    by_run: Dict[int, List[dict]] = {}
    for m in mentions:
        if m.get('mentioned', True):
            by_run.setdefault(m['run_id'], []).append(m)
    ours = next((e['name'] for e in entities if e.get('role') == 'primary'), None)

    rows, sources_left_out = [], 0
    outside: Dict[str, Counter] = {'others': Counter(), 'own': Counter()}
    for run in sorted(runs, key=lambda r: (r.get('query_code') or '', r.get('platform') or '', r.get('run_number') or 0, r['id'])):
        platform = run.get('platform')
        extraction = _json(extractions.get(run['id']))
        named, first, basis, sources = _visibility_run(by_run.get(run['id'], []), extraction or {}, brands)
        sources_left_out += sources
        tier = run.get('tier') or VIS_UNPROMPTED
        answered = run.get('answer_status') == surfaces.ANSWERED
        products = named_products(extraction, brands)
        if answered and unprompted.is_brand_choice(run, terms):
            for p in outside_category(extraction, brands):
                outside['own' if p['you'] else 'others'][p['name']] += 1
        # 2T-5 (V4): what the first pick is, coded: a brand; no single pick (the coding names brands, none
        # first); no brand named; no pick coded only when the answer has no coding at all
        pick = None if not answered else 'first' if first else 'no_single_pick' if named else \
            'no_brand_named' if (by_run.get(run['id']) or extraction) else 'no_pick_coded'
        rows.append(compact({
            'q': run.get('query_text') or '', 'type': VIS_TIER_LABELS.get(run.get('tier')) or run.get('stage') or '',
            'tier': tier, 'surface': run.get('surface') or surfaces.surface_of(platform) or 'unlabelled',
            'agent': surfaces.agent_of(platform) or platform, 'named': named, 'first': first,
            # beside the typed fields
            'run': f"run-{run['id']}", 'platform': platform, 'query_code': run.get('query_code'),
            'stage': run.get('stage'), 'answered': run.get('answer_status') == surfaces.ANSWERED,
            'unprompted': unprompted.is_unprompted(run, terms),
            'brand_choice': unprompted.is_brand_choice(run, terms),
            'first_basis': basis,
            'pick': pick,
            # 2T-5 (V1): the products the answer named, each with its brand, as written
            'named_products': products or None,
        }, ('first_basis', 'pick', 'named_products')))

    counted = [r for r in rows if r['answered']]
    # 2I-8: `all` first, every agent together, as the console demo counts
    # them, and the default; each surface's own entry beside it
    surface_list = surfaces.with_all(_ordered_surfaces({r['surface'] for r in rows}))
    on = surfaces.on_surface
    denoms = {s: sum(1 for r in counted if on(r['surface'], s)) for s in surface_list}
    agent_denoms = {s: _agent_counts([r for r in counted if on(r['surface'], s)], s) for s in surface_list}
    uncoded = {s: _agent_counts([r for r in counted if on(r['surface'], s) and r.get('first_basis') == 'uncoded'], s)
               for s in surface_list}
    default = surface_list[0] if surface_list else None

    ranking_rows = _ranking_rows(counted, surface_list, agent_denoms, default, ours)
    # 2G: brands named outside the comparison set, with how many answers on
    # each surface named them (over every answered run there), most named
    # first: the demo's "Also named but not tracked" line
    tracked = {e['name'] for e in entities if e.get('name')}
    # 2T-5 (V3): a product outside the category (wipes, training pants) is not a brand left untracked
    untracked = {s: [{'name': r['name'], 'named': r['surfaces'][s]['named']}
                     for r in sorted(ranking_rows, key=lambda r: (-r['surfaces'][s]['named'], r['name'].lower()))
                     if r['name'] not in tracked and not r['you'] and r['surfaces'][s]['named'] > 0
                     and not is_outside_category(r['name'])][:VIS_UNTRACKED_KEEP]
                 for s in surface_list}
    tiers = [t for t in VIS_TIER_ORDER if any(r['tier'] == t for r in rows)]
    tiers += sorted({r['tier'] for r in rows} - set(tiers))
    # 2N-1: a brand's ranking opens on its brand-choice answers, the demo's
    # "Who agents pick first, Pampers category prompts": every question counts
    # the ones that name it
    choice = [r for r in counted if r.get('brand_choice')]
    brand_choice = None
    if choice and kind == 'brand':
        c_denoms = {s: sum(1 for r in choice if on(r['surface'], s)) for s in surface_list}
        c_agents = {s: _agent_counts([r for r in choice if on(r['surface'], s)], s) for s in surface_list}
        c_uncoded = {s: _agent_counts([r for r in choice if on(r['surface'], s) and r.get('first_basis') == 'uncoded'], s)
                     for s in surface_list}
        who = ours or (merchant or {}).get('brand') or 'the brand'
        brand_choice = {'tier': VIS_BRAND_CHOICE, 'label': VIS_BRAND_CHOICE_LABEL,
                        'title': f"Who agents pick first, {who} category prompts",
                        'sub': f"{c_denoms.get(default, 0)} category and comparison answers",
                        'rows': _ranking_rows(choice, surface_list, c_agents, default, ours),
                        'denom': c_denoms.get(default, 0), 'denoms': c_denoms, 'agent_denoms': c_agents,
                        'first_uncoded': {s: sum(v.values()) for s, v in c_uncoded.items()},
                        'agent_first_uncoded': c_uncoded}
    return {
        'cycle': cycle_code,
        'lede': (f"Who the answers name, and who they name first, in {cycle_name or 'cycle ' + cycle_code}. Every agent "
                 "together, as the demo counts them. Pick a surface to count one alone."),
        'byQuestion': rows,
        'ranking': {'surface': default, 'rows': ranking_rows, 'denom': denoms.get(default, 0),
                    # beside the typed fields
                    'denoms': denoms, 'agent_denoms': agent_denoms,
                    'first_uncoded': {s: sum(v.values()) for s, v in uncoded.items()},
                    'agent_first_uncoded': uncoded,
                    'untracked': untracked,
                    # 2T-5 (V3): named in brand-choice answers, outside the category: other brands' products
                    # apart from the brand's own lines
                    'outside_category': {k: [{'name': n, 'named': c} for n, c in
                                             sorted(v.items(), key=lambda kv: (-kv[1], kv[0].lower()))]
                                         for k, v in outside.items()},
                    **({'brand_choice': brand_choice, 'default_tier': VIS_BRAND_CHOICE} if brand_choice else {})},
        'note': VIS_FIRST_PICK_RULE,
        # beside the typed fields
        'surfaces': [{'surface': s, 'label': surfaces.SURFACE_LABELS.get(s, s), 'answered': denoms[s],
                      'runs': sum(1 for r in rows if on(r['surface'], s))} for s in surface_list],
        'tiers': [{'tier': t, 'label': VIS_TIER_LABELS.get(t, t)} for t in tiers],
        'first_basis': dict(Counter(r.get('first_basis') for r in counted if r.get('first_basis'))),
        'sources_left_out': sources_left_out,
        'divergences': VISIBILITY_DIVERGENCES,
        **({'retired_named': build_retired_named(list(retired), rows=rows, runs=runs, texts=answer_texts or {},
                                                 surface_list=surface_list, retired_by=retired_by)}
           if retired else {}),
        **_routing_block(rows, runs, extractions, surface_list, merchant, ours),
    }


def _ranking_rows(counted: List[dict], surface_list: List[str], agent_denoms: dict, default: Optional[str],
                  ours: Optional[str]) -> List[dict]:
    """RankRows over `counted` (answered Visibility rows): every brand named, ours always, most named first."""
    on = surfaces.on_surface
    tally: Dict[str, dict] = {}
    if ours:
        tally[ours] = {'name': ours, 'you': True}
    for r in counted:
        for n in r['named']:
            tally.setdefault(n['name'], {'name': n['name'], 'you': n['you']})
    ranking_rows = []
    for name, row in tally.items():
        per = {}
        for s in surface_list:
            mine = [r for r in counted if on(r['surface'], s)]
            agents = {}
            for a in agent_denoms[s]:
                ra = [r for r in mine if r['agent'] == a]
                agents[a] = {'named': sum(1 for r in ra if any(n['name'] == name for n in r['named'])),
                             'first': sum(1 for r in ra if (r.get('first') or {}).get('name') == name)}
            per[s] = {'named': sum(v['named'] for v in agents.values()),
                      'first': sum(v['first'] for v in agents.values()), 'agents': agents}
        top = per.get(default) or {'named': 0, 'first': 0}
        ranking_rows.append({'name': name, 'you': row['you'], 'named': top['named'], 'first': top['first'],
                             'surfaces': per})
    ranking_rows.sort(key=lambda r: (-r['named'], -r['first'], not r['you'], r['name'].lower()))
    return ranking_rows


def _routing_block(rows, runs, extractions, surface_list, merchant: Optional[dict], ours: Optional[str]) -> dict:
    """2L-4: {'routing': ...} for a brand merchant whose cycle asked an intent question, else {}."""
    if not merchant or merchant.get('kind') != 'brand':
        return {}
    block = build_routing(rows, runs, extractions, surface_list=surface_list, brand=merchant.get('brand') or ours,
                          retailers=merchant.get('retailers') or [], own_domains=merchant.get('own_domains') or [],
                          reads=merchant.get('reads'), retailers_source=merchant.get('retailers_source'))
    return {'routing': block} if block else {}


# ─── Retired product named (2L-2) ──────────────────────────────────────────
#
# Visibility's "Retired product named" block, and the Overview's fifth brand
# tile input: for each line the brand's record says is retired
# (soa_shared/retired_lines.py), how many brand-choice answers named it and
# how many named its successor, and how the brand-direct question about it
# was answered. "Named" is the line's terms as whole words in the answer as
# the agent gave it (soa_runs.raw_response): a category question carries no
# expectation, so it is never scored and has no stored extraction to read.
# Deterministic, no model.

RETIRED_NAMED_RULE = (
    "Counted over answered brand-choice answers (category and comparison questions; "
    "soa_shared/unprompted.is_brand_choice). An answer names a line when its text "
    "contains the product name, the line's name, or the brand with the line's first word, "
    "as whole words; the line's first word alone does not count."
)
#: Why `still_sold` is null: the extraction stores no availability field.
RETIRED_STILL_SOLD_NOTE = (
    "Not counted: the stored extraction has no field saying whether an answer called the line "
    "still sold, so only which answers named it, and its successor, are counted."
)


def _times(n: int) -> str:
    return f"{n} time" if n == 1 else f"{n} times"


def build_retired_named(retired: List[dict], *, rows: List[dict], runs: List[dict], texts: Dict[int, str],
                        surface_list: List[str], retired_by: Optional[str] = None) -> dict:
    """
    {lines: [{line, label, product_name, variant_ids, successor, brand_choice,
    agents, brand_direct, headline, sentence}], rule, still_sold_note}. `rows` are
    build_visibility's byQuestion rows (each `run` is `run-<id>`); `runs`
    the loaded runs with their question's `source_ref`; `texts` each run's
    answer text by run id.

    brand_choice: per surface (`all` first), the answered brand-choice
    answers (`answers`), how many named the line (`named`) and how many its
    successor (`successor_named`), plus `no_text`: answers with no stored
    text, counted in `answers` and never as naming anything.
    agents (2R-2): on the first surface, how many agents answered a
    brand-choice question (`of`) and how many of them named the line.
    brand_direct: the answered runs of the question asked about this line
    (source_ref.retired_line), how many named the successor, and
    `still_sold`: null, with RETIRED_STILL_SOLD_NOTE.
    """
    refs = {r['id']: _json(r.get('source_ref')) or {} for r in runs}
    on = surfaces.on_surface
    texts_of = {}
    for r in rows:
        run_id = int(r['run'][len('run-'):])
        texts_of[r['run']] = (run_id, texts.get(run_id) or None)
    answered = [r for r in rows if r['answered']]
    choice = [r for r in answered if r.get('brand_choice')]
    by = retired_by or 'the brand'
    lines = []
    for line in retired:
        succ = line.get('successor') or None

        def named(r, terms):
            return bool(terms) and retired_lines.names(texts_of[r['run']][1], terms)

        per = {}
        for s in surface_list:
            mine = [r for r in choice if on(r['surface'], s)]
            per[s] = {'answers': len(mine),
                      'named': sum(1 for r in mine if named(r, line.get('terms'))),
                      'successor_named': sum(1 for r in mine if succ and named(r, succ.get('terms'))) if succ else None,
                      'no_text': sum(1 for r in mine if texts_of[r['run']][1] is None)}
        asked = [r for r in answered if r.get('tier') == 'brand_direct'
                 and ((refs.get(texts_of[r['run']][0]) or {}).get('retired_line') or {}).get('line') == line.get('line')]
        top = per.get(surface_list[0]) if surface_list else {'answers': 0, 'named': 0, 'successor_named': 0}
        # 2R-2 (B1): the agents that answered on the first surface, and those that named the line
        on_top = [r for r in choice if surface_list and on(r['surface'], surface_list[0])]
        agents_of = {r.get('agent') or r.get('platform') for r in on_top}
        agents_named = {r.get('agent') or r.get('platform') for r in on_top if named(r, line.get('terms'))}
        label = line.get('label') or line.get('line')
        headline = f"{label} named in {top['named']} of {top['answers']} brand-choice answers"
        sentence = f"Agents named {label}, which {by} retired, {_times(top['named'])} in {top['answers']} category answers"
        if succ:
            headline += f", {succ.get('label')} in {top['successor_named']}"
            sentence += f" and {succ.get('label')}, its successor, {_times(top['successor_named'])}"
        lines.append({
            'line': line.get('line'), 'label': label, 'product_name': line.get('product_name'),
            'variant_ids': line.get('variant_ids') or [],
            'successor': {k: succ.get(k) for k in ('variant_id', 'sku', 'product_name', 'line', 'label')} if succ else None,
            'brand_choice': per,
            'agents': {'named': len(agents_named), 'of': len(agents_of)},
            'brand_direct': {'answers': len(asked),
                             'named_successor': sum(1 for r in asked if named(r, succ.get('terms'))) if succ else None,
                             'still_sold': None},
            'headline': headline + '.',
            'sentence': sentence + '.',
        })
    return {'lines': lines, 'retired_by': retired_by, 'rule': RETIRED_NAMED_RULE,
            'still_sold_note': RETIRED_STILL_SOLD_NOTE}


# ─── Where agents send shoppers first (2L-4) ───────────────────────────────
#
# Visibility's "Where agents send <brand> shoppers first" and the brand
# Overview's Retailer coverage tile. 2Q-1: read from the stores the scorer
# coded over the whole answer (`named_stores`, soa_shared/retailers.
# named_stores: the merchant's retailers, the retailer lexicon and its own
# site, in the answer's order). A row scored before 2Q-1 reads the stores its
# Layer 2 extraction coded (`retailer_mentions`, on every scored run), in the
# order the answer names them: the record's stored `spans` are the answer cut
# verbatim and in order, so the earliest span naming a store places it, as
# Visibility's first pick places brands (_span_hit). A store the coding did
# not find in any span keeps its coded order, after those it did. A store the
# answer says is unavailable there is not one it sends the shopper to.
# Counted over the brand-direct where-to-buy and cheapest-place questions
# (source_ref.intent, catalog_tiers.build_intent_questions). Deterministic,
# no model. A retailer merchant has no block: its stores are its rivals, and
# Visibility already ranks them.

ROUTING_INTENTS = ('where_to_buy', 'cheapest_place')
WHERE_TO_BUY = 'where_to_buy'
#: A store coded with this role is not one the answer sends the shopper to.
ROUTING_NOT_SENT = ('unavailable',)
#: A reference read with this status never reached the page.
WALLED_STATUSES = ('blocked', 'challenged')
ROUTING_OTHER = 'Other stores'
#: 2T-5 (V5): the routing table per intent
ROUTING_INTENT_TITLES = {'where_to_buy': 'Where agents send {brand} shoppers first',
                         'cheapest_place': 'Where agents say {brand} is cheapest'}
ROUTING_INTENT_SUBS = {'where_to_buy': '{n} where-to-buy answers', 'cheapest_place': '{n} cheapest-place answers'}
ROUTING_WALLED_NOTE = 'Walled every read'
ROUTING_THIRD_PARTY_NOTE = 'Third-party seller only'
#: The demo's footnote, as written.
ROUTING_FOOTNOTE = ('A brand wants agents to show every retailer the same way. Today the store an agent names first '
                    'is whichever page it happened to read.')
ROUTING_RULE = (
    "First store named: the first store each where-to-buy or cheapest-place answer names, from the stores coded "
    "over the whole answer when it was scored (named_stores: the merchant's retailers, the retailer lexicon and "
    "the brand's own site), in the order the answer names them. Counted over the answers that name a store. A "
    "store the answer says is unavailable there is not counted as sent to.")
COVERAGE_RULE = (
    "Retailer coverage: where-to-buy answers naming two or more of the merchant's retailers (supply's retailer "
    "list), of the answered where-to-buy answers whose stores were coded.")


def _store(name) -> Optional[tuple]:
    """(key, display, domain | None) for a store as the coding wrote it: a
    known retailer or a written domain is its domain (soa_shared/retailers.py),
    anything else its own name."""
    from soa_shared import retailers as af
    if not isinstance(name, str) or not name.strip():
        return None
    domains = af.retailers_named(name)
    if domains:
        return domains[0], af.retailer_name(domains[0]), domains[0]
    return _brand_key(name), name.strip(), None


def _store_names(written: str, display: str, domain: Optional[str]) -> List[str]:
    """Every way an answer may write the store, for placing it in the spans."""
    from soa_shared import retailers as af
    names = [written, display] + ([domain] if domain else [])
    if domain:
        names += [alias for alias, d in af.KNOWN_RETAILERS.items() if d == domain]
    return list(dict.fromkeys(n for n in names if n))


def stores_in_order(extraction: Optional[dict]) -> Optional[List[dict]]:
    """The stores an answer sends the shopper to, first named first:
    [{key, name, domain}]. None when the answer has no coding (not scored).
    2Q-1: the scorer's `named_stores` when the row carries it."""
    if not isinstance(extraction, dict):
        return None
    coded = extraction.get('named_stores')
    if isinstance(coded, list):
        out = []
        for st in sorted((st for st in coded if isinstance(st, dict)), key=lambda st: st.get('position') or 0):
            if st.get('role') in ROUTING_NOT_SENT or not (st.get('domain') or st.get('name')):
                continue
            out.append({'key': st.get('domain') or _brand_key(st['name']), 'name': st.get('name') or st['domain'],
                        'domain': st.get('domain')})
        return out
    spans = extraction.get('spans') or []
    found: Dict[str, tuple] = {}
    for i, m in enumerate(extraction.get('retailer_mentions') or []):
        if not isinstance(m, dict) or m.get('role') in ROUTING_NOT_SENT:
            continue
        store = _store(m.get('name'))
        if store is None or store[0] in found:
            continue
        key, display, domain = store
        hit = _span_hit(spans, _store_names(m['name'], display, domain))
        found[key] = (hit is None, hit or (0, 0), i, {'key': key, 'name': display, 'domain': domain})
    return [v[3] for v in sorted(found.values(), key=lambda v: v[:3])]


def _walled(reads: Optional[List[dict]]) -> Dict[str, str]:
    """{domain: note} from supply's reference reads: every read of the domain
    walled, or every price read there from a third-party seller (a `seller`
    on the row, when supply serves one)."""
    by: Dict[str, List[dict]] = {}
    for r in reads or []:
        d = (r.get('retailer_domain') or '').lower().removeprefix('www.')
        if d:
            by.setdefault(d, []).append(r)
    out = {}
    for d, rows in by.items():
        if all(r.get('read_status') in WALLED_STATUSES for r in rows):
            out[d] = ROUTING_WALLED_NOTE
            continue
        priced = [r for r in rows if r.get('read_status') == 'ok' and r.get('price') is not None]
        if priced and all(r.get('seller') for r in priced):
            out[d] = ROUTING_THIRD_PARTY_NOTE
    return out


def _names_list(names: List[str]) -> str:
    return ', '.join(names)


def build_routing(rows: List[dict], runs: List[dict], extractions: Dict[int, dict], *, surface_list: List[str],
                  brand: Optional[str], retailers: List[str], own_domains: Iterable[str] = (),
                  reads: Optional[List[dict]] = None, retailers_source: Optional[str] = None) -> Optional[dict]:
    """
    {title, sub, rows: [{name, domain, first, you, note, surfaces}], total,
    answers, no_store, uncoded, footnote, rule, coverage, retailers, ...};
    None when the cycle asked no where-to-buy or cheapest-place question.

    `rows` are build_visibility's byQuestion rows; `runs` the loaded runs
    with their question's `source_ref`; `extractions` Layer 2 by run id.
    `retailers` are the merchant's retailer domains (supply's /retailers
    `domains`): each is a row, most sent first first; every other store is
    counted in one "Other stores" row whose note names them. The brand's own
    site is a row only when an answer sends a shopper there first.

    `coverage`, per surface (`all` first): the answered where-to-buy answers
    whose stores were coded (`answers`) and how many named two or more of
    the merchant's retailers (`named_two_plus`), the Overview's Retailer
    coverage tile.
    """
    refs = {r['id']: _json(r.get('source_ref')) or {} for r in runs}
    on = surfaces.on_surface
    asked = []
    for r in rows:
        run_id = int(r['run'][len('run-'):])
        intent = (refs.get(run_id) or {}).get('intent')
        if r['answered'] and intent in ROUTING_INTENTS:
            asked.append((r, intent, stores_in_order(extractions.get(run_id))))
    if not any(intent in ROUTING_INTENTS for ref in refs.values() for intent in [ref.get('intent')]):
        return None
    mine = [d.lower().removeprefix('www.') for d in retailers or [] if d]
    own = {d.lower().removeprefix('www.') for d in own_domains or [] if d}
    mine = [d for d in dict.fromkeys(mine) if d not in own]
    coded = [(r, intent, stores) for r, intent, stores in asked if stores is not None]
    sent = [(r, stores[0]) for r, _i, stores in coded if stores]

    own_first = next((d.lower().removeprefix('www.') for d in own_domains or [] if d), None)
    brand_words = set(_brand_key(brand).split()) if brand else set()

    def bucket(store) -> str:
        if store['domain'] in mine:
            return store['domain']
        if store['domain'] in own:
            return 'own:' + store['domain']
        # 2N-1: "Pampers", "Pampers Official Store", "Pampers official site / product page" are the brand's site
        if store['domain'] is None and own_first and brand_words and brand_words <= set(_brand_key(store['name']).split()):
            return 'own:' + own_first
        return ROUTING_OTHER

    from soa_shared import retailers as af
    notes = _walled(reads)
    default = surface_list[0] if surface_list else surfaces.ALL

    def table_for(items) -> List[dict]:
        # `items` (row, intent, stores) coded. 2T-5 (V5): beside who is sent first, `named`: the answers
        # that name the store anywhere (named_stores), each store once per answer
        sent_here = [(r, stores[0]) for r, _i, stores in items if stores]
        counts = {s: Counter(bucket(st) for r, st in sent_here if on(r['surface'], s)) for s in surface_list}
        named = {s: Counter(k for r, _i, stores in items if on(r['surface'], s)
                            for k in {bucket(st) for st in stores}) for s in surface_list}
        top, top_named = counts.get(default) or Counter(), named.get(default) or Counter()
        keys = list(mine) + sorted({k for c in counts.values() for k in c if k.startswith('own:')})
        table = []
        for k in keys:
            domain = k[len('own:'):] if k.startswith('own:') else k
            table.append({'name': domain if k.startswith('own:') else af.retailer_name(domain), 'domain': domain,
                          'first': top.get(k, 0), 'named': top_named.get(k, 0), 'you': k.startswith('own:'),
                          **({'note': notes[domain]} if domain in notes else {}),
                          'surfaces': {s: counts[s].get(k, 0) for s in surface_list},
                          'named_surfaces': {s: named[s].get(k, 0) for s in surface_list}})
        table.sort(key=lambda x: -x['first'])   # stable: the merchant's list order on a tie
        others = Counter(st['name'] for r, st in sent_here if bucket(st) == ROUTING_OTHER and on(r['surface'], default))
        if any(counts[s].get(ROUTING_OTHER) for s in surface_list):
            table.append({'name': ROUTING_OTHER, 'domain': None, 'first': top.get(ROUTING_OTHER, 0),
                          'named': top_named.get(ROUTING_OTHER, 0), 'you': False,
                          'note': _names_list([n for n, _c in sorted(others.items(),
                                                                      key=lambda kv: (-kv[1], kv[0].lower()))]),
                          'surfaces': {s: counts[s].get(ROUTING_OTHER, 0) for s in surface_list},
                          'named_surfaces': {s: named[s].get(ROUTING_OTHER, 0) for s in surface_list}})
        return table

    table = table_for(coded)
    total = sum(1 for r, _st in sent if on(r['surface'], default))
    who_ = brand or 'the brand'
    # 2T-5 (V5): where to buy alone (the demo's table), the cheapest place beside it, each its own table
    intents = {}
    for intent in ROUTING_INTENTS:
        mine_items = [(r, i, st) for r, i, st in coded if i == intent]
        if not any(i == intent for _r, i, _st in asked):
            continue
        n_sent = sum(1 for r, _i, st in mine_items if st and on(r['surface'], default))
        intents[intent] = {'title': ROUTING_INTENT_TITLES[intent].format(brand=who_),
                           'sub': ROUTING_INTENT_SUBS[intent].format(n=n_sent),
                           'rows': table_for(mine_items), 'total': n_sent,
                           'answers': sum(1 for r, i, _st in asked if i == intent and on(r['surface'], default))}
    names = [af.retailer_name(d) for d in mine]
    coverage = {}
    for s in surface_list:
        wtb = [stores for r, intent, stores in coded if intent == WHERE_TO_BUY and on(r['surface'], s)]
        coverage[s] = {'answers': len(wtb),
                       'named_two_plus': sum(1 for stores in wtb if len({st['domain'] for st in stores} & set(mine)) >= 2)}
    who = brand or 'the brand'
    return {
        'title': f"Where agents send {who} shoppers first",
        'sub': f"First store named in {total} where-to-buy and cheapest-place answers",
        'rows': table,
        'total': total,
        'totals': {s: sum(1 for r, _st in sent if on(r['surface'], s)) for s in surface_list},
        'answers': sum(1 for r, _i, _st in asked if on(r['surface'], default)),
        'no_store': sum(1 for r, _i, stores in coded if not stores and on(r['surface'], default)),
        'uncoded': sum(1 for r, _i, stores in asked if stores is None and on(r['surface'], default)),
        'footnote': ROUTING_FOOTNOTE,
        'rule': ROUTING_RULE,
        'retailers': names,
        'retailers_source': retailers_source,
        'coverage': coverage,
        'coverage_rule': COVERAGE_RULE,
        'coverage_line': coverage_line(coverage.get(default) or {'answers': 0, 'named_two_plus': 0}, names),
        'intents': intents,
        'default_intent': WHERE_TO_BUY if WHERE_TO_BUY in intents else next(iter(intents), None),
    }


def coverage_line(c: dict, names: List[str]) -> str:
    """'45 of 49 where-to-buy answers name 2 or more of Walmart, Target, Amazon'"""
    return (f"{c['named_two_plus']} of {c['answers']} where-to-buy answers name 2 or more of "
            f"{_names_list(names) if names else 'the merchant' + chr(39) + 's retailers'}")


# ─── Offer record (2C-1) ───────────────────────────────────────────────────
#
# Fix > Offer record: one product's record as supply holds it (the listing
# GET /merchants/{slug}/catalog serves, its publications, its incentives),
# with where the latest reference read of its pages disagrees. Read-only.

#: Provenance, stated once. A field's `prov` says who stands behind the value.
RECORD_PROVENANCE = {
    ('published', 'seller'): 'retail',   # the seller published it: the retailer's own record
    ('published', 'brand'): 'brand',     # the brand published it
    ('scrape', None): 'parleo',          # Parleo read it off a page: our observation
    ('agent', None): 'agent',            # taken from an agent's answer
}
RECORD_PROV_UNKNOWN = 'unknown'
#: The 2A findings that are a disagreement about what the product IS (the
#: price is True Value's, and an unreadable page is Accessibility's).
RECORD_FINDINGS = {
    'name_differs': 'Name', 'pack_differs': 'Pack count', 'gtin_mismatch': 'GTIN',
    'gtin_missing_on_page': 'GTIN', 'brand_missing_on_page': 'Brand',
    # 2T-8 (B1): soa's own comparison of a brand page's ProductGroup variant (console_product_record)
    'size_differs': 'Size', 'weight_differs': 'Weight range',
}
RECORD_ISSUE_TONE = {'conflict': 'bad', 'dropped': 'warn', 'approx': 'warn', 'info': 'neu'}
RECORD_ISSUE_LABEL = {'conflict': 'fails validation', 'dropped': 'dropped by the channel',
                      'approx': 'approximated by the channel', 'info': 'note'}
NOT_CARRIED = 'not carried'
RECORD_DIVERGENCES = [
    "Field.prov is mapped once (RECORD_PROVENANCE): source 'published' on a seller merchant is "
    "'retail', on a brand merchant 'brand'; 'scrape' is 'parleo'; a value taken from an agent answer "
    "is 'agent'. A published listing whose merchant kind is unknown is 'unknown', which the console "
    "renders neutral.",
    "A listing's source is supply's provenance mix (listing rows); an external merchant's feed has no "
    "listing rows, so its record is 'published' with source_basis 'feed'.",
    "Field.was is what the latest reference read found on the page, not an earlier record value; "
    "`diff` marks the field, and `note` says which page, when and how it was read.",
    "Variant-level disagreements are their own fields ('Name · <variant>'), since 2A compares each "
    "variant with each page.",
    "`json` is the schema_org publication's artifact; empty when the product was never compiled for "
    "schema.org (an external merchant's feed is not compiled here).",
    "A price the record does not carry reads 'not carried', never blank.",
    "issues are the validator and expressiveness lines of the publications that compiled (the "
    "artifacts the channels host); a failed publish is one 'Not published to …' issue with its error, "
    "as the TrueSync matrix shows it blocked.",
]


def record_prov(source: Optional[str], kind: Optional[str]) -> str:
    if source in ('scrape', 'agent'):
        return RECORD_PROVENANCE[(source, None)]
    return RECORD_PROVENANCE.get((source, kind), RECORD_PROV_UNKNOWN)


def _listing_source(mix: dict, has_publication: bool, *, from_feed: bool = False) -> tuple:
    """(source, basis) for one listing from supply's provenance mix: the
    merchant's when all its listings are one source; mixed, a listing with a
    publication is 'published' and the rest 'scrape'. The mix counts listing
    rows, which an external merchant's feed does not have: its feed is what
    the merchant published (basis 'feed'). No basis at all is None."""
    scraped, published = mix.get('scrape', 0) or 0, mix.get('published', 0) or 0
    if scraped and not published:
        return 'scrape', 'merchant'
    if published and not scraped:
        return 'published', 'merchant'
    if scraped and published:
        return ('published' if has_publication else 'scrape'), 'publication'
    if from_feed:
        return 'published', 'feed'
    return ('published', 'publication') if has_publication else (None, 'unknown')


def _short_day(value) -> str:
    text_ = (_iso(value) or '')[:10]
    try:
        from datetime import date as _date
        d = _date.fromisoformat(text_)
        return f"{d.strftime('%b')} {d.day}"
    except ValueError:
        return 'an unrecorded date'


def _newest_member_read(rows: List[dict]) -> Optional[dict]:
    hits = [r for r in rows if r.get('read_status') in ('ok', 'empty') and _num(r.get('member_price')) is not None]
    return max(hits, key=lambda r: str(r.get('observed_at') or '')) if hits else None


def _price_text(value, currency) -> str:
    return money(value, currency) if value not in (None, '') else NOT_CARRIED


def _num(value) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _member_prices(incentives: Optional[dict], listing_id) -> Dict[str, str]:
    """variant_id -> the lowest member price the record's incentives state."""
    out: Dict[str, str] = {}
    entry = next((l for l in (incentives or {}).get('listings') or [] if l.get('listing_id') == listing_id), None)
    # 2C-2: supply's own answer per variant (the lowest member price the
    # record states, explicit first) when it gives one.
    for v in (entry or {}).get('variants') or []:
        price = v.get('entitled_member_price')
        if v.get('variant_id') and _num(price) is not None:
            out[v['variant_id']] = str(price)
    for inc in (entry or {}).get('incentives') or []:
        price = (inc.get('value') or {}).get('member_price')
        if inc.get('mechanic') != 'member_price' or _num(price) is None:
            continue
        for v in inc.get('variant_scope') or ['*']:
            if v not in out or _num(price) < _num(out[v]):
                out[v] = str(price)
    return out


def _same_page(a, b) -> bool:
    def norm(u):
        u = str(u or '').split('#', 1)[0].split('?', 1)[0].rstrip('/').lower()
        return u.split('//', 1)[-1].removeprefix('www.')
    return bool(a) and bool(b) and norm(a) == norm(b)


def reference_matches(row: dict, variant: dict, listing: Optional[dict] = None) -> bool:
    """2C-2: does this reference read speak for this record variant? By the
    variant's id first, then its SKU, then (a listing with one variant) its
    page; the GTIN is a second key, never the only one. supply's read carries
    variant_ref (`catalog_variant:<n>`, `feed_sku:<n>`, `listing:<n>`, or the
    variant key itself), the variant key as variant_label, the merchant SKU
    and the page URL, so a variant with no GTIN still finds its read."""
    vid = variant.get('variant_id')
    ids = {str(x) for x in (vid, variant.get('sku')) if x}
    if ids & {str(row.get('variant_ref') or ''), str(row.get('variant_label') or ''), str(row.get('sku') or '')}:
        return True
    lid = (listing or {}).get('listing_id')
    single = listing is not None and len(listing.get('variants') or []) <= 1
    if single and (row.get('variant_ref') == f"listing:{lid}"
                   or _same_page(row.get('url'), (listing or {}).get('product_url'))):
        return True
    gtin = _gtin14_or(variant.get('gtin'))
    return bool(gtin) and _gtin14_or(row.get('gtin')) == gtin


def _reference_rows(reference: Optional[dict], variant: dict, listing: Optional[dict] = None) -> List[dict]:
    return [r for r in (reference or {}).get('rows') or [] if reference_matches(r, variant, listing)]


def _read_note(row: dict) -> str:
    how = {'honest_fetch': 'our own fetch', 'hosted_render': 'a hosted render'}.get(row.get('reference_source'),
                                                                                    row.get('reference_source') or 'a read')
    when = (_iso(row.get('observed_at')) or '')[:10]
    return f"{row.get('retailer_domain') or 'the page'}, read {when or 'at an unrecorded time'} by {how}"


def _markup_rows(rows: List[dict], variant: dict, listing: dict) -> List[dict]:
    """2T-8 (B1): a brand page read whose markup is a ProductGroup carries soa's own findings for this
    variant (the page's variant that is its own, the fields both carry), never supply's, which compare it
    with the group's first variant. Every other read is as supply serves it."""
    from app.services import console_product_record as pr
    out = []
    for row in rows:
        if row.get('role') == 'own' and pr.is_product_group(row.get('json_ld')):
            mine = {'gtin': variant.get('gtin'), 'label': variant.get('title'), 'count': variant.get('count'),
                    'product_name': listing.get('title')}
            row = {**row, 'findings': pr.markup_findings(row, mine, brand=listing.get('brand'))}
        out.append(row)
    return out


def _diff_fields(variant: dict, rows: List[dict], prov: str) -> List[dict]:
    label = variant.get('title') or variant.get('variant_id') or 'variant'
    out = []
    for row in rows:
        for f in row.get('findings') or []:
            kind = f.get('finding')
            if kind not in RECORD_FINDINGS:
                continue
            detail = f.get('detail') or {}
            note = _read_note(row)
            if kind == 'name_differs':
                diff = detail.get('diff') or {}
                bits = [f"only on the page: {' '.join(diff['only_on_page'])}" if diff.get('only_on_page') else None,
                        f"only in the record: {' '.join(diff['only_in_record'])}" if diff.get('only_in_record') else None]
                note += '. ' + ', '.join(b for b in bits if b) if any(bits) else ''
            observed = f.get('observed') if f.get('observed') not in (None, '') else 'not on the page'
            out.append(compact({'k': f"{RECORD_FINDINGS[kind]} · {label}", 'v': f.get('expected') or '—', 'prov': prov,
                                'mono': kind in ('gtin_mismatch', 'gtin_missing_on_page') or None,
                                'was': observed, 'diff': True, 'note': note,
                                # beside the typed fields
                                'finding': kind, 'variant_id': variant.get('variant_id'),
                                'url': row.get('url')}, ('mono',)))
    return out


def _variant_status(rows: List[dict]) -> tuple:
    if not rows:
        return 'Not read yet', 'neu'
    gaps = [f for r in rows for f in r.get('findings') or [] if f.get('finding') in RECORD_FINDINGS]
    if gaps:
        kinds = sorted({RECORD_FINDINGS[f['finding']].lower() for f in gaps})
        return f"Page differs: {', '.join(kinds)}", 'warn'
    if all(any(f.get('finding') == 'page_unreadable' for f in r.get('findings') or []) for r in rows):
        return 'Page not read', 'neu'
    return 'Matches the page', 'ok'


def _record_publications(listing_id, publications: List[dict]) -> Dict[str, dict]:
    best: Dict[str, dict] = {}
    for pub in publications or []:
        if pub.get('listing_id') != listing_id:
            continue
        slug = pub.get('channel_slug')
        cur = best.get(slug)
        if cur is None or (_ts(pub.get('compiled_at')), pub.get('id') or 0) > (_ts(cur.get('compiled_at')), cur.get('id') or 0):
            best[slug] = pub
    return best


def _record_status(pubs: Dict[str, dict], issues: List[dict], diffs: int, hosting: Optional[str], names) -> dict:
    failing = [s for s, p in pubs.items() if (p.get('validation') or {}).get('errors') and p.get('status') != 'failed']
    if failing:
        return {'label': f"Fails validation on {', '.join(names.get(s, s) for s in failing)}", 'tone': 'bad'}
    if diffs:
        return {'label': f"{diffs} page {'difference' if diffs == 1 else 'differences'}", 'tone': 'warn'}
    live = [s for s, p in pubs.items() if p.get('status') == 'published']
    if live:
        return {'label': f"Published to {len(live)} {'channel' if len(live) == 1 else 'channels'}", 'tone': 'ok'}
    if hosting == 'external':
        return {'label': 'From your feed', 'tone': 'neu'}
    return {'label': 'Not published yet', 'tone': 'neu'}


def _listing_sku(listing: dict) -> str:
    return str(listing.get('product_id') or listing.get('listing_id'))


def build_record(merchant: str, listing: dict, *, merchant_record: Optional[dict], publications: List[dict],
                 channels: List[dict], provenance: Optional[dict], reference: Optional[dict],
                 incentives: Optional[dict], read_errors: Optional[Dict[str, str]] = None,
                 member_reads: Optional[List[dict]] = None) -> dict:
    """GET /api/console/record: the console's Record_ for one listing.
    2C-2c: `member_reads` is supply's read history (every readable read,
    newest first); a variant's member price is the newest read of it that
    states one. Without it, the newest read per page (/reference)."""
    kind = (merchant_record or {}).get('kind')
    hosting = (merchant_record or {}).get('hosting')
    lid = listing.get('listing_id')
    names = {c.get('slug'): c.get('name') or c.get('slug') for c in channels or []}
    pubs = _record_publications(lid, publications)
    from_feed = hosting == 'external' or str(listing.get('product_id') or '').startswith('feed:')
    source, basis = _listing_source((provenance or {}).get('listings') or {}, bool(pubs), from_feed=from_feed)
    prov = record_prov(source, kind)
    variants = listing.get('variants') or []
    members = _member_prices(incentives, lid)
    currency = next((v.get('currency') for v in variants if v.get('currency')), 'USD')

    prices = sorted(p for p in (_num(v.get('list_price')) for v in variants) if p is not None)
    if not prices:
        price = NOT_CARRIED
    elif prices[0] == prices[-1]:
        price = money(f"{prices[0]:.2f}", currency)
    else:
        price = f"{money(f'{prices[0]:.2f}', currency)} to {money(f'{prices[-1]:.2f}', currency)}"
    member_of = {v.get('variant_id'): members.get(v.get('variant_id')) or members.get('*') for v in variants}
    member_vals = sorted({_num(m) for m in member_of.values() if m})
    gtins = [v.get('gtin') for v in variants if v.get('gtin')]
    counts = sorted({v.get('count') for v in variants if v.get('count')})

    fields = [
        {'k': 'Name', 'v': listing.get('title') or NOT_CARRIED, 'prov': prov},
        {'k': 'Brand', 'v': listing.get('brand') or NOT_CARRIED, 'prov': prov},
        {'k': 'Product page', 'v': listing.get('product_url') or NOT_CARRIED, 'prov': prov, 'mono': bool(listing.get('product_url'))},
        {'k': 'Price', 'v': price, 'prov': prov,
         **({'note': f"{len(variants)} variants"} if len(variants) > 1 and prices else {})},
    ]
    if member_vals:
        priced = sum(1 for m in member_of.values() if m)
        fields.append(compact({'k': 'Member price', 'v': money(f"{member_vals[0]:.2f}", currency) if len(member_vals) == 1
                               else f"{money(f'{member_vals[0]:.2f}', currency)} to {money(f'{member_vals[-1]:.2f}', currency)}",
                               'prov': prov, 'note': None if priced == len(variants) else f"on {priced} of {len(variants)} variants"},
                              ('note',)))
    fields.append({'k': 'GTIN', 'v': (gtins[0] if len(gtins) == 1 and len(variants) == 1 else
                                      f"{len(gtins)} of {len(variants)} variants carry one" if gtins else NOT_CARRIED),
                   'prov': prov, 'mono': len(gtins) == 1 and len(variants) == 1})
    if counts:
        fields.append({'k': 'Count', 'v': str(counts[0]) if len(counts) == 1 else f"{counts[0]} to {counts[-1]}", 'prov': prov})
    fields.append(compact({'k': 'Published', 'v': (_iso(listing.get('published_at')) or '')[:10] or NOT_CARRIED,
                           'prov': prov, 'note': listing.get('spec_version')}, ('note',)))

    variant_rows, diffs = [], 0
    page_members: Dict[str, tuple] = {}
    for v in variants:
        rows = _markup_rows(_reference_rows(reference, v, listing), v, listing)
        extra = _diff_fields(v, rows, prov)
        diffs += len(extra)
        fields.extend(extra)
        status, tone = _variant_status(rows) if reference is not None else ('Not read yet', 'neu')
        # 2C-2b: the member price in one source order (the ladder's): the
        # record's, else the newest page read that states one, named.
        member, member_source, member_note = member_of.get(v.get('variant_id')), None, None
        if member:
            member_source, member_note = 'record', 'from the record'
        else:
            read = _newest_member_read(_reference_rows({'rows': member_reads}, v, listing)
                                       if member_reads is not None else rows)
            if read:
                member, member_source = str(read['member_price']), 'reference_read'
                member_note = f"from the page read {_short_day(read.get('observed_at'))}"
                page_members[v.get('variant_id')] = (member, read.get('observed_at'))
        shown = _price_text(v.get('list_price'), v.get('currency') or currency)
        if member:
            shown += f" · member {money(member, v.get('currency') or currency)}"
            if member_source == 'reference_read':
                shown += f", {member_note}"
        variant_rows.append({'id': v.get('variant_id') or v.get('gtin') or '—', 'name': v.get('title') or v.get('variant_id') or '',
                             'price': shown, 'status': status, 'tone': tone,
                             # beside the typed fields
                             'gtin': v.get('gtin'), 'list_price': v.get('list_price'), 'member_price': member,
                             'member_source': member_source, 'member_note': member_note,
                             'count': v.get('count'), 'pages': [r.get('url') for r in rows if r.get('url')]})
    if page_members and not member_vals:
        vals = sorted(_num(m) for m, _ in page_members.values())
        newest = max(str(o or '') for _, o in page_members.values())
        fields.append({'k': 'Member price', 'v': money(f"{vals[0]:.2f}", currency) if vals[0] == vals[-1]
                       else f"{money(f'{vals[0]:.2f}', currency)} to {money(f'{vals[-1]:.2f}', currency)}",
                       'prov': RECORD_PROVENANCE[('scrape', None)],
                       'note': f"from the page read {_short_day(newest)}, on {len(vals)} of {len(variants)} variants. "
                               "The record states none"})

    issues = []
    failed = {slug: pub for slug, pub in pubs.items() if pub.get('status') == 'failed'}
    if failed:
        # 2K-3: sentences, not semicolons
        reasons = sorted({pub.get('error') or '. '.join((pub.get('validation') or {}).get('errors') or []) or 'failed'
                          for pub in failed.values()})
        issues.append({'title': f"Not published to {', '.join(names.get(s, s) for s in failed)}",
                       'detail': f"The publish failed: {'. '.join(r.rstrip('.') for r in reasons)}.", 'tone': 'warn',
                       'channel': ','.join(failed), 'verdict': 'blocked'})
    for slug, pub in pubs.items():
        if slug in failed:
            continue
        for line in _validator(pub):
            if line['verdict'] == 'ok':
                continue
            issues.append({'title': f"{names.get(slug, slug)}: {line['field'] or 'record'} {RECORD_ISSUE_LABEL.get(line['verdict'], line['verdict'])}",
                           'detail': line['note'], 'tone': RECORD_ISSUE_TONE.get(line['verdict'], 'neu'),
                           # beside the typed fields
                           'channel': slug, 'verdict': line['verdict']})
    issues.sort(key=lambda i: ['bad', 'warn', 'neu'].index(i['tone']) if i['tone'] in ('bad', 'warn', 'neu') else 3)
    schema = pubs.get('schema_org')
    sub_bits = [listing.get('brand'), f"{len(variants)} {'variant' if len(variants) == 1 else 'variants'}",
                (merchant_record or {}).get('domain')]
    return {
        'kind': 'offer' if kind == 'seller' else 'product',
        'sku': _listing_sku(listing),
        'title': listing.get('title') or f"Listing {lid}",
        'sub': ' · '.join(b for b in sub_bits if b),
        'status': _record_status(pubs, issues, diffs, hosting, names),
        'fields': fields,
        'issues': issues,
        'json': json.dumps(schema.get('payload'), indent=2, ensure_ascii=False) if schema and schema.get('payload') is not None else '',
        'variants': variant_rows,
        # beside the typed fields
        'merchant': merchant, 'listing_id': lid, 'product_url': listing.get('product_url'),
        # 2L-2: the line is retired when every variant is (soa_shared/retired_lines.py)
        'retired': (next((r for r in (retired_view(v.get('status'), v.get('successor'), listing.get('brand'))
                                      for v in variants) if r and r['successor']), None)
                    or retired_view('retired', None))
                   if variants and all(v.get('status') == 'retired' for v in variants) else None,
        'merchant_kind': kind, 'hosting': hosting, 'source': source, 'source_basis': basis,
        'json_channel': 'schema_org' if schema else None,
        'channels': {s: {'status': p.get('status'), 'published_at': _iso(p.get('published_at'))} for s, p in pubs.items()},
        'reference_run': (reference or {}).get('reference_run'),
        'read_errors': read_errors or {},
        'divergences': RECORD_DIVERGENCES,
    }


def build_record_list(merchant: str, catalog: Optional[dict], *, merchant_record: Optional[dict],
                      publications: List[dict], channels: List[dict], provenance: Optional[dict],
                      reference: Optional[dict], read_errors: Optional[Dict[str, str]] = None) -> dict:
    """GET /api/console/record/list: one row per product, for the record list."""
    products = []
    for listing in (catalog or {}).get('listings') or []:
        record = build_record(merchant, listing, merchant_record=merchant_record, publications=publications,
                              channels=channels, provenance=provenance, reference=reference, incentives=None)
        products.append({'sku': record['sku'], 'listing_id': record['listing_id'], 'title': record['title'],
                         'sub': record['sub'], 'variants': len(record['variants']), 'status': record['status'],
                         'diffs': sum(1 for f in record['fields'] if f.get('diff')),
                         **({'retired': record['retired']} if record.get('retired') else {})})
    return {'merchant': merchant, 'kind': (merchant_record or {}).get('kind'),
            'hosting': (merchant_record or {}).get('hosting'), 'products': products,
            'read_errors': read_errors or {}}


STUDIO_MIRROR = [
    "Entity.id is a slug string in studio.ts; soa_entities.id is an integer and slug is the string. "
    "Mapped id <- slug; soa_id carries the integer.",
    "EntityType: studio has 'product' and 'group'; soa has 'service' and 'aggregate'. Mapped "
    "aggregate -> group and service -> group (soa_entity_type keeps the original); 'product' "
    "has no soa value.",
    "Entity.domain: soa stores website_url, not a domain; the host is derived.",
    "Entity.parent, logo, tenant, note: no soa column.",
    "Category vocabularies differ: studio has Footwear, Apparel, Outdoor, Household Paper, Adult "
    "Care, Feminine Care, Laundry; soa has Makeup, Fragrance, Haircare, Cross-Category.",
    "Stage: studio spells 'Ready to buy', soa 'Ready to Buy'. Mapped.",
    "Prompt.branded has no soa column; derived from whether the text names the study's brand.",
    "Prompt.source ('ai'|'manual'|'csv') is not soa's provenance ('catalog'|'ai_from_catalog'|'ai'); "
    "mapped catalog->csv, the rest->ai, with provenance beside it.",
    "Study: soa has no studies table. A study is a study_type; its definition is its generation "
    "job. rivals, agents and runsPerPrompt live on cycles, not the study; cadence, shelfReads and "
    "crawl have no soa column.",
    "Study.status: soa's generation status (pending|running|complete|failed) is not the console's "
    "(active|draft|paused|done); mapped complete->done, failed->paused, else draft.",
    "Run: a soa cycle. status planned -> queued; usable = runs with answer_status 'answered'; "
    "elapsed is not stored. Run.agents can include 'claude'.",
    "Study patterns agree (retailer, brand_at_retail, brand_vs_brand); soa cycles also have 'mixed'.",
]


# ─── loaders ───────────────────────────────────────────────────────────────

def load_primary(conn, cycle: dict) -> Optional[str]:
    """The cycle's primary entity's name (the brand), None without one."""
    return conn.execute(text("""
        SELECT e.name FROM soa_cycle_entities ce JOIN soa_entities e ON e.id = ce.entity_id
        WHERE ce.cycle_id = :c AND ce.role = 'primary' ORDER BY e.id LIMIT 1
    """), {'c': cycle['id']}).scalar()


def load_answers(conn, cycle: dict, features: Optional[List[str]] = None,
                 club_keys: Optional[set] = None) -> List[dict]:
    """Every answer of the cycle (build_answer). 2T-4 (2): `club_keys` the
    feed's club-only variants' keys, when the reader read the feed."""
    runs = conn.execute(text("""
        SELECT r.*, q.query_code, q.query_text, q.tier, q.stage, q.source_ref, q.expected_answer AS query_expected
        FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
        WHERE r.cycle_id = :c ORDER BY q.query_code, r.platform, r.run_number
    """), {'c': cycle['id']}).mappings().all()
    unpriced = brand_sets_no_price_runs(conn, cycle)
    outcomes = {o['run_id']: not_priced(dict(o), unpriced) for o in conn.execute(text(
        "SELECT * FROM soa_expectation_outcomes WHERE cycle_id = :c"), {'c': cycle['id']}).mappings()}
    mentions: Dict[int, List[dict]] = {}
    for m in conn.execute(text("""
        SELECT cm.run_id, e.name, cm.position, ce.role FROM soa_coded_mentions cm
        JOIN soa_entities e ON e.id = cm.entity_id
        JOIN soa_runs r ON r.id = cm.run_id
        LEFT JOIN soa_cycle_entities ce ON ce.cycle_id = r.cycle_id AND ce.entity_id = cm.entity_id
        WHERE r.cycle_id = :c AND cm.mentioned = :yes
    """), {'c': cycle['id'], 'yes': True}).mappings():
        mentions.setdefault(m['run_id'], []).append(dict(m))
    # 2T-4 (2): the brand, for a comparison answer that put a rival first
    ours = load_primary(conn, cycle)
    names = load_variant_names(conn, cycle)
    reference = cycle.get('reference_prices') if 'reference_prices' in cycle else conn.execute(text(
        "SELECT reference_prices FROM soa_cycles WHERE id = :c"), {'c': cycle['id']}).scalar()
    index = reference_index(_json(reference))   # 2L-1: a left-out check's reference
    truths = attribute_accuracy.truth_index(_json(reference))   # 2N-1: the cycle's brand truths
    deals = ppt.deals_from_rows([r for r in (_json(reference) or {}).get('prices') or [] if isinstance(r, dict)])
    return [build_answer(dict(r), dict(r), outcomes.get(r['id']), mentions.get(r['id'], []),
                         runs_per_query=cycle.get('runs_per_query'), cycle_code=cycle['cycle_code'],
                         variant_names=names, features=features, references=index, truths=truths, deals=deals,
                         ours=ours, club_keys=club_keys)
            for r in runs]


def variant_label(query_text: str, brand: Optional[str] = None) -> str:
    """'What does the Wiggle & Snug Snug-Fit Trial Pack cost?' -> 'Snug-Fit
    Trial Pack'. The catalog tier's wording is fixed
    (generation/catalog_tiers.py), so this is a parse, not a guess."""
    label = (query_text or '').removeprefix('What does the ').removesuffix(' cost?')
    if ' cost at ' in label:
        label = label.split(' cost at ', 1)[0]
    if brand and label.startswith(brand + ' '):
        label = label[len(brand) + 1:]
    return label


def load_variant_names(conn, cycle: dict) -> Dict[str, str]:
    """2C-2c: variant id -> the record's name for it, from the study's
    catalog questions (one per variant), the brand prefix dropped."""
    brand = conn.execute(text("""
        SELECT e.name FROM soa_cycle_entities ce JOIN soa_entities e ON e.id = ce.entity_id
        WHERE ce.cycle_id = :c AND ce.role = 'primary'
    """), {'c': cycle['id']}).scalar()
    out: Dict[str, str] = {}
    for q in conn.execute(text("""
        SELECT query_text, source_ref FROM soa_queries WHERE study_type = :st AND tier = 'catalog_accuracy'
    """), {'st': cycle['study_type']}).mappings():
        vid = (_json(q['source_ref']) or {}).get('variant_id')
        if vid:
            out.setdefault(vid, variant_label(q['query_text'], brand))
    return out





def load_visibility(conn, cycle: dict, merchant: Optional[dict] = None) -> dict:
    """2C-1: the rows build_visibility reads, for one cycle. 2L-4: merchant
    as routing_merchant reads it, for `routing`."""
    runs = [dict(r) for r in conn.execute(text("""
        SELECT r.id, r.platform, r.run_number, r.surface, r.answer_status,
               q.query_code, q.query_text, q.tier, q.stage, q.source_ref
        FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
        WHERE r.cycle_id = :c
    """), {'c': cycle['id']}).mappings()]
    entities = [dict(e) for e in conn.execute(text("""
        SELECT e.name, e.aliases, ce.role FROM soa_cycle_entities ce
        JOIN soa_entities e ON e.id = ce.entity_id WHERE ce.cycle_id = :c
    """), {'c': cycle['id']}).mappings()]
    mentions = [dict(m) for m in conn.execute(text("""
        SELECT cm.run_id, e.name, cm.position, ce.role
        FROM soa_coded_mentions cm
        JOIN soa_entities e ON e.id = cm.entity_id
        JOIN soa_runs r ON r.id = cm.run_id
        LEFT JOIN soa_cycle_entities ce ON ce.cycle_id = r.cycle_id AND ce.entity_id = cm.entity_id
        WHERE r.cycle_id = :c AND cm.mentioned = :yes
    """), {'c': cycle['id'], 'yes': True}).mappings()]
    extractions = {o['run_id']: _json(o['extraction']) for o in conn.execute(text(
        "SELECT run_id, extraction FROM soa_expectation_outcomes WHERE cycle_id = :c"), {'c': cycle['id']}).mappings()}
    retired, retired_by = load_retired(conn, cycle)
    # 2L-2: the answers' own text, read only for a study with a retired line
    texts = {r['id']: r['raw_response'] for r in conn.execute(text(
        "SELECT id, raw_response FROM soa_runs WHERE cycle_id = :c"), {'c': cycle['id']}).mappings()} if retired else {}
    # 2N-1: the merchant's line names name it, and its kind picks the ranking's default
    stored = study_merchant_block(conn, cycle)
    brand = stored.get('study_brand') or stored.get('brand') or next(
        (e['name'] for e in entities if e.get('role') == 'primary'), None)
    names = list(stored.get('product_names') or []) + [r.get('product_name') for r in retired if r.get('product_name')]
    label = cycle_label_of(conn, cycle) or {}
    return build_visibility(cycle['cycle_code'], cycle_name=label['name'] if label.get('day') else None, runs=runs, entities=entities, mentions=mentions,
                            extractions=extractions, terms=load_brand_terms(conn, cycle),
                            retired=retired, retired_by=retired_by, answer_texts=texts, merchant=merchant,
                            lines=line_aliases(names, brand), kind=(merchant or {}).get('kind') or stored.get('kind'))


def study_merchant_block(conn, cycle: dict) -> dict:
    """2L-4: tier_config.merchant of the cycle's study, as generation wrote it ({} for none)."""
    job = conn.execute(text("SELECT tier_config FROM soa_query_generation_jobs WHERE study_type = :st"),
                       {'st': cycle.get('study_type')}).fetchone() if cycle.get('study_type') else None
    return ((_json(job[0]) if job else None) or {}).get('merchant') or {}


def asks_intents(conn, cycle: dict) -> bool:
    """2L-4: whether the cycle's study has a where-to-buy or cheapest-place
    question (brand-direct, source_ref.intent), so `routing` needs supply."""
    if not cycle.get('study_type'):
        return False
    refs = conn.execute(text("SELECT source_ref FROM soa_queries WHERE study_type = :st AND tier = 'brand_direct'"),
                        {'st': cycle['study_type']}).scalars()
    return any((_json(r) or {}).get('intent') in ROUTING_INTENTS for r in refs)


def routing_merchant(conn, cycle: dict, *, kind: Optional[str], retailers: Optional[dict], reference: Optional[dict],
                     retailers_error: Optional[str] = None) -> dict:
    """2L-4: the merchant facts `routing` reads. kind: the merchant record's
    (supply's /tenant), else the one the study was generated for
    (tier_config.merchant.kind). retailers: supply's /retailers payload; when
    it could not be read, the list the study was generated with
    (tier_config.merchant.retailer_list), and `retailers_source` says which.
    reference: supply's /reference payload, for the walled notes."""
    stored = study_merchant_block(conn, cycle)
    if retailers_error is None and isinstance(retailers, dict):
        listed, source = list(retailers.get('domains') or []), 'supply'
        own = list(retailers.get('own_domains') or [retailers.get('own_domain')])
    else:
        listed, source = list(stored.get('retailer_list') or []), 'study'
        own = [stored.get('own_domain')]
    return {'kind': kind or stored.get('kind'), 'retailers': listed, 'own_domains': [d for d in own if d],
            'reads': (reference or {}).get('rows'), 'brand': stored.get('study_brand') or stored.get('brand'),
            'retailers_source': source}


def load_retired(conn, cycle: dict) -> tuple:
    """2L-2: (the study's retired lines, the brand's domain) from its job's
    tier_config.merchant, written at generation; ([], None) for a study
    generated before 2L-2 or a brand with no retired line."""
    job = conn.execute(text("SELECT tier_config FROM soa_query_generation_jobs WHERE study_type = :st"),
                       {'st': cycle.get('study_type')}).fetchone() if cycle.get('study_type') else None
    merchant = ((_json(job[0]) if job else None) or {}).get('merchant') or {}
    return list(merchant.get('retired') or []), merchant.get('own_domain') or merchant.get('domain')


def study_brand_terms(tier_config, primary: Optional[dict]) -> List[str]:
    """2I-7: the terms that name the brand (soa_shared/unprompted.py): the
    primary entity's name and aliases, and the product names the generator
    stored from the catalog (tier_config.merchant.product_names, written
    from 2I-7 on; a study generated before has none)."""
    merchant = ((_json(tier_config) or {}).get('merchant') or {})
    primary = primary or {}
    return unprompted.brand_terms(primary.get('name'), _json(primary.get('aliases')) or [],
                                  merchant.get('product_names') or [])


def load_brand_terms(conn, cycle: dict) -> List[str]:
    """study_brand_terms for one cycle: its primary entity, its study's job."""
    primary = conn.execute(text("""
        SELECT e.name, e.aliases FROM soa_cycle_entities ce JOIN soa_entities e ON e.id = ce.entity_id
        WHERE ce.cycle_id = :c AND ce.role = 'primary'
    """), {'c': cycle['id']}).mappings().first()
    job = conn.execute(text("SELECT tier_config FROM soa_query_generation_jobs WHERE study_type = :st"),
                       {'st': cycle.get('study_type')}).fetchone() if cycle.get('study_type') else None
    return study_brand_terms(job[0] if job else None, dict(primary) if primary else None)


# ─── Attribute accuracy (2M-1) ─────────────────────────────────────────────
#
# The demo's first brand tile: the weight range for the size asked, on the
# retailer pages supply read for each variant (its /reference `attributes`,
# truesync/fullloop/weight.py) and in the answers to the study's attribute
# questions (source_ref.intent 'attribute', soa_shared/attribute_accuracy.py),
# each match / mismatch / absent against one brand truth per variant.
# Deterministic; no model.

def asks_attribute(conn, cycle: dict) -> bool:
    """2M-1: whether the cycle's study has an attribute question."""
    if not cycle.get('study_type'):
        return False
    refs = conn.execute(text("SELECT source_ref FROM soa_queries WHERE study_type = :st AND tier = 'brand_direct'"),
                        {'st': cycle['study_type']}).scalars()
    return any((_json(r) or {}).get('intent') == attribute_accuracy.ATTRIBUTE_INTENT for r in refs)


def cycle_reference(conn, cycle: dict) -> Optional[dict]:
    """The retailer-prices payload cached on the cycle (2B), or None."""
    if 'reference_prices' in cycle:
        return _json(cycle.get('reference_prices'))
    return _json(conn.execute(text("SELECT reference_prices FROM soa_cycles WHERE id = :c"),
                              {'c': cycle['id']}).scalar())


def attribute_answers(conn, cycle: dict, reference: Optional[dict] = None) -> List[dict]:
    """Every answered, scored run of the cycle's attribute questions, judged:
    {run_id, surface, platform, variant_id, variant, size, stated, truth, verdict, evidence}.
    2N-1: against the cycle's brand truth: its cached retailer-prices first,
    then `reference` (supply's /reference, the payload the drift rows read;
    pass it only for the cycle it is current for), then what the scorer
    stored. Never the study's copy."""
    rows = conn.execute(text("""
        SELECT r.id, r.platform, r.surface, r.answer_status, r.raw_response, q.source_ref, o.extraction
        FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
        JOIN soa_expectation_outcomes o ON o.run_id = r.id
        WHERE r.cycle_id = :c AND q.tier = 'brand_direct'
        ORDER BY r.id
    """), {'c': cycle['id']}).mappings().all()
    truths = attribute_accuracy.truth_index(cycle_reference(conn, cycle), reference)
    out = []
    for r in rows:
        ref = _json(r['source_ref']) or {}
        if ref.get('intent') != attribute_accuracy.ATTRIBUTE_INTENT:
            continue
        if (r['answer_status'] or surfaces.ANSWERED) != surfaces.ANSWERED:
            continue
        judged = attribute_accuracy.answer_attribute(ref, _json(r['extraction']), r['raw_response'], truths=truths)
        out.append({'run_id': r['id'], 'platform': r['platform'],
                    'surface': r['surface'] or surfaces.surface_of(r['platform']),
                    'variant_id': ref.get('variant_id'),
                    'variant': ' '.join(w for w in (ref.get('line'), ref.get('size')) if w) or ref.get('variant_id'),
                    'size': ref.get('size'), 'site': ref.get('own_domain') or ref.get('domain'),
                    'stated': judged['stated'], 'truth': judged['truth'],
                    'verdict': judged['verdict'], 'evidence': judged['evidence']})
    return out


def build_attribute_accuracy(answers: List[dict], reference: Optional[dict]) -> Optional[dict]:
    """
    /overview's attribute_accuracy, the Attribute accuracy tile's input:
    {n, k, pages: {n, k}, answers: {n, k}, answers_by_surface: {surface:
    {n, k}}, misses: [{variant, size, surface, kind, stated, truth}], site:
    the brand site the truth is the size chart of (the questions'), or None}, k the
    matches. Pages are the retailer pages supply read for each variant
    (/reference attributes[].pages); answers every judged attribute answer
    (a variant with no brand truth gives no verdict and is not counted).
    None when neither half has anything to count: the tile reads "not
    measured".
    """
    phrase = attribute_accuracy.phrase
    pages_n = pages_k = 0
    misses = []
    for variant in (reference or {}).get('attributes') or []:
        pages = variant.get('pages') or {}
        pages_n += pages.get('n') or 0
        pages_k += pages.get('k') or 0
        size = attribute_accuracy.size_label(variant.get('variant_label'))
        for p in pages.get('rows') or []:
            if p.get('verdict') in ('mismatch', 'absent'):
                misses.append({'variant': variant.get('variant_label') or variant.get('variant_ref'), 'size': size,
                               'surface': p.get('retailer_domain'), 'kind': 'page', 'verdict': p['verdict'],
                               'stated': phrase(p.get('stated')), 'truth': phrase(variant.get('truth'))})
    judged = [a for a in answers if a['verdict'] is not None]
    by_surface: Dict[str, dict] = {}
    for a in judged:
        cell = by_surface.setdefault(a['surface'], {'n': 0, 'k': 0})
        cell['n'] += 1
        cell['k'] += a['verdict'] == 'match'
        if a['verdict'] != 'match':
            misses.append({'variant': a['variant'], 'size': a['size'], 'surface': a['surface'], 'kind': 'answer',
                           'verdict': a['verdict'], 'stated': phrase(a['stated']), 'truth': phrase(a['truth'])})
    answers_k = sum(1 for a in judged if a['verdict'] == 'match')
    if not pages_n and not judged:
        return None
    return {'n': pages_n + len(judged), 'k': pages_k + answers_k,
            'pages': {'n': pages_n, 'k': pages_k}, 'answers': {'n': len(judged), 'k': answers_k},
            'answers_by_surface': by_surface, 'misses': misses,
            'site': next((a.get('site') for a in answers if a.get('site')), None)}


def load_attribute_accuracy(conn, cycle: dict, reference: Optional[dict]) -> Optional[dict]:
    return build_attribute_accuracy(attribute_answers(conn, cycle, reference), reference)


#: 2M-1: the Changes line's and the drift rows' copy (kept out of
#: console_parity.TEMPLATES, which the Overview serves pinned as `rules`).
ATTRIBUTE_TEMPLATES = {
    'changes.label': '{size} weight range right',
    'changes.new': '{a} of {n} accuracy answers on {size} gave the range {site} states. First cycle with this question.',
    'changes.detail': '{a} of {n} this cycle against {b} of {m} in {code}.',
}


def attribute_changes(now: List[dict], prev: Optional[List[dict]], prev_code: Optional[str], surface: str,
                      compared: bool, site: str = 'the brand site') -> List[dict]:
    """
    2M-1: the Overview's Changes line per size an accuracy answer missed on
    `surface` this cycle ("Size 4 weight range right"): matches of judged
    answers on that size. With a compared previous cycle that asked it, a
    delta as 2K-4's lines give one; otherwise (a first cycle, or one that
    did not ask the size) `delta` is 'new'.
    """
    def on(rows):
        return [a for a in rows or [] if a['verdict'] is not None and surfaces.on_surface(a['surface'], surface)]

    mine, theirs = on(now), on(prev) if compared else []
    sizes = list(dict.fromkeys(a['size'] for a in mine if a['verdict'] != 'match' and a['size']))
    out = []
    for size in sizes:
        here = [a for a in mine if a['size'] == size]
        then = [a for a in theirs if a['size'] == size]
        a, n = sum(1 for x in here if x['verdict'] == 'match'), len(here)
        label = ATTRIBUTE_TEMPLATES['changes.label'].format(size=size)
        if then:
            b, m = sum(1 for x in then if x['verdict'] == 'match'), len(then)
            d = a - b
            delta, direction = (f"+{d}" if d > 0 else str(d) if d < 0 else '0'), ('up' if d > 0 else 'down' if d < 0 else 'flat')
            tone = 'neu' if direction == 'flat' else ('ok' if direction == 'up' else 'bad')
            detail = ATTRIBUTE_TEMPLATES['changes.detail'].format(a=a, n=n, b=b, m=m, code=prev_code)
        else:
            b = m = None
            delta, direction, tone = 'new', 'new', 'bad' if a < n else 'neu'
            detail = ATTRIBUTE_TEMPLATES['changes.new'].format(a=a, n=n, size=size, site=site)
        out.append({'label': label, 'delta': delta, 'dir': direction, 'tone': tone, 'detail': detail,
                    'route': 'answers', 'metric': 'attribute', 'size': size,
                    'now': a, 'prev': b, 'of_now': n, 'of_prev': m})
    return out


def _slug(text: Optional[str]) -> str:
    return re.sub(r'[^a-z0-9]+', '_', (text or '').lower()).strip('_')


def line_of(product_name: Optional[str], brand: Optional[str] = None) -> str:
    """"Pampers Swaddlers Overnights Diapers, Size 4, 104 Count" -> "swaddlers_overnights": the
    product's own words before any comma or size, the brand and the word "diapers" left out."""
    head = re.split(r',|\bsize\b', product_name or '', maxsplit=1, flags=re.I)[0]
    words = [w for w in re.findall(r"[A-Za-z0-9']+", head)
             if w.lower() not in {(brand or '').lower(), 'diapers', 'diaper'}]
    return _slug(' '.join(words)) or 'product'


def build_weight_drift(reference: Optional[dict], brand: Optional[str] = None) -> List[dict]:
    """
    2M-1: the TrueSync records preview's weight rows, from supply's
    /reference attributes: one per variant whose brand-page markup states
    another range than its chart ("zzz.size_4.weight (markup)", was the
    markup, now the chart, prov brand), and one per retailer page whose
    stated range mismatches the truth ("swaddlers.size_4.weight (amazon.com)",
    was the page's, now the truth, prov retail).
    """
    phrase = attribute_accuracy.phrase
    out = []
    variants = (reference or {}).get('attributes') or []
    firsts = {(v.get('product_name') or '').split(' ')[0].lower() for v in variants if v.get('product_name')}
    if len(firsts) == 1 and len([v for v in variants if v.get('product_name')]) > 1:
        brand = brand if brand and brand.lower() in firsts else next(iter(firsts))   # the brand every name starts with
    for v in variants:
        size = attribute_accuracy.size_label(v.get('variant_label'))
        base = f"{line_of(v.get('product_name') or v.get('variant_label'), brand)}.{_slug(size or v.get('variant_label'))}.weight"
        chart, markup = v.get('chart') or v.get('truth'), v.get('markup')
        if chart and markup and not attribute_accuracy.same(chart, markup):
            out.append({'field': f"{base} (markup)", 'was': phrase(markup), 'now': phrase(chart), 'prov': 'brand',
                        'kind': 'markup', 'variant_ref': v.get('variant_ref'), 'evidence': v.get('markup_evidence')})
        for p in (v.get('pages') or {}).get('rows') or []:
            if p.get('verdict') == 'mismatch':
                out.append({'field': f"{base} ({p.get('retailer_domain')})", 'was': phrase(p.get('stated')),
                            'now': phrase(v.get('truth')), 'prov': 'retail', 'kind': 'page',
                            'variant_ref': v.get('variant_ref'), 'url': p.get('url'), 'evidence': p.get('evidence')})
    return out


# ─── Promo pass-through (2M-2) ─────────────────────────────────────────────
#
# The demo's fifth brand tile and its Trade promotions screen: of the
# answered cheapest-place answers (source_ref.intent 'cheapest_place',
# 2L-4), how many named a deal live on a retailer shelf for the question's
# variant on the cycle's read date (supply's /deals, parleo-supply-app 2M-2;
# soa_shared/promo_pass_through.py). Where-to-buy answers are counted the
# same way and reported apart. Deterministic; no model.


#: The copy, kept out of console_parity.TEMPLATES as 2M-1's is.
PROMO_TEMPLATES = {
    'tile.note': 'Cheapest-place answers naming a deal live that day. {deal}: named {k} of {n}',
    'tile.note.none': 'Cheapest-place answers naming a deal live that day',
    'changes.label': 'Deals named, cheapest-place answers',
    'changes.new': '{k} of {n}. {named}{biggest} First cycle with this question.',
    'changes.detail': '{k} of {n} this cycle against {b} of {m} in {code}.',
    'changes.biggest': '{deal} ran on {skus} and {named} of {asked} answers named it.',
    'prove.title': 'Trade promotions',
    'prove.sub': 'Deals live on a retailer shelf for the {brand} SKUs on {date}, and whether agents passed them on.',
    'prove.kick': 'Promo pass-through, {date}',
    'prove.label': 'cheapest-place answers named a deal that was live on a shelf that day',
    'prove.sub.subscribe': 'Subscribe & Save came up in {s} answers, and the charter counts it as a standing program.',
    'prove.note': ('Manufacturer mode never sets a price. Every figure here is what a named retailer showed on '
                   '{date}.'),
    'prove.note.walled': ' {names} walled every read, so their deals could not be checked.',
    'prove.none': 'No deals read this cycle: supply found no deal live on a retailer shelf for these SKUs on {date}.',
    'prove.agents': 'Named {k} of {n}',
    # 2T-8 (B6): the derived detail
    'prove.named_by': '{agents} named it.',
    'prove.quoted': '{agents} quoted the {line} cut without {word}, which the study rule does not count.',
    'prove.word.rollback': 'the word Rollback',
    'prove.word.other': 'naming the {kind}',
    # 2Q-1 (B4): a deal beside "Out of stock" on the shelf
    'prove.out_of_stock': 'Not live: the shelf said out of stock on {date}, so no answer is counted against it.',
    'prove.agents.out_of_stock': 'Not counted: out of stock',
    'baseline.label': 'Promo pass-through',
    'baseline.note': 'Named a deal live that day',
}


def promo_as_of(cycle: dict) -> Optional[str]:
    """The cycle's read date as supply's /deals takes it: the as_of of the
    retailer-prices read cached on the cycle (2B), else the cycle's creation,
    else its start day (a bare date: that whole day)."""
    for key in ('reference_as_of', 'created_at'):
        value = cycle.get(key)
        if value:
            return value.isoformat() if hasattr(value, 'isoformat') else str(value)
    start = cycle.get('start_date')
    return (start.isoformat() if hasattr(start, 'isoformat') else str(start))[:10] if start else None


def asks_cheapest_place(conn, cycle: dict) -> bool:
    """2M-2: whether the cycle's study has a cheapest-place question."""
    if not cycle.get('study_type'):
        return False
    refs = conn.execute(text("SELECT source_ref FROM soa_queries WHERE study_type = :st AND tier = 'brand_direct'"),
                        {'st': cycle['study_type']}).scalars()
    return any((_json(r) or {}).get('intent') == ppt.CHEAPEST_PLACE for r in refs)


def promo_answers(conn, cycle: dict) -> List[dict]:
    """Every answered run of the cycle's cheapest-place and where-to-buy
    questions: {run_id, platform, surface, intent, source_ref, text, query}."""
    rows = conn.execute(text("""
        SELECT r.id, r.platform, r.surface, r.answer_status, r.raw_response, q.query_text, q.source_ref
        FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
        WHERE r.cycle_id = :c AND q.tier = 'brand_direct'
        ORDER BY r.id
    """), {'c': cycle['id']}).mappings().all()
    out = []
    for r in rows:
        ref = _json(r['source_ref']) or {}
        if ref.get('intent') not in ppt.INTENTS:
            continue
        if (r['answer_status'] or surfaces.ANSWERED) != surfaces.ANSWERED or not (r['raw_response'] or '').strip():
            continue
        out.append({'run_id': r['id'], 'platform': r['platform'],
                    'surface': r['surface'] or surfaces.surface_of(r['platform']),
                    'intent': ref['intent'], 'source_ref': ref, 'text': r['raw_response'], 'query': r['query_text']})
    return out


def _read_day(deals: Optional[dict], as_of: Optional[str]) -> Optional[str]:
    """"Oct 20" for the deals' read date (supply's read_date, else the as_of)."""
    day = (deals or {}).get('read_date') or (as_of or '')[:10]
    try:
        from datetime import date
        d = date.fromisoformat(day)
        return f"{d.strftime('%b')} {d.day}"
    except (TypeError, ValueError):
        return None


def build_promo_pass_through(answers: List[dict], deals: Optional[dict], as_of: Optional[str] = None) -> Optional[dict]:
    """
    /overview's promo_pass_through, the Promo pass-through tile's input:
    {n, k, loose, subscribe, per_deal: [{retailer, retailer_domain, text,
    kind, title, short, asked, named}], by_surface, where_to_buy: {n, k,
    loose, subscribe, by_surface}, rule, read_date, as_of, walled, note}.
    None when the cycle has no answered cheapest-place answer: the tile
    reads "not measured".
    """
    cheapest = ppt.count(answers, deals, ppt.CHEAPEST_PLACE)
    if not cheapest['n']:
        return None
    where = ppt.count(answers, deals, ppt.WHERE_TO_BUY)
    top = ppt.biggest(cheapest['per_deal'])
    note = PROMO_TEMPLATES['tile.note'].format(deal=top['short'], k=top['named'], n=top['asked']) if top \
        else PROMO_TEMPLATES['tile.note.none']
    return {
        'n': cheapest['n'], 'k': cheapest['k'], 'loose': cheapest['loose'], 'subscribe': cheapest['subscribe'],
        'per_deal': [{k: v for k, v in d.items() if k != 'id'} for d in cheapest['per_deal']],
        'by_surface': cheapest['by_surface'],
        'where_to_buy': {k: where[k] for k in ('n', 'k', 'loose', 'subscribe', 'by_surface')},
        'rule': ppt.RULE, 'as_of': as_of, 'read_date': (deals or {}).get('read_date'),
        'deals_read': deals is not None, 'live_deals': len((deals or {}).get('deals') or []),
        'walled': list((deals or {}).get('walled') or []), 'note': note,
        'judged': cheapest['judged'],
    }


def promo_changes(now: Optional[dict], prev: Optional[dict], prev_code: Optional[str], surface: str,
                  compared: bool) -> List[dict]:
    """
    2M-2: the Overview's Changes line "Deals named, cheapest-place answers"
    on `surface`: k of n. Against a compared previous cycle that measured it,
    a delta; otherwise `new`, with the deals named and the biggest deal's
    count, as the demo writes it.
    """
    if not now:
        return []

    def cell(block):
        if surface == surfaces.ALL:
            return {'n': block['n'], 'k': block['k']}
        found = [c for s, c in (block.get('by_surface') or {}).items() if surfaces.on_surface(s, surface)]
        return {'n': sum(c['n'] for c in found), 'k': sum(c['k'] for c in found)}

    here = cell(now)
    if not here['n']:
        return []
    then = cell(prev) if compared and prev else None
    t = PROMO_TEMPLATES
    if then and then['n']:
        d = here['k'] - then['k']
        delta, direction = (f"+{d}" if d > 0 else str(d) if d < 0 else '0'), ('up' if d > 0 else 'down' if d < 0 else 'flat')
        tone = 'neu' if direction == 'flat' else ('ok' if direction == 'up' else 'bad')
        detail = t['changes.detail'].format(k=here['k'], n=here['n'], b=then['k'], m=then['n'], code=prev_code)
    else:
        delta, direction = 'new', 'flat'
        tone = 'bad' if here['k'] * 2 < here['n'] else 'neu'
        said = ppt.named_words(now['per_deal'])
        top = ppt.biggest(now['per_deal'])
        skus = len({j['variant_id'] for j in now.get('judged') or [] if top and ppt.deal_id(top) in j['live']}) if top else 0
        biggest = t['changes.biggest'].format(deal=top['short'], skus=f"{skus} SKU{'s' if skus != 1 else ''}",
                                              named=top['named'], asked=top['asked']) if top else ''
        detail = t['changes.new'].format(k=here['k'], n=here['n'], named=f"Named {said}. " if said else '',
                                         biggest=biggest).replace('  ', ' ')
    return [{'label': t['changes.label'], 'delta': delta, 'dir': direction, 'tone': tone, 'detail': detail.strip(),
             'route': 'prove', 'metric': 'promo', 'now': here['k'], 'of_now': here['n'],
             'prev': (then or {}).get('k'), 'of_prev': (then or {}).get('n')}]


def _variant_words(entry: dict) -> str:
    return entry.get('product_name') or entry.get('variant_label') or entry.get('sku') or entry.get('variant_ref') or ''


def _price_words(entry: dict) -> Optional[str]:
    price, was = entry.get('price') or entry.get('shelf_price'), entry.get('was_price')
    if price and was:
        return f"${was} to ${price}"
    return f"${price}" if price else None


def _deal_value(deal: dict) -> Optional[str]:
    value, unit = deal.get('value'), deal.get('value_unit')
    if value is None:
        variants = deal.get('variants') or []
        cuts = sorted({(Decimal(v['was_price']) - Decimal(v['price'])).quantize(Decimal('0.01'))
                       for v in variants if v.get('was_price') and v.get('price')})
        if not cuts:
            return None
        return f"${cuts[0]}" if len(cuts) == 1 else f"${cuts[0]} to ${cuts[-1]}"
    v = format(Decimal(str(value)).normalize(), 'f')
    return f"{v}% off" if unit == 'percent' else f"${Decimal(str(value)).quantize(Decimal('0.01'))}"


def _deal_terms(deal: dict) -> str:
    from soa_shared import retailers as af
    if deal.get('kind') == 'member_cash':
        return deal.get('program') or 'Members'
    # 2N-1: a price cut in its retailer's words (Rollback, List price cut, Sale, Sale price)
    cut = ppt.kind_words(deal)
    words = {'multi_buy': deal.get('terms') or 'Multi-buy',
             'rollback_or_was': 'Rollback' if 'rollback' in (deal.get('text') or '').lower() else cut[0].upper() + cut[1:],
             'sale': 'Sale', 'coupon': 'Coupon', 'other': deal.get('terms') or 'Deal'}
    term = words.get(deal.get('kind'), 'Deal')
    return f"{af.retailer_name(deal.get('retailer_domain'))}, {term}" if deal.get('kind') == 'multi_buy' else term


def _entry_flat_keys(deal: dict) -> set:
    """2T-8 (B6): a deal's identity per SKU it ran on, (retailer, SKU key, mechanic, amount) (ppt.deal_key)."""
    out = set()
    for v in deal.get('variants') or ([deal['variant']] if deal.get('variant') else []):
        domain, skus, kind, amount = ppt.deal_key(deal, v)
        out |= {(domain, k, kind, amount) for k in skus}
    return out


def _agents_words(names: List[str]) -> str:
    names = list(dict.fromkeys(n for n in names if n))
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def build_prove(promo: Optional[dict], deals: Optional[dict], brand: Optional[str], as_of: Optional[str],
                agent_of_run: Optional[Dict] = None) -> dict:
    """
    /prove, the Trade promotions screen: {state, title, sub, rows: [{retailer,
    retailer_domain, title, detail, terms, agents, value, tone, kind, asked,
    named}], aside: {kick, value, label, sub}, note, walled, rule}. One row
    per deal live that day; `agents` "Named k of n" over the cheapest-place
    answers about a SKU it ran on. state `measured`; `no_deals` when supply
    read the shelves and found none; `not_measured` when the cycle asked no
    cheapest-place question or supply could not be read.
    """
    from soa_shared import retailers as af
    t = PROMO_TEMPLATES
    day = _read_day(deals, as_of) or 'the read date'
    walled = [af.retailer_name(d) for d in (deals or {}).get('walled') or []]
    note = t['prove.note'].format(date=day) + (
        t['prove.note.walled'].format(names=' and '.join([', '.join(walled[:-1]), walled[-1]] if len(walled) > 1 else walled))
        if walled else '')
    per = {d['title']: d for d in (promo or {}).get('per_deal') or []}
    rows = []
    for deal in (deals or {}).get('deals') or []:
        variants = deal.get('variants') or []
        tally = per.get(ppt.title(deal)) or {'asked': 0, 'named': 0}
        where = ', '.join(dict.fromkeys(_variant_words(v) for v in variants))
        prices = '. '.join(dict.fromkeys(f"{_variant_words(v)} {_price_words(v)}" for v in variants if _price_words(v)))
        gone = ppt.out_of_stock(deal)
        # 2Q-1 (B4): a deal beside "Out of stock" was shown, never live
        detail = f"{'Shown' if gone else 'Live'} on {where}." + (f" {prices}." if prices else '')
        # 2T-8 (B6): the shelf's own words are `shelf_text`, behind an expander, never in the sentence
        said = ppt.evidence(next((v.get('evidence') for v in variants if v.get('evidence')), None) or deal.get('text'))
        shelf_text = said.rstrip('.') if said and re.search(r"\d", said) and \
            said.rstrip('.').lower() not in ppt.title(deal).lower() else None
        # who named it, and who quoted its price without naming it (the study rule counts naming only)
        did = ppt.deal_id(deal)
        judged = (promo or {}).get('judged') or []
        if agent_of_run is not None:
            namers = [agent_of_run.get(j.get('run_id')) for j in judged if did in (j.get('named') or [])]
            quoters = [agent_of_run.get(j.get('run_id')) for j in judged if did in (j.get('quoted') or [])]
            if any(namers):
                detail += ' ' + t['prove.named_by'].format(agents=_agents_words(namers))
            if any(quoters):
                line = next((ppt.deal_line(v) for v in variants if ppt.deal_line(v)), None)
                word = t['prove.word.rollback'] if deal.get('kind') == 'rollback_or_was' and \
                    deal.get('retailer_domain') == 'walmart.com' else t['prove.word.other'].format(kind=ppt.kind_words(deal))
                detail += ' ' + t['prove.quoted'].format(agents=_agents_words(quoters), line=(line or 'the').split(' Size')[0],
                                                          word=word)
        asked, named = tally['asked'], tally['named']
        if gone:
            # 2Q-1 (B4): never live, so never asked about: the row says why
            detail = t['prove.out_of_stock'].format(date=day) + ' ' + detail
        rows.append({'retailer': af.retailer_name(deal.get('retailer_domain')), 'retailer_domain': deal.get('retailer_domain'),
                     'title': ppt.title(deal), 'detail': detail, 'terms': _deal_terms(deal),
                     'agents': t['prove.agents.out_of_stock'] if gone else
                     t['prove.agents'].format(k=named, n=asked) if asked else 'Not asked this cycle',
                     'value': _deal_value(deal), 'kind': deal.get('kind'), 'kind_label': ppt.kind_words(deal),
                     'asked': asked, 'named': named,
                     'tone': 'neu' if gone else 'ok' if asked and named * 2 >= asked else ('warn' if named else 'bad'),
                     'skus': len(variants), 'shelf_text': shelf_text,
                     **({'live': False, 'not_live': 'out_of_stock'} if gone else {})})
    rows.sort(key=lambda r: (r.get('live') is False, -r['asked'], r['named'], r['retailer'] or ''))
    who = brand or 'the brand'
    if promo is None or deals is None:
        state = 'not_measured'
    else:
        state = 'measured' if rows else 'no_deals'
    aside = None
    if promo is not None:
        said = ppt.named_words(promo['per_deal'])
        sub = ' '.join(x for x in (f"Answers named {said}." if said else None,
                                   t['prove.sub.subscribe'].format(s=promo['subscribe']) if promo['subscribe'] else None) if x)
        aside = {'kick': t['prove.kick'].format(date=day), 'value': f"{promo['k']} of {promo['n']}",
                 'label': t['prove.label'], 'sub': sub or None}
    return {'state': state, 'title': t['prove.title'], 'sub': t['prove.sub'].format(brand=who, date=day),
            'rows': rows, 'aside': aside, 'note': note if state != 'no_deals' else t['prove.none'].format(date=day),
            'walled': walled, 'rule': ppt.RULE, 'read_date': (deals or {}).get('read_date'), 'as_of': as_of}


def promo_baseline(promo: Optional[dict]) -> Optional[dict]:
    """Impact's baseline row: {key, label, value, note, n, k}; None when not measured."""
    if promo is None:
        return None
    return {'key': 'promo', 'label': PROMO_TEMPLATES['baseline.label'], 'value': f"{promo['k']} of {promo['n']}",
            'note': PROMO_TEMPLATES['baseline.note'], 'n': promo['n'], 'k': promo['k']}


# ─── The brand's first-cycle Changes and Impact baseline (2N-1) ────────────
#
# The demo's Changes for a brand, beside the weight range (2M-1) and the
# deals named (2M-2): "Retired product named", "First pick, category
# questions", "Retailer coverage". Each is `new` on a first cycle (or one
# not compared), and a delta afterwards as 2K-4's lines take one. Impact's
# baseline holds the same measures: Attribute accuracy, Retailer coverage,
# Promo pass-through, Category presence. Read from Visibility's blocks; no
# model.

BRAND_CHANGE_TEMPLATES = {
    'retired.label': 'Retired product named',
    'retired.new': '{named}. First cycle with this question.',
    'first.label': 'First pick, category questions',
    'first.new': '{brand} {first} of {n}{rivals}. First cycle with these questions.',
    'coverage.label': 'Retailer coverage',
    'coverage.new': '{k} of {n} where-to-buy answers named at least two of {names}. First cycle with this question.',
    'detail': '{a} of {n} this cycle against {b} of {m} in {code}.',
    'baseline.attribute': 'Attribute accuracy',
    'baseline.attribute.note': 'Weight range matches {site}, {date}',
    'baseline.coverage': 'Retailer coverage',
    'baseline.coverage.note': 'Names 2 of {names}',
    'baseline.category': 'Category presence',
    'baseline.category.note': '{brand} named, first in {first}',
}


def _change(label: str, a: int, n: int, then: Optional[tuple], code: Optional[str], *, up_good: bool,
            new_detail: str, new_tone: str, route: str, metric: str) -> dict:
    t = BRAND_CHANGE_TEMPLATES
    if then is not None and then[1]:
        b, m = then
        d = a - b
        delta, direction = (f"+{d}" if d > 0 else str(d) if d < 0 else '0'), ('up' if d > 0 else 'down' if d < 0 else 'flat')
        tone = 'neu' if direction == 'flat' else ('ok' if (direction == 'up') == up_good else 'bad')
        detail = t['detail'].format(a=a, n=n, b=b, m=m, code=code)
    else:
        b = m = None
        delta, direction, tone, detail = 'new', 'flat', new_tone, new_detail
    return {'label': label, 'delta': delta, 'dir': direction, 'tone': tone, 'detail': detail, 'route': route,
            'metric': metric, 'now': a, 'of_now': n, 'prev': b, 'of_prev': m}


def _retired_counts(vis: Optional[dict], surface: str) -> Optional[tuple]:
    lines = ((vis or {}).get('retired_named') or {}).get('lines') or []
    cells = [(line, (line.get('brand_choice') or {}).get(surface)) for line in lines]
    cells = [(line, c) for line, c in cells if c and c.get('answers')]
    if not cells:
        return None
    return sum(c['named'] for _l, c in cells), cells[0][1]['answers'], cells


def _first_counts(vis: Optional[dict], surface: str) -> Optional[tuple]:
    rows = [r for r in (vis or {}).get('byQuestion') or []
            if r.get('answered') and r.get('brand_choice') and surfaces.on_surface(r.get('surface'), surface)]
    if not rows:
        return None
    firsts = Counter((r.get('first') or {}).get('name') for r in rows if r.get('first'))
    ours = next((n for r in rows for n in [r.get('first') or {}] if n.get('you')), None)
    mine = sum(1 for r in rows if (r.get('first') or {}).get('you'))
    named = sum(1 for r in rows if any(n.get('you') for n in r.get('named') or []))
    rivals = [(k, v) for k, v in firsts.most_common() if k and k != (ours or {}).get('name')]
    return mine, len(rows), rivals, named


def _coverage_counts(vis: Optional[dict], surface: str) -> Optional[tuple]:
    routing = (vis or {}).get('routing') or {}
    c = (routing.get('coverage') or {}).get(surface)
    if not c or not c.get('answers'):
        return None
    return c['named_two_plus'], c['answers'], routing.get('retailers') or []


def brand_changes(vis: dict, prev_vis: Optional[dict], prev_code: Optional[str], surface: str, *, compared: bool,
                  brand: str) -> List[dict]:
    """2N-1: the brand's Changes lines on `surface`, in the demo's order:
    Retired product named, First pick (category questions), Retailer
    coverage. A line appears when this cycle measured it."""
    t = BRAND_CHANGE_TEMPLATES
    prev = prev_vis if compared else None
    out = []
    retired = _retired_counts(vis, surface)
    if retired:
        named, answers, cells = retired
        then = _retired_counts(prev, surface)
        words = '. '.join(f"{(line.get('label') or line.get('line'))} in {c['named']} of {c['answers']} category answers" + (
            f", {line['successor'].get('label')} in {c.get('successor_named') or 0}"
            if line.get('successor') and c.get('successor_named') is not None else '') for line, c in cells)
        out.append(_change(t['retired.label'], named, answers, then[:2] if then else None, prev_code, up_good=False,
                           new_detail=t['retired.new'].format(named=words, answers=answers),
                           new_tone='bad' if named else 'ok', route='visibility', metric='retired'))
    first = _first_counts(vis, surface)
    if first:
        mine, n, rivals, _named = first
        then = _first_counts(prev, surface)
        lead = rivals[0][1] if rivals else 0
        said = ''.join(f", {k} {v}" for k, v in rivals[:2])
        out.append(_change(t['first.label'], mine, n, then[:2] if then else None, prev_code, up_good=True,
                           new_detail=t['first.new'].format(brand=brand, first=mine, n=n, rivals=said),
                           new_tone='ok' if mine > lead else 'warn', route='visibility', metric='first_category'))
    coverage = _coverage_counts(vis, surface)
    if coverage:
        k, n, names = coverage
        then = _coverage_counts(prev, surface)
        listed = [n_ for n_ in names][:3]
        out.append(_change(t['coverage.label'], k, n, then[:2] if then else None, prev_code, up_good=True,
                           new_detail=t['coverage.new'].format(k=k, n=n, names=_and(listed) if listed else 'its retailers'),
                           new_tone='ok' if k * 2 >= n else 'bad', route='visibility', metric='coverage'))
    return out


def brand_baseline(*, attribute: Optional[dict], vis: Optional[dict], promo: Optional[dict], brand: str,
                   day: Optional[str]) -> List[dict]:
    """2N-1: Impact's baseline for a brand, in the demo's order: Attribute
    accuracy, Retailer coverage, Promo pass-through, Category presence. Each
    {key, label, value, note, n, k}; a measure this cycle did not take is left out."""
    t = BRAND_CHANGE_TEMPLATES
    out = []
    if attribute:
        out.append({'key': 'attribute', 'label': t['baseline.attribute'], 'value': f"{attribute['k']} of {attribute['n']}",
                    'note': t['baseline.attribute.note'].format(site=attribute.get('site') or 'the brand site',
                                                               date=day or 'this cycle'),
                    'n': attribute['n'], 'k': attribute['k']})
    coverage = _coverage_counts(vis, surfaces.ALL)
    if coverage:
        k, n, names = coverage
        out.append({'key': 'coverage', 'label': t['baseline.coverage'], 'value': f"{k} of {n}",
                    'note': t['baseline.coverage.note'].format(names=', '.join(names[:3]) or 'its retailers'), 'n': n, 'k': k})
    promo_row = promo_baseline(promo)
    if promo_row:
        out.append(promo_row)
    first = _first_counts(vis, surfaces.ALL)
    if first:
        mine, n, _rivals, named = first
        out.append({'key': 'category', 'label': t['baseline.category'], 'value': f"{named} of {n}",
                    'note': t['baseline.category.note'].format(brand=brand, first=mine), 'n': n, 'k': named})
    return out


# ─── 2P-1 (B3): what moved since a compared previous cycle ─────────────────
#
# Four reads that only a second cycle has, each against the previous scored
# cycle and only when the shared rule (soa_shared/cycle_compare, as the
# Changes block reads it) says the two compare. Not compared, each is absent
# and the reason rides beside it, never a delta.

MOVED_TEMPLATES = {
    'prove.new': 'New since {code}.',
    'prove.continuing': 'Live in {code} too.',
    'prove.ended': 'Ended since {code}. {retailer} was read on {date} and no longer ran it.',
    'prove.not_read': 'Not read on {date}: {retailer} walled every read. Live in {code}.',
    # 2Q-1 (B4): live last cycle, beside "Out of stock" this one
    'prove.out_of_stock': 'Out of stock on {date}: {retailer} showed it beside "Out of stock". Live in {code}.',
    'prove.delta': '{k} of {n} this cycle against {b} of {m} in {code}.',
    'tv.drift': '{product} at {column}: {was} in {code}, {now} this cycle.',
    'vis.first': '{name} first in {now} of {n} brand-choice answers, {then} in {code}.',
    'baseline.moved': '{label}: {then} in {code}, {now} this cycle.',
}


def _signed(d: int) -> str:
    return f"+{d}" if d > 0 else str(d)


def _dir(d: int) -> str:
    return 'up' if d > 0 else 'down' if d < 0 else 'flat'


def prove_changes(body: dict, deals: Optional[dict], prev_deals: Optional[dict], promo: Optional[dict],
                  prev_promo: Optional[dict], prev_code: str) -> dict:
    """
    /prove against a compared previous cycle: each row's `change` ('new' when
    the deal was not live in the previous cycle's read, 'kept' otherwise),
    `ended` (the previous cycle's deals no longer live, each 'ended' when its
    retailer was read this cycle, 'not_read' when it was walled: a deal on a
    shelf nobody read never ended), and `aside.delta` against the previous
    pass-through. Changes `body` in place and returns it.
    """
    from soa_shared import retailers as af
    t = MOVED_TEMPLATES
    day = _read_day(deals, None) or 'the read date'
    # 2T-8 (B6): a deal is the same deal across cycles by retailer, SKU, mechanic and amount (ppt.deal_key), never
    # its id or shelf text, which change between reads: in both cycles it is `continuing`
    before = {ppt.deal_id(d): d for d in (prev_deals or {}).get('deals') or [] if not ppt.out_of_stock(d)}
    before_keys = set().union(*(_entry_flat_keys(d) for d in before.values())) if before else set()
    now_keys = set().union(*(_entry_flat_keys(d) for d in (deals or {}).get('deals') or [])) \
        if (deals or {}).get('deals') else set()
    by_title = {ppt.title(d): d for d in (deals or {}).get('deals') or []}
    for row in body.get('rows') or []:
        deal = by_title.get(row['title'])
        new = not (deal is not None and _entry_flat_keys(deal) & before_keys)
        if row.get('not_live') == 'out_of_stock':
            # 2Q-1 (B4): the row's own note says why; against the previous cycle it is out of stock, or new
            row['change'] = 'new' if new else 'out_of_stock'
            if not new:
                row['change_note'] = t['prove.out_of_stock'].format(date=day, retailer=row['retailer'], code=prev_code)
            continue
        row['change'] = 'new' if new else 'continuing'
        if new:
            row['change_note'] = t['prove.new'].format(code=prev_code)
        else:
            row['change_note'] = t['prove.continuing'].format(code=prev_code)
    walled = set((deals or {}).get('walled') or [])
    ended = []
    for key, deal in before.items():
        if _entry_flat_keys(deal) & now_keys:
            continue
        domain = deal.get('retailer_domain')
        state = 'not_read' if domain in walled else 'ended'
        retailer = af.retailer_name(domain)
        ended.append({'retailer': retailer, 'retailer_domain': domain, 'title': ppt.title(deal),
                      'kind': deal.get('kind'), 'kind_label': ppt.kind_words(deal), 'change': state,
                      'note': t[f'prove.{state}'].format(code=prev_code, retailer=retailer, date=day)})
    body['ended'] = ended
    if body.get('aside') and promo is not None and prev_promo is not None and prev_promo.get('n'):
        d = promo['k'] - prev_promo['k']
        body['aside']['delta'] = {'delta': _signed(d), 'dir': _dir(d), 'prev': prev_promo['k'], 'of_prev': prev_promo['n'],
                                  'detail': t['prove.delta'].format(k=promo['k'], n=promo['n'], b=prev_promo['k'],
                                                                   m=prev_promo['n'], code=prev_code)}
    return body


#: a True Value cell's verdict, as the drift compares it (a stale quote is its own)
def _verdict(cell: dict) -> Optional[str]:
    return cell.get('outcome') if cell.get('outcome') == 'stale' else cell.get('status')


def true_value_drift(now: dict, prev: dict, prev_code: str) -> List[dict]:
    """
    The cells that changed verdict since a compared previous cycle: one per
    product x column both cycles quoted, whose verdict (exact, wrong, stale,
    partial, unverifiable) differs, on the cycle's `surface`. Each {product,
    variant_id, column, was, now, was_quoted, now_quoted, was_live, now_live,
    dir, detail}; `dir` 'better' when it moved to exact, 'worse' when it moved
    from exact, else 'changed'.
    """
    t = MOVED_TEMPLATES
    names = {c['id']: c.get('name') or c['id'] for c in (now.get('columns') or []) + (prev.get('columns') or [])}
    then = {(r.get('variant_id') or r.get('product'), col): cell for r in prev.get('rows') or []
            for col, cell in (r.get('cells') or {}).items() if cell.get('runs')}
    out = []
    for row in now.get('rows') or []:
        for col, cell in (row.get('cells') or {}).items():
            was = then.get((row.get('variant_id') or row.get('product'), col))
            if not cell.get('runs') or was is None or _verdict(was) == _verdict(cell):
                continue
            a, b = _verdict(was), _verdict(cell)
            out.append({'product': row.get('product'), 'variant_id': row.get('variant_id'), 'column': col,
                        'column_name': names.get(col, col), 'was': a, 'now': b,
                        'was_quoted': was.get('quoted'), 'now_quoted': cell.get('quoted'),
                        'was_live': was.get('live'), 'now_live': cell.get('live'),
                        'dir': 'better' if b == 'exact' else 'worse' if a == 'exact' else 'changed',
                        'detail': t['tv.drift'].format(product=row.get('product'), column=names.get(col, col),
                                                      was=a, now=b, code=prev_code)})
    return out


def visibility_movement(vis: dict, prev_vis: dict, prev_code: str) -> Dict[str, dict]:
    """
    Visibility against a compared previous cycle, per surface: each brand's
    first picks on the brand-choice answers (the ranking's set) now and then,
    with the delta; the routing table's coverage and each retailer's first
    named; the retired lines' counts. {surface: {brands, coverage, routing,
    retired}}; a block this cycle did not measure is absent.
    """
    t = MOVED_TEMPLATES
    ranking, before = vis.get('ranking') or {}, prev_vis.get('ranking') or {}
    use = 'brand_choice' if ranking.get('default_tier') == VIS_BRAND_CHOICE and ranking.get('brand_choice') else None
    rows_now = ((ranking.get(use) or {}) if use else ranking).get('rows') or []
    rows_then = ((before.get(use) or {}) if use else before).get('rows') or []
    out = {}
    for s in [x for x in (vis.get('surfaces') or [{'surface': surfaces.ALL}])]:
        s = s['surface'] if isinstance(s, dict) else s
        then = {r['name']: ((r.get('surfaces') or {}).get(s) or {}) for r in rows_then}
        n = ((ranking.get(use) or {}) if use else ranking).get('denoms', {}).get(s)
        brands = []
        for r in rows_now:
            here = (r.get('surfaces') or {}).get(s) or {}
            if not here and s != surfaces.ALL:
                continue
            first = here.get('first', r.get('first') if s == surfaces.ALL else 0) or 0
            was = (then.get(r['name']) or {}).get('first')
            if was is None and r['name'] not in then:
                was = 0
            d = first - (was or 0)
            brands.append({'name': r['name'], 'you': bool(r.get('you')), 'first': first, 'prev_first': was,
                           'delta': _signed(d), 'dir': _dir(d),
                           'detail': t['vis.first'].format(name=r['name'], now=first, n=n or 'the', then=was,
                                                          code=prev_code)})
        block = {'brands': sorted(brands, key=lambda b: (b['dir'] == 'flat', -abs(int(b['delta'])), b['name']))}
        cov_now, cov_then = _coverage_counts(vis, s), _coverage_counts(prev_vis, s)
        if cov_now and cov_then:
            d = cov_now[0] - cov_then[0]
            block['coverage'] = {'now': cov_now[0], 'of_now': cov_now[1], 'prev': cov_then[0], 'of_prev': cov_then[1],
                                 'delta': _signed(d), 'dir': _dir(d)}
            first_then = {r.get('name'): (r.get('surfaces') or {}).get(s, 0)
                          for r in ((prev_vis.get('routing') or {}).get('rows') or [])}
            block['routing'] = [{'name': r.get('name'), 'domain': r.get('domain'),
                                 'first': (r.get('surfaces') or {}).get(s, 0),
                                 'prev_first': first_then.get(r.get('name'), 0),
                                 'delta': _signed((r.get('surfaces') or {}).get(s, 0) - first_then.get(r.get('name'), 0))}
                                for r in (vis.get('routing') or {}).get('rows') or []]
        ret_now, ret_then = _retired_counts(vis, s), _retired_counts(prev_vis, s)
        if ret_now and ret_then:
            d = ret_now[0] - ret_then[0]
            block['retired'] = {'now': ret_now[0], 'of_now': ret_now[1], 'prev': ret_then[0], 'of_prev': ret_then[1],
                                'delta': _signed(d), 'dir': _dir(d)}
        out[s] = block
    return out


def since_baseline(now_rows: List[dict], base_rows: List[dict], base_code: str) -> List[dict]:
    """Impact's "What moved since the baseline": each baseline measure both
    cycles took, {key, label, then, now, delta, dir, detail}, k of n each."""
    t = MOVED_TEMPLATES
    then = {r['key']: r for r in base_rows or []}
    out = []
    for r in now_rows or []:
        b = then.get(r['key'])
        if b is None or r.get('k') is None or b.get('k') is None:
            continue
        d = r['k'] - b['k']
        out.append({'key': r['key'], 'label': r['label'], 'then': b['value'], 'now': r['value'],
                    'delta': _signed(d), 'dir': _dir(d),
                    'detail': t['baseline.moved'].format(label=r['label'], then=b['value'], now=r['value'], code=base_code)})
    return out
