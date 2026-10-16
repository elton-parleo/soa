"""
2E: the Audit's domain checks, run from the worker against a cycle's merchant.

Protocol & Feed Presence and Value Protocols are the Audit's own checks
(scan/scorer.py: score_protocol_feed, score_value_protocols), which read a
scan's pages: /llms.txt, /.well-known/mcp.json, and the agentic-protocol
hints structured_data.extract finds on the homepage and a product page. A
loop cycle has no scan, so this module fetches exactly those pages, for the
merchant's own domains only, through the scan's own fetcher (honest UA,
robots.txt, the SSRF guard, challenge detection, Web Bot Auth signing), and
hands them to the Audit's functions unchanged. Nothing under scan/ is
copied or edited: every check and every score is the Audit's.

One fetch policy is the Audit's own, restated here because discover_pages
is not called (it also walks sitemaps, which neither check reads): when
robots.txt and the store root both refuse us, nothing more is requested,
and the two checks score that as discovery's short circuit does.

The signed-agent probe is separate and is not an Audit dimension. The
merchant's product page is fetched twice, the same UA, once signed (Web
Bot Auth, the worker's key) and once unsigned, and both outcomes are kept.
It feeds the Accessibility row "Edge lets signed agents in" and never the
score.

What is stored (soa_cycles.domain_checks, migration b4e8f1c3a9d2) is the
raw record, not only the result: per domain, each fetch's status, HTTP
status, content type and, for the two protocol files, the body (llms.txt
cut to LLMS_BODY_KEEP characters, which keeps every fact its check reads),
the hints, and the site type. score_entry rebuilds the scan's pages from
that record and calls the Audit's functions, which is also how the live
run scores, so a stored record re-scores to the same numbers (the score of
record is reproducible). The record carries the scan module's own version
(scan_dimensions.SCORER_VERSION, which engine.py stamps on every scan) and
EXTRACTION_REV beside this adapter's revision.

No model is called. The only network calls are the merchant's own domains
(through the fetcher) and supply's /retailers and /retailer-prices.
"""
import json
import logging
import threading
import urllib.robotparser
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional
from urllib.parse import urljoin

from sqlalchemy import inspect, text

from scan import fetcher, scorer, signing
from scan.discovery import LLMS_TXT_PATH, MCP_WELL_KNOWN_PATH, PageCandidate
from scan.engine import PageScanData, _serialize_dim_score
from scan.site_typing import SiteTypeResult, classify_site
from scan.structured_data import EXTRACTION_REV, ExtractedData, extract
from soa_shared import expected_answers as ea
from soa_shared.scan_dimensions import SCORER_VERSION as SCAN_VERSION

logger = logging.getLogger(__name__)

#: This adapter's own revision: what it fetches and how it records it. A
#: change re-runs nothing by itself; it is stored so a record says which
#: adapter wrote it.
ADAPTER_REVISION = 1

#: llms.txt is scored on three facts: non-empty, not an HTML document (its
#: first 15 characters), and its content type. A prefix keeps all three.
LLMS_BODY_KEEP = 2000
#: A manifest is parsed whole; anything past this is not a manifest.
MANIFEST_BODY_KEEP = 65536

KIND_ROBOTS, KIND_HOMEPAGE, KIND_LLMS, KIND_MCP, KIND_PRODUCT = (
    'robots', 'homepage', 'llms_txt', 'mcp_well_known', 'product')
KIND_PRODUCT_UNSIGNED = 'product_unsigned'

#: The signed-agent probe's outcomes.
BOTH_IN, SIGNED_ONLY, UNSIGNED_ONLY, NEITHER, NOT_CHECKED = (
    'both_in', 'signed_only', 'unsigned_only', 'neither', 'not_checked')

_REFUSED_HTTP = (401, 403, 429)

FetchFn = Callable[..., fetcher.FetchResult]


# ─── fetching ──────────────────────────────────────────────────────────────

_SIGNING_LOCK = threading.Lock()


