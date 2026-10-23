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
surface scores, rounded once. 2I (scorer 7): grounded surfaces only. An
`api` surface (the model alone, no search) is listed beside the score as
ungrounded and not scored. Pure functions here; the loaders and the
stored score are at the bottom. No model is called.
"""
import json
import logging
from collections import Counter
from contextvars import ContextVar
from datetime import datetime, timezone
from statistics import mean
from typing import Dict, Iterable, List, Optional

from sqlalchemy import text

from soa_shared import cycle_compare, surfaces, unprompted
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
#: it and every stored console score reads stale. 2I-6: "8" is
#: FULL_CYCLE_SCORER_VERSION ("7") plus a rule only the console applies (share
#: of mentions is not measured on a cycle that tracks no rival), so it is the
#: console's own: the full-cycle scorer, and what it stamps, stay "7".
#: 2I-7: "9", category-control questions count as unprompted (and a question
#: naming the brand does not), soa_shared/unprompted.py.
#: 2I-8a: "10", the five metric rows count every agent (`all`), as the rest of
#: the Overview does since 2I-8. The stored score carries the rows' counts, so
#: a stored cycle re-scores to serve them; the score itself does not move.
#: 2K-1: "11", the brand-choice set (unprompted plus the comparison tier,
#: soa_shared/unprompted.is_brand_choice) for Lost and the first-pick rows
#: (first, share, program) when a cycle asked comparison questions. No
#: dimension reads it (share of mentions and recommendation strength stay on
#: unprompted), so the score does not move; the rows' counts beside it do.
SCORER_VERSION = "11"
#: The adapter's own revision, beside the scorer's: a change to how loop
#: counts become scorer inputs re-scores stored cycles too. Not a scorer
#: version and never shown as one.
ADAPTER_REVISION = 3   # 2E-2: Deal Citability's seen half counts markup only

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
    'check.flag_text': '{flag} {n} of {d} pages, the page text included',
    'gap.on_surface': '{line} on {surface}',
    'reason.no_unprompted': 'no unprompted question answered on this surface',
    'reason.all_named_the_brand': ('no unprompted question answered on this surface: every category-control '
                                   'question names the brand ({n} answered), and a question that names it is not counted'),
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
    'reason.ungrounded': 'ungrounded · not scored',
    'reason.no_rivals': 'no competitor is tracked on this cycle: add competitors in the wizard',
    'previous.first_cycle': 'First cycle. Changes appear from the next one.',
    'previous.not_stored': 'Not comparable: {code} has no stored score yet. Open it to score it.',
    # 2K-4 (B1): kept in `rules` as served (the score body is pinned); the reasons served
    # come from soa_shared/cycle_compare.TEMPLATES, one set for every reader
    'previous.version': 'Scored under v{version}, re-score to compare.',
    'previous.surfaces': 'Not comparable: {code} scored {prev}, this cycle scored {now}.',
    'previous.agents': 'Not comparable: on {surface} {code} ran {prev}, this cycle ran {now}.',
    # 2I-8a: a previous score stored before the rows counted every agent has no `all` counts
    'previous.no_all': 'Not comparable: {code} was scored before metric rows counted every agent',
    'previous.applicable': 'applicable points changed from {prev} to {now}',
    'verdict.withheld': 'No readiness verdict while {n} of {total} points are not measured. The Audit gives one only when every dimension is.',
    'coverage': '{surfaces}, {questions}, {agents} · pooled across surfaces, equal weight',
    'coverage.no_answers': ' · {surface} ran, no answers',
    'coverage.ungrounded': ' · {surface}: ungrounded · not scored',
    'recompute.version': 'scorer {prev} → {now}',
    'recompute.version_changed': 'scorer {prev} → {now}: {change}',
    'recompute.input_changed': ' · {input} changed',
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
    scanned = [(r, m) for r, m in ((r, supply_fields.incentive_in_markup(r)) for r in pages) if m and m['json_ld_scanned']]
    flags = supply_fields.INCENTIVE_FLAGS
    return {
        'identities': len(measured), 'through': sum(1 for r in measured if r.get('ok')),
        'pages': len(pages),
        'catalog': sum(1 for r in pages if r.get('method') == 'json_ld' and gtin_ok(r)),
        'price': sum(1 for r in pages if r.get('price') not in (None, '')),
        'member_price': sum(1 for r in pages if r.get('member_price') not in (None, '')),
        'incentive_fields': supply_fields.carries_incentive_fields(rows),
        'incentive_scanned': len(scanned),
        # 2E-2: a page carries an incentive in markup when a flag is true AND
        # supply says it came from structured data (source json_ld). A served
        # flag is the JSON-LD half OR a text half read from the page's
        # offer_text, so a site-wide "Free shipping" line sets promo on every
        # page without any markup saying so; a text-only page does not count
        'incentive_any': sum(1 for _, m in scanned if m['source'] == 'json_ld' and any(m[f] for f in flags)),
        'incentive_flags': {f: sum(1 for _, m in scanned if m[f]) for f in flags},
        # how many of a flag's pages also carry offer_text, which may be what set it
        'incentive_flags_text': {f: sum(1 for r, m in scanned if m[f] and r.get('offer_text')) for f in flags},
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
    """Deal Citability, seen: reads whose page carries an incentive in its
    markup (a flag true, from structured data) over the pages read whose
    markup supply scanned."""
    seen_max = float(DIMENSIONS_BY_CODE['deal_citability'].seen_max)
    source = 'reference read: incentive_in_markup (supply), json_ld_scanned pages'
    if not crawl['pages']:
        return {**_unsourced_part('seen', seen_max, 'reason.deal_seen'), 'reason': page_reason, 'source': source}
    if not crawl['incentive_fields']:
        return {**_unsourced_part('seen', seen_max, 'reason.deal_seen'), 'source': source}
    if not crawl['incentive_scanned']:
        return {**_unsourced_part('seen', seen_max, 'reason.deal_unscanned'), 'source': source}
    part = _ratio_part('deal_citability', 'seen', crawl['incentive_any'], crawl['incentive_scanned'], seen_max, source)
    # Each flag as supply serves it, its value read (a false is 'fail'); a flag
    # true on pages that also carry offer_text says so, since supply's served
    # flag may be the text half there (2E-2)
    text = crawl.get('incentive_flags_text') or {}
    part['checks'] = [{'code': f, 'label': TEMPLATES['check.flag_text' if text.get(f) else 'check.flag'].format(
                           flag=f.replace('_', ' '), n=k, d=crawl['incentive_scanned']),
                       'state': 'pass' if k else 'fail'} for f, k in crawl['incentive_flags'].items()]
    return part


def visibility_inputs(runs: List[dict], mentions: List[dict], surface: str, terms: Iterable[str] = ()) -> dict:
    """The scorer's som_pct / rsi_score / total_mentions for one surface, over
    answered unprompted runs, counted as MetricsCalculator counts them: our
    mentions over every cycle entity's mentions, and the mean Layer 1 strength
    weight over our mentions.

    2I-7 (scorer 9): unprompted is soa_shared/unprompted.py's rule, the one
    the read models count by: no tier or category_control, and a question
    that names none of the brand's `terms`. Before, only an untiered run
    counted, so a study generated with the brand box on (its stage questions
    tagged category_control) measured no Visibility at all (FL12).
    `named_the_brand` is how many answered runs of an unprompted tier were
    left out for naming the brand."""
    answered = [r for r in runs if parity._surface_of(r) == surface and r.get('answer_status') == surfaces.ANSWERED
                and unprompted.is_unprompted_tier(r.get('tier'))]
    unprompted_runs = {r['run_id'] for r in answered if unprompted.is_unprompted(r, terms)}
    ours = [m for m in mentions if m['run_id'] in unprompted_runs and m.get('mentioned') and m.get('role') == 'primary']
    every = [m for m in mentions if m['run_id'] in unprompted_runs and m.get('mentioned') and m.get('role')]
    return {
        'runs': len(unprompted_runs), 'ours': len(ours), 'all': len(every),
        'named_the_brand': len(answered) - len(unprompted_runs),
        'category_control': sum(1 for r in answered if r.get('tier') == 'category_control'),
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
                  domain_checks: Optional[dict] = None, rivals_tracked: bool = True,
                  terms: Iterable[str] = ()) -> dict:
    """Every dimension on one surface, from the scorer's functions, and the
    surface's score: round-free earned ÷ applicable max × 100.

    2I-6 (scorer 8): share of mentions counts our mentions over every
    tracked entity's, so a cycle that tracks no rival scores it 1 of 1
    whenever we are named (FL7). Without a rival it is not measured: its
    points leave the applicable max and the verdict is withheld, as for any
    unmeasured dimension. Recommendation strength (our first picks over our
    mentions) and the named counts do not depend on the set."""
    errors = crawl_errors or {}
    dims = []

    # Visibility: the Audit's two functions over unprompted Layer 1 counts
    at(f'visibility on {surface}')
    vis = visibility_inputs(runs, mentions, surface, terms)
    for code, fn, n, d, value in (
            ('share_of_mentions', score_share_of_mentions_full, vis['ours'], vis['all'], vis['som_pct']),
            ('recommendation_strength', score_recommendation_strength_full, vis['picks'], vis['ours'], vis['rsi_score'])):
        at(f'{code} on {surface}')
        source = 'soa_coded_mentions, answered unprompted runs'
        unmeasured = ('reason.all_named_the_brand' if not vis['runs'] and vis['named_the_brand'] else
                      'reason.no_unprompted' if not vis['runs'] else
                      'reason.no_rivals' if code == 'share_of_mentions' and not rivals_tracked else None)
        if unmeasured:
            part = _unsourced_part(None, float(DIMENSIONS_BY_CODE[code].weight), unmeasured)
            if unmeasured == 'reason.all_named_the_brand':
                part['reason'] = part['reason'].format(n=vis['named_the_brand'])
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


#: 2L-4: a brand merchant's five tiles, the demo's charter set in its order:
#: (key, name). Retailer merchants keep METRICS.
BRAND_METRICS = (
    ('attribute', 'Attribute accuracy'),
    ('coverage', 'Retailer coverage'),
    ('presence', 'Category presence'),
    ('retired', 'Retired product named'),
    ('promo', 'Promo pass-through'),
)
#: 2L-4: the brand tiles' copy, filled from their counts. Kept out of
#: TEMPLATES, which the score serves as `rules` and is pinned.
BRAND_TILE_TEMPLATES = {
    'attribute.not_measured': ("Not measured yet: each product's attributes are not yet checked against the brand's "
                               "record."),
    'attribute.sub': 'Weight range for the size asked: pages {pk} of {pn}, answers {ak} of {an}',
    'note.attribute': '{where}, retailer pages and accuracy answers',
    'promo.not_measured': "Not measured: retailer-page deals are not read yet.",
    'promo.sub': 'Cheapest-place answers naming a deal live that day. {deal}: named {k} of {n}',
    'promo.sub.none': 'Cheapest-place answers naming a deal live that day. No deal was live on these SKUs',
    'note.promo': '{where}, cheapest-place answers',
    'retired.not_measured': "Not measured: the brand's record has no retired line.",
    'coverage.not_measured': ("Not measured: this cycle asked no where-to-buy question. The study's next "
                              "regeneration adds them."),
    'coverage.sub': '{n} of {d} where-to-buy answers name 2 or more of {names}',
    'presence.sub': 'Category answers naming {brand}. First in {first}',
    'presence.rival': ', {rival} first in {n}',
    'retired.sub': 'Category answers naming {label}, which {by} retired',
    'retired.successor': '. {successor}, its successor: {n}',
    'previous.no_tile': 'Not comparable: {code} was scored before this tile was counted',
    'note.coverage': '{where}, where-to-buy answers',
    'note.retired': '{where}, brand-choice answers',
}


def brand_counts(brand_inputs: Optional[dict], vis_rows: List[dict], surface: str, tier: str, totals: dict,
                 surface_set: Optional[List[str]] = None) -> dict:
    """2L-4: the brand tiles' counts on one surface. `brand_inputs` is
    {routing, retired_named, brand} from Visibility (rm.build_routing,
    rm.build_retired_named). On `all` the per-surface counts of
    `surface_set` (the pooled surfaces) are summed, as the score pools
    them. A tile with nothing to count is None, its tile "not measured".

    presence is Share of answers (named of named_of on the Overview's
    tier), with first and the rival first most often for its sub-line;
    coverage the where-to-buy answers naming 2 or more of the merchant's
    retailers; retired the first retired line's brand-choice answers
    naming it. 2M-1: attribute is the weight range for the size asked,
    matches over the retailer pages supply read (every surface) plus the
    surface's judged accuracy answers (rm.build_attribute_accuracy). 2M-2:
    promo is the cheapest-place answers naming a deal live on a retailer
    shelf for the SKU that day, of the surface's answered cheapest-place
    answers (rm.build_promo_pass_through), the deal asked about most beside."""
    inputs = brand_inputs or {}
    keys = [s for s in (surface_set or []) if s != surfaces.ALL] if surface == surfaces.ALL else [surface]

    def summed(per: dict, a: str, b: str) -> Optional[dict]:
        got = [per.get(s) for s in keys if per.get(s)]
        return {'value': sum(g[a] for g in got), 'of': sum(g[b] for g in got)} if got else None

    rivals = Counter((v.get('first') or {}).get('name') for v in vis_rows
                     if parity._on(v.get('surface'), surface) and v.get('answered') and parity._in_tier(v, tier)
                     and v.get('first') and not v['first'].get('you'))
    rival = rivals.most_common(1)[0] if rivals else None
    routing = inputs.get('routing')
    coverage = summed(routing.get('coverage') or {}, 'named_two_plus', 'answers') if routing else None
    if coverage is not None:
        coverage['names'] = list(routing.get('retailers') or [])
    line = ((inputs.get('retired_named') or {}).get('lines') or [None])[0]
    retired = None
    if line:
        retired = summed(line.get('brand_choice') or {}, 'named', 'answers') or {'value': 0, 'of': 0}
        succ = summed({s: c for s, c in (line.get('brand_choice') or {}).items() if c.get('successor_named') is not None},
                      'successor_named', 'answers')
        retired.update(label=line.get('label'), by=(inputs.get('retired_named') or {}).get('retired_by'),
                       successor=(line.get('successor') or {}).get('label'),
                       successor_named=succ['value'] if succ else None)
    attribute = None
    accuracy = inputs.get('attribute_accuracy')
    if accuracy:
        per = accuracy.get('answers_by_surface') or {}
        an = sum((per.get(s) or {}).get('n', 0) for s in keys)
        ak = sum((per.get(s) or {}).get('k', 0) for s in keys)
        pn, pk = accuracy['pages']['n'], accuracy['pages']['k']
        if pn or an:
            attribute = {'value': pk + ak, 'of': pn + an, 'pages': {'n': pn, 'k': pk}, 'answers': {'n': an, 'k': ak}}
    promo = None
    passed = inputs.get('promo_pass_through')
    if passed:
        per = passed.get('by_surface') or {}
        n = sum((per.get(s) or {}).get('n', 0) for s in keys)
        if n:
            top = (passed.get('per_deal') or [None])[0]
            deal = None
            if top is not None:
                # the deal asked about most, counted on this tile's surfaces
                from soa_shared import promo_pass_through as ppt
                tid = ppt.deal_id(top)
                here = [j for j in passed.get('judged') or [] if j.get('surface') in keys and tid in j['live']]
                # 2N-2: the deal's kind in its retailer's words, as the Trade promotions row (kind_label)
                named = {'short': top['short'], 'kind_label': top.get('kind_label')}
                deal = {**named, 'asked': len(here), 'named': sum(1 for j in here if tid in j['named'])} \
                    if passed.get('judged') is not None else {**named, 'asked': top['asked'], 'named': top['named']}
            promo = {'value': sum((per.get(s) or {}).get('k', 0) for s in keys), 'of': n,
                     'loose': sum((per.get(s) or {}).get('loose', 0) for s in keys),
                     'subscribe': sum((per.get(s) or {}).get('subscribe', 0) for s in keys), 'deal': deal}
    return {
        'attribute': attribute,
        'coverage': coverage,
        'presence': {'value': totals['named'], 'of': totals['named_of'], 'first': totals['first'],
                     'brand': inputs.get('brand'), 'rival': {'name': rival[0], 'first': rival[1]} if rival else None},
        'retired': retired,
        'promo': promo,
    }


def metric_counts(runs: List[dict], mentions: List[dict], vis_rows: List[dict], surface: str,
                  terms: Iterable[str] = (), brand_inputs: Optional[dict] = None,
                  surface_set: Optional[List[str]] = None) -> dict:
    """The counts behind the five rows on one surface, from the counts the
    Overview already reads: named and first over answered runs of the
    Overview's tier (unprompted when the cycle asked any, parity.surface_
    metrics); program named = our Layer 1 mention coded deal_cited or
    member_value_cited, over the answered runs of that tier naming us; prices
    exact of scored on the catalog tier, program terms exact of scored on the
    value tier. 2I-7: unprompted by soa_shared/unprompted.py, as the score.
    2I-8a: on `all`, every run given (build_score passes the pooled ones).
    2K-1 (scorer 11): brand-choice (unprompted plus comparison) when the
    cycle asked a comparison question, as the Overview reads it."""
    vis = parity.surface_metrics(runs, vis_rows, surface)
    tier = vis['tier']
    catalog = parity.surface_metrics([r for r in runs if r.get('tier') == 'catalog_accuracy'], [], surface)['total']
    value = parity.surface_metrics([r for r in runs if r.get('tier') == 'value_incentives'], [], surface)['total']
    in_tier = {r['run_id'] for r in runs if surfaces.on_surface(parity._surface_of(r), surface)
               and r.get('answer_status') == surfaces.ANSWERED
               and (tier == 'all' or (unprompted.is_unprompted(r, terms) if tier == rm.VIS_UNPROMPTED
                                      else unprompted.is_brand_choice(r, terms) if tier == rm.VIS_BRAND_CHOICE
                                      else r.get('tier') == tier))}
    ours = [m for m in mentions if m['run_id'] in in_tier and m.get('role') == 'primary' and m.get('mentioned')]
    return {
        # 2L-4: the brand tiles' counts beside the five, every merchant's
        **brand_counts(brand_inputs, vis_rows, surface, tier, vis['total'], surface_set),
        'tier': tier, 'agent_set': vis['agent_set'],
        'first': {'value': vis['total']['first'], 'of': vis['total']['named_of']},
        'share': {'value': vis['total']['named'], 'of': vis['total']['named_of']},
        'program': {'value': sum(1 for m in ours if m.get('deal_cited') or m.get('member_value_cited')),
                    'of': len({m['run_id'] for m in ours})},
        'exact': {'value': catalog['exact'], 'of': catalog['scored']},
        'terms': {'value': value['exact'], 'of': value['scored']},
    }


def _surface_note(surface: str, tier: str, key: str) -> str:
    # 2I-8a: "across every agent" on `all`, 2I-8's copy map
    where = parity._on_words(surface)
    if key in ('first', 'share', 'program'):
        return f"{where}, {parity._answers(tier) if tier in (rm.VIS_UNPROMPTED, rm.VIS_BRAND_CHOICE) else 'every answered question'}"
    return f"{where}, {'catalog' if key == 'exact' else 'value'} tier, exact of scored"


def _brand_sub(key: str, c: Optional[dict]) -> Optional[str]:
    """2L-4: a brand tile's sub-line, from its counts."""
    t = BRAND_TILE_TEMPLATES
    if c is None:
        return None
    if key == 'attribute':
        return t['attribute.sub'].format(pk=c['pages']['k'], pn=c['pages']['n'], ak=c['answers']['k'],
                                         an=c['answers']['n'])
    if key == 'promo':
        deal = c.get('deal')
        return t['promo.sub'].format(deal=deal['short'], k=deal['named'], n=deal['asked']) \
            if deal and deal['asked'] else t['promo.sub.none']
    if key == 'coverage':
        return t['coverage.sub'].format(n=c['value'], d=c['of'], names=', '.join(c.get('names') or [])
                                        or "the merchant's retailers")
    if key == 'presence':
        line = t['presence.sub'].format(brand=c.get('brand') or 'the brand', first=c.get('first', 0))
        if c.get('rival'):
            line += t['presence.rival'].format(rival=c['rival']['name'], n=c['rival']['first'])
        return line
    if key == 'retired':
        line = t['retired.sub'].format(label=c.get('label'), by=c.get('by') or 'the brand')
        if c.get('successor') and c.get('successor_named') is not None:
            line += t['retired.successor'].format(successor=c['successor'], n=c['successor_named'])
        return line
    return None


