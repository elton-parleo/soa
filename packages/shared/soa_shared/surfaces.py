"""
2B §4: surface fidelity — what kind of surface an answer came from, and who
collected it.

Every run row carries `surface` (api | grounded_api | consumer_ui) and
`collector`, and every per-surface accuracy is split by `surface`, never
pooled. A surface here is a CONFIGURATION: `grounded_api` means the request
carried a search/grounding tool (whether a given run used it is
soa_runs.search_triggered), `consumer_ui` means the logged-out consumer page
read by a hosted scraper.

ONE catalogue, used by the pipeline (which runner, what to stamp on the
run), the API (what the Create Study modal lists) and the console read
models (which agent an answer belongs to). Sync copies to
apps/api/soa_shared/ and apps/pipeline/soa_shared/.

Consumer surfaces run only through SerpApi, and only on a worker with
SOA_CONSUMER_SURFACES_ENABLED=1 and SERPAPI_API_KEY set. There is no
Playwright or browser-automation path, by decision. The dialog lists what
the worker reports it can run (worker_list, from soa_worker_surfaces): the
API never reads those two settings, since it never calls SerpApi. Gemini
web and ChatGPT web have no hosted provider we have verified; they are
listed as not available, with that reason, so the modal says so rather
than hiding them.

2I-6: a surface names a configuration, not a model. Perplexity's runner asks
the model SOA_PERPLEXITY_MODEL configures (soa_shared/config.py, default
sonar-pro); it is grounded whichever Sonar model that is.
"""
import os
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional

API = 'api'
GROUNDED_API = 'grounded_api'
CONSUMER_UI = 'consumer_ui'
SURFACE_KINDS = (API, GROUNDED_API, CONSUMER_UI)

#: 2I-8: the console's pooled read, every run in the cycle whatever its
#: surface, as the console demo counts them. A read-model key, listed first
#: and read by default; never a surface kind, never a run's surface, never
#: dispatched (resolve refuses it: it is no surface id or alias).
ALL = 'all'

SURFACE_LABELS = {
    ALL: 'All agents',
    API: 'API, no tools',
    GROUNDED_API: 'API with search grounding',
    CONSUMER_UI: 'Consumer UI, logged out',
}


def with_all(keys: Iterable[str]) -> List[str]:
    """2I-8: a read model's surface list, `all` first, then the surfaces in
    the order given. Empty when there are none (a cycle with no run)."""
    keys = [k for k in keys if k != ALL]
    return [ALL, *keys] if keys else []


def on_surface(row_surface: Optional[str], surface: str) -> bool:
    """2I-8: whether a row counts toward `surface`: every row toward `all`."""
    return surface == ALL or row_surface == surface

ANSWERED = 'answered'
NO_AI_ANSWER = 'no_ai_answer'
SIGN_IN_WALL = 'sign_in_wall'
BLOCKED = 'blocked'
ANSWER_STATUSES = (ANSWERED, NO_AI_ANSWER, SIGN_IN_WALL, BLOCKED)
#: Results that are not answers: scored absent, counted in coverage,
#: excluded from accuracy.
NO_ANSWER_STATUSES = (NO_AI_ANSWER, SIGN_IN_WALL, BLOCKED)

NO_VERIFIED_PROVIDER = 'No hosted provider we have verified. Not built (no browser automation).'


@dataclass(frozen=True)
class Surface:
    #: The platform id stored in soa_runs.platform.
    id: str
    label: str
    surface: str
    collector: str
    #: The console's AgentId this surface's answers belong to.
    agent: str
    #: One line the modal shows beside the label.
    fidelity: str
    consumer: bool = False
    #: Set when the surface can never run here, whatever the environment.
    never_available: Optional[str] = None
    #: 2I: the runner's request lets the model search the web (a search or
    #: grounding tool, or a search product's own answer). Classified from
    #: each runner's code; only grounded surfaces are dispatched and pooled.
    grounded: bool = False

    def as_dict(self, *, env=None, configured=None) -> dict:
        """With `configured` (the worker's report), availability comes from
        the report (reported_reason); without it, from `env` (the worker's
        own environment, unavailable_reason)."""
        out = asdict(self)
        reason = (unavailable_reason(self.id, env=env) if configured is None
                  else reported_reason(self.id, configured))
        out['available'] = reason is None
        out['unavailable_reason'] = reason
        out['surface_label'] = SURFACE_LABELS[self.surface]
        out.pop('never_available', None)
        return out


