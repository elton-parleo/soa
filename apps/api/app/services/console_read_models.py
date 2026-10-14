"""
2B §6: soa's results in the console's shapes.

The console (parleohq/truesync console-demo apps/console/src/data/types.ts
and studio.ts) is the product UI from 2C-0 on. These builders turn soa's
stored rows into its types, with every mapping written down here and in
docs/console-read-models.md. Where a console type cannot hold what soa
knows, the payload carries the extra field BESIDE the typed one rather than
bending it, and says so in `divergences` — the same rule supply's Command
Center payloads follow.

Pure functions over rows (the loaders at the bottom do the SQL), so each
mapping is tested without a database.
"""
import json
from collections import Counter
from typing import Dict, Iterable, List, Optional

from sqlalchemy import text

from soa_shared import surfaces

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
}
VERDICT_TONE = {
    'right': 'ok', 'wrong': 'bad', 'missed': 'warn', 'partial': 'warn',
    'stale': 'warn', 'unverifiable': 'neu', 'unscoreable': 'neu',
}
BRAND_TONE = {
    'grounded': 'ok', 'echoed': 'neu', 'misattributed': 'bad', 'fabricated': 'bad',
    'acknowledged_unknown': 'warn', 'absent': 'warn', 'unscoreable': 'neu',
}
#: Segment.mark per claim outcome. The console labels `miss` "left out";
#: soa uses it for a claim that landed near the reference but not on it.
MARK = {'exact': 'ok', 'wrong': 'wrong', 'partial': 'miss', 'stale': 'miss'}
#: TvCell.status, extended by `unverifiable`. A stale quote is wrong today;
#: the raw outcome rides beside it in `outcome`.
TV_STATUS = {'exact': 'exact', 'wrong': 'wrong', 'partial': 'partial', 'absent': 'missed',
             'stale': 'wrong', 'unverifiable': 'unverifiable', 'unscoreable': 'none'}
#: StudyCell.s per outcome (value and brand vocabularies).
CELL_TONE = {
    'exact': 'ok', 'grounded': 'ok', 'wrong': 'bad', 'fabricated': 'bad', 'misattributed': 'bad',
    'partial': 'warn', 'stale': 'warn', 'echoed': 'warn', 'acknowledged_unknown': 'warn',
    'absent': 'neu', 'unverifiable': 'neu', 'unscoreable': 'neu',
}
#: Worst first, for picking one outcome to stand for several runs.
SEVERITY = ['wrong', 'fabricated', 'misattributed', 'stale', 'partial', 'acknowledged_unknown',
            'absent', 'echoed', 'unverifiable', 'unscoreable', 'exact', 'grounded']
TIER_LABELS = {'brand_direct': 'Brand-direct', 'catalog_accuracy': 'Catalog accuracy',
               'value_incentives': 'Value & incentives', 'category_control': 'Category control'}

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

def _severity(outcome, brand: bool, flags) -> str:
    if flags and any(f.get('flag') in ('fabricated_citation', 'fabricated_availability') for f in flags):
        return 'high'
    if brand:
        return {'fabricated': 'high', 'misattributed': 'high', 'grounded': 'ok', 'echoed': 'low',
                'acknowledged_unknown': 'medium', 'absent': 'low'}.get(outcome, 'low')
    return {'wrong': 'high', 'partial': 'medium', 'stale': 'medium', 'unverifiable': 'low',
            'absent': 'low', 'exact': 'ok', 'unscoreable': 'low'}.get(outcome, 'low')


#: 2C: the classifier's reason codes (scoring/expectation_comparator.py
#: REASON_*), carried in Check.reason and Answer.reason. A code soa adds
#: later passes through verbatim; the console renders an unknown one neutral.
REASON_CODES = ('other_brand', 'not_our_product', 'variant_clash', 'product_inferred', 'variant_swap')


def _reason_code(value) -> Optional[str]:
    return value if isinstance(value, str) and value else None


def _claim_text(claim) -> str:
    stated = claim.get('stated')
    product = claim.get('product')
    return f"{money(stated)} for {product}" if product else money(stated)


