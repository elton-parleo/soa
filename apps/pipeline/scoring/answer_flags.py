"""
2B: what an answer said about WHERE — the retailers it placed the product
at, and the domains it cited — classified against the record.

Deterministic, no network (the DNS/HTTP citation check is
scoring/citation_check.py, and its result is handed in). Reads only what
Layer 2 already stored: `retailer_mentions` (names with the labelling
pass's role), `sources_cited`, and the run's `retrieved_sources`.

fabricated_availability
    The answer places the product at a retailer that is not in the
    record's retailer list. "Places" means a retailer mention whose role is
    recommendation, source, or unlabelled; `unavailable` is the answer
    saying the product is NOT there, which is not a placement. Names are
    mapped through a CLOSED enum (KNOWN_RETAILERS below) plus any domain
    written in the name. A name the enum does not know is reported as
    unrecognised and never flagged: we cannot call a placement fabricated
    when we cannot say which store it names.

    "online" counts, as the brief says: an answer saying the product is
    "available online" names no store, so it is fabricated unless the
    merchant's own site sells it — always for a seller, and for a brand
    only when its own domain is in its retailer list.

grounded by source
    Each cited domain is own_domain (the merchant's own site, or a
    subdomain of it), listed_retailer (in the record's retailer list), or
    other. The existing `grounded` bucket and `source_attribution` are
    unchanged; this split sits underneath them.
"""
import re
from typing import Iterable, List, Optional

from soa_shared import expected_answers as ea

# ─── The closed retailer enum ──────────────────────────────────────────────
#
# VENDORED. Seeded from the retailer entities in the console's operator
# registry (parleohq/truesync console-demo, apps/console/src/data/studio.ts,
# ENTITIES of type 'retailer', with their aliases), plus the stores the
# brand-direct classifier has seen invented (Aldi, Kohl's) and a handful of
# US grocery and baby retailers. Lower-case alias -> domain.
KNOWN_RETAILERS = {
    'amazon': 'amazon.com', 'amazon.com': 'amazon.com', 'subscribe & save': 'amazon.com',
    'walmart': 'walmart.com', 'walmart.com': 'walmart.com', 'rollback': 'walmart.com',
    'target': 'target.com', 'target circle': 'target.com',
    'costco': 'costco.com', "sam's club": 'samsclub.com', 'sams club': 'samsclub.com',
    "bj's": 'bjs.com', 'bjs': 'bjs.com', 'bjs wholesale': 'bjs.com',
    'kroger': 'kroger.com', 'cvs': 'cvs.com', 'walgreens': 'walgreens.com',
    'rite aid': 'riteaid.com', 'meijer': 'meijer.com', 'h-e-b': 'heb.com', 'heb': 'heb.com',
    'publix': 'publix.com', 'whole foods': 'wholefoodsmarket.com',
    'dollar general': 'dollargeneral.com', 'family dollar': 'familydollar.com',
    'aldi': 'aldi.us', "kohl's": 'kohls.com', 'kohls': 'kohls.com',
    'buy buy baby': 'buybuybaby.com', 'babylist': 'babylist.com',
    'chewy': 'chewy.com', 'chewy.com': 'chewy.com', 'autoship (chewy)': 'chewy.com',
    'petco': 'petco.com', 'petsmart': 'petsmart.com', 'tractor supply': 'tractorsupply.com',
    '1-800-petmeds': '1800petmeds.com', 'petmeds': '1800petmeds.com',
    'best buy': 'bestbuy.com', 'home depot': 'homedepot.com', "lowe's": 'lowes.com',
    'ebay': 'ebay.com', 'temu': 'temu.com', 'ulta': 'ulta.com', 'sephora': 'sephora.com',
    'foot locker': 'footlocker.com', "dick's sporting goods": 'dickssportinggoods.com',
    "dick's": 'dickssportinggoods.com', 'jd sports': 'jdsports.com',
    'nordstrom': 'nordstrom.com', 'nordstrom rack': 'nordstrom.com', "macy's": 'macys.com',
    'uniqlo': 'uniqlo.com', 'zara': 'zara.com', 'h&m': 'hm.com',
    'rei': 'rei.com', 'rei co-op': 'rei.com', 'backcountry': 'backcountry.com',
    'moosejaw': 'moosejaw.com', 'public lands': 'publiclands.com', 'scheels': 'scheels.com',
}

