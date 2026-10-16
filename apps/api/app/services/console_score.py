"""
2C-3: the Share of Algorithm score on the console, from loop data.

One score: the Audit's formula at a loop's coverage. Weights, seen/said
splits, dimension_max and the readiness bar come from soa_shared/
scan_dimensions.py; each dimension's points come from the Audit's own
scoring functions (lite_pillars.py, cycle_scoring_full.py), called, never
changed. This module only adapts loop counts into those functions' inputs
(docs/console-read-models.md, "2C-3", the mapping table) and adds the
measured dimensions up.

Why the Audit's assembly (build_full_cycle_pillars) is not called whole:
its three said scorers read one shared run_signals list, so the catalog
tier's signals would land in Member Value's denominator and the other way
round, and its compute_composite only shrinks the basis for Member Value,
so an unmeasured Protocol & Feed or Value Protocols would count as zero.
The console sums the scorer's own dimension results over the measured
dimensions instead.

Pooled across surfaces by pooling scores, never counts: each surface is
scored on its own, the pooled score is the equal-weight mean of the
surface scores, rounded once. Pure functions here; the loaders and the
stored score are at the bottom. No model is called.
"""
import json
import logging
from contextvars import ContextVar
from statistics import mean
from typing import Dict, Iterable, List, Optional

from sqlalchemy import text

from soa_shared import surfaces
from soa_shared.scan_dimensions import (
    DIMENSIONS,
    DIMENSIONS_BY_CODE,
    FULL_CYCLE_SCORER_VERSION,
    PILLAR_NAMES,
    PILLAR_ORDER,
    PILLAR_WEIGHTS,
    PURCHASE_INTENT_STAGES,
    TOTAL_MAX,
    VERDICT_COMPOSITE_THRESHOLD,
    compute_verdict,
    dimension_max,
)

from app.services import console_parity as parity
from app.services import console_read_models as rm
from app.services.cycle_scoring_full import (
    score_deal_citability_said_full,
    score_recommendation_strength_full,
    score_share_of_mentions_full,
)
from app.services.lite_crosswalk import RunSignal
from app.services.lite_pillars import (
    _protocol_feed_checks,
    _value_protocols_checks,
    member_value_applicable,
    score_member_value_said,
    score_price_truth_said,
)
from clients import truesync_client as supply_fields

#: The scorer whose formula this is (reused, not forked). A re-weight bumps
#: it and every stored console score reads stale.
SCORER_VERSION = FULL_CYCLE_SCORER_VERSION
#: The adapter's own revision, beside the scorer's: a change to how loop
#: counts become scorer inputs re-scores stored cycles too. Not a scorer
#: version and never shown as one.
ADAPTER_REVISION = 2

READINESS_BAR = VERDICT_COMPOSITE_THRESHOLD

MEASURED, NOT_MEASURED, NA, PARTIAL = 'measured', 'not_measured', 'na', 'partial'

#: Layer 1 strength weights, as MetricsCalculator sums rsi_score_sum.
STRENGTH_WEIGHTS = {'Primary': 3, 'Positive': 1, 'Neutral': 0, 'Negative': -1}

#: The value tier's expectation types, by the dimension whose said half reads them.
MEMBER_TYPES = ('member_price',)
DEAL_TYPES = ('code', 'points')

#: The stage a value-tier signal is placed in, so the scorer's own
#: purchase-intent filter keeps it (the value tier is the purchase question).
_VALUE_STAGE = PURCHASE_INTENT_STAGES[-1]

#: Agent identities in supply's access run that are not an answer-time agent.
_CONTROL_IDENTITY = 'control'

#: 2E: the two dimensions scored on the worker by the Audit's own functions
#: (scan/scorer.py, through apps/pipeline/scoring/domain_checks.py) and read
#: here from the cycle's stored record, with the Audit's sub-check builders
#: (lite_pillars), the ones the Audit's report reads its chips with.
DOMAIN_CODES = ('protocol_feed', 'value_protocols')
_DOMAIN_CHECKS = {'protocol_feed': _protocol_feed_checks, 'value_protocols': _value_protocols_checks}
#: How many earlier stored values a score keeps in its history.
HISTORY_KEEP = 10

#: House rules as console_parity.TEMPLATES: no dashes, no semicolons.
TEMPLATES = {
    'part.share_of_mentions': 'Share of mentions {n} of {d} brand mentions',
    'part.recommendation_strength': 'Coded as the pick in {n} of {d} mentions',
    'part.agent_access': 'Agent identities through {n} of {d}',
    'part.catalog_context': 'Product markup with a GTIN {n} of {d} pages',
    'part.price_truth.seen': 'Price in markup {n} of {d} pages',
    'part.price_truth.said': 'Prices quoted exactly {n} of {d} scored',
    'part.member_value.seen': 'Member price in markup {n} of {d} pages',
    'part.member_value.said': 'Member prices right {n} of {d} scored',
    'part.deal_citability.seen': 'Incentive in markup {n} of {d} pages',
    'part.deal_citability.said': 'Codes and points right {n} of {d} scored',
    'part.protocol_feed': 'Protocol checks passed {n} of {d}',
    'part.value_protocols.seen': 'Manifest checks passed {n} of {d}',
    'check.flag': '{flag} {n} of {d} pages',
    'gap.on_surface': '{line} on {surface}',
    'reason.no_unprompted': 'no unprompted question answered on this surface',
    'reason.no_access': 'no agent identity measured in the access run',
    'reason.no_pages': 'no page read in the reference run',
    'reason.read_failed': 'the {read} read failed: {error}',
    'reason.no_merchant': 'no merchant record for this cycle',
    'reason.protocol_feed': 'no domain checks on this cycle yet',
    'reason.value_protocols': 'no domain checks on this cycle yet',
    'reason.domain_blocked': 'the domain checks could not read {domain}',
    'reason.deal_seen': 'supply serves no incentive in markup on its page reads (a supply before #21)',
    'reason.deal_unscanned': "no page read has had its markup scanned for incentives yet (supply's backfill fills reads stored before 2A-3)",
    'reason.deal_whole': 'its markup half is not measured, so the dimension is out of the applicable max',
    'reason.no_program': 'the record states no member program and no page shows a member price',
    'reason.no_answers': 'no answer on this surface',
    'previous.first_cycle': 'First cycle. Changes appear from the next one.',
    'previous.not_stored': 'Not comparable: {code} has no stored score yet. Open it to score it.',
    'previous.version': 'Scored under v{version}, re-score to compare.',
    'previous.surfaces': 'Not comparable: {code} scored {prev}, this cycle scored {now}.',
    'previous.agents': 'Not comparable: on {surface} {code} ran {prev}, this cycle ran {now}.',
    'previous.applicable': 'applicable points changed from {prev} to {now}',
    'verdict.withheld': 'No readiness verdict while {n} of {total} points are not measured. The Audit gives one only when every dimension is.',
    'coverage': '{surfaces}, {questions}, {agents} · pooled across surfaces, equal weight',
    'coverage.no_answers': ' · {surface} ran, no answers',
    'unavailable': 'Score unavailable: {step} failed ({error})',
}