@contextmanager
def unsigned():
    """Fetches inside are unsigned, the same UA. signing.WEB_BOT_AUTH=off is
    the module's own documented switch (a controlled rollback); flipped for
    the one request and restored. The worker's loop is sequential, and the
    lock keeps two probes from interleaving."""
    with _SIGNING_LOCK:
        before = signing.WEB_BOT_AUTH
        signing.WEB_BOT_AUTH = 'off'
        try:
            yield
        finally:
            signing.WEB_BOT_AUTH = before


def origin_of(domain: str) -> str:
    return f"https://{ea.normalize_domain(domain) or domain}"


def _record(kind: str, fr: Optional[fetcher.FetchResult]) -> Optional[dict]:
    """A fetch as stored. Bodies only for the two protocol files: a page we
    read is never stored (fetcher.py's own rule), only what was found in it."""
    if fr is None:
        return None
    content_type = (fr.response_headers or {}).get('content-type')
    body = None
    if kind == KIND_LLMS and fr.html is not None:
        body = fr.html.strip()[:LLMS_BODY_KEEP]
    elif kind == KIND_MCP and fr.html is not None:
        body = fr.html[:MANIFEST_BODY_KEEP]
    return {
        'kind': kind, 'url': fr.url, 'final_url': fr.final_url, 'status': fr.status,
        'http_status': fr.http_status, 'content_type': content_type, 'body': body,
        'bytes': fr.bytes, 'attempts': fr.attempts, 'error': fr.error,
        'edge_vendor_hint': fr.edge_vendor_hint, 'title': fr.title if fr.status != fetcher.FETCHED else None,
    }


@dataclass
class _Discovery:
    """What classify_site reads off a DiscoveryResult: robots.txt, and the
    sitemap lists, empty because no sitemap is walked here."""
    robots_fetch: fetcher.FetchResult
    sitemap_urls: list = field(default_factory=list)
    sitemap_index_entries: list = field(default_factory=list)


def _robot_parser(robots: fetcher.FetchResult) -> Optional[urllib.robotparser.RobotFileParser]:
    if robots.status != fetcher.FETCHED or not robots.html:
        return None
    try:
        rp = urllib.robotparser.RobotFileParser()
        rp.set_url(robots.url)
        rp.parse(robots.html.splitlines())
        return rp
    except Exception:  # noqa: BLE001 - an unparseable file is no parser, as in discovery
        logger.exception("[domain-checks] robots.txt for %s did not parse", robots.url)
        return None


def fetch_domain(domain: str, *, pdp_url: Optional[str] = None, fetch: FetchFn = None) -> dict:
    """The raw record for one own domain: robots.txt, the store root, the two
    protocol files and (when the reference read has one on this domain) a
    product page, signed, then the same page unsigned. Never raises."""
    fetch = fetch or fetcher.fetch
    origin = origin_of(domain)
    robots = fetch(urljoin(origin, '/robots.txt'), robot_parser=None, max_403_attempts=1)
    parser = _robot_parser(robots)
    home = fetch(origin, robot_parser=parser, check_short_body=True)
    # discover_pages' hard_refused, as it has it: both refused, stop
    short = (robots.http_status in (403, 429) and home.status != fetcher.FETCHED
             and home.http_status in (403, 429))
    llms = mcp = pdp = pdp_unsigned = None
    if not short:
        llms = fetch(urljoin(origin, LLMS_TXT_PATH), robot_parser=parser)
        mcp = fetch(urljoin(origin, MCP_WELL_KNOWN_PATH), robot_parser=parser)
        if pdp_url:
            pdp = fetch(pdp_url, robot_parser=parser, check_short_body=True)
            if signing.is_signing_enabled() and pdp.status != fetcher.ROBOTS_DISALLOWED:
                # once: a refusal is the answer, not a reason to knock again
                with unsigned():
                    pdp_unsigned = fetch(pdp_url, robot_parser=parser, check_short_body=True, max_403_attempts=1)

    # The pages the hints come from, extracted as engine._gather_pages does,
    # and the site type from them (classify_site, never re-stated).
    read = [PageScanData(candidate=PageCandidate(url=origin, kind='homepage'), fetch_result=home,
                         extracted=extract(home.html) if home.status == fetcher.FETCHED and home.html else None)]
    if pdp is not None:
        read.append(PageScanData(candidate=PageCandidate(url=pdp_url, kind='product'), fetch_result=pdp,
                                 extracted=extract(pdp.html) if pdp.status == fetcher.FETCHED and pdp.html else None))
    hints = [h for p in read if p.extracted for h in p.extracted.agentic_protocol_hints]
    site = classify_site(read, _Discovery(robots_fetch=robots))

    entry = {
        'domain': ea.normalize_domain(domain) or domain, 'origin': origin, 'short_circuited': short,
        'fetches': [r for r in (_record(KIND_ROBOTS, robots), _record(KIND_HOMEPAGE, home), _record(KIND_LLMS, llms),
                                _record(KIND_MCP, mcp), _record(KIND_PRODUCT, pdp),
                                _record(KIND_PRODUCT_UNSIGNED, pdp_unsigned)) if r],
        'agentic_protocol_hints': hints,
        'site_type': {'site_type': site.site_type, 'reason': site.reason, 'signals': list(site.signals)},
        'pdp_url': pdp_url,
    }
    entry.update(score_entry(entry))
    entry['signed_probe'] = signed_probe(entry)
    return entry