def _brand_note(key: str, surface: str, tier: str) -> Optional[str]:
    where = parity._on_words(surface)
    if key == 'presence':
        return _surface_note(surface, tier, 'share')
    if key in ('coverage', 'retired', 'attribute', 'promo'):
        return BRAND_TILE_TEMPLATES[f'note.{key}'].format(where=where)
    return None


def build_brand_metrics(counts: Dict[str, dict], surface: str, previous: Optional[dict]) -> List[dict]:
    """2L-4: a brand merchant's five tiles (BRAND_METRICS) on `surface`, the
    retailer rows' shape plus `state` (measured | not_measured), `reason`
    and `sub`. A not-measured tile has no value, denominator or delta. A
    delta as build_metrics gives one; a previous score stored before the
    tile was counted has none, and says so."""
    out = []
    comparable = bool(previous and previous.get('comparable'))
    prev_counts = (previous or {}).get('metric_counts') or {}
    for key, name in BRAND_METRICS:
        now = counts[surface].get(key)
        delta, reason = None, None
        if now is not None:
            prev = (prev_counts.get(surface) or {}).get(key) if comparable else None
            if prev is not None:
                delta = now['value'] - prev['value']
            elif comparable:
                reason = BRAND_TILE_TEMPLATES['previous.no_tile'].format(code=previous.get('cycle'))
            else:
                reason = (previous or {}).get('reason') or TEMPLATES['previous.first_cycle']
        out.append({'key': key, 'name': name, 'state': 'measured' if now is not None else 'not_measured',
                    'reason': None if now is not None else BRAND_TILE_TEMPLATES[f'{key}.not_measured'],
                    'value': now['value'] if now else None, 'denominator': now['of'] if now else None,
                    'sub': _brand_sub(key, now), 'surface': surface,
                    'surface_note': _brand_note(key, surface, counts[surface]['tier']) if now else None,
                    'delta': delta, 'delta_reason': reason,
                    'by_surface': {s: {'value': c[key]['value'], 'of': c[key]['of']} for s, c in counts.items()
                                   if s != surfaces.ALL and c.get(key)}})
    return out