log = logging.getLogger(__name__)

#: 2C-3a: the step the computation is on, so a failure names it (the router
#: logs it and returns it in the 422). Per request: a ContextVar.
_STEP: ContextVar[str] = ContextVar('score_step', default='start')


def at(step: str) -> None:
    _STEP.set(step)


def current_step() -> str:
    return _STEP.get()


def log_event(event: str, **fields) -> None:
    """One structured line: a JSON object, so Vercel's log view and a grep
    both read it. Counts and identifiers only, never row data."""
    log.info(json.dumps({'event': event, **fields}, default=str))


def unavailable(error: BaseException) -> str:
    """The 422's one line, which the console's tile shows as is."""
    return TEMPLATES['unavailable'].format(step=current_step(), error=type(error).__name__)


def _n(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def _surface_words(s: str) -> str:
    return parity._surface_label(s)


def _ratio_part(code: str, half: Optional[str], n: int, d: int, max_: float, source: str,
                reason: Optional[str] = None) -> dict:
    """A crawl-side half: n of d pages (or identities) as the scorer's
    crawl_dimensions entry, {score, max, coverage}, the score rounded to one
    place as scan/scorer.py rounds its crawl scores. d == 0 is not measured."""
    key = f"part.{code}.{half}" if half else f"part.{code}"
    if not d:
        return {'half': half, 'score': None, 'max': max_, 'state': NOT_MEASURED, 'numerator': None,
                'denominator': None, 'source': source, 'reason': reason, 'line': None}
    return {'half': half, 'score': round(n / d * max_, 1), 'max': max_, 'state': MEASURED, 'numerator': n,
            'denominator': d, 'source': source, 'reason': None, 'line': TEMPLATES[key].format(n=n, d=d)}


def _unsourced_part(half: Optional[str], max_: float, reason_key: str) -> dict:
    return {'half': half, 'score': None, 'max': max_, 'state': NOT_MEASURED, 'numerator': None,
            'denominator': None, 'source': None, 'reason': TEMPLATES[reason_key], 'line': None}


def _said_part(code: str, result: dict, source: str) -> dict:
    """A said half from the scorer's own result. The scorer's na (fewer than
    MIN_OPPORTUNITY_SET_MENTIONS in the set) stays na: the dimension then
    rescales onto its seen half, as dimension_max does in the Audit."""
    na = bool(result.get('na'))
    n, d = result.get('cited'), result.get('total')
    return {'half': 'said', 'score': None if na else float(result['earned']), 'max': float(result['max']),
            'state': NA if na else MEASURED, 'numerator': n, 'denominator': d, 'source': source,
            'reason': (result.get('evidence') or [None])[0] if na else None,
            'line': None if na else TEMPLATES[f"part.{code}.said"].format(n=n, d=d)}


# ─── loop counts → scorer inputs ───────────────────────────────────────────

def crawl_counts(access: Optional[dict], reference_rows: Optional[List[dict]]) -> dict:
    """The surface-independent counts: the access run's measured identities,
    and the reference read's pages by the predicates Accessibility's merchant
    checks count (console_parity.build_access_checks), so the two screens
    agree on every page count."""
    requests = [r for r in ((access or {}).get('requests') or [])
                if r.get('agent') and _CONTROL_IDENTITY not in str(r.get('identity') or '').lower()]
    measured = [r for r in requests if parity._measured(r)]
    rows = reference_rows or []
    pages = [r for r in rows if r.get('read_status') in ('ok', 'empty')]

    def gtin_ok(r):
        return r.get('gtin') and not any(f.get('finding') in ('no_structured_data', 'gtin_missing_on_page')
                                         for f in r.get('findings') or [])

    # 2E: Deal Citability's seen half, supply #21's incentive_in_markup. A
    # read stored before 2A-3 (json_ld_scanned false) was not scanned: out of
    # the count both ways, never a false
    scanned = [m for m in (supply_fields.incentive_in_markup(r) for r in pages) if m and m['json_ld_scanned']]
    return {
        'identities': len(measured), 'through': sum(1 for r in measured if r.get('ok')),
        'pages': len(pages),
        'catalog': sum(1 for r in pages if r.get('method') == 'json_ld' and gtin_ok(r)),
        'price': sum(1 for r in pages if r.get('price') not in (None, '')),
        'member_price': sum(1 for r in pages if r.get('member_price') not in (None, '')),
        'incentive_fields': supply_fields.carries_incentive_fields(rows),
        'incentive_scanned': len(scanned),
        'incentive_any': sum(1 for m in scanned if any(m[f] for f in supply_fields.INCENTIVE_FLAGS)),
        'incentive_flags': {f: sum(1 for m in scanned if m[f]) for f in supply_fields.INCENTIVE_FLAGS},
    }


def domain_part(code: str, record: Optional[dict]) -> dict:
    """Protocol & Feed Presence or Value Protocols from the cycle's stored
    domain checks: the Audit's own score for the scored domain, its coverage
    (the Audit's 'na' on a brand-only site stays na, its 'blocked' is not
    measured), and the Audit's sub-checks by name. No record: not measured."""
    weight = float(DIMENSIONS_BY_CODE[code].weight)
    half = 'seen' if code == 'value_protocols' else None
    dim = (record or {}).get(code)
    if not isinstance(dim, dict) or (dim.get('score') is None and dim.get('coverage') != 'not_measured'):
        return _unsourced_part(half, weight, f'reason.{code}')
    domain = (record or {}).get('scored_domain')
    source = f"domain checks on {domain}, {str((record or {}).get('checked_at') or '')[:10]}".rstrip(', ')
    evidence = list(dim.get('evidence') or [])
    checks = _DOMAIN_CHECKS[code](evidence)
    base = {'half': half, 'max': weight, 'numerator': None, 'denominator': None, 'source': source,
            'checks': checks, 'evidence': evidence}
    if dim.get('coverage') == 'na':
        return {**base, 'score': None, 'state': NA, 'reason': evidence[0] if evidence else None, 'line': None}
    if dim.get('coverage') == 'not_measured':
        # 2E-1: the checks could not measure it (no product page to type the
        # site on), which is not the Audit's 'na'
        return {**base, 'score': None, 'state': NOT_MEASURED, 'line': None,
                'reason': evidence[0] if evidence else TEMPLATES[f'reason.{code}']}
    if dim.get('coverage') == 'blocked':
        return {**base, 'score': None, 'state': NOT_MEASURED, 'line': None,
                'reason': TEMPLATES['reason.domain_blocked'].format(domain=domain)}
    n = sum(1 for c in checks if c['state'] == 'pass')
    d = sum(1 for c in checks if c['state'] in ('pass', 'fail'))
    key = f"part.{code}.{half}" if half else f"part.{code}"
    return {**base, 'score': float(dim['score']), 'state': MEASURED, 'numerator': n, 'denominator': d, 'reason': None,
            'line': TEMPLATES[key].format(n=n, d=d) if d else (evidence[0] if evidence else None)}


def measured_from_record(record: Optional[dict]) -> List[str]:
    """The domain-check dimensions a record makes measured: what the score
    of record is recomputed on when it changes (with the scorer version)."""
    return [c for c in DOMAIN_CODES if domain_part(c, record)['state'] == MEASURED]


def deal_seen_part(crawl: dict, page_reason: str) -> dict:
    """Deal Citability, seen: reads whose page carries any incentive flag in
    markup over the pages read whose markup supply scanned."""
    seen_max = float(DIMENSIONS_BY_CODE['deal_citability'].seen_max)
    source = 'reference read: incentive_in_markup (supply), json_ld_scanned pages'
    if not crawl['pages']:
        return {**_unsourced_part('seen', seen_max, 'reason.deal_seen'), 'reason': page_reason, 'source': source}
    if not crawl['incentive_fields']:
        return {**_unsourced_part('seen', seen_max, 'reason.deal_seen'), 'source': source}
    if not crawl['incentive_scanned']:
        return {**_unsourced_part('seen', seen_max, 'reason.deal_unscanned'), 'source': source}
    part = _ratio_part('deal_citability', 'seen', crawl['incentive_any'], crawl['incentive_scanned'], seen_max, source)
    part['checks'] = [{'code': f, 'label': TEMPLATES['check.flag'].format(flag=f.replace('_', ' '), n=k, d=crawl['incentive_scanned']),
                       'state': 'pass' if k else 'fail'} for f, k in crawl['incentive_flags'].items()]
    return part


def visibility_inputs(runs: List[dict], mentions: List[dict], surface: str) -> dict:
    """The scorer's som_pct / rsi_score / total_mentions for one surface, over
    answered unprompted runs, counted as MetricsCalculator counts them: our
    mentions over every cycle entity's mentions, and the mean Layer 1 strength
    weight over our mentions."""
    unprompted = {r['run_id'] for r in runs if parity._surface_of(r) == surface and not r.get('tier')
                  and r.get('answer_status') == surfaces.ANSWERED}
    ours = [m for m in mentions if m['run_id'] in unprompted and m.get('mentioned') and m.get('role') == 'primary']
    every = [m for m in mentions if m['run_id'] in unprompted and m.get('mentioned') and m.get('role')]
    return {
        'runs': len(unprompted), 'ours': len(ours), 'all': len(every),
        'picks': sum(1 for m in ours if m.get('strength') == 'Primary'),
        'som_pct': (len(ours) / len(every) * 100) if every else None,
        'rsi_score': (sum(STRENGTH_WEIGHTS.get(m.get('strength'), 0) for m in ours) / len(ours)) if ours else None,
    }


def said_signals(runs: List[dict], surface: str, *, tier: str, types: Optional[Iterable[str]] = None) -> List[RunSignal]:
    """One signal per scored run of the tier on the surface (exact, partial,
    stale, wrong: unverifiable, absent and unscoreable are outside it), cited
    when exact. Every signal is a mention of ours that pass 2 coded, so the
    scorer's own denominator is the scored count."""
    out = []
    for r in runs:
        if parity._surface_of(r) != surface or r.get('tier') != tier or r.get('outcome') not in parity.SCORED:
            continue
        if types is not None and r.get('expected_type') not in types:
            continue
        exact = r['outcome'] == 'exact'
        out.append(RunSignal(
            stage=_VALUE_STAGE if tier == 'value_incentives' else (r.get('stage') or ''),
            primary_mentioned=True, pass2_coded=True,
            primary_price_quoted=exact, primary_member_price_claimed=exact, primary_deal_cited=exact))
    return out


# ─── one surface ───────────────────────────────────────────────────────────

def _domain_dim(code: str, record: Optional[dict]) -> dict:
    """A domain-check dimension's row: counted at the Audit's score when
    measured; its 'na' leaves the applicable max as Member Value's does."""
    part = domain_part(code, record)
    if part['state'] == MEASURED:
        return _dim(code, earned=part['score'], applicable=part['max'], state=MEASURED, parts=[part])
    return _dim(code, earned=None, applicable=0, state=part['state'], parts=[part], reason=part['reason'])


def _dim(code: str, *, earned: Optional[float], applicable: float, state: str, parts: List[dict],
         reason: Optional[str] = None) -> dict:
    d = DIMENSIONS_BY_CODE[code]
    return {'code': code, 'name': d.name, 'pillar': d.pillar, 'max': float(d.weight),
            'score': None if earned is None else round(earned, 1), 'applicable_max': float(applicable),
            'state': state, 'reason': reason, 'parts': parts}


def score_surface(surface: str, *, runs: List[dict], mentions: List[dict], crawl: dict,
                  crawl_errors: Optional[Dict[str, str]] = None, program_stated: bool,
                  domain_checks: Optional[dict] = None) -> dict:
    """Every dimension on one surface, from the scorer's functions, and the
    surface's score: round-free earned ÷ applicable max × 100."""
    errors = crawl_errors or {}
    dims = []

    # Visibility: the Audit's two functions over unprompted Layer 1 counts
    at(f'visibility on {surface}')
    vis = visibility_inputs(runs, mentions, surface)
    for code, fn, n, d, value in (
            ('share_of_mentions', score_share_of_mentions_full, vis['ours'], vis['all'], vis['som_pct']),
            ('recommendation_strength', score_recommendation_strength_full, vis['picks'], vis['ours'], vis['rsi_score'])):
        at(f'{code} on {surface}')
        source = 'soa_coded_mentions, answered unprompted runs'
        if not vis['runs']:
            part = _unsourced_part(None, float(DIMENSIONS_BY_CODE[code].weight), 'reason.no_unprompted')
            part['source'] = source
            dims.append(_dim(code, earned=None, applicable=0, state=NOT_MEASURED, parts=[part], reason=part['reason']))
            continue
        result = fn(value, vis['ours'], vis['runs'])
        part = {'half': None, 'score': float(result['earned']), 'max': float(result['max']), 'state': MEASURED,
                'numerator': n, 'denominator': d, 'source': source, 'reason': None,
                'value': None if value is None else round(value, 4),
                'line': TEMPLATES[f"part.{code}"].format(n=n, d=d)}
        dims.append(_dim(code, earned=result['earned'], applicable=result['max'], state=MEASURED, parts=[part]))

    # Accessibility: crawl-side, one value for every surface
    at(f'accessibility on {surface}')
    access_reason = (TEMPLATES['reason.read_failed'].format(read='access', error=errors['access'])
                     if 'access' in errors else TEMPLATES['reason.no_access'])
    page_reason = (TEMPLATES['reason.read_failed'].format(read='reference', error=errors['reference'])
                   if 'reference' in errors else TEMPLATES['reason.no_pages'])
    if 'merchant' in errors:
        access_reason = page_reason = TEMPLATES['reason.no_merchant']
    for code, n, d, source, reason in (
            ('agent_access', crawl['through'], crawl['identities'], 'access run: measured agent identities', access_reason),
            ('catalog_context', crawl['catalog'], crawl['pages'], 'reference read: json_ld with a GTIN', page_reason)):
        part = _ratio_part(code, None, n, d, float(DIMENSIONS_BY_CODE[code].weight), source, reason)
        measured = part['state'] == MEASURED
        dims.append(_dim(code, earned=part['score'] if measured else None, applicable=part['max'] if measured else 0,
                         state=part['state'], parts=[part], reason=None if measured else reason))
    dims.append(_domain_dim('protocol_feed', domain_checks))

    # True Value: seen from the reference read, said from the scorer's functions
    at(f'true value said halves on {surface}')
    said = {
        'price_truth': _said_part('price_truth', score_price_truth_said(
            said_signals(runs, surface, tier='catalog_accuracy')), 'catalog tier, exact of scored'),
        'member_value': _said_part('member_value', score_member_value_said(
            said_signals(runs, surface, tier='value_incentives', types=MEMBER_TYPES)), 'value tier, member price questions, exact of scored'),
        'deal_citability': _said_part('deal_citability', score_deal_citability_said_full(
            said_signals(runs, surface, tier='value_incentives', types=DEAL_TYPES)), 'value tier, code and points questions, exact of scored'),
    }
    seen = {
        'price_truth': _ratio_part('price_truth', 'seen', crawl['price'], crawl['pages'],
                                   float(DIMENSIONS_BY_CODE['price_truth'].seen_max), 'reference read: a price', page_reason),
        'member_value': _ratio_part('member_value', 'seen', crawl['member_price'], crawl['pages'],
                                    float(DIMENSIONS_BY_CODE['member_value'].seen_max), 'reference read: member_price', page_reason),
        'deal_citability': deal_seen_part(crawl, page_reason),
    }
    for code in ('price_truth', 'member_value', 'deal_citability'):
        at(f'{code} on {surface}')
        dim = DIMENSIONS_BY_CODE[code]
        s, t = seen[code], said[code]
        if code == 'member_value' and not member_value_applicable('yes' if program_stated else None, s['score'] or 0.0):
            dims.append(_dim(code, earned=None, applicable=0, state=NA, parts=[s, t], reason=TEMPLATES['reason.no_program']))
            continue
        if s['state'] != MEASURED:
            # The Audit's seen_blocked rule: an unmeasurable encode half takes
            # the whole dimension out of the applicable max, said attached, uncounted
            reason = TEMPLATES['reason.deal_whole'] if code == 'deal_citability' else s['reason']
            dims.append(_dim(code, earned=None, applicable=0, state=NOT_MEASURED, parts=[s, t], reason=reason))
            continue
        said_na = t['state'] != MEASURED
        dims.append(_dim(code, earned=s['score'] + (0.0 if said_na else t['score']),
                         applicable=dimension_max(dim, said_na=said_na), state=MEASURED, parts=[s, t]))
    dims.append(_domain_dim('value_protocols', domain_checks))

    dims.sort(key=lambda x: [d.code for d in DIMENSIONS].index(x['code']))
    counted = [x for x in dims if x['state'] == MEASURED]
    earned = sum(x['score'] for x in counted)
    applicable = sum(x['applicable_max'] for x in counted)
    pillars = {}
    for p in PILLAR_ORDER:
        mine = [x for x in counted if x['pillar'] == p]
        pillars[p] = {'score': round(sum(x['score'] for x in mine), 1) if mine else None,
                      'applicable_max': float(sum(x['applicable_max'] for x in mine))}
    return {'surface': surface, 'label': surfaces.SURFACE_LABELS.get(surface, surface),
            'score': (earned / applicable * 100) if applicable else None,
            'earned': round(earned, 1), 'applicable_max': float(applicable), 'pillars': pillars, 'dimensions': dims}


# ─── pooled ────────────────────────────────────────────────────────────────

def _pool_dimension(code: str, per: List[dict]) -> dict:
    """A dimension across the pooled surfaces: the mean of its per-surface
    points and applicable max (0 where a surface did not count it), with every
    surface's own row beside. Numerators and denominators stay per surface:
    the pooled row carries one only when every surface reads the same one (a
    crawl-side count)."""
    rows = [next(x for x in s['dimensions'] if x['code'] == code) for s in per]
    states = {r['state'] for r in rows}
    state = states.pop() if len(states) == 1 else PARTIAL
    counted = [r for r in rows if r['state'] == MEASURED]
    d = DIMENSIONS_BY_CODE[code]
    first = rows[0]
    same = all(r['parts'] == first['parts'] for r in rows)
    one_part = first['parts'][0] if len(first['parts']) == 1 else None
    return {
        'code': code, 'name': d.name, 'pillar': d.pillar, 'max': float(d.weight),
        'score': round(mean(r['score'] if r['state'] == MEASURED else 0.0 for r in rows), 2) if counted else None,
        'applicable_max': round(mean(r['applicable_max'] for r in rows), 2),
        'state': state, 'reason': first['reason'] if len({r['reason'] for r in rows}) == 1 else None,
        'numerator': one_part['numerator'] if same and one_part else None,
        'denominator': one_part['denominator'] if same and one_part else None,
        'source': one_part['source'] if one_part else '; '.join(p['source'] or '' for p in first['parts']).strip('; ') or None,
        'parts': first['parts'] if same else None,
        'by_surface': {s['surface']: {k: r[k] for k in ('score', 'applicable_max', 'state', 'reason', 'parts')}
                       for s, r in zip(per, rows)},
    }


def biggest_gap(per: List[dict], pooled_dims: List[dict]) -> Optional[dict]:
    """The counted dimension with the most points left on the table (pooled),
    with the line of its part that leaves the most, on the surface where it
    leaves the most. Ties go to the registry's order."""
    order = [d.code for d in DIMENSIONS]
    candidates = [d for d in pooled_dims if d['state'] in (MEASURED, PARTIAL) and d['score'] is not None]
    if not candidates:
        return None
    top = max(candidates, key=lambda d: (round(d['applicable_max'] - d['score'], 2), -order.index(d['code'])))
    left = round(top['applicable_max'] - top['score'], 1)
    best, where = None, None
    for s in per:
        row = next(x for x in s['dimensions'] if x['code'] == top['code'])
        if row['state'] != MEASURED:
            continue
        for p in row['parts']:
            if p['state'] != MEASURED or p['line'] is None:
                continue
            gap = p['max'] - p['score']
            if best is None or gap > best[0]:
                best, where = (gap, p), s['surface']
    if best is None:
        return {'dimension': top['name'], 'code': top['code'], 'points': left, 'line': top['name']}
    part = best[1]
    crawl_side = part['half'] == 'seen' or top['code'] in ('agent_access', 'catalog_context')
    line = part['line'] if crawl_side or len(per) == 1 else TEMPLATES['gap.on_surface'].format(
        line=part['line'], surface=_surface_words(where))
    return {'dimension': top['name'], 'code': top['code'], 'points': left, 'line': line,
            'surface': None if crawl_side else where, 'numerator': part['numerator'], 'denominator': part['denominator']}


#: The demo's five metric rows: (key, name, the count, over, the rows' tier).
METRICS = (
    ('first', 'First recommendation', 'first', 'named_of'),
    ('share', 'Share of answers', 'named', 'named_of'),
    ('program', 'Program named when the brand is named', 'program', 'program_of'),
    ('exact', 'Prices quoted exactly', 'exact', 'scored'),
    ('terms', 'Program terms right', 'exact', 'scored'),
)


def metric_counts(runs: List[dict], mentions: List[dict], vis_rows: List[dict], surface: str) -> dict:
    """The counts behind the five rows on one surface, from the counts the
    Overview already reads: named and first over answered runs of the
    Overview's tier (unprompted when the cycle asked any, parity.surface_
    metrics); program named = our Layer 1 mention coded deal_cited or
    member_value_cited, over the answered runs of that tier naming us; prices
    exact of scored on the catalog tier, program terms exact of scored on the
    value tier."""
    vis = parity.surface_metrics(runs, vis_rows, surface)
    tier = vis['tier']
    catalog = parity.surface_metrics([r for r in runs if r.get('tier') == 'catalog_accuracy'], [], surface)['total']
    value = parity.surface_metrics([r for r in runs if r.get('tier') == 'value_incentives'], [], surface)['total']
    in_tier = {r['run_id'] for r in runs if parity._surface_of(r) == surface and r.get('answer_status') == surfaces.ANSWERED
               and (tier == 'all' or (r.get('tier') or rm.VIS_UNPROMPTED) == tier)}
    ours = [m for m in mentions if m['run_id'] in in_tier and m.get('role') == 'primary' and m.get('mentioned')]
    return {
        'tier': tier, 'agent_set': vis['agent_set'],
        'first': {'value': vis['total']['first'], 'of': vis['total']['named_of']},
        'share': {'value': vis['total']['named'], 'of': vis['total']['named_of']},
        'program': {'value': sum(1 for m in ours if m.get('deal_cited') or m.get('member_value_cited')),
                    'of': len({m['run_id'] for m in ours})},
        'exact': {'value': catalog['exact'], 'of': catalog['scored']},
        'terms': {'value': value['exact'], 'of': value['scored']},
    }


def _surface_note(surface: str, tier: str, key: str) -> str:
    where = f"on {_surface_words(surface)}"
    if key in ('first', 'share', 'program'):
        return f"{where}, {'unprompted answers' if tier == rm.VIS_UNPROMPTED else 'every answered question'}"
    return f"{where}, {'catalog' if key == 'exact' else 'value'} tier, exact of scored"


def build_metrics(counts: Dict[str, dict], surface: str, previous: Optional[dict]) -> List[dict]:
    """The five rows on `surface` (the highest-fidelity pooled one, as the
    Overview reads it), every surface beside. A delta only when the previous
    cycle is comparable, else null with the reason."""
    out = []
    comparable = bool(previous and previous.get('comparable'))
    prev_counts = (previous or {}).get('metric_counts') or {}
    for key, name, _, _ in METRICS:
        now = counts[surface][key]
        delta, reason = None, None
        if comparable and surface in prev_counts:
            delta = now['value'] - prev_counts[surface][key]['value']
        else:
            reason = (previous or {}).get('reason') or TEMPLATES['previous.first_cycle']
        out.append({'key': key, 'name': name, 'value': now['value'], 'denominator': now['of'], 'surface': surface,
                    'surface_note': _surface_note(surface, counts[surface]['tier'], key), 'delta': delta,
                    'delta_reason': reason,
                    'by_surface': {s: c[key] for s, c in counts.items()}})
    return out


def compare(now: dict, prev_code: Optional[str], prev_stored: Optional[dict]) -> Optional[dict]:
    """2C-2a's rule, plus the scorer: comparable only with the same pooled
    surfaces, the same agents on each, and the same scorer version."""
    if prev_code is None:
        return None
    base = {'cycle': prev_code, 'scorer_version': None, 'score': None, 'comparable': False}
    if not prev_stored:
        return {**base, 'reason': TEMPLATES['previous.not_stored'].format(code=prev_code)}
    base.update(scorer_version=prev_stored.get('scorer_version'), score=prev_stored.get('score'))
    if prev_stored.get('scorer_version') != now['scorer_version']:
        return {**base, 'reason': TEMPLATES['previous.version'].format(version=prev_stored.get('scorer_version'))}
    a, b = [s['surface'] for s in now['surfaces']], [s['surface'] for s in prev_stored.get('surfaces') or []]
    if set(a) != set(b):
        words = lambda xs: ' and '.join(_surface_words(x) for x in xs) or 'no surface'
        return {**base, 'reason': TEMPLATES['previous.surfaces'].format(code=prev_code, prev=words(b), now=words(a))}
    for s in a:
        x, y = now['metric_counts'][s]['agent_set'], (prev_stored.get('metric_counts') or {}).get(s, {}).get('agent_set') or []
        if set(x) != set(y):
            return {**base, 'reason': TEMPLATES['previous.agents'].format(
                surface=_surface_words(s), code=prev_code, prev=parity._agents_text(y) or 'no agent', now=parity._agents_text(x))}
    now_max, prev_max = now.get('applicable_max'), prev_stored.get('applicable_max')
    changed = prev_max is not None and now_max is not None and round(float(prev_max), 1) != round(float(now_max), 1)
    return {**base, 'comparable': True, 'reason': None, 'metric_counts': prev_stored.get('metric_counts'),
            'delta': None if now['score'] is None or prev_stored.get('score') is None else now['score'] - prev_stored['score'],
            'applicable_max': prev_max,
            'applicable_note': TEMPLATES['previous.applicable'].format(prev=_fmt(float(prev_max)), now=_fmt(float(now_max)))
            if changed else None,
            'dimension_deltas': dimension_deltas(now, prev_stored)}


def _dims_of(body: dict) -> Dict[str, dict]:
    return {d['code']: d for p in body.get('pillars') or [] for d in p.get('dimensions') or []}


def dimension_deltas(now: dict, prev: dict) -> List[dict]:
    """Each dimension's change, only where both cycles measured it: a
    dimension measured on one side only has no delta (its points are in one
    applicable max and not the other), in registry order."""
    a, b = _dims_of(now), _dims_of(prev)
    out = []
    for d in DIMENSIONS:
        x, y = a.get(d.code), b.get(d.code)
        if not x or not y or x.get('state') not in (MEASURED, PARTIAL) or y.get('state') not in (MEASURED, PARTIAL):
            continue
        if x.get('score') is None or y.get('score') is None:
            continue
        out.append({'code': d.code, 'name': d.name, 'delta': round(x['score'] - y['score'], 2),
                    'score': x['score'], 'previous': y['score']})
    return out


def build_score(cycle_code: str, *, runs: List[dict], mentions: List[dict], vis_rows: List[dict],
                access: Optional[dict], reference_rows: Optional[List[dict]],
                read_errors: Optional[Dict[str, str]] = None, inputs: Optional[dict] = None,
                domain_checks: Optional[dict] = None) -> dict:
    """GET /api/console/score without `previous` (score_with_previous adds it).

    runs: load_score_runs (one per run, with tier, stage, outcome and the
    expectation's type). mentions: load_score_mentions (Layer 1, with role
    and strength). vis_rows: Visibility's byQuestion. access: supply's access
    payload as accessibility_from_supply maps it. reference_rows: supply's
    /reference rows. domain_checks: the cycle's stored domain-check record
    (soa_cycles.domain_checks, 2E), or None."""
    errors = read_errors or {}
    at('crawl counts')
    crawl = crawl_counts(access, reference_rows)
    program_stated = any(r.get('tier') == 'value_incentives' and r.get('expected_type') in MEMBER_TYPES for r in runs)
    ran = parity.ordered_surfaces({parity._surface_of(r) for r in runs})
    answered = {parity._surface_of(r) for r in runs if r.get('answer_status') == surfaces.ANSWERED}
    pooled = [s for s in ran if s in answered]
    per = [score_surface(s, runs=runs, mentions=mentions, crawl=crawl, crawl_errors=errors,
                         program_stated=program_stated, domain_checks=domain_checks) for s in pooled]
    at('pooling')
    scored = [p for p in per if p['score'] is not None]
    dims = [_pool_dimension(d.code, per) for d in DIMENSIONS] if per else []
    pillars = []
    for p in PILLAR_ORDER:
        mine = [d for d in dims if d['pillar'] == p]
        pillars.append({'code': p, 'name': PILLAR_NAMES[p], 'max': float(PILLAR_WEIGHTS[p]),
                        'score': (round(mean(s['pillars'][p]['score'] or 0.0 for s in per), 1)
                                  if any(s['pillars'][p]['score'] is not None for s in per) else None),
                        'applicable_max': round(mean(s['pillars'][p]['applicable_max'] for s in per), 1) if per else 0.0,
                        'dimensions': mine})
    score = round(mean(p['score'] for p in scored)) if scored else None
    # points out of the applicable max for not being measured. The scorer's
    # own 'na' (Member Value with no program, a said half too thin to judge)
    # is not: the Audit still gives its verdict on those.
    unmeasured = mean(sum(d['max'] for d in s['dimensions'] if d['state'] == NOT_MEASURED) for s in per) if per else 0
    tv = next((p for p in pillars if p['code'] == 'true_value'), None)
    at('metric rows')
    counts = {s: metric_counts(runs, mentions, vis_rows, s) for s in pooled}
    in_pool = [r for r in runs if parity._surface_of(r) in pooled]
    agents = {surfaces.agent_of(r.get('platform')) or r.get('platform') for r in in_pool}
    questions = len({r.get('query_code') for r in in_pool})
    record = domain_checks or {}
    return {
        'cycle': cycle_code,
        'scorer_version': SCORER_VERSION,
        'adapter_revision': ADAPTER_REVISION,
        # 2E: the dimensions this score counts, stored beside it: a change in
        # the set is the second recompute trigger (needs_recompute)
        'measured': [d['code'] for d in dims if d['state'] in (MEASURED, PARTIAL)],
        'score': score,
        'earned': round(mean(p['earned'] for p in scored), 1) if scored else None,
        'applicable_max': round(mean(p['applicable_max'] for p in scored), 1) if scored else 0.0,
        'total_max': float(TOTAL_MAX),
        'readiness_bar': READINESS_BAR,
        # The Audit issues a verdict only in its 'scored' state, with nothing
        # unmeasured (build_pillars_payload). A not-measured dimension
        # withholds it here the same way; Member Value 'na' does not.
        'verdict': (compute_verdict(score, tv['score'] or 0.0, tv['applicable_max'])
                    if score is not None and tv and not unmeasured else None),
        'verdict_note': (TEMPLATES['verdict.withheld'].format(n=_fmt(unmeasured), total=TOTAL_MAX)
                         if score is not None and unmeasured else None),
        'surfaces': [{'surface': p['surface'], 'label': p['label'], 'score': p['score'], 'earned': p['earned'],
                      'applicable_max': p['applicable_max'],
                      'pillars': [{'code': k, 'score': v['score'], 'applicable_max': v['applicable_max']}
                                  for k, v in p['pillars'].items()]} for p in per],
        'surfaces_left_out': [{'surface': s, 'label': surfaces.SURFACE_LABELS.get(s, s), 'reason': TEMPLATES['reason.no_answers']}
                              for s in ran if s not in answered],
        'pillars': pillars,
        'biggest_gap': biggest_gap(per, dims),
        'metric_surface': pooled[0] if pooled else None,
        'metric_counts': counts,
        'coverage': {'surfaces': len(pooled), 'questions': questions, 'agents': len(agents), 'runs': len(in_pool),
                     'ran_no_answers': [s for s in ran if s not in answered],
                     'line': TEMPLATES['coverage'].format(surfaces=_n(len(pooled), 'surface', 'surfaces'),
                                                          questions=_n(questions, 'question', 'questions'),
                                                          agents=_n(len(agents), 'agent', 'agents'))
                     + ''.join(TEMPLATES['coverage.no_answers'].format(surface=_surface_words(s))
                               for s in ran if s not in answered)},
        'inputs': {**(inputs or {}), 'domain_checks': {
            'checked_at': record.get('checked_at'), 'scored_domain': record.get('scored_domain'),
            'version': record.get('version'), 'revision': record_revision(record)} if record else None},
        'history': [],
        'read_errors': errors,
        'rules': TEMPLATES,
    }


def with_previous(body: dict, prev_code: Optional[str], prev_stored: Optional[dict]) -> dict:
    """Adds `previous` and the five rows (whose deltas need it)."""
    at('comparing with the previous cycle')
    previous = compare(body, prev_code, prev_stored)
    out = dict(body)
    out['previous'] = None if previous is None else {k: v for k, v in previous.items() if k != 'metric_counts'}
    out['metrics'] = build_metrics(body['metric_counts'], body['metric_surface'], previous) if body['metric_surface'] else []
    return out


# ─── loaders and the stored score ──────────────────────────────────────────

def load_score_runs(conn, cycle: dict) -> List[dict]:
    """load_overview_rows plus the expectation's type, which the value tier's
    two said halves split on."""
    at('loading runs')
    rows = parity.load_overview_rows(conn, cycle)
    # 2C-3a: no DISTINCT. soa_queries.expected_answer is a Postgres json
    # column, which has no equality operator: SELECT DISTINCT over it raised
    # UndefinedFunction on every cycle in production (sqlite's TEXT hid it).
    # One row per question the cycle asked, by subquery instead.
    types = {r['query_code']: (rm._json(r['expected_answer']) or {}).get('type') for r in conn.execute(text("""
        SELECT q.query_code, q.expected_answer FROM soa_queries q
        WHERE q.id IN (SELECT r.query_id FROM soa_runs r WHERE r.cycle_id = :c)
    """), {'c': cycle['id']}).mappings()}
    for r in rows:
        r['expected_type'] = types.get(r.get('query_code'))
    return rows


def load_score_mentions(conn, cycle: dict) -> List[dict]:
    """Layer 1 for the cycle's entities, with the columns MetricsCalculator
    reads (strength, deal_cited) and member_value_cited."""
    at('loading mentions')
    return [dict(m) for m in conn.execute(text("""
        SELECT cm.run_id, cm.mentioned, cm.position, cm.strength, cm.deal_cited, cm.member_value_cited, ce.role
        FROM soa_coded_mentions cm
        JOIN soa_runs r ON r.id = cm.run_id
        JOIN soa_cycle_entities ce ON ce.cycle_id = r.cycle_id AND ce.entity_id = cm.entity_id
        WHERE r.cycle_id = :c
    """), {'c': cycle['id']}).mappings()]


def cycle_merchant(conn, cycle: dict) -> Optional[str]:
    """The merchant the cycle's questions were built from (their source_ref)."""
    at('finding the merchant')
    counts: Dict[str, int] = {}
    for r in conn.execute(text("""
        SELECT q.source_ref FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id WHERE r.cycle_id = :c
    """), {'c': cycle['id']}):
        slug = (rm._json(r[0]) or {}).get('merchant_slug')
        if slug:
            counts[slug] = counts.get(slug, 0) + 1
    return max(counts, key=counts.get) if counts else None


def stored_score(engine, cycle_id: int) -> Optional[dict]:
    """The score stored on the cycle row, or None (never stored, or the
    column is not there yet: the read works before the migration does)."""
    try:
        with engine.connect() as c:
            row = c.execute(text("SELECT share_of_algorithm, share_of_algorithm_version FROM soa_cycles WHERE id = :i"),
                            {'i': cycle_id}).fetchone()
    except Exception:  # noqa: BLE001 - column missing before the migration is applied
        return None
    if not row or row[0] is None:
        return None
    body = rm._json(row[0])
    return body if isinstance(body, dict) else None


def is_current(body: Optional[dict]) -> bool:
    return bool(body) and body.get('scorer_version') == SCORER_VERSION and body.get('adapter_revision') == ADAPTER_REVISION


def record_revision(record: Optional[dict]) -> Optional[int]:
    """The domain-check record's revision (2E-1): 1 for a record stored
    before revisions were, None for no record."""
    if not record:
        return None
    return int(record.get('revision') or 1)


def needs_recompute(body: Optional[dict], domain_checks: Optional[dict]) -> Optional[str]:
    """Why a stored score is recomputed on this read, or None to serve it.
    2C-3's trigger, the scorer version (and the adapter's revision), and 2E's:
    the set of measured dimensions changed, or the record's revision did
    (a re-run replaced it). The cycle row says which of the
    domain-check dimensions are measured now, with no supply call, so a
    record stored after the score (run_domain_checks.py on 229) recomputes it
    on the next read."""
    if not body:
        return 'first read'
    if not is_current(body):
        return 'stale'
    was = [c for c in DOMAIN_CODES if c in (body.get('measured') or [])]
    if was != measured_from_record(domain_checks):
        return 'measured set changed'
    # 2E-1: a re-run replaced the record (run_domain_checks.py --replace).
    # A score stored before revisions were read a record of revision 1; one
    # scored with no record (inputs.domain_checks None) read none.
    inputs = body.get('inputs') or {}
    if 'domain_checks' in inputs:
        scored_on = inputs['domain_checks'] and int(inputs['domain_checks'].get('revision') or 1)
    else:
        scored_on = 1
    if domain_checks and scored_on != record_revision(domain_checks):
        return 'domain checks revision changed'
    return None


def carry_history(new: dict, old: Optional[dict], reason: str) -> dict:
    """The new score with the one it replaces kept in its history (newest
    last, HISTORY_KEEP at most), so a report can show both."""
    if not old:
        return new
    entry = {k: old.get(k) for k in ('score', 'earned', 'applicable_max', 'measured', 'scorer_version', 'adapter_revision')}
    entry['scored_at'] = (old.get('inputs') or {}).get('scored_at')
    entry['replaced_because'] = reason
    new = dict(new)
    new['history'] = ((old.get('history') or []) + [entry])[-HISTORY_KEEP:]
    return new


def store_score(engine, cycle_id: int, body: dict) -> bool:
    """Stores the score with its scorer_version. False when the column is not
    there yet: the score is still served, only recomputed on the next read."""
    try:
        with engine.begin() as c:
            c.execute(text("UPDATE soa_cycles SET share_of_algorithm = :b, share_of_algorithm_version = :v WHERE id = :i"),
                      {'b': json.dumps(body), 'v': body['scorer_version'], 'i': cycle_id})
        return True
    except Exception:  # noqa: BLE001 - column missing before the migration is applied
        return False
