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

Consumer surfaces run only through SerpApi, and only with
SOA_CONSUMER_SURFACES_ENABLED=1 and SERPAPI_API_KEY set. There is no
Playwright or browser-automation path, by decision. Gemini web and ChatGPT
web have no hosted provider we have verified; they are listed as not
available, with that reason, so the modal says so rather than hiding them.
"""
import os
from dataclasses import asdict, dataclass
from typing import Dict, Iterable, List, Optional

API = 'api'
GROUNDED_API = 'grounded_api'
CONSUMER_UI = 'consumer_ui'
SURFACE_KINDS = (API, GROUNDED_API, CONSUMER_UI)

SURFACE_LABELS = {
    API: 'API, no tools',
    GROUNDED_API: 'API with search grounding',
    CONSUMER_UI: 'Consumer UI, logged out',
}

ANSWERED = 'answered'
NO_AI_ANSWER = 'no_ai_answer'
SIGN_IN_WALL = 'sign_in_wall'
BLOCKED = 'blocked'
ANSWER_STATUSES = (ANSWERED, NO_AI_ANSWER, SIGN_IN_WALL, BLOCKED)
#: Results that are not answers: scored absent, counted in coverage,
#: excluded from accuracy.
NO_ANSWER_STATUSES = (NO_AI_ANSWER, SIGN_IN_WALL, BLOCKED)

NO_VERIFIED_PROVIDER = 'no hosted provider we have verified; not built (no browser automation)'


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

    def as_dict(self, *, env=None) -> dict:
        out = asdict(self)
        reason = unavailable_reason(self.id, env=env)
        out['available'] = reason is None
        out['unavailable_reason'] = reason
        out['surface_label'] = SURFACE_LABELS[self.surface]
        out.pop('never_available', None)
        return out


SURFACES: List[Surface] = [
    Surface('chatgpt_api', 'ChatGPT (OpenAI API)', API, 'openai', 'chatgpt',
            'OpenAI Responses API, no tools: answers from the model alone'),
    Surface('chatgpt', 'ChatGPT with web search (OpenAI API)', GROUNDED_API, 'openai', 'chatgpt',
            'OpenAI Responses API with the web_search tool available; the model decides whether to search'),
    Surface('gemini_api', 'Gemini (Gemini API)', API, 'google_genai', 'gemini',
            'Gemini API, no grounding tool: answers from the model alone'),
    Surface('gemini_grounded', 'Gemini with Google Search (Gemini API)', GROUNDED_API, 'google_genai',
            'gemini', 'Gemini API with the Google Search grounding tool'),
    Surface('perplexity', 'Perplexity Sonar (Perplexity API)', GROUNDED_API, 'perplexity', 'perplexity',
            'Perplexity Sonar, grounded by nature, with its citations'),
    Surface('claude', 'Claude with web search (Anthropic API)', GROUNDED_API, 'anthropic', 'claude',
            'Anthropic Messages API with the web_search tool available; the model decides whether to search'),
    Surface('aimode', 'Google AI Mode (consumer, via SerpApi)', CONSUMER_UI, 'serpapi', 'aimode',
            'google.com/search?udm=50, logged out, read by SerpApi (engine google_ai_mode)', consumer=True),
    Surface('copilot', 'Bing Copilot (consumer, via SerpApi)', CONSUMER_UI, 'serpapi', 'copilot',
            'Bing Copilot Search, logged out, read by SerpApi (engine bing_copilot)', consumer=True),
    Surface('gemini_web', 'Gemini web app (consumer)', CONSUMER_UI, '-', 'gemini',
            'gemini.google.com, logged out', consumer=True, never_available=NO_VERIFIED_PROVIDER),
    Surface('chatgpt_web', 'ChatGPT web app (consumer)', CONSUMER_UI, '-', 'chatgpt',
            'chatgpt.com, logged out', consumer=True, never_available=NO_VERIFIED_PROVIDER),
]

#: Platform ids stored before 2B that are not selectable surfaces today.
#: 'gemini' rows were the ungrounded API. Read only: a new cycle never
#: stores this id (see ALIASES).
LEGACY = {'gemini': Surface('gemini', 'Gemini (Gemini API, legacy id)', API, 'google_genai', 'gemini',
                            'Stored under the pre-2B id; the ungrounded Gemini API')}

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


def modal_list(env=None) -> List[dict]:
    """
    What the Create Study modal shows: every surface that will actually
    run, with its fidelity label, then the surfaces that cannot run here
    for a reason that is not a setting (no verified provider), shown as not
    available with that reason. A consumer surface that is merely switched
    off is not listed: it will not run, and the modal shows what will.
    """
    runnable = [s.as_dict(env=env) for s in SURFACES if unavailable_reason(s.id, env=env) is None]
    never = [s.as_dict(env=env) for s in SURFACES if s.never_available]
    return runnable + never