def build_metrics(counts: Dict[str, dict], surface: str, previous: Optional[dict]) -> List[dict]:
    """The five rows on `surface` (2I-8a: `all`, every pooled agent, as the
    Overview reads it; before, the highest-fidelity pooled surface), each
    pooled surface's value and denominator beside in `by_surface`. A delta
    only when the previous cycle is comparable and stored counts on the same
    key, else null with the reason (a score stored before 2I-8a has no `all`)."""
    out = []
    comparable = bool(previous and previous.get('comparable'))
    prev_counts = (previous or {}).get('metric_counts') or {}
    for key, name, _, _ in METRICS:
        now = counts[surface][key]
        delta, reason = None, None
        if comparable and surface in prev_counts:
            delta = now['value'] - prev_counts[surface][key]['value']
        elif comparable:
            reason = TEMPLATES['previous.no_all'].format(code=previous.get('cycle'))
        else:
            reason = (previous or {}).get('reason') or TEMPLATES['previous.first_cycle']
        out.append({'key': key, 'name': name, 'value': now['value'], 'denominator': now['of'], 'surface': surface,
                    'surface_note': _surface_note(surface, counts[surface]['tier'], key), 'delta': delta,
                    'delta_reason': reason,
                    'by_surface': {s: c[key] for s, c in counts.items() if s != surfaces.ALL}})
    return out


