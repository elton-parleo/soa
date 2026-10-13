"""
Google AI Mode and Bing Copilot, logged out, read by SerpApi (2B §4).

Ported from parleohq/truesync console-demo services/engine/src/runners/
serpapi.ts: the same request shape, the same answer rebuilt from
text_blocks in page order with AI Mode's product cards appended, the same
sources from `references`, and the api_key never in a stored URL or error.

    GET https://serpapi.com/search?engine=google_ai_mode&q=...&location=...&gl=us&hl=en&api_key=...
    GET https://serpapi.com/search?engine=bing_copilot&q=...&api_key=...

What changed in the port: the engine recorded "no AI answer" as an error
answer. Here it is a RESULT — status success, answer_status no_ai_answer —
because a consumer surface showing no AI answer is a measurement of that
surface, counted in coverage and excluded from accuracy (soa_shared/
surfaces.py). A sign-in wall and a blocked page are results the same way.

How those two are recognised is a heuristic, stated here because it is
not documented by SerpApi in anything this repo has verified: a short
answer that asks the reader to sign in or log in is a sign-in wall; an
`error` that names a captcha, unusual traffic or a block is blocked; any
other `error`, and an empty answer, is no_ai_answer. An HTTP error from
SerpApi itself (401, 429, 5xx) is a failed CALL, not a result, and the run
is recorded as an error exactly as every API runner records one.

Cost unit: one SerpApi search per call (the engine's docs/BACKEND.md
budgets "one SerpApi search per agent" per question). The dollar price of
a search depends on the SerpApi plan and is not stated anywhere in the
repos this was ported from; check the current SerpApi pricing page.

No browser, no Playwright, no fallback to the engine's browser.ts.
"""
import logging
import re
from typing import List, Optional

import httpx

import soa_shared.config as config
from runners.base_runner import BasePlatformRunner
from runners.platform_response import PlatformResponse

logger = logging.getLogger(__name__)

SERPAPI_URL = 'https://serpapi.com/search'
SERPAPI_ENGINES = {'aimode': 'google_ai_mode', 'copilot': 'bing_copilot'}
#: SerpApi searches consumed by one call.
COST_UNITS_PER_CALL = 1

#: The engine's default: the Oct study evidence was captured from Berkeley.
DEFAULT_LOCATION = {'city': 'Berkeley', 'region': 'California', 'country': 'US'}
_COUNTRY_NAMES = {'US': 'United States'}

_SIGN_IN = re.compile(r'\b(sign in|log in|login|signing in|create an account)\b', re.IGNORECASE)
_BLOCKED = re.compile(r'(captcha|unusual traffic|blocked|access denied|forbidden)', re.IGNORECASE)
#: An answer longer than this that mentions signing in is an answer that
#: mentions signing in, not a wall.
SIGN_IN_WALL_MAX_CHARS = 400


def build_params(agent: str, query_text: str, location: Optional[dict] = None) -> dict:
    """Engine: buildSerpApiParams. Bing Copilot takes no location."""
    params = {'engine': SERPAPI_ENGINES[agent], 'q': query_text}
    if agent == 'aimode':
        loc = location or DEFAULT_LOCATION
        params['location'] = (f"{loc['city']}, {loc['region']}, "
                              f"{_COUNTRY_NAMES.get(loc['country'], loc['country'])}")
        params['gl'] = loc['country'].lower()
        params['hl'] = 'en'
    return params


def _list_lines(items, depth: int) -> List[str]:
    out = []
    for item in items or []:
        pad = '  ' * depth
        if isinstance(item, str):
            out.append(f'{pad}- {item}')
            continue
        text = ': '.join(x for x in (item.get('title'), item.get('snippet')) if x)
        if text:
            out.append(f'{pad}- {text}')
        out.extend(_list_lines(item.get('list'), depth + 1))
    return out


def _cell(value) -> str:
    return '' if value is None else str(value)


def render_text_blocks(blocks) -> str:
    """Engine: renderTextBlocks. text_blocks back to plain text in page order."""
    parts = []
    for block in blocks or []:
        kind = block.get('type')
        if kind == 'list':
            lines = [line for line in [block.get('snippet')] + _list_lines(block.get('list'), 0) if line]
            if lines:
                parts.append('\n'.join(lines))
        elif kind == 'table':
            rows = []
            if block.get('headers'):
                rows.append(' | '.join(_cell(h) for h in block['headers']))
            for row in block.get('table') or []:
                rows.append(' | '.join(_cell(c) for c in row))
            if not rows:
                for row in block.get('formatted') or []:
                    rows.append(' | '.join(f'{k}: {_cell(v)}' for k, v in row.items()))
            if block.get('snippet'):
                rows.insert(0, block['snippet'])
            if rows:
                parts.append('\n'.join(rows))
        elif kind == 'code_block':
            code = block.get('code') or block.get('snippet')
            if code:
                parts.append(code)
        elif block.get('snippet'):
            parts.append(block['snippet'])
    return '\n\n'.join(parts)