# ─── scoring: the Audit's functions over the record ────────────────────────

def _fetch_of(entry: dict, kind: str) -> Optional[dict]:
    return next((f for f in entry.get('fetches') or [] if f.get('kind') == kind), None)


def _as_fetch_result(rec: dict) -> fetcher.FetchResult:
    headers = {'content-type': rec['content_type']} if rec.get('content_type') else {}
    return fetcher.FetchResult(url=rec['url'], status=rec['status'], html=rec.get('body'),
                               http_status=rec.get('http_status'), response_headers=headers)


def pages_from_entry(entry: dict) -> list:
    """The scan's pages, rebuilt from a stored record: the two protocol files
    as fetched, and one page carrying the hints extracted from the store root
    and the product page (score_f3 reads the hints across every page)."""
    pages = []
    for kind in (KIND_LLMS, KIND_MCP):
        rec = _fetch_of(entry, kind)
        if rec is not None:
            pages.append(PageScanData(candidate=PageCandidate(url=rec['url'], kind=kind),
                                      fetch_result=_as_fetch_result(rec), extracted=None))
    hints = list(entry.get('agentic_protocol_hints') or [])
    if hints:
        pages.append(PageScanData(
            candidate=PageCandidate(url=entry.get('origin') or '', kind='homepage'),
            fetch_result=fetcher.FetchResult(url=entry.get('origin') or '', status=fetcher.FETCHED),
            extracted=ExtractedData(agentic_protocol_hints=hints)))
    return pages


def score_entry(entry: dict) -> dict:
    """{'protocol_feed', 'value_protocols'}: the Audit's two functions on the
    record, serialized as engine.py serializes a scan's dimensions."""
    pages = pages_from_entry(entry)
    site = SiteTypeResult(**{k: entry['site_type'][k] for k in ('site_type', 'reason', 'signals')})
    short = bool(entry.get('short_circuited'))
    return {
        'protocol_feed': _serialize_dim_score(scorer.score_protocol_feed(pages, site, short_circuited=short)),
        'value_protocols': _serialize_dim_score(scorer.score_value_protocols(pages, short_circuited=short)),
    }


# ─── the signed-agent probe ────────────────────────────────────────────────

def _admitted(rec: Optional[dict]) -> bool:
    return bool(rec) and rec['status'] == fetcher.FETCHED


def _refused(rec: Optional[dict]) -> bool:
    return bool(rec) and (rec['status'] == fetcher.BLOCKED or rec.get('http_status') in _REFUSED_HTTP)


def _outcome_facts(rec: Optional[dict]) -> Optional[dict]:
    if not rec:
        return None
    return {k: rec.get(k) for k in ('status', 'http_status', 'edge_vendor_hint', 'title')}