def compare(now: dict, prev_code: Optional[str], prev_stored: Optional[dict],
            studies: Optional[tuple] = None) -> Optional[dict]:
    """2C-2a's rule, plus the scorer: comparable only with the same pooled
    surfaces, the same agents on each, and the same scorer version. 2K-4
    (B1): soa_shared/cycle_compare.cycles_comparable decides, as it does for
    the Changes block and the revenue history, so the same study (or the
    same questions) and the same measured set come first and second;
    studies is ({'study', 'questions'} now, the same for the previous)."""
    if prev_code is None:
        return None
    base = {'cycle': prev_code, 'scorer_version': None, 'score': None, 'comparable': False}
    if not prev_stored:
        return {**base, 'reason': TEMPLATES['previous.not_stored'].format(code=prev_code)}
    base.update(scorer_version=prev_stored.get('scorer_version'), score=prev_stored.get('score'))
    ok, condition, reason = cycle_compare.cycles_comparable(
        *score_facts(now, prev_code, prev_stored, studies), on=None, agent_name=parity._agent, surface_name=_surface_words)
    if not ok:
        return {**base, 'reason': reason, 'condition': condition}
    now_max, prev_max = now.get('applicable_max'), prev_stored.get('applicable_max')
    changed = prev_max is not None and now_max is not None and round(float(prev_max), 1) != round(float(now_max), 1)
    return {**base, 'comparable': True, 'reason': None, 'condition': None, 'metric_counts': prev_stored.get('metric_counts'),
            'delta': None if now['score'] is None or prev_stored.get('score') is None else now['score'] - prev_stored['score'],
            'applicable_max': prev_max,
            'applicable_note': TEMPLATES['previous.applicable'].format(prev=_fmt(float(prev_max)), now=_fmt(float(now_max)))
            if changed else None,
            'dimension_deltas': dimension_deltas(now, prev_stored)}


