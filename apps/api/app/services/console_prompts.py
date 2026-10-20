"""
2J-2: the Prompts read model, GET /api/console/prompts?merchant=.

The demo's Prompts page (`#pg.prompts`): "36 prompts in 4 sets, 1 run each on
5 agents, every week", the sets with their counts and answers, three example
prompts per set, and the agents with their method and last status. From
stored data only: no LLM, no new table.

  study        the merchant's current study: the study of its newest cycle,
               else the newest study generated for it. None when it has none.
  sets         the study's tiers in stage order (an untiered question is in
               `unprompted`, as Visibility files it), each with its question
               count, its first three questions (generation order) and
               answers_per_cycle = questions x the agents that ran on the
               study's last cycle (the newest with a run).
  runs_per_question  the last full-loop request's for the study, else the
               last cycle's runs_per_query.
  agents       the surfaces report (/api/console/surfaces, 2I-2): every
               surface that can be dispatched (grounded and available) and
               any that ran on the last cycle, each with its method and its
               last-cycle runs and answered count.
  cadence      None: soa stores no schedule (build_study says the same), so
               the headline says nothing about how often.
"""
from typing import Dict, List, Optional

from sqlalchemy import text

from app.services import console_read_models as rm
from soa_shared import surfaces

#: the sets, in stage order (Visibility's tier order)
SET_ORDER = rm.VIS_TIER_ORDER
EXAMPLES = 3


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def current_study(cycles: List[dict], jobs: List[dict]) -> Optional[dict]:
    """The job of the merchant's newest cycle, else its newest job.
    cycles: the merchant's, newest first. jobs: the merchant's, newest first."""
    by_type = {j['study_type']: j for j in jobs}
    for c in cycles:
        if c['study_type'] in by_type:
            return by_type[c['study_type']]
    return jobs[0] if jobs else None


def last_cycle(conn, cycles: List[dict], study_type: str) -> Optional[dict]:
    """The study's newest cycle with a run, else its newest."""
    mine = [c for c in cycles if c['study_type'] == study_type]
    for c in mine:
        if conn.execute(text("SELECT 1 FROM soa_runs WHERE cycle_id = :c LIMIT 1"), {'c': c['id']}).first():
            return c
    return mine[0] if mine else None


def agent_runs(conn, cycle: Optional[dict]) -> Dict[str, dict]:
    """{platform: {runs, answered, errored}} on the cycle."""
    if cycle is None:
        return {}
    out: Dict[str, dict] = {}
    for r in conn.execute(text("""
        SELECT platform, COUNT(*) AS runs,
               SUM(CASE WHEN answer_status = 'answered' THEN 1 ELSE 0 END) AS answered,
               SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errored
        FROM soa_runs WHERE cycle_id = :c GROUP BY platform
    """), {'c': cycle['id']}).mappings():
        out[r['platform']] = {'runs': int(r['runs'] or 0), 'answered': int(r['answered'] or 0),
                              'errored': int(r['errored'] or 0)}
    return out


def last_status(counts: Optional[dict]) -> str:
    if not counts or not counts['runs']:
        return 'not_run'
    if counts['answered'] == counts['runs']:
        return 'answered'
    return 'partial' if counts['answered'] else 'no_answers'


def build_agents(report: List[dict], ran: Dict[str, dict]) -> List[dict]:
    """The surfaces report's dispatchable surfaces and those that ran, in the
    demo's agent order (ChatGPT, Gemini, AI Mode, Perplexity, Copilot, Claude)."""
    rows = [s for s in report if (s.get('grounded') and s.get('available')) or s['id'] in ran]
    known = {s['id'] for s in rows}
    for platform in ran:
        if platform not in known:   # a stored id no longer in the registry (a legacy 'gemini' run)
            rows.append({'id': platform, 'label': platform, 'agent': surfaces.agent_of(platform) or platform,
                         'surface': surfaces.surface_of(platform), 'fidelity_label': None, 'fidelity': None,
                         'collector': None, 'grounded': False, 'available': False})
    order = list(rm.AGENT_NAMES)
    registry = [s['id'] for s in report]
    rows.sort(key=lambda s: (order.index(s['agent']) if s.get('agent') in order else 99,
                             registry.index(s['id']) if s['id'] in registry else 99))
    out = []
    for s in rows:
        counts = ran.get(s['id'])
        out.append({
            'id': s['id'], 'agent': s.get('agent'), 'name': rm.AGENT_NAMES.get(s.get('agent'), s.get('label')),
            'label': s.get('label'), 'surface': s.get('surface'),
            'method': s.get('fidelity_label'), 'method_detail': s.get('fidelity'), 'collector': s.get('collector'),
            'grounded': bool(s.get('grounded')), 'available': bool(s.get('available')),
            'worker_note': s.get('worker_note'),
            'last_status': last_status(counts),
            'last_runs': (counts or {}).get('runs', 0), 'last_answered': (counts or {}).get('answered', 0),
            'last_errored': (counts or {}).get('errored', 0),
        })
    return out


def build_prompts(merchant: Optional[str], job: Optional[dict], questions: List[dict], cycle: Optional[dict],
                  ran: Dict[str, dict], report: List[dict], full_loop: Optional[dict]) -> dict:
    """The Prompts page for one merchant. questions: the study's, in
    generation order ({tier, query_text, query_code, stage})."""
    agents = build_agents(report, ran)
    on_last = len(ran)
    by_set: Dict[str, List[dict]] = {}
    for q in questions:
        by_set.setdefault(q.get('tier') or rm.VIS_UNPROMPTED, []).append(q)
    keys = [t for t in SET_ORDER if t in by_set] + sorted(t for t in by_set if t not in SET_ORDER)
    sets = []
    for key in keys:
        qs = by_set[key]
        sets.append({
            'tier': key, 'name': rm.VIS_TIER_LABELS.get(key, key), 'count': len(qs),
            'examples': [q.get('query_text') or '' for q in qs[:EXAMPLES]],
            'answers_per_cycle': len(qs) * on_last,
            'line': f"{_plural(len(qs), 'prompt', 'prompts')}, {_plural(len(qs) * on_last, 'answer', 'answers')} a cycle",
        })
    if full_loop and full_loop.get('runs_per_query'):
        runs, runs_source = int(full_loop['runs_per_query']), 'full_loop'
    elif cycle and cycle.get('runs_per_query'):
        runs, runs_source = int(cycle['runs_per_query']), 'cycle'
    else:
        runs, runs_source = None, None
    total = len(questions)
    headline = f"{_plural(total, 'prompt', 'prompts')} in {_plural(len(sets), 'set', 'sets')}"
    if runs is not None:
        headline += f", {_plural(runs, 'run', 'runs')} each"
    if on_last:
        headline += f" on {_plural(on_last, 'agent', 'agents')}"
    return {
        'merchant': merchant,
        'study': ({'id': job['study_type'], 'name': job.get('study_name') or job['study_type']} if job else None),
        'cycle': (cycle or {}).get('cycle_code'),
        'last_run': rm._iso((cycle or {}).get('start_date')),
        'prompts': total,
        'set_count': len(sets),
        'runs_per_question': runs,
        'runs_per_question_source': runs_source,
        'full_loop_id': (full_loop or {}).get('id') if runs_source == 'full_loop' else None,
        'agents_on_last_cycle': on_last,
        'answers_per_cycle': total * on_last,
        'cadence': None,
        'headline': headline,
        'sets': sets,
        'agents': agents,
    }