def signed_probe(entry: dict) -> dict:
    """The product page, signed and unsigned: both outcomes, and which
    admitted. Not checked, with the reason, when it could not be run."""
    signed, plain = _fetch_of(entry, KIND_PRODUCT), _fetch_of(entry, KIND_PRODUCT_UNSIGNED)
    base = {'url': entry.get('pdp_url'), 'signed': _outcome_facts(signed), 'unsigned': _outcome_facts(plain),
            'key_id': signing.key_id()}
    if entry.get('short_circuited'):
        return {**base, 'outcome': NOT_CHECKED, 'reason': 'robots.txt and the store root both refused our reader'}
    if not entry.get('pdp_url'):
        return {**base, 'outcome': NOT_CHECKED, 'reason': "no product page on the merchant's own domain in the reference read"}
    if signed and signed['status'] == fetcher.ROBOTS_DISALLOWED:
        return {**base, 'outcome': NOT_CHECKED, 'reason': 'robots.txt disallows the product page to our reader'}
    if plain is None:
        return {**base, 'outcome': NOT_CHECKED, 'reason': 'no Web Bot Auth key on the worker, so no signed request was sent'}
    if _admitted(signed) and _admitted(plain):
        return {**base, 'outcome': BOTH_IN, 'reason': None}
    if _admitted(signed) and _refused(plain):
        return {**base, 'outcome': SIGNED_ONLY, 'reason': None}
    if _refused(signed) and _admitted(plain):
        return {**base, 'outcome': UNSIGNED_ONLY, 'reason': None}
    if _refused(signed) and _refused(plain):
        return {**base, 'outcome': NEITHER, 'reason': None}
    return {**base, 'outcome': NOT_CHECKED,
            'reason': f"the product page did not answer (signed {signed['status']}, unsigned {plain['status']})"}


# ─── a cycle ───────────────────────────────────────────────────────────────

def _json(value):
    if value is None or isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def cycle_merchant(conn, cycle_id: int) -> Optional[str]:
    """The merchant the cycle's questions were built from (their source_ref),
    as the console's score reads it (console_score.cycle_merchant)."""
    counts: Counter = Counter()
    for (ref,) in conn.execute(text(
            "SELECT q.source_ref FROM soa_runs r JOIN soa_queries q ON q.id = r.query_id WHERE r.cycle_id = :c"),
            {'c': cycle_id}):
        slug = (_json(ref) or {}).get('merchant_slug')
        if slug:
            counts[slug] += 1
    return counts.most_common(1)[0][0] if counts else None


def own_domains(client, slug: str) -> tuple:
    """(the merchant's own domains, error): supply /retailers' own_domains
    (#20), else its deprecated own_domain, else the tenant record's domain."""
    payload, error = client.retailers(slug)
    listed = []
    if error is None:
        listed = list((payload or {}).get('own_domains') or []) or [(payload or {}).get('own_domain')]
    domains = []
    for d in (ea.normalize_domain(x) for x in listed):
        if d and d not in domains:
            domains.append(d)
    if not domains:
        record, record_error = client.merchant_record(slug)
        d = ea.normalize_domain((record or {}).get('domain'))
        if d:
            return [d], None
        return [], error or record_error or 'the merchant record names no own domain'
    return domains, None


def product_page(rows: Optional[List[dict]], domain: str) -> Optional[str]:
    """A product page on `domain` from the reference read: a page read ok
    first, then any with a URL, in the read's order."""
    def on(r):
        d = ea.normalize_domain(r.get('retailer_domain') or r.get('url'))
        return d and (d == domain or d.endswith('.' + domain))
    candidates = [r for r in rows or [] if r.get('url') and on(r)]
    ok = [r for r in candidates if r.get('read_status') == 'ok']
    return (ok or candidates or [{}])[0].get('url')


def reference_rows(conn, cycle_id: int, client, slug: str) -> tuple:
    """The reference read the cycle was scored against (soa_cycles.
    reference_prices, cached by 2B), else supply's current one."""
    stored = conn.execute(text("SELECT reference_prices FROM soa_cycles WHERE id = :i"), {'i': cycle_id}).scalar()
    payload = _json(stored)
    if payload:
        return payload.get('rows') or [], 'cycle'
    payload, error = client.retailer_prices(slug)
    return ((payload or {}).get('rows') or []), ('supply' if error is None else f'unavailable: {error}')