def score_facts(now: dict, prev_code: str, prev_stored: dict, studies: Optional[tuple]) -> tuple:
    """2K-4: (this cycle, the previous) as cycle_compare reads a score: the
    scorer version, the pooled surfaces, the agents on each, the set the
    first-pick rows read and, for the previous, the sets its stored rows
    measured."""
    now_study, prev_study = studies or ({}, {})
    pooled = [s['surface'] for s in now['surfaces']]
    counts, prev_counts = now.get('metric_counts') or {}, prev_stored.get('metric_counts') or {}
    ms = now.get('metric_surface')
    reads = (counts.get(ms) or {}).get('tier')
    prev_m = prev_counts.get(ms) or {}
    prev_tier, prev_of = prev_m.get('tier'), ((prev_m.get('first') or {}).get('of') or 0)
    measured = {cycle_compare.UNPROMPTED: prev_of if prev_tier in (rm.VIS_UNPROMPTED, rm.VIS_BRAND_CHOICE) else 0,
                'comparison': prev_of if prev_tier == rm.VIS_BRAND_CHOICE else 0}
    a = cycle_compare.facts('this cycle', study=now_study.get('study'), questions=now_study.get('questions'),
                            scorer_version=now['scorer_version'], surfaces=pooled,
                            agents={s: (counts.get(s) or {}).get('agent_set') or [] for s in pooled},
                            reads=reads if prev_m else None)
    b = cycle_compare.facts(prev_code, study=prev_study.get('study'), questions=prev_study.get('questions'),
                            scorer_version=prev_stored.get('scorer_version'),
                            surfaces=[s['surface'] for s in prev_stored.get('surfaces') or []],
                            agents={s: (prev_counts.get(s) or {}).get('agent_set') or [] for s in pooled}, measured=measured)
    return a, b


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
                domain_checks: Optional[dict] = None, rivals: Optional[int] = None,
                terms: Optional[Iterable[str]] = None, kind: Optional[str] = None,
                brand_inputs: Optional[dict] = None) -> dict:
    """GET /api/console/score without `previous` (score_with_previous adds it).

    runs: load_score_runs (one per run, with tier, stage, outcome and the
    expectation's type). mentions: load_score_mentions (Layer 1, with role
    and strength). vis_rows: Visibility's byQuestion. access: supply's access
    payload as accessibility_from_supply maps it. reference_rows: supply's
    /reference rows. domain_checks: the cycle's stored domain-check record
    (soa_cycles.domain_checks, 2E), or None. rivals: how many competitors the
    cycle's comparison set tracks (load_tracked_rivals); None when not read,
    which scores as before 2I-6. terms: the brand's terms
    (rm.load_brand_terms); None or empty checks the tier alone (2I-7).
    kind: 2L-4, the merchant's ('brand' | 'seller'), which picks the five
    rows (`metric_kind`); brand_inputs: Visibility's routing and
    retired_named and the brand's name, the brand tiles' counts."""
    errors = read_errors or {}
    terms = list(terms or [])
    at('crawl counts')
    crawl = crawl_counts(access, reference_rows)
    program_stated = any(r.get('tier') == 'value_incentives' and r.get('expected_type') in MEMBER_TYPES for r in runs)
    ran = parity.ordered_surfaces({parity._surface_of(r) for r in runs})
    answered = {parity._surface_of(r) for r in runs if r.get('answer_status') == surfaces.ANSWERED}
    # 2I (scorer 7): an ungrounded surface is never pooled
    ungrounded = [s for s in ran if s not in surfaces.GROUNDED_KINDS]
    pooled = [s for s in ran if s in answered and s not in ungrounded]
    per = [score_surface(s, runs=runs, mentions=mentions, crawl=crawl, crawl_errors=errors,
                         program_stated=program_stated, domain_checks=domain_checks,
                         rivals_tracked=rivals is None or rivals > 0, terms=terms) for s in pooled]
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
    counts = {s: metric_counts(runs, mentions, vis_rows, s, terms, brand_inputs) for s in pooled}
    in_pool = [r for r in runs if parity._surface_of(r) in pooled]
    # 2I-8a: the rows count every pooled agent together, as the Overview does
    if pooled:
        counts = {surfaces.ALL: metric_counts(in_pool, mentions, [v for v in vis_rows if v.get('surface') in pooled],
                                              surfaces.ALL, terms, brand_inputs, pooled), **counts}
    agents = {surfaces.agent_of(r.get('platform')) or r.get('platform') for r in in_pool}
    questions = len({r.get('query_code') for r in in_pool})
    # 2I-7: the unprompted questions this score counted, and the ones left out
    asked = {r.get('query_code'): r for r in in_pool if unprompted.is_unprompted_tier(r.get('tier'))}
    counted = [q for q, r in asked.items() if unprompted.is_unprompted(r, terms)]
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
        'verdict': verdict(score, tv, unmeasured),
        'verdict_note': (TEMPLATES['verdict.withheld'].format(n=_fmt(unmeasured), total=TOTAL_MAX)
                         if score is not None and unmeasured else None),
        'surfaces': [{'surface': p['surface'], 'label': p['label'], 'score': p['score'], 'earned': p['earned'],
                      'applicable_max': p['applicable_max'],
                      'pillars': [{'code': k, 'score': v['score'], 'applicable_max': v['applicable_max']}
                                  for k, v in p['pillars'].items()]} for p in per],
        'surfaces_left_out': [{'surface': s, 'label': surfaces.SURFACE_LABELS.get(s, s),
                               'reason': TEMPLATES['reason.ungrounded'] if s in ungrounded else TEMPLATES['reason.no_answers']}
                              for s in ran if s not in pooled],
        'pillars': pillars,
        'biggest_gap': biggest_gap(per, dims),
        'metric_surface': surfaces.ALL if pooled else None,
        'metric_counts': counts,
        # 2L-4: which five rows the merchant reads; both sets are counted
        'metric_kind': 'brand' if kind == 'brand' else 'retailer',
        'coverage': {'surfaces': len(pooled), 'questions': questions, 'agents': len(agents), 'runs': len(in_pool),
                     'ran_no_answers': [s for s in ran if s not in answered and s not in ungrounded],
                     **({'ungrounded': ungrounded} if ungrounded else {}),
                     'line': TEMPLATES['coverage'].format(surfaces=_n(len(pooled), 'surface', 'surfaces'),
                                                          questions=_n(questions, 'question', 'questions'),
                                                          agents=_n(len(agents), 'agent', 'agents'))
                     + ''.join(TEMPLATES['coverage.no_answers'].format(surface=_surface_words(s))
                               for s in ran if s not in answered and s not in ungrounded)
                     + ''.join(TEMPLATES['coverage.ungrounded'].format(surface=_surface_words(s)) for s in ungrounded)},
        # 2I-7: the unprompted questions counted (soa_shared/unprompted.py),
        # those of an unprompted tier left out for naming the brand, and how
        # many of the tier's were category control
        'unprompted': {'questions': len(counted), 'named_the_brand': len(asked) - len(counted),
                       'category_control': sum(1 for r in asked.values() if r.get('tier') == 'category_control')},
        'inputs': {**(inputs or {}), 'domain_checks': {
            'checked_at': record.get('checked_at'), 'scored_domain': record.get('scored_domain'),
            'version': record.get('version'), 'revision': record_revision(record)} if record else None},
        'history': [],
        'read_errors': errors,
        'rules': TEMPLATES,
    }