SURFACES: List[Surface] = [
    Surface('chatgpt_api', 'ChatGPT (OpenAI API)', API, 'openai', 'chatgpt',
            'OpenAI Responses API, no tools: answers from the model alone'),
    Surface('chatgpt', 'ChatGPT with web search (OpenAI API)', GROUNDED_API, 'openai', 'chatgpt',
            'OpenAI Responses API with the web_search tool available. The model decides whether to search.',
            grounded=True),
    Surface('gemini_api', 'Gemini (Gemini API)', API, 'google_genai', 'gemini',
            'Gemini API, no grounding tool: answers from the model alone'),
    Surface('gemini_grounded', 'Gemini with Google Search (Gemini API)', GROUNDED_API, 'google_genai',
            'gemini', 'Gemini API with the Google Search grounding tool', grounded=True),
    Surface('perplexity', 'Perplexity Sonar (Perplexity API)', GROUNDED_API, 'perplexity', 'perplexity',
            'Perplexity Sonar, grounded by nature, with its citations', grounded=True),
    Surface('claude', 'Claude with web search (Anthropic API)', GROUNDED_API, 'anthropic', 'claude',
            'Anthropic Messages API with the web_search tool available. The model decides whether to search.',
            grounded=True),
    Surface('aimode', 'Google AI Mode (consumer, via SerpApi)', CONSUMER_UI, 'serpapi', 'aimode',
            'google.com/search?udm=50, logged out, read by SerpApi (engine google_ai_mode)', consumer=True,
            grounded=True),
    Surface('copilot', 'Bing Copilot (consumer, via SerpApi)', CONSUMER_UI, 'serpapi', 'copilot',
            'Bing Copilot Search, logged out, read by SerpApi (engine bing_copilot)', consumer=True,
            grounded=True),
    Surface('gemini_web', 'Gemini web app (consumer)', CONSUMER_UI, '-', 'gemini',
            'gemini.google.com, logged out', consumer=True, never_available=NO_VERIFIED_PROVIDER),
    Surface('chatgpt_web', 'ChatGPT web app (consumer)', CONSUMER_UI, '-', 'chatgpt',
            'chatgpt.com, logged out', consumer=True, never_available=NO_VERIFIED_PROVIDER),
]

#: Platform ids stored before 2B that are not selectable surfaces today.
#: 'gemini' rows were the ungrounded API. Read only: a new cycle never
#: stores this id (see ALIASES).
LEGACY = {'gemini': Surface('gemini', 'Gemini (Gemini API, legacy id)', API, 'google_genai', 'gemini',
                            'Stored under the pre-2B id. The ungrounded Gemini API.')}

#: 2D: the names a caller may send that are not surface ids, each to the id
#: it means. Explicit and complete: a name that is neither an id nor here is
#: refused, never resolved to anything. 'gemini' is the ungrounded API, what
#: the September cycle's 'gemini' rows were. Before 2D it was aliased to
#: gemini_grounded when a cycle RAN, so cycle 229, created with ["gemini"],
#: has its runs on grounded_api: the drift docs/console-read-models.md (2D)
#: describes. A cycle that should land where 229 did asks for
#: gemini_grounded by name.
ALIASES = {'gemini': 'gemini_api'}

_BY_ID = {s.id: s for s in SURFACES}


class UnknownSurface(ValueError):
    """A name that is neither a surface id nor an alias."""


def resolve(name: str) -> Surface:
    """The surface a name means, by id, else by ALIASES. Raises
    UnknownSurface otherwise. Cycle creation resolves through this and
    stores what it returns, so a cycle and its runs carry the id and
    surface that ran, never the alias."""
    if name in _BY_ID:
        return _BY_ID[name]
    if name in ALIASES:
        return _BY_ID[ALIASES[name]]
    raise UnknownSurface(f"unknown surface {name!r}: send an id from /api/console/surfaces "
                         f"(aliases: {', '.join(f'{a} = {i}' for a, i in ALIASES.items())})")


def resolve_platforms(names: Iterable[str]) -> List[str]:
    """The resolved ids, in order, each once (gemini and gemini_api are one)."""
    return list(dict.fromkeys(resolve(n).id for n in names))


def surfaces_by_platform(platform_ids: Iterable[str]) -> Dict[str, str]:
    """{resolved id: surface}, what soa_cycles.surfaces stores."""
    return {s.id: s.surface for s in (resolve(p) for p in platform_ids)}


#: 2I: the surface kinds whose answers come from a model that could search.
#: An `api` answer is the model alone: listed, never pooled into the score.
GROUNDED_KINDS = (GROUNDED_API, CONSUMER_UI)

#: 2I: what to send instead of an ungrounded id.
GROUNDED_INSTEAD = {'gemini_api': 'gemini_grounded', 'chatgpt_api': 'chatgpt'}

UNGROUNDED_SURFACE = 'ungrounded_surface_not_allowed'
SURFACE_NOT_CONFIGURED = 'surface_not_configured'


def is_grounded(platform: str) -> bool:
    s = get(platform)
    return bool(s and s.grounded)