def _live(claim, expectation) -> str:
    reference = claim.get('reference') or {}
    against = reference.get('against') if reference else claim.get('against')
    if against is None and claim.get('target') == 'asked' and not reference:
        against = expectation.get('amount')
    if reference and not reference.get('verifiable', True):
        return f"unverifiable: {reference.get('unverifiable_reason') or 'page unreadable'}"
    where = f" at {reference.get('retailer_domain')}" if reference.get('retailer_domain') else ''
    return f"{money(against, expectation.get('currency'))}{where}"


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


def build_answer(run: dict, query: dict, outcome: Optional[dict], mentions: List[dict],
                 *, runs_per_query: Optional[int], cycle_code: str) -> dict:
    platform = run['platform']
    agent = surfaces.agent_of(platform) or platform
    extraction = _json((outcome or {}).get('extraction')) or {}
    expectation = _json((outcome or {}).get('expected_answer')) or {}
    claims = _json((outcome or {}).get('claim_results')) or []
    flags = _json((outcome or {}).get('flags')) or []
    tier = query.get('tier')
    brand = tier == 'brand_direct'
    raw = (outcome or {}).get('outcome')

    verdict = None if brand or raw is None else VALUE_VERDICT.get(raw, raw)
    brand_verdict = raw if brand else None
    checks = []
    if not brand and outcome is not None:
        for claim in claims:
            mapped = VALUE_VERDICT.get(claim.get('outcome'), claim.get('outcome'))
            # 2C: the rule that decided the claim is `reason` (a code from
            # REASON_CODES); `note` keeps the prose.
            checks.append(compact({'claim': _claim_text(claim), 'agent': AGENT_NAMES.get(agent, agent),
                                   'live': _live(claim, expectation), 'verdict': mapped,
                                   'note': claim.get('reason') or claim.get('conflict'),
                                   'reason': _reason_code(claim.get('reason_code')),
                                   'tone': VERDICT_TONE.get(mapped, 'neu')}, ('note', 'reason')))
        if not claims:
            checks.append(compact({'claim': '—', 'agent': AGENT_NAMES.get(agent, agent),
                                   'live': money(expectation.get('amount'), expectation.get('currency'))
                                   if expectation.get('amount') else '—',
                                   'verdict': verdict, 'note': outcome.get('outcome_reason'),
                                   'reason': _reason_code(outcome.get('reason_code')),
                                   'tone': VERDICT_TONE.get(verdict, 'neu')}, ('note', 'reason')))

    # 2C: which True Value cell this answer is judged in (variant x retailer),
    # so the console's drawer can show the reference price behind the verdict.
    source_ref = _json(query.get('source_ref')) or {}
    named = [m['name'] for m in sorted(mentions, key=lambda m: m.get('position') or 99)]
    first = next((m['name'] for m in mentions if m.get('position') == 1), '')
    return compact({
        'id': f"run-{run['id']}",
        'agent': agent,
        'query': query.get('query_text'),
        'queryType': TIER_LABELS.get(tier) or query.get('stage') or '',
        'runAt': _iso(run.get('run_at')),
        'runs': f"run {run.get('run_number')} of {runs_per_query}" if runs_per_query else None,
        'severity': _severity(raw, brand, flags),
        'summary': (outcome or {}).get('outcome_reason') or (
            f"No answer ({run.get('answer_status')})" if run.get('answer_status') not in (None, 'answered')
            else 'Not scored'),
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
        'reason': _reason_code((outcome or {}).get('reason_code')),
        'verdict': verdict,
        'tone': BRAND_TONE.get(raw, 'neu') if brand else VERDICT_TONE.get(verdict, 'neu'),
        'brand_verdict': brand_verdict,
        'flags': [f.get('flag') for f in flags],
        'flag_details': flags,
        'variant_id': source_ref.get('variant_id'),
        'gtin': source_ref.get('gtin'),
        'retailer': expectation.get('attributed_to') or source_ref.get('own_domain') or source_ref.get('domain'),
    }, ('runs', 'reason', 'variant_id', 'gtin', 'retailer'))


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
        if r.get('answer_status') in (None, 'answered'):
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

    Never pooled across surfaces: there is no all-surfaces total, by tier or
    overall, by design (soa_shared/surface_accuracy.py). `surfaces` is per
    surface across the value tiers; brand-direct, whose outcomes are not a
    price verdict, is only in `tiers`.

    rows: [{tier, surface, platform, answer_status, outcome, reason_code, flags}]
    """
    by_tier: Dict[str, List[dict]] = {}
    for r in rows:
        by_tier.setdefault(r.get('tier') or 'untiered', []).append(r)
    tier_order = [t for t in TIER_LABELS if t in by_tier] + sorted(t for t in by_tier if t not in TIER_LABELS)

    def per_surface(subset: List[dict]) -> List[dict]:
        grouped: Dict[str, List[dict]] = {}
        for r in subset:
            grouped.setdefault(_surface_key(r), []).append(r)
        return [{'surface': k, 'label': surfaces.SURFACE_LABELS.get(k, k), **_summary_cell(grouped[k])}
                for k in _ordered_surfaces(grouped)]

    value_rows = [r for r in rows if r.get('tier') != 'brand_direct']
    return {
        'cycle': cycle_code,
        'surfaces': per_surface(value_rows),
        'tiers': [{'tier': t, 'label': TIER_LABELS.get(t, t), 'surfaces': per_surface(by_tier[t])}
                  for t in tier_order],
    }


def load_answers_summary(conn, cycle: dict) -> dict:
    rows = [dict(r) for r in conn.execute(text("""
        SELECT r.id AS run_id, r.platform, COALESCE(o.surface, r.surface) AS surface,
               r.answer_status, q.tier, o.outcome, o.reason_code, o.flags
        FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
        LEFT JOIN soa_expectation_outcomes o ON o.run_id = r.id
        WHERE r.cycle_id = :c
    """), {'c': cycle['id']}).mappings()]
    return build_answers_summary(rows, cycle_code=cycle['cycle_code'])


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


def build_true_value(reference: Optional[dict], scored: List[dict], *, own_domain: Optional[str],
                     record_variants: List[dict]) -> dict:
    """
    TrueValue: columns = retailers from the record; rows = variants;
    cells = TvCell {quoted, live, status}.

    `live` is the 2A reference (supply's retailer-prices row cached on the
    cycle); `quoted` and `status` are this cycle's scored answers for that
    variant at that page. With no reference cached (a cycle scored against
    the record), `live` is the record's price on the own-domain column.

    scored: [{variant_id, gtin, retailer, outcome, stated}], one per scored
    run of a price question.
    """
    rows_by_key: Dict[str, dict] = {}
    columns: List[str] = []
    live: Dict[tuple, dict] = {}

    for row in (reference or {}).get('prices') or []:
        domain = row.get('retailer_domain')
        key = _gtin14(row.get('gtin')) or row.get('variant_ref')
        if domain and domain not in columns:
            columns.append(domain)
        rows_by_key.setdefault(key, {'product': row.get('variant_label') or key, 'sku': row.get('gtin') or key})
        live[(key, domain)] = row

    if not reference:
        if own_domain:
            columns.append(own_domain)
        for v in record_variants:
            key = v['variant_id']
            rows_by_key.setdefault(key, {'product': v.get('label') or key, 'sku': v.get('gtin') or key})
            live[(key, own_domain)] = {'price': v.get('list_price'), 'verifiable': True,
                                       'currency': v.get('currency'), 'reference_source': 'record',
                                       'observed_at': v.get('published_at')}

    grouped: Dict[tuple, List[dict]] = {}
    for item in scored:
        key = _gtin14(item.get('gtin')) or item.get('variant_id')
        if key not in rows_by_key:
            continue
        domain = item.get('retailer') or own_domain
        grouped.setdefault((key, domain), []).append(item)

    rows = []
    for key, meta in rows_by_key.items():
        cells = {}
        for domain in columns:
            ref = live.get((key, domain))
            runs = grouped.get((key, domain), [])
            # The scored outcomes decide; an absent (no price, or a wall)
            # decides only when no run was scored. Ties go to the worse.
            outcome = worst(r['outcome'] for r in runs
                            if r['outcome'] not in ('absent', 'unscoreable')) or \
                worst(r['outcome'] for r in runs)
            if ref is None:
                live_text = '—'
            elif not ref.get('verifiable', True):
                live_text = 'unverifiable'
            else:
                live_text = money(ref.get('price'), ref.get('currency') or 'USD')
            # The quote shown is one from the runs the status reports, so a
            # cell never reads "$12.99 ... wrong" when $12.99 was right.
            quoted = Counter(str(r['stated']) for r in runs
                             if r.get('stated') and r['outcome'] == outcome) or \
                Counter(str(r['stated']) for r in runs if r.get('stated'))
            cells[domain] = {
                'quoted': money(quoted.most_common(1)[0][0]) if quoted else '—',
                'live': live_text,
                'status': ('unverifiable' if ref is not None and not ref.get('verifiable', True) and runs
                           else TV_STATUS.get(outcome, 'none') if outcome else 'none'),
                # beside the typed fields
                'outcome': outcome,
                'runs': len(runs),
                # 2C: where `live` came from, so "honest fetch" and "hosted render"
                # are told apart; 'record' when no reference was cached.
                'reference_source': (None if ref is None else
                                     ref.get('reference_source') or ('record' if not reference else None)),
                'method': None if ref is None else ref.get('method'),
                'observed_at': None if ref is None else ref.get('observed_at'),
            }
        rows.append({'product': meta['product'], 'sku': meta['sku'], 'cells': cells})

    return {
        'columns': [{'id': d, 'name': _retailer_name(d), 'you': d == own_domain} for d in columns],
        'rows': rows,
        'programs': [],
        'as_of': (reference or {}).get('as_of'),
        'divergences': [
            "TvCell.status is extended by 'unverifiable' (the page blocked both reference sources).",
            "A stale quote has status 'wrong' (it is wrong today); `outcome` carries 'stale'.",
            "`programs` is empty: soa scores no program terms per retailer here.",
            "Each cell carries reference_source (honest_fetch | hosted_render | record), method and "
            "observed_at beside the typed fields (2C).",
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


def _program_matches(inc: dict, expected: dict) -> bool:
    if inc.get('code') and expected.get('code'):
        return str(expected['code']).upper() == str(inc['code']).upper()
    if inc.get('tier_name') and expected.get('tier_name'):
        return expected['tier_name'] == inc['tier_name']
    return False


def build_programs(incentives: List[dict], value_outcomes: List[dict]) -> List[dict]:
    """
    TrueValue.programs from the merchant's owned incentives (supply's
    /incentives/owned, as entered). `agentsRight` counts this cycle's
    value & incentives answers about that program: right / scored, where
    scored excludes absent, unscoreable and unverifiable. A program no
    question asked about says so rather than showing 0.

    value_outcomes: [{outcome, expected_answer}] for tier value_incentives.
    """
    out = []
    for inc in incentives or []:
        about = [o for o in value_outcomes if _program_matches(inc, _json(o.get('expected_answer')) or {})]
        scored = [o for o in about if o.get('outcome') in SUMMARY_SCORED]
        right = sum(1 for o in scored if o.get('outcome') == 'exact')
        if not about:
            agents_right, tone = 'not asked this cycle', 'neu'
        elif not scored:
            agents_right, tone = f"{len(about)} asked, none scored", 'neu'
        else:
            agents_right = f"{right} of {len(scored)} right"
            tone = 'ok' if right == len(scored) else 'bad' if right == 0 else 'warn'
        out.append({
            'name': inc.get('name') or inc.get('tier_name') or inc.get('code') or (inc.get('mechanic') or 'Program'),
            'terms': _program_terms(inc), 'agentsRight': agents_right, 'tone': tone,
            # beside the typed fields
            'mechanic': inc.get('mechanic'), 'code': inc.get('code'), 'tier_name': inc.get('tier_name'),
            'valid_until': inc.get('valid_until'), 'asked': len(about), 'scored': len(scored), 'right': right,
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
                text_ += f"; multipack {multiples[0]} would explain it"
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
                rows.append({'gtin': v.get('gtin'), 'variant_id': v.get('variant_id'),
                             'product_name': listing.get('title'), 'brand_name': listing.get('brand'),
                             'variant_label': v.get('title'), 'size': v.get('size'), 'pack_count': v.get('count'),
                             'multipack': None, 'price': v.get('list_price'), 'currency': v.get('currency'),
                             'published_at': _iso(listing.get('published_at')), 'product_url': listing.get('product_url')})
        return {'merchant': merchant, 'source': 'hosted', 'read_only': True,
                'note': 'Hosted on Parleo: this catalog comes from the store config. Edit it there; no feed upload applies.',
                'version': None, 'rows': rows, 'versions': []}
    if feed is None:
        return {'merchant': merchant, 'source': 'none', 'read_only': False,
                'note': 'No feed committed yet. Download the template, fill it in and upload it here.',
                'version': None, 'rows': [], 'versions': history or []}
    return {'merchant': merchant, 'source': 'feed', 'read_only': False, 'note': None,
            'version': feed.get('version'), 'rows': feed.get('rows') or [], 'versions': history or []}


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
    pubs: Dict[tuple, dict] = {}
    for pub in publications or []:
        if pub.get('listing_id') not in listing_ids:
            continue
        key = (pub['listing_id'], pub.get('channel_slug'))
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
                    ('; '.join((pub.get('validation') or {}).get('errors') or []) or None)
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
    divergences = [d for d in payload.get('divergences') or [] if "no 'claude'" not in d]
    divergences.append("AccessRow.vendor can be 'claude' (vendor 'claude', agent 'claude'); "
                       "the console adds it to AgentId in 2C-0.")
    return {**access, 'merchant': payload.get('merchant'), 'access_run': payload.get('access_run'),
            'divergences': divergences}


# ─── Studies ───────────────────────────────────────────────────────────────

_SURFACE_RANK = {'consumer_ui': 3, 'grounded_api': 2, 'api': 1}


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


def build_prompt(row: dict, brand: Optional[str]) -> dict:
    from soa_shared import expected_answers as ea
    return compact({
        'id': row['query_code'], 'text': row['query_text'],
        'stage': STAGE_TO_STUDIO.get(row.get('stage'), row.get('stage')),
        'branded': bool(brand) and ea.names_brand(row['query_text'], brand),
        'persona': row.get('persona'),
        # soa's provenance vocabulary, which is not the console's source
        'source': {'catalog': 'csv', 'ai_from_catalog': 'ai', 'ai': 'ai'}.get(row.get('provenance'), 'ai'),
        'provenance': row.get('provenance'), 'tier': row.get('tier'),
    }, ('persona',))


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
        'status': {'complete': 'done', 'failed': 'paused', 'pending': 'draft',
                   'running': 'draft'}.get(job.get('status'), 'draft'),
        'created': _iso(job.get('created_at')) or '', 'lastRun': _iso(latest.get('start_date')),
        'owner': job.get('created_by') or '',
        # beside the typed fields
        'platforms': platforms, 'generation_status': job.get('status'),
    }, ('lastRun',))


def build_run(cycle: dict, collected: int, usable: int) -> dict:
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
    }, ('finished', 'note'))


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

def load_answers(conn, cycle: dict) -> List[dict]:
    runs = conn.execute(text("""
        SELECT r.*, q.query_code, q.query_text, q.tier, q.stage, q.source_ref
        FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id
        WHERE r.cycle_id = :c ORDER BY q.query_code, r.platform, r.run_number
    """), {'c': cycle['id']}).mappings().all()
    outcomes = {o['run_id']: dict(o) for o in conn.execute(text(
        "SELECT * FROM soa_expectation_outcomes WHERE cycle_id = :c"), {'c': cycle['id']}).mappings()}
    mentions: Dict[int, List[dict]] = {}
    for m in conn.execute(text("""
        SELECT cm.run_id, e.name, cm.position FROM soa_coded_mentions cm
        JOIN soa_entities e ON e.id = cm.entity_id
        JOIN soa_runs r ON r.id = cm.run_id
        WHERE r.cycle_id = :c AND cm.mentioned = :yes
    """), {'c': cycle['id'], 'yes': True}).mappings():
        mentions.setdefault(m['run_id'], []).append(dict(m))
    return [build_answer(dict(r), dict(r), outcomes.get(r['id']), mentions.get(r['id'], []),
                         runs_per_query=cycle.get('runs_per_query'), cycle_code=cycle['cycle_code'])
            for r in runs]