def verdict(score: Optional[int], true_value: Optional[dict], unmeasured: float) -> Optional[str]:
    """The Audit's readiness verdict (scan_dimensions.compute_verdict, called
    as is: AGENT-READY at or above the bar with True Value at or above a
    quarter of its applicable points, else NOT AGENT-READY), only when no
    dimension is not measured. None otherwise; verdict_note says why."""
    if score is None or not true_value or unmeasured:
        return None
    return compute_verdict(score, true_value['score'] or 0.0, true_value['applicable_max'])


def with_previous(body: dict, prev_code: Optional[str], prev_stored: Optional[dict],
                  studies: Optional[tuple] = None) -> dict:
    """Adds `previous` and the five rows (whose deltas need it)."""
    at('comparing with the previous cycle')
    previous = compare(body, prev_code, prev_stored, studies)
    out = dict(body)
    out['previous'] = None if previous is None else {k: v for k, v in previous.items() if k != 'metric_counts'}
    ms = body['metric_surface']
    # 2L-4: both sets, keyed by merchant kind; `metrics` is the merchant's
    out['metrics_by_kind'] = {
        'retailer': build_metrics(body['metric_counts'], ms, previous) if ms else [],
        'brand': build_brand_metrics(body['metric_counts'], ms, previous)
        if ms and 'presence' in (body['metric_counts'].get(ms) or {}) else [],
    }
    out['metric_kind'] = body.get('metric_kind') or 'retailer'
    out['metrics'] = out['metrics_by_kind'][out['metric_kind']]
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