def run_for_cycle(cycle_id: int, *, engine, client, fetch: FetchFn = None, now: Callable[[], datetime] = None) -> dict:
    """The record for a cycle: every own domain of its merchant checked, the
    first (the merchant's own site, as the Audit scans one store) scored.
    Raises only what the catalog client raises on a refused token."""
    with engine.connect() as conn:
        slug = cycle_merchant(conn, cycle_id)
        if not slug:
            return {'merchant': None, 'domains': [], 'errors': ['no merchant on the cycle\'s questions']}
        domains, error = own_domains(client, slug)
        rows, rows_from = reference_rows(conn, cycle_id, client, slug)
    checked = [fetch_domain(d, pdp_url=product_page(rows, d), fetch=fetch) for d in domains]
    first = checked[0] if checked else None
    return {
        'version': {'scan': SCAN_VERSION, 'extraction_rev': EXTRACTION_REV, 'adapter_revision': ADAPTER_REVISION},
        'checked_at': (now or (lambda: datetime.now(timezone.utc)))().isoformat(),
        'merchant': slug, 'own_domains': domains, 'scored_domain': first['domain'] if first else None,
        'reference_rows_from': rows_from,
        'domains': checked,
        'protocol_feed': first['protocol_feed'] if first else None,
        'value_protocols': first['value_protocols'] if first else None,
        'signed_probe': first['signed_probe'] if first else None,
        'errors': [error] if error else [],
    }


COLUMN = 'domain_checks'


def column_exists(conn) -> bool:
    return COLUMN in {c['name'] for c in inspect(conn).get_columns('soa_cycles')}


def stored(engine, cycle_id: int) -> Optional[dict]:
    """The stored record, or None (none yet, or the column is not there)."""
    with engine.connect() as conn:
        if not column_exists(conn):
            return None
        return _json(conn.execute(text(f"SELECT {COLUMN} FROM soa_cycles WHERE id = :i"), {'i': cycle_id}).scalar())


def store(engine, cycle_id: int, record: dict) -> bool:
    """soa_cycles.domain_checks (migration b4e8f1c3a9d2). Not mapped on
    SoaCycle and written only when the column exists, as 2C-3's score and
    2D's surfaces are: a database the migration has not reached still runs
    the loop, and says so in the log."""
    with engine.begin() as conn:
        if not column_exists(conn):
            logger.warning("soa_cycles.%s is missing (migration b4e8f1c3a9d2 not applied): cycle %s keeps "
                           "its domain checks in the log only", COLUMN, cycle_id)
            return False
        conn.execute(text(f"UPDATE soa_cycles SET {COLUMN} = :j WHERE id = :i"),
                     {'j': json.dumps(record), 'i': cycle_id})
    return True


def summary_lines(record: dict) -> List[str]:
    """What a person reads: per domain, each fetch and the two scores."""
    out = [f"merchant {record.get('merchant')}   own domains: {', '.join(record.get('own_domains') or []) or '(none)'}"
           f"   reference read from: {record.get('reference_rows_from')}"]
    for e in record.get('domains') or []:
        scored = '   (scored)' if e['domain'] == record.get('scored_domain') else '   (recorded, not scored)'
        out.append(f"  {e['domain']}{scored}   site type {e['site_type']['site_type']}"
                   + ('   SHORT-CIRCUITED: robots.txt and the store root refused' if e.get('short_circuited') else ''))
        for f in e['fetches']:
            out.append(f"    {f['kind']:<17} {f['status']:<17} {f.get('http_status') or '-'!s:<4} {f['url']}")
        for code in ('protocol_feed', 'value_protocols'):
            d = e[code]
            out.append(f"    {code:<17} {d['score']} / {d['max']}  coverage {d['coverage']}")
            out.extend(f"      · {line}" for line in d['evidence'])
        p = e['signed_probe']
        out.append(f"    signed probe      {p['outcome']}" + (f" ({p['reason']})" if p.get('reason') else ''))
    out.extend(f"  error: {x}" for x in record.get('errors') or [])
    return out