ONLINE = 'online'

# Phrases meaning "the merchant's own site", and phrases meaning "online"
# with no store named.
_OWN_SITE = re.compile(r"\b(official (web)?site|their (own )?(web)?site|brand'?s? (own )?(web)?site|directly from (the )?brand)\b")
_ONLINE = re.compile(r'^(online|online retailers?|online stores?|various online retailers?|e-?commerce sites?)$')
_DOMAIN_IN_TEXT = re.compile(r'([a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|co|us|io|shop|store|ca|co\.uk))\b')

PLACEMENT_ROLES = (None, 'recommendation', 'source')


def _norm_name(name) -> str:
    return ' '.join(str(name or '').lower().replace('’', "'").split())


def claimed_retailer(name, *, own_domain: Optional[str]) -> Optional[str]:
    """A retailer mention's name -> a domain, ONLINE, or None (unrecognised)."""
    text = _norm_name(name)
    if not text:
        return None
    domain_match = _DOMAIN_IN_TEXT.search(text)
    if domain_match:
        return ea.normalize_domain(domain_match.group(1))
    if text in KNOWN_RETAILERS:
        return KNOWN_RETAILERS[text]
    stripped = re.sub(r'^(at |from |on |via )', '', text).strip(' .')
    if stripped in KNOWN_RETAILERS:
        return KNOWN_RETAILERS[stripped]
    if _OWN_SITE.search(text) and own_domain:
        return own_domain
    if _ONLINE.match(stripped):
        return ONLINE
    return None


def _domain_in(domain: Optional[str], allowed: Iterable[str]) -> bool:
    if not domain:
        return False
    for candidate in allowed:
        if candidate and (domain == candidate or domain.endswith('.' + candidate)):
            return True
    return False


def fabricated_availability(retailer_mentions, *, retailer_list: List[str],
                            own_domain: Optional[str], merchant_kind: Optional[str]) -> dict:
    """
    {'fabricated': [...], 'listed': [...], 'unrecognised': [...]} — each entry
    {'name', 'domain'}. `fabricated` non-empty is the flag.
    """
    allowed = {ea.normalize_domain(d) for d in retailer_list or [] if ea.normalize_domain(d)}
    own = ea.normalize_domain(own_domain)
    if own:
        allowed.add(own)
    online_ok = merchant_kind == 'seller' or (own is not None and own in {
        ea.normalize_domain(d) for d in retailer_list or []
    })

    out = {'fabricated': [], 'listed': [], 'unrecognised': []}
    for mention in retailer_mentions or []:
        if not isinstance(mention, dict) or not mention.get('name'):
            continue
        if mention.get('role') not in PLACEMENT_ROLES:
            continue
        domain = claimed_retailer(mention['name'], own_domain=own)
        entry = {'name': mention['name'], 'domain': domain}
        if domain is None:
            out['unrecognised'].append(entry)
        elif domain == ONLINE:
            (out['listed'] if online_ok else out['fabricated']).append(entry)
        elif _domain_in(domain, allowed):
            out['listed'].append(entry)
        else:
            out['fabricated'].append(entry)
    return out


def cited_domains(sources_cited, retrieved_sources=None) -> List[str]:
    """Every distinct domain the answer cited or the surface retrieved, in order."""
    seen, out = set(), []
    for value in list(sources_cited or []) + list(retrieved_sources or []):
        domain = ea.normalize_domain(value)
        if not domain:
            match = _DOMAIN_IN_TEXT.search(_norm_name(value))
            domain = ea.normalize_domain(match.group(1)) if match else None
        if domain and domain not in seen:
            seen.add(domain)
            out.append(domain)
    return out


def source_split(domains: Iterable[str], *, own_domain: Optional[str],
                 retailer_list: List[str]) -> dict:
    """{own_domain: [...], listed_retailer: [...], other: [...]}"""
    own = ea.normalize_domain(own_domain)
    listed = [ea.normalize_domain(d) for d in retailer_list or [] if ea.normalize_domain(d)]
    out = {'own_domain': [], 'listed_retailer': [], 'other': []}
    for domain in domains:
        if own and _domain_in(domain, [own]):
            out['own_domain'].append(domain)
        elif _domain_in(domain, listed):
            out['listed_retailer'].append(domain)
        else:
            out['other'].append(domain)
    return out