def load_tracked_rivals(conn, cycle: dict) -> int:
    """2I-6: how many competitors the cycle's comparison set tracks."""
    return conn.execute(text(
        "SELECT COUNT(*) FROM soa_cycle_entities WHERE cycle_id = :c AND role = 'competitor'"),
        {'c': cycle['id']}).scalar() or 0


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


def reference_refreshed_at(reference: Optional[dict]) -> Optional[str]:
    """2J-4: when rescore_cycle --refresh-reference last replaced the
    cycle's cached retailer-prices (the payload's own `refreshed_at`), None
    for a copy never refreshed."""
    return reference.get('refreshed_at') if isinstance(reference, dict) else None


def reference_input(reference: Optional[dict]) -> dict:
    """The score's `inputs` entry for the cached reference it was computed
    on: `cycle_reference_refreshed_at` for a refreshed copy, nothing for one
    never refreshed (so such a cycle's score body is as it was)."""
    refreshed = reference_refreshed_at(reference)
    return {'cycle_reference_refreshed_at': refreshed} if refreshed else {}


def outcomes_scored_at(conn, cycle_id: int) -> Optional[str]:
    """2N-2: when the cycle's Layer 2 outcomes were last written (the newest
    soa_expectation_outcomes.scored_at, ISO 8601), None for a cycle with none
    (or a table without the column: the score is served as stored, as before)."""
    try:
        value = conn.execute(text("SELECT MAX(scored_at) FROM soa_expectation_outcomes WHERE cycle_id = :c"),
                             {'c': cycle_id}).scalar()
    except Exception:  # noqa: BLE001 - a test schema without scored_at
        return None
    if value is None:
        return None
    return value.isoformat() if hasattr(value, 'isoformat') else str(value)


def _instant(value) -> Optional[datetime]:
    """An ISO 8601 stamp as an aware datetime; one with no zone is UTC (the
    column's NOW() on Postgres, sqlite's text). None when it does not parse."""
    try:
        at = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def needs_recompute(body: Optional[dict], domain_checks: Optional[dict],
                    reference: Optional[dict] = None, outcomes_at: Optional[str] = None) -> Optional[str]:
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
    # 2L-4: a score stored before the brand tiles were counted beside the five
    if body.get('metric_surface') and 'presence' not in ((body.get('metric_counts') or {}).get(body['metric_surface']) or {}):
        return 'brand tiles not counted'
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
    # 2J-4: a refresh (or a restore) re-classified the cycle's price
    # outcomes against a new cached reference, which no other trigger sees.
    # A score stored before 2J-4 read a copy never refreshed (None).
    refreshed = reference_refreshed_at(reference)
    if refreshed != inputs.get('cycle_reference_refreshed_at'):
        return 'cycle reference refreshed' if refreshed else 'cycle reference restored'
    # 2N-2: rescore_cycle re-scored the outcomes after the score was stored, with
    # no reference refresh to stamp it. FL14's Attribute accuracy tile read
    # "answers 0 of 0" and its promo note the old deal kind, a score stored before
    # 2N-1 and served since. `outcomes_at` is outcomes_scored_at()'s.
    scored, written = _instant(inputs.get('scored_at')), _instant(outcomes_at) if outcomes_at else None
    if scored and written and written > scored:
        return 'outcomes re-scored'
    return None