def parse_response(body: dict) -> dict:
    """Engine: parseSerpApiResponse. {text, sources, page_url, error}."""
    meta = body.get('search_metadata') or {}
    error = body.get('error') or (
        (meta.get('error') or 'SerpApi search failed') if meta.get('status') == 'Error' else None)
    text = render_text_blocks(body.get('text_blocks'))
    if not text.strip() and body.get('reconstructed_markdown'):
        text = body['reconstructed_markdown']
    if text.strip() and body.get('header') and not text.startswith(body['header']):
        text = f"{body['header']}\n\n{text}"
    products = [
        f"- {p['title']}{': ' + p['price'] if p.get('price') else ''}"
        f"{' (was ' + p['old_price'] + ')' if p.get('old_price') else ''}"
        f"{', ' + p['source'] if p.get('source') else ''}"
        for p in body.get('shopping_results') or [] if p.get('title')
    ]
    if text.strip() and products:
        text = f"{text}\n\nProducts shown:\n" + '\n'.join(products)
    sources = []
    for ref in sorted(body.get('references') or [], key=lambda r: r.get('index') or 0):
        if ref.get('link') and ref['link'] not in sources:
            sources.append(ref['link'])
    page_url = meta.get('google_ai_mode_url') or meta.get('bing_copilot_url')
    return {'text': text, 'sources': sources, 'page_url': page_url, 'error': error}


def classify_result(parsed: dict) -> str:
    """answered | no_ai_answer | sign_in_wall | blocked — see the module docstring."""
    text = (parsed.get('text') or '').strip()
    error = parsed.get('error')
    if error and _BLOCKED.search(error):
        return 'blocked'
    if text and len(text) <= SIGN_IN_WALL_MAX_CHARS and _SIGN_IN.search(text):
        return 'sign_in_wall'
    if error or not text:
        return 'no_ai_answer'
    return 'answered'


class SerpApiRunner(BasePlatformRunner):
    """One consumer surface. Subclasses set `platform` (aimode | copilot)."""

    platform = None

    def __init__(self, api_key: Optional[str] = None, *, transport=None,
                 timeout_seconds: Optional[int] = None, location: Optional[dict] = None):
        key = config.SERPAPI_API_KEY if api_key is None else api_key
        if not key:
            raise RuntimeError("SERPAPI_API_KEY is not set (consumer surfaces need it).")
        super().__init__(model=SERPAPI_ENGINES[self.platform],
                         timeout_seconds=timeout_seconds or config.SOA_SERPAPI_TIMEOUT_SECONDS)
        self._key = key
        self._transport = transport
        self._location = location

    def _scrub(self, text: str) -> str:
        return (text or '').replace(self._key, '***')

    async def _call_api(self, query_text: str) -> PlatformResponse:
        params = build_params(self.platform, query_text, self._location)
        async with httpx.AsyncClient(transport=self._transport, timeout=self.timeout_seconds) as client:
            try:
                response = await client.get(SERPAPI_URL, params={**params, 'api_key': self._key},
                                            headers={'accept': 'application/json'})
            except httpx.HTTPError as exc:
                raise RuntimeError(self._scrub(f"SerpApi request failed: {type(exc).__name__}: {exc}"))
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code >= 400:
            detail = body.get('error') if isinstance(body, dict) else None
            raise RuntimeError(self._scrub(
                f"HTTP {response.status_code} from SerpApi: {detail or response.text[:300]}"))

        parsed = parse_response(body if isinstance(body, dict) else {})
        status = classify_result(parsed)
        logger.info("[%s] SerpApi %s: %s (%d search)", self.platform, self.model, status,
                    COST_UNITS_PER_CALL)
        return PlatformResponse(
            response_text=parsed['text'] if status != 'no_ai_answer' else '',
            prompt_tokens=0,
            completion_tokens=0,
            latency_ms=0,
            platform=self.platform,
            model=self.model,
            status='success',
            # A wall or an empty page says why, without the key.
            error=None if status == 'answered' else self._scrub(
                parsed.get('error') or f'{status}: the page showed no AI answer'),
            search_triggered=None,
            retrieved_sources=parsed['sources'] or None,
            answer_status=status,
            cost_units=COST_UNITS_PER_CALL,
        )


class AiModeRunner(SerpApiRunner):
    platform = 'aimode'


class CopilotRunner(SerpApiRunner):
    platform = 'copilot'
