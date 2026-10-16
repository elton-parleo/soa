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

The product page (2E-1) comes from the reference read the cycle was
scored against (supply /retailer-prices, whose rows are under `prices`):
the readable read (read_status ok or empty) whose page is on the domain
being checked, json_ld before regex before any other method, then the
newest, over every variant. The domain is a member of the tenant-wide
own-domain set (2D, #112), the set source_split reads, and www. or a bare
host match alike (normalize_domain). The Audit types a site from its store
root AND a product page; with no product page on the domain, the site is
not typed from the store root alone: Protocol & Feed Presence is recorded
"not measured: no product page", and every row seen is kept with the reason
it was not taken.

The signed-agent probe is separate and is not an Audit dimension. The
merchant's product page is fetched twice, the same UA, once signed (Web
Bot Auth, the worker's key) and once unsigned, and both outcomes are kept.
With no product page on the domain (a brand whose reads are all on a
retailer), the probe alone falls back to a readable page elsewhere,
another own domain of the tenant first, then a retailer's, and says so; the
site is still not typed from it. It feeds the Accessibility row "Edge lets
signed agents in" and never the score.

What is stored (soa_cycles.domain_checks, migration b4e8f1c3a9d2) is the
raw record, not only the result: per domain, each fetch's status, HTTP
status, content type and, for the two protocol files, the body (llms.txt
cut to LLMS_BODY_KEEP characters, which keeps every fact its check reads),
the hints, and the site type. score_entry rebuilds the scan's pages from
that record and calls the Audit's functions, which is also how the live
run scores, so a stored record re-scores to the same numbers (the score of
record is reproducible). The record carries the scan module's own version
(scan_dimensions.SCORER_VERSION, which engine.py stamps on every scan) and
EXTRACTION_REV beside this adapter's revision, and its own `revision`:
1 when first stored, one more each time a re-run replaces it (one record
per cycle, never appended). The console's score of record recomputes when
it changes.

No model is called. The only network calls are the merchant's own domains
(through the fetcher), supply's /tenant, /retailers and /retailer-prices,
and, for a merchant with no product page of its own, the probe's one
fallback page and its site's robots.txt.
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
from soa_shared.scan_dimensions import DIMENSIONS_BY_CODE
from soa_shared.scan_dimensions import SCORER_VERSION as SCAN_VERSION

logger = logging.getLogger(__name__)

#: This adapter's own revision: what it fetches and how it records it. A
#: change re-runs nothing by itself; it is stored so a record says which
#: adapter wrote it.
ADAPTER_REVISION = 2   # 2E-1: the product page from supply's `prices` rows; not typed without one

#: llms.txt is scored on three facts: non-empty, not an HTML document (its
#: first 15 characters), and its content type. A prefix keeps all three.
LLMS_BODY_KEEP = 2000
#: A manifest is parsed whole; anything past this is not a manifest.
MANIFEST_BODY_KEEP = 65536

KIND_ROBOTS, KIND_HOMEPAGE, KIND_LLMS, KIND_MCP, KIND_PRODUCT = (
    'robots', 'homepage', 'llms_txt', 'mcp_well_known', 'product')
KIND_PRODUCT_UNSIGNED = 'product_unsigned'
KIND_PROBE_ROBOTS = 'probe_robots'

#: A read whose page was reached and parsed (supply's prices.READABLE).
READABLE = ('ok', 'empty')
#: The read's parse, best first: Offer markup is what types a store.
METHOD_RANK = {'json_ld': 0, 'regex': 1}
#: Where the page came from.
FROM_OWN, FROM_TENANT, FROM_RETAILER = 'own_domain', 'tenant_domain', 'retailer'

NO_PDP = 'not measured: no product page'
#: How many rejected rows a record keeps (the count is kept whole).
REJECTED_KEEP = 50

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


def fetch_domain(domain: str, *, pdp_url: Optional[str] = None, probe_url: Optional[str] = None,
                 selection: Optional[dict] = None, fetch: FetchFn = None) -> dict:
    """The raw record for one own domain: robots.txt, the store root, the two
    protocol files and (when the reference read has one on this domain) a
    product page, signed, then the same page unsigned. Without one, the probe
    alone reads `probe_url` (a page off this domain, under its own site's
    robots.txt) and the site is not typed. Never raises."""
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
    probe_robots = None
    if not short and not pdp_url and probe_url:
        # the probe's fallback, on its own site: that site's robots.txt is the rule
        probe_robots = fetch(urljoin(origin_of(probe_url), '/robots.txt'), robot_parser=None, max_403_attempts=1)
        probe_parser = _robot_parser(probe_robots)
        pdp = fetch(probe_url, robot_parser=probe_parser, check_short_body=True)
        if signing.is_signing_enabled() and pdp.status != fetcher.ROBOTS_DISALLOWED:
            with unsigned():
                pdp_unsigned = fetch(probe_url, robot_parser=probe_parser, check_short_body=True, max_403_attempts=1)

    # The pages the hints come from, extracted as engine._gather_pages does,
    # and the site type from them (classify_site, never re-stated).
    read = [PageScanData(candidate=PageCandidate(url=origin, kind='homepage'), fetch_result=home,
                         extracted=extract(home.html) if home.status == fetcher.FETCHED and home.html else None)]
    if pdp is not None and pdp_url:
        read.append(PageScanData(candidate=PageCandidate(url=pdp_url, kind='product'), fetch_result=pdp,
                                 extracted=extract(pdp.html) if pdp.status == fetcher.FETCHED and pdp.html else None))
    hints = [h for p in read if p.extracted for h in p.extracted.agentic_protocol_hints]
    if pdp_url or short:
        site = classify_site(read, _Discovery(robots_fetch=robots))
        site_type = {'site_type': site.site_type, 'reason': site.reason, 'signals': list(site.signals)}
    else:
        # The Audit types a site on its store root and a product page; the
        # store root alone called a store brand_only (229). Not typed, and
        # what the store root alone would have said is kept beside it.
        alone = classify_site(read, _Discovery(robots_fetch=robots))
        site_type = {'site_type': None, 'reason': NO_PDP, 'signals': [],
                     'store_root_only': {'site_type': alone.site_type, 'reason': alone.reason,
                                         'signals': list(alone.signals)}}

    entry = {
        'domain': ea.normalize_domain(domain) or domain, 'origin': origin, 'short_circuited': short,
        'fetches': [r for r in (_record(KIND_ROBOTS, robots), _record(KIND_HOMEPAGE, home), _record(KIND_LLMS, llms),
                                _record(KIND_MCP, mcp), _record(KIND_PRODUCT, pdp),
                                _record(KIND_PRODUCT_UNSIGNED, pdp_unsigned),
                                _record(KIND_PROBE_ROBOTS, probe_robots)) if r],
        'agentic_protocol_hints': hints,
        'site_type': site_type,
        'pdp_url': pdp_url,
        'probe_url': pdp_url or probe_url,
        'pdp_selection': selection,
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
    short = bool(entry.get('short_circuited'))
    if entry['site_type'].get('site_type') is None:
        protocol_feed = not_measured('protocol_feed', NO_PDP)
    else:
        site = SiteTypeResult(**{k: entry['site_type'][k] for k in ('site_type', 'reason', 'signals')})
        protocol_feed = _serialize_dim_score(scorer.score_protocol_feed(pages, site, short_circuited=short))
    return {
        'protocol_feed': protocol_feed,
        'value_protocols': _serialize_dim_score(scorer.score_value_protocols(pages, short_circuited=short)),
    }


def not_measured(code: str, why: str) -> dict:
    """A dimension the checks could not measure, in the serialized shape: no
    score, coverage 'not_measured' (never the Audit's 'na', which is a
    finding about the site), and why."""
    return {'score': None, 'max': DIMENSIONS_BY_CODE[code].weight, 'evidence': [why], 'fix': None,
            'fix_human': None, 'coverage': 'not_measured', 'deferred_items': [], 'cap_basis': []}


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
    url = entry.get('pdp_url') or entry.get('probe_url')
    page_from = FROM_OWN if entry.get('pdp_url') else ((entry.get('pdp_selection') or {}).get('probe_from') if url else None)
    base = {'url': url, 'page_from': page_from, 'signed': _outcome_facts(signed), 'unsigned': _outcome_facts(plain),
            'key_id': signing.key_id()}
    if page_from and page_from != FROM_OWN:
        base['note'] = (f"no product page on {entry.get('domain')}: probed "
                        f"{'another own domain of the tenant' if page_from == FROM_TENANT else 'a retailer page'} "
                        f"instead ({ea.normalize_domain(url)}); the probe only, the site is not typed from it")
    if entry.get('short_circuited'):
        return {**base, 'outcome': NOT_CHECKED, 'reason': 'robots.txt and the store root both refused our reader'}
    if not url:
        return {**base, 'outcome': NOT_CHECKED, 'reason': 'no readable product page in the reference read'}
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


def _on(host: Optional[str], domain: str) -> bool:
    return bool(host) and (host == domain or host.endswith('.' + domain))


def _newest_first(value) -> float:
    try:
        return -datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return 0.0   # undated reads after dated ones


def _rank(row: dict) -> tuple:
    return METHOD_RANK.get(row.get('method'), len(METHOD_RANK)), _newest_first(row.get('observed_at'))


def _page(row: dict) -> dict:
    return {k: row.get(k) for k in ('url', 'retailer_domain', 'method', 'read_status', 'observed_at',
                                    'reference_run_id', 'variant_label')}


def select_product_page(rows: Optional[List[dict]], domain: str, tenant_domains=()) -> dict:
    """
    The product page for `domain` from the reference read (supply
    /retailer-prices rows): the readable read whose page is on `domain`,
    json_ld before regex before any other method, then the newest, over every
    variant. `domain` is one of the tenant-wide own domains (2D); a page on
    another of them, or on a retailer, is not this site's page.

    With none, `probe_url` is the probe's fallback alone (another own domain
    of the tenant first, then a retailer), and every row seen is listed with
    why it was not taken. The site is never typed from the fallback.
    """
    domain = ea.normalize_domain(domain) or domain
    tenant = {d for d in (ea.normalize_domain(x) for x in tenant_domains or ()) if d} | {domain}
    taken, elsewhere, rejected = [], [], []
    for row in rows or []:
        url = row.get('url')
        host = ea.normalize_domain(url)
        status = row.get('read_status')
        if not url or not host:
            why = 'no page URL'
        elif status not in READABLE:
            why = 'not read yet' if status is None else f'not readable (read_status {status})'
        elif _on(host, domain):
            taken.append(row)
            continue
        else:
            own = next((d for d in tenant if _on(host, d)), None)
            elsewhere.append((0 if own else 1, row))
            why = (f'on {host}, another own domain of the tenant, not {domain}' if own
                   else f'on {host}, a retailer, not an own domain')
        rejected.append({'url': url, 'retailer_domain': row.get('retailer_domain'), 'read_status': status,
                         'method': row.get('method'), 'why': why})
    out = {'domain': domain, 'rows_seen': len(rows or []), 'url': None, 'page': None,
           'probe_url': None, 'probe_from': None, 'probe_page': None}
    if taken:
        best = min(taken, key=_rank)
        return {**out, 'url': best['url'], 'page': _page(best), 'probe_url': best['url'], 'probe_from': FROM_OWN}
    out['rejected'] = rejected[:REJECTED_KEEP]
    out['rejected_count'] = len(rejected)
    if elsewhere:
        _, best = min(elsewhere, key=lambda t: (t[0], _rank(t[1])))
        out.update(probe_url=best['url'], probe_page=_page(best),
                   probe_from=FROM_TENANT if min(t[0] for t in elsewhere) == 0 else FROM_RETAILER)
    return out


def product_page(rows: Optional[List[dict]], domain: str, tenant_domains=()) -> Optional[str]:
    """The product page on `domain`, or None (select_product_page)."""
    return select_product_page(rows, domain, tenant_domains)['url']


def tenant_own_domains(client) -> tuple:
    """(every own domain of every merchant in the tenant, error): the 2D set,
    read as expectation_scorer.TenantDomainsCache reads it (a client without
    the read gives the merchant's own domains only)."""
    read = getattr(client, 'tenant_own_domains', None)
    return read() if read else ([], None)


def reference_rows(conn, cycle_id: int, client, slug: str) -> tuple:
    """The reference read the cycle was scored against (soa_cycles.
    reference_prices, cached by 2B), else supply's current one."""
    stored = conn.execute(text("SELECT reference_prices FROM soa_cycles WHERE id = :i"), {'i': cycle_id}).scalar()
    payload = _json(stored)
    # supply serves the rows under `prices` (truesync/fullloop/prices.py; 2B
    # caches the payload as served). 2E read `rows`, which is never there.
    if payload:
        return payload.get('prices') or [], 'cycle'
    payload, error = client.retailer_prices(slug)
    return ((payload or {}).get('prices') or []), ('supply' if error is None else f'unavailable: {error}')


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
    tenant, tenant_error = tenant_own_domains(client)
    tenant = list(dict.fromkeys(list(domains) + list(tenant)))
    checked = []
    for d in domains:
        sel = select_product_page(rows, d, tenant)
        checked.append(fetch_domain(d, pdp_url=sel['url'], probe_url=sel['probe_url'], selection=sel, fetch=fetch))
    first = checked[0] if checked else None
    errors = [x for x in (error, tenant_error and f'tenant own domains: {tenant_error}') if x]
    return {
        'version': {'scan': SCAN_VERSION, 'extraction_rev': EXTRACTION_REV, 'adapter_revision': ADAPTER_REVISION},
        'revision': None,   # set by store(): 1, then one more per replacement
        'checked_at': (now or (lambda: datetime.now(timezone.utc)))().isoformat(),
        'merchant': slug, 'own_domains': domains, 'tenant_own_domains': tenant,
        'scored_domain': first['domain'] if first else None,
        'reference_rows_from': rows_from, 'reference_rows': len(rows),
        'domains': checked,
        'protocol_feed': first['protocol_feed'] if first else None,
        'value_protocols': first['value_protocols'] if first else None,
        'signed_probe': first['signed_probe'] if first else None,
        'errors': errors,
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


def next_revision(existing: Optional[dict]) -> int:
    """The revision a record stored now gets: 1, or one past the record it
    replaces (a record stored before 2E-1 has none and counts as 1)."""
    if not existing:
        return 1
    return int(existing.get('revision') or 1) + 1


def store(engine, cycle_id: int, record: dict) -> bool:
    """soa_cycles.domain_checks (migration b4e8f1c3a9d2). Not mapped on
    SoaCycle and written only when the column exists, as 2C-3's score and
    2D's surfaces are: a database the migration has not reached still runs
    the loop, and says so in the log.

    One record per cycle: a record already there is replaced, and the new
    one's `revision` is one past it (set on `record` too)."""
    with engine.begin() as conn:
        if not column_exists(conn):
            logger.warning("soa_cycles.%s is missing (migration b4e8f1c3a9d2 not applied): cycle %s keeps "
                           "its domain checks in the log only", COLUMN, cycle_id)
            return False
        existing = _json(conn.execute(text(f"SELECT {COLUMN} FROM soa_cycles WHERE id = :i"), {'i': cycle_id}).scalar())
        record['revision'] = next_revision(existing if isinstance(existing, dict) else None)
        conn.execute(text(f"UPDATE soa_cycles SET {COLUMN} = :j WHERE id = :i"),
                     {'j': json.dumps(record), 'i': cycle_id})
    return True


def summary_lines(record: dict) -> List[str]:
    """What a person reads: per domain, each fetch and the two scores."""
    out = [f"merchant {record.get('merchant')}   own domains: {', '.join(record.get('own_domains') or []) or '(none)'}"
           f"   reference read from: {record.get('reference_rows_from')} ({record.get('reference_rows', 0)} rows)"]
    for e in record.get('domains') or []:
        scored = '   (scored)' if e['domain'] == record.get('scored_domain') else '   (recorded, not scored)'
        out.append(f"  {e['domain']}{scored}   site type {e['site_type']['site_type']}"
                   + ('   SHORT-CIRCUITED: robots.txt and the store root refused' if e.get('short_circuited') else ''))
        out.extend(selection_lines(e))
        for f in e['fetches']:
            out.append(f"    {f['kind']:<17} {f['status']:<17} {f.get('http_status') or '-'!s:<4} {f['url']}")
        for code in ('protocol_feed', 'value_protocols'):
            d = e[code]
            score = 'not measured' if d['score'] is None else f"{d['score']} / {d['max']}"
            out.append(f"    {code:<17} {score}  coverage {d['coverage']}")
            out.extend(f"      · {line}" for line in d['evidence'])
        p = e['signed_probe']
        out.append(f"    signed probe      {p['outcome']}" + (f" ({p['reason']})" if p.get('reason') else ''))
        if p.get('note'):
            out.append(f"      · {p['note']}")
    out.extend(f"  error: {x}" for x in record.get('errors') or [])
    return out


def selection_lines(entry: dict) -> List[str]:
    """Which product page the checks read, or every row seen and why none was
    taken: never a silent store-root-only reading."""
    sel = entry.get('pdp_selection') or {}
    page = sel.get('page')
    if page:
        return [f"    product page      {page['url']}   ({page.get('method')}, {page.get('read_status')}, "
                f"observed {page.get('observed_at') or '?'}; of {sel.get('rows_seen')} reference rows)"]
    out = [f"    product page      NONE on {entry['domain']}: {sel.get('rows_seen', 0)} reference rows seen, "
           f"none readable on this domain — site not typed, protocol_feed {NO_PDP}"]
    root = (entry.get('site_type') or {}).get('store_root_only')
    if root:
        out.append(f"      (the store root alone would say {root['site_type']}: {root['reason']})")
    for r in sel.get('rejected') or []:
        out.append(f"      rejected  {r.get('url') or '(no url)'}   {r['why']}")
    more = (sel.get('rejected_count') or 0) - len(sel.get('rejected') or [])
    if more > 0:
        out.append(f"      … and {more} more rejected rows")
    return out


#: The fields the dry run sets side by side: (label, path into the record).
_COMPARED = (
    ('revision', ('revision',)), ('checked_at', ('checked_at',)), ('version', ('version',)),
    ('own_domains', ('own_domains',)), ('scored_domain', ('scored_domain',)),
    ('reference_rows_from', ('reference_rows_from',)), ('reference_rows', ('reference_rows',)),
)
_COMPARED_DOMAIN = (
    ('pdp_url', ('pdp_url',)), ('site_type', ('site_type', 'site_type')), ('site_type.reason', ('site_type', 'reason')),
    ('hints', ('agentic_protocol_hints',)),
    ('protocol_feed.score', ('protocol_feed', 'score')), ('protocol_feed.coverage', ('protocol_feed', 'coverage')),
    ('protocol_feed.evidence', ('protocol_feed', 'evidence')),
    ('value_protocols.score', ('value_protocols', 'score')), ('value_protocols.coverage', ('value_protocols', 'coverage')),
    ('value_protocols.evidence', ('value_protocols', 'evidence')),
    ('signed_probe.url', ('signed_probe', 'url')), ('signed_probe.outcome', ('signed_probe', 'outcome')),
    ('signed_probe.reason', ('signed_probe', 'reason')),
)


def _at(obj, path):
    for k in path:
        obj = obj.get(k) if isinstance(obj, dict) else None
    return obj


def _show(value) -> str:
    return '-' if value is None else (json.dumps(value) if isinstance(value, (dict, list)) else str(value))


def compare_lines(old: dict, new: dict) -> List[str]:
    """The stored record beside the new one, field by field (the dry run)."""
    rows = [(label, _at(old, p), _at(new, p)) for label, p in _COMPARED]
    old_d = {e.get('domain'): e for e in old.get('domains') or []}
    for e in new.get('domains') or []:
        before = old_d.pop(e['domain'], {})
        rows += [(f"{e['domain']} {label}", _at(before, p), _at(e, p)) for label, p in _COMPARED_DOMAIN]
    for d, before in old_d.items():
        rows.append((f"{d}", 'checked', 'not checked now'))
    width = max(len(r[0]) for r in rows)
    out = [f"  {'field':<{width}}  {'':1} stored  →  new"]
    for label, a, b in rows:
        mark = ' ' if a == b else '*'
        out.append(f"  {label:<{width}}  {mark} {_show(a)}  →  {_show(b)}")
    return out