def ungrounded_refusal(names: Iterable[str]) -> Optional[dict]:
    """2I: the 422 body for a dispatch naming an ungrounded surface, alias
    or id, or None when every name is grounded. Unknown names are left to
    resolve(), which refuses them on its own."""
    lines = []
    for name in names:
        try:
            s = resolve(name)
        except UnknownSurface:
            continue
        if s.grounded:
            continue
        what = f"{name!r} ({s.id})" if name != s.id else repr(s.id)
        instead = GROUNDED_INSTEAD.get(s.id)
        lines.append(f"{what} answers without searching. "
                     + (f"Use {instead}." if instead else "It is not a grounded surface."))
    if not lines:
        return None
    # 2L-1: one sentence per surface, no semicolons (house rule)
    return {'code': UNGROUNDED_SURFACE,
            'message': 'Only grounded surfaces run. ' + ' '.join(lines)}


def unconfigured_refusal(platform_ids: Iterable[str], configured: Dict[str, bool]) -> Optional[dict]:
    """2I: the 422 body for a dispatch naming a surface the worker reported
    it has no key for, or None. A surface the worker has not reported on
    (no row yet) is not refused: the worker reports at boot."""
    missing = [p for p in platform_ids if configured.get(p) is False]
    if not missing:
        return None
    return {'code': SURFACE_NOT_CONFIGURED,
            'message': f"no key on the worker for {', '.join(missing)}"}


def default_platforms(configured: Dict[str, bool]) -> List[str]:
    """2I: the agents a run starts with: every grounded surface the worker
    has a key for, in registry order."""
    return [s.id for s in SURFACES if s.grounded and configured.get(s.id) is True]


def get(platform: str) -> Optional[Surface]:
    return _BY_ID.get(platform) or LEGACY.get(platform)


def surface_of(platform: str) -> Optional[str]:
    s = get(platform)
    return s.surface if s else None


def collector_of(platform: str) -> Optional[str]:
    s = get(platform)
    return s.collector if s else None


def agent_of(platform: str) -> Optional[str]:
    s = get(platform)
    return s.agent if s else None


def consumer_enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return env.get('SOA_CONSUMER_SURFACES_ENABLED') == '1' and bool(env.get('SERPAPI_API_KEY'))


def unavailable_reason(platform: str, *, env=None) -> Optional[str]:
    """Why this surface will not run here, or None when it will."""
    s = get(platform)
    if s is None:
        return f'unknown surface {platform!r}'
    if s.never_available:
        return s.never_available
    if s.consumer:
        env = os.environ if env is None else env
        if env.get('SOA_CONSUMER_SURFACES_ENABLED') != '1':
            return 'consumer surfaces are off (SOA_CONSUMER_SURFACES_ENABLED is not 1)'
        if not env.get('SERPAPI_API_KEY'):
            return 'SERPAPI_API_KEY is not set'
    return None


NO_KEY_ON_WORKER = 'no key on the worker'
WORKER_NOT_REPORTED = 'the worker has not reported yet'


def reported_reason(platform: str, configured: Optional[Dict[str, bool]] = None) -> Optional[str]:
    """2I-2: why this surface will not run, from the worker's report
    ({id: bool}, soa_worker_surfaces) and never from this process's
    environment: the API holds none of the runners' settings. A surface the
    worker has not reported on has no reason; it is not refused."""
    s = get(platform)
    if s is None:
        return f'unknown surface {platform!r}'
    if s.never_available:
        return s.never_available
    if (configured or {}).get(platform) is False:
        return NO_KEY_ON_WORKER
    return None


def worker_list(configured: Dict[str, bool]) -> List[dict]:
    """
    2I-2: what the dialog shows, from the worker's report: every surface
    with a runner, in registry order, then the surfaces with no verified
    provider. One the worker reported no key for is listed not available
    ('no key on the worker'); one it has not reported on is listed
    available, with `worker_note` 'the worker has not reported yet', API
    and consumer surfaces alike.
    """
    out = []
    for s in [s for s in SURFACES if not s.never_available] + [s for s in SURFACES if s.never_available]:
        row = s.as_dict(configured=configured)
        state = configured.get(s.id)
        row['worker_note'] = (None if s.never_available or state is True else
                              NO_KEY_ON_WORKER if state is False else WORKER_NOT_REPORTED)
        out.append(row)
    return out


def modal_list(env=None) -> List[dict]:
    """
    What the Create Study modal shows: every surface that will actually
    run in `env` (a worker's environment), with its fidelity label, then
    the surfaces that cannot run here for a reason that is not a setting
    (no verified provider), shown as not available with that reason. The
    API does not call this: the dialog lists what the worker reports it can
    run (worker_list).
    """
    runnable = [s.as_dict(env=env) for s in SURFACES if unavailable_reason(s.id, env=env) is None]
    never = [s.as_dict(env=env) for s in SURFACES if s.never_available]
    return runnable + never
