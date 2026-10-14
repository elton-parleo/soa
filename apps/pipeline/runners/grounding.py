"""
The source metadata a grounded surface returns, in one shape.

retrieved_sources has always held the source URLs. That is not enough to
say where an answer's facts came from: Gemini's URLs are opaque
vertexaisearch.cloud.google.com redirects, and none of the three surfaces'
URL lists says WHICH part of the answer a source backs. This module keeps
what each platform does say, per run, in soa_runs.grounding:

    {"sources":  [{"uri", "title", "domain"}],
     "supports": [{"text", "start", "end", "sources": [index into sources]}]}

  sources   one per source the platform returned, in its order. `domain`
            is the destination site when the platform says it (Gemini's
            web.domain, or its web.title, which is the site name), else
            the URI's own host — never the redirect host, which names
            Google, not the page. None when nothing names the site; the
            redirect backfill (scripts/resolve_grounding_redirects.py)
            may fill it later, with `resolved_at` beside it.
  supports  one per span the platform attributes: its text as the platform
            gives it, its offsets as the platform counts them (Gemini:
            UTF-8 bytes; OpenAI: characters), and the sources behind it.

Deterministic, and reads only the response object. Nothing here fetches.
"""
import re
from typing import Iterable, List, Optional

#: Hosts whose URLs are redirects to the real source. The host names the
#: redirector, so it is never recorded as the source's domain.
REDIRECT_HOSTS = frozenset({'vertexaisearch.cloud.google.com'})

_SITE_NAME = re.compile(r'^(?:[a-z0-9-]+\.)+[a-z]{2,}$')


def domain_of(value) -> Optional[str]:
    """A bare site name ('trueshopstore.com') from a URL or a site name;
    None for anything else, and for a redirect host."""
    from soa_shared.expected_answers import normalize_domain

    domain = normalize_domain(value)
    if not domain or domain in REDIRECT_HOSTS or not _SITE_NAME.match(domain):
        return None
    return domain


def source(uri, title=None, domain=None) -> dict:
    """One source. The platform's own domain, else its title when that is a
    site name, else the URI's host when that is not a redirector."""
    return {'uri': uri, 'title': title,
            'domain': domain_of(domain) or domain_of(title) or domain_of(uri)}


def build(sources: List[dict], supports: Iterable[dict] = ()) -> Optional[dict]:
    supports = [s for s in supports if s.get('sources')]
    if not sources:
        return None
    return {'sources': sources, 'supports': supports}


# ─── Gemini ────────────────────────────────────────────────────────────────

def from_gemini(response) -> Optional[dict]:
    """grounding_metadata.grounding_chunks (web.uri, web.title, web.domain)
    and grounding_supports (segment -> grounding_chunk_indices), across
    candidates. Chunk indices are per candidate, so they are offset into
    the run's one source list."""
    sources, supports = [], []
    for candidate in getattr(response, 'candidates', None) or []:
        meta = getattr(candidate, 'grounding_metadata', None)
        if meta is None:
            continue
        base = len(sources)
        for chunk in getattr(meta, 'grounding_chunks', None) or []:
            web = getattr(chunk, 'web', None)
            uri = getattr(web, 'uri', None) if web else None
            if uri:
                sources.append(source(uri, getattr(web, 'title', None), getattr(web, 'domain', None)))
        for support in getattr(meta, 'grounding_supports', None) or []:
            segment = getattr(support, 'segment', None)
            indices = [base + i for i in getattr(support, 'grounding_chunk_indices', None) or []
                       if isinstance(i, int)]
            supports.append({
                'text': getattr(segment, 'text', None) if segment else None,
                'start': getattr(segment, 'start_index', None) if segment else None,
                'end': getattr(segment, 'end_index', None) if segment else None,
                'sources': [i for i in indices if i < len(sources)],
            })
    return build(sources, supports)


# ─── OpenAI Responses (web_search) ─────────────────────────────────────────

def _get(obj, name):
    return obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)