#: 2I: what each scorer version changed, for the recompute line.
SCORER_CHANGES = {'7': 'ungrounded surfaces excluded from pooling',
                  '8': 'share of mentions not measured without a tracked competitor',
                  '9': 'category-control questions count as unprompted',
                  '10': 'metric rows count every agent',
                  '11': 'brand-choice set for Lost and the first-pick tiles'}


def _no_rivals(body: dict) -> bool:
    """Share of mentions went unmeasured for want of a rival on some surface."""
    return any(row.get('reason') == TEMPLATES['reason.no_rivals']
               for p in body.get('pillars') or [] for d in p.get('dimensions') or [] if d.get('code') == 'share_of_mentions'
               for row in (d.get('by_surface') or {}).values())


#: whether the new score is one the version's change applies to
def _category_control(body: dict) -> bool:
    """2I-7: the cycle asked category-control questions, or one of its
    unprompted questions named the brand: the two the rule changed."""
    u = body.get('unprompted') or {}
    return bool(u.get('category_control') or u.get('named_the_brand'))


SCORER_CHANGE_APPLIES = {'7': lambda new: bool((new.get('coverage') or {}).get('ungrounded')),
                         '8': _no_rivals,
                         '9': _category_control,
                         # 2I-8a never moves a score (only the rows beside it), so it never explains one
                         '10': lambda _new: False,
                         # 2K-1 never moves a score either: no dimension reads the brand-choice set
                         '11': lambda _new: False}


_NOT_CARRIED = object()


def _domain_checks_input(body: dict):
    """inputs.domain_checks.revision; None for a score that read no record,
    _NOT_CARRIED for one stored before the score recorded it."""
    inputs = body.get('inputs') or {}
    if 'domain_checks' not in inputs:
        return _NOT_CARRIED
    record = inputs['domain_checks']
    return record and record.get('revision')


def _reference_read_input(body: dict):
    """When the reference read the score used was read (its run's read_at,
    else finished_at). A score with no reference run (a failed read) does not
    carry one."""
    run = (body.get('inputs') or {}).get('reference_run')
    if not isinstance(run, dict):
        return _NOT_CARRIED
    return run.get('read_at') or run.get('finished_at') or _NOT_CARRIED


def _incentive_flags_input(body: dict):
    """Deal Citability's seen half as the score stored it: its state, n of d,
    and each flag's check. _NOT_CARRIED when the body has no such part."""
    for pillar in body.get('pillars') or []:
        for d in pillar.get('dimensions') or []:
            if d.get('code') != 'deal_citability':
                continue
            for row in (d.get('by_surface') or {}).values():
                for part in row.get('parts') or []:
                    if part.get('half') == 'seen':
                        return (part.get('state'), part.get('numerator'), part.get('denominator'), part.get('reason'),
                                [(c.get('code'), c.get('state')) for c in part.get('checks') or []])
    return _NOT_CARRIED


#: 2I-2: the inputs re-read from supply or the cycle that can move a score
#: across a scorer version, each read from the stored body itself.
RECOMPUTE_INPUTS = (('domain checks', _domain_checks_input),
                    ('reference read', _reference_read_input),
                    ('incentive flags', _incentive_flags_input))


def changed_inputs(old: dict, new: dict) -> List[str]:
    """The inputs that differ between two scores, compared only where both
    carry the input: none is guessed."""
    out = []
    for name, read in RECOMPUTE_INPUTS:
        a, b = read(old), read(new)
        if a is not _NOT_CARRIED and b is not _NOT_CARRIED and a != b:
            out.append(name)
    return out


def recompute_line(old: dict, new: dict, reason: str) -> str:
    """Why a stored score was replaced. Across a scorer version: "scorer 6 →
    7: ungrounded surfaces excluded from pooling" when an ungrounded surface
    was in fact dropped (the new score's coverage.ungrounded) and the score
    moved. Otherwise "scorer 6 → 7", with " · <input> changed" for each
    input the two stored bodies show differs (changed_inputs). Any other
    reason as it is."""
    prev, now = old.get('scorer_version'), new.get('scorer_version')
    if prev == now or prev is None or now is None:
        return reason
    # 2I-6: every version's change between the two that applies to the new score (6 -> 8 can be both)
    try:
        between = [str(v) for v in range(int(prev) + 1, int(now) + 1)]
    except ValueError:
        between = [str(now)]
    changes = [SCORER_CHANGES[v] for v in between
               if v in SCORER_CHANGES and SCORER_CHANGE_APPLIES.get(v, lambda _new: False)(new)]
    if changes and old.get('score') != new.get('score'):
        return TEMPLATES['recompute.version_changed'].format(prev=prev, now=now, change=', '.join(changes))
    return (TEMPLATES['recompute.version'].format(prev=prev, now=now)
            + ''.join(TEMPLATES['recompute.input_changed'].format(input=i) for i in changed_inputs(old, new)))


def carry_history(new: dict, old: Optional[dict], reason: str) -> dict:
    """The new score with the one it replaces kept in its history (newest
    last, HISTORY_KEEP at most), so a report can show both."""
    if not old:
        return new
    entry = {k: old.get(k) for k in ('score', 'earned', 'applicable_max', 'measured', 'scorer_version', 'adapter_revision')}
    entry['scored_at'] = (old.get('inputs') or {}).get('scored_at')
    # 2I-2: the per-pillar scores it had, so the console can show the deltas
    entry['pillars'] = [{k: p.get(k) for k in ('code', 'score', 'applicable_max')} for p in old.get('pillars') or []]
    entry['replaced_because'] = recompute_line(old, new, reason)
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