def from_openai(output, output_text: str = '') -> Optional[dict]:
    """web_search_call action.sources, and every url_citation annotation:
    a citation is a support for the span [start_index, end_index) of the
    output text, backed by its url."""
    sources, index, supports = [], {}, []

    def add(url, title=None):
        if url not in index:
            index[url] = len(sources)
            sources.append(source(url, title))
        elif title and not sources[index[url]]['title']:
            sources[index[url]] = source(url, title)
        return index[url]

    for item in output or []:
        if _get(item, 'type') == 'web_search_call':
            for src in _get(_get(item, 'action'), 'sources') or []:
                if _get(src, 'url'):
                    add(_get(src, 'url'), _get(src, 'title'))
        contents = _get(item, 'content') or []
        annotated = [item] + list(contents)
        for part in annotated:
            for annotation in _get(part, 'annotations') or []:
                if _get(annotation, 'type') != 'url_citation' or not _get(annotation, 'url'):
                    continue
                i = add(_get(annotation, 'url'), _get(annotation, 'title'))
                start, end = _get(annotation, 'start_index'), _get(annotation, 'end_index')
                text = _get(part, 'text') or output_text or ''
                supports.append({
                    'text': text[start:end] if isinstance(start, int) and isinstance(end, int) else None,
                    'start': start, 'end': end, 'sources': [i],
                })
    return build(sources, supports)


# ─── Perplexity ────────────────────────────────────────────────────────────

_MARKER = re.compile(r'\[(\d{1,3})\]')
#: Where a sentence ends: a full stop (not the one in "$6.99") and any
#: markers after it, since Perplexity writes "$6.99.[1]"; or a line break.
_SENTENCE_END = re.compile(r'[.!?]+(?:\[\d{1,3}\])*(?=\s|$)|\n')


def _sentences(text):
    """(start, end, sentence) for each sentence, markers included."""
    start = 0
    for match in _SENTENCE_END.finditer(text):
        yield start, match.end(), text[start:match.end()]
        start = match.end()
    if start < len(text):
        yield start, len(text), text[start:]


def from_perplexity(response, text: str) -> Optional[dict]:
    """`citations` (URLs) and, when present, `search_results` (title, url).
    Perplexity marks the sentence a citation backs with [n], 1-based into
    citations; each sentence carrying markers is one support."""
    citations = list(_get(response, 'citations') or [])
    titles = {_get(r, 'url'): _get(r, 'title') for r in _get(response, 'search_results') or []}
    sources = [source(url, titles.get(url)) for url in citations if url]
    supports = []
    for start, end, sentence in _sentences(text or ''):
        indices = sorted({int(n) - 1 for n in _MARKER.findall(sentence)
                          if 0 < int(n) <= len(sources)})
        if indices and _MARKER.sub('', sentence).strip():
            supports.append({'text': _MARKER.sub('', sentence).strip(),
                             'start': start, 'end': end, 'sources': indices})
    return build(sources, supports)


# ─── SerpApi (Google AI Mode, Bing Copilot) ────────────────────────────────

def from_serpapi(body: dict) -> Optional[dict]:
    """`references` (title, link) and every text block carrying
    reference_indexes, which name references by their own `index` field.
    List items are blocks too. No offsets: the page has none."""
    refs = sorted((r for r in (body or {}).get('references') or [] if r.get('link')),
                  key=lambda r: r.get('index') or 0)
    sources, by_ref_index = [], {}
    for ref in refs:
        by_ref_index[ref.get('index')] = len(sources)
        sources.append(source(ref['link'], ref.get('title')))
    supports = []

    def walk(blocks):
        for block in blocks or []:
            indices = sorted({by_ref_index[i] for i in block.get('reference_indexes') or []
                              if i in by_ref_index})
            if indices and block.get('snippet'):
                supports.append({'text': block['snippet'], 'start': None, 'end': None,
                                 'sources': indices})
            walk(block.get('list'))
            walk(block.get('text_blocks'))

    walk((body or {}).get('text_blocks'))
    return build(sources, supports)
