"""
The closed retailer enum and the retailer names a question uses.

Shared by the scorer (scoring/answer_flags.py, which re-exports every name
here) and the catalog-tier generator (soa_shared/catalog_tiers.py), which
the API also runs for the console's study preview (2C). Moved here
verbatim from scoring/answer_flags.py; nothing about matching changed.
Sync copies to apps/api/soa_shared/ and apps/pipeline/soa_shared/.

2Q-1: and the stores an answer names (named_stores), the deterministic
retailer coding coverage, routing and the "sent the shopper to" fact read.
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
    # 2N-1: FL14 named it as a brand
    'hy-vee': 'hy-vee.com', 'hyvee': 'hy-vee.com',
    # 2Q-1: the delivery apps and online grocers where-to-buy answers send shoppers to
    'instacart': 'instacart.com', 'doordash': 'doordash.com', 'uber eats': 'ubereats.com',
    'shipt': 'shipt.com', 'gopuff': 'gopuff.com', 'thrive market': 'thrivemarket.com',
}

#: 2N-1: a retailer's own label, named by agents as if it were a brand
#: ("Kirkland" is Costco's). Visibility's brand table leaves it out with
#: the retailers it belongs to; routing counts the retailer.
STORE_LABELS = {'kirkland': 'costco.com', 'kirkland signature': 'costco.com'}
#: Words a store's name carries beside it ("Walmart store", "Amazon.com online").
_STORE_WORDS = {'store', 'stores', 'online', 'com', 'inc', 'brand', 'website', 'site', 'app'}

#: How a question names a retailer domain. The first alias written for a
#: domain above that reads as a store name; the domain itself otherwise.
RETAILER_NAMES = {
    'amazon.com': 'Amazon', 'walmart.com': 'Walmart', 'target.com': 'Target',
    'costco.com': 'Costco', 'samsclub.com': "Sam's Club", 'bjs.com': "BJ's",
    'kroger.com': 'Kroger', 'cvs.com': 'CVS', 'walgreens.com': 'Walgreens',
    'riteaid.com': 'Rite Aid', 'meijer.com': 'Meijer', 'heb.com': 'H-E-B',
    'publix.com': 'Publix', 'wholefoodsmarket.com': 'Whole Foods',
    'dollargeneral.com': 'Dollar General', 'familydollar.com': 'Family Dollar',
    'aldi.us': 'Aldi', 'kohls.com': "Kohl's", 'buybuybaby.com': 'buybuy BABY',
    'babylist.com': 'Babylist', 'chewy.com': 'Chewy', 'petco.com': 'Petco',
    'petsmart.com': 'PetSmart', 'tractorsupply.com': 'Tractor Supply',
    '1800petmeds.com': '1-800-PetMeds', 'bestbuy.com': 'Best Buy',
    'homedepot.com': 'Home Depot', 'lowes.com': "Lowe's", 'ebay.com': 'eBay',
    'temu.com': 'Temu', 'ulta.com': 'Ulta', 'sephora.com': 'Sephora',
    'footlocker.com': 'Foot Locker', 'dickssportinggoods.com': "DICK'S Sporting Goods",
    'jdsports.com': 'JD Sports', 'nordstrom.com': 'Nordstrom', 'macys.com': "Macy's",
    'uniqlo.com': 'Uniqlo', 'zara.com': 'Zara', 'hm.com': 'H&M', 'rei.com': 'REI',
    'backcountry.com': 'Backcountry', 'moosejaw.com': 'Moosejaw',
    'publiclands.com': 'Public Lands', 'scheels.com': 'Scheels', 'hy-vee.com': 'Hy-Vee',
    'instacart.com': 'Instacart', 'doordash.com': 'DoorDash', 'ubereats.com': 'Uber Eats',
    'shipt.com': 'Shipt', 'gopuff.com': 'Gopuff', 'thrivemarket.com': 'Thrive Market',
}


def retailer_name(domain: Optional[str]) -> Optional[str]:
    domain = ea.normalize_domain(domain)
    return RETAILER_NAMES.get(domain, domain) if domain else None


def retailers_named(text) -> List[str]:
    """Every known retailer a question names, as domains (closed enum and
    written domains). The generator's check that a question names a
    retailer only from the record's list."""
    lowered = ' ' + _norm_name(text) + ' '
    found: List[str] = []
    for alias, domain in sorted(KNOWN_RETAILERS.items(), key=lambda kv: -len(kv[0])):
        if re.search(r'(?<![a-z0-9])' + re.escape(alias) + r'(?![a-z0-9])', lowered):
            if domain not in found:
                found.append(domain)
    for match in _DOMAIN_IN_TEXT.finditer(lowered):
        domain = ea.normalize_domain(match.group(1))
        if domain and domain not in found:
            found.append(domain)
    return found


def is_store_name(name) -> bool:
    """2N-1: whether a name an answer gave as a brand is a retailer (or a
    retailer's own label): the whole name is a known retailer, a written
    domain or STORE_LABELS, with at most a store word beside it ("Walmart",
    "Amazon.com", "Hy-Vee", "Kirkland Signature"). "Walmart Parent's
    Choice" names more than the store and is not one."""
    words = [w for w in re.split(r"[^a-z0-9'&-]+", _norm_name(name).replace('.com', ' com')) if w]
    core = ' '.join(w for w in words if w not in _STORE_WORDS)
    if not core:
        return False
    return core in KNOWN_RETAILERS or core in STORE_LABELS or bool(_DOMAIN_IN_TEXT.fullmatch(_norm_name(name)))


_DOMAIN_IN_TEXT = re.compile(r'([a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|co|us|io|shop|store|ca|co\.uk))\b')


def _norm_name(name) -> str:
    return ' '.join(str(name or '').lower().replace('’', "'").split())


# ─── The stores an answer names (2Q-1) ─────────────────────────────────────
#
# 2O-4 made the brand-direct record a rule's, and its store pass kept a store
# only from a unit that also carried a buy word ("buy", "sold", "in stock"),
# and never the brand's own site. A where-to-buy answer lists stores with a
# price after each ("**Target** - $28.49", "Costco also has a bulk box for
# $44.99"), so FL14's Retailer coverage read 49 of 60 before the 2O-4 rescore
# and 36 of 60 after, on the same answers. This is the coding instead: one
# pass over the whole answer, no model, the same text giving the same list.
#
#   stores    every alias of KNOWN_RETAILERS, every domain of the merchant's
#             retailer list (supply's /retailers) written or named by its
#             label, and the merchant's own site (2N-1's brand row): an own
#             domain written ("pampers.com") or the brand's site in words
#             ("the Pampers website", "directly from Pampers").
#   order     first appearance in the answer (`position` 1..n, `at` the
#             character offset of that first mention).
#   role      'unavailable' when every mention sits in a clause that says
#             the store does not have it ("Costco doesn't carry Size 1"),
#             'recommendation' otherwise. Routing counts neither an
#             unavailable store nor a domain written only as a source.

#: Aliases that are also everyday words ("target weight", "a chewy texture"):
#: in an answer they name the store only written with a capital.
CAPITALISED_ONLY = frozenset({'target', 'chewy', 'backcountry', 'rollback', 'rei', 'public lands'})

#: A clause that says the store does not have the product.
_UNAVAILABLE = re.compile(
    r"\b(?:out of stock|sold out|unavailable|not (?:available|sold|carried|stocked|in stock|listed)|"
    r"(?:doesn't|does not|don't|do not|won't|no longer|never) (?:carry|carries|sell|sells|stock|stocks|have|has|list)|"
    r"(?:isn't|is not|aren't|are not) (?:available|sold|carried|stocked|listed))\b", re.I)
#: Where a clause ends: a line, a sentence, a semicolon, a "but", or a comma
#: before "and", "while", "whereas" or "though" ("Pampers.com sells it, and
#: Costco doesn't carry it").
_CLAUSE_BREAK = re.compile(r"\n+|(?<=[.!?])\s+(?=[A-Z0-9*\"'(\[-])|;\s+|,?\s+but\s+|"
                           r",\s+(?:and|while|whereas|although|though)\s+", re.I)
#: The brand's own site in words. {b} is the brand, escaped.
_OWN_SITE = (
    r"(?<![a-z0-9]){b}(?:'s)?\s+(?:official\s+)?(?:web\s?site|site|online\s+store|store|shop)(?![a-z])",
    r"(?<![a-z0-9])official\s+{b}\s+(?:web\s?site|site|online\s+store|store|shop)(?![a-z])",
    r"(?<![a-z])(?:directly|direct|straight)\s+from\s+(?:the\s+)?{b}(?![a-z0-9])",
)


def _clauses(text: str) -> List[tuple]:
    """(start, end) of each clause, in order."""
    out, at = [], 0
    for m in _CLAUSE_BREAK.finditer(text):
        out.append((at, m.start()))
        at = m.end()
    out.append((at, len(text)))
    return out


def _label(domain: str) -> Optional[str]:
    """The name a domain is written by ("babylist" of babylist.com), when it reads as one."""
    head = domain.split('.')[0]
    return head if len(head) >= 4 and head.isalpha() else None


def named_stores(answer, *, retailers: Iterable[str] = (), own_domains: Iterable[str] = (),
                 brand: Optional[str] = None) -> List[dict]:
    """
    The stores an answer names, first named first: [{name, domain, position,
    at, role, own, listed}]. `retailers` are the merchant's retailer domains
    (supply's /retailers `domains`), `own_domains` its own sites, `brand` the
    brand's name for its site written in words. See the section comment.
    """
    text = str(answer or '').replace('\u2019', "'")
    lowered = text.lower()
    own = [d for d in dict.fromkeys(ea.normalize_domain(d) for d in own_domains or []) if d]
    listed = [d for d in dict.fromkeys(ea.normalize_domain(d) for d in retailers or []) if d and d not in own]
    patterns = {alias: domain for alias, domain in KNOWN_RETAILERS.items()}
    for domain in listed + own:
        patterns.setdefault(domain, domain)
        label = _label(domain)
        if label and domain in listed and label not in patterns:
            patterns[label] = domain
    hits: List[tuple] = []   # (start, end, domain)
    taken: List[tuple] = []
    for alias, domain in sorted(patterns.items(), key=lambda kv: -len(kv[0])):
        for m in re.finditer(r'(?<![a-z0-9])' + re.escape(alias) + r'(?![a-z0-9])', lowered):
            if any(s < m.end() and m.start() < e for s, e in taken):
                continue
            if (alias in CAPITALISED_ONLY or (alias == _label(domain) and alias not in KNOWN_RETAILERS)) \
                    and not text[m.start()].isupper():
                continue
            hits.append((m.start(), m.end(), domain))
            taken.append((m.start(), m.end()))
    for m in _DOMAIN_IN_TEXT.finditer(lowered):
        domain = ea.normalize_domain(m.group(1))
        if domain in KNOWN_RETAILERS.values() or domain in listed or domain in own:
            if not any(s < m.end() and m.start() < e for s, e in taken):
                hits.append((m.start(), m.end(), domain))
                taken.append((m.start(), m.end()))
    if brand and own:
        b = r'[\s\-]+'.join(re.escape(w) for w in _norm_name(brand).split())
        for rx in _OWN_SITE:
            for m in re.finditer(rx.format(b=b), lowered):
                if not any(s < m.end() and m.start() < e for s, e in taken):
                    hits.append((m.start(), m.end(), own[0]))
                    taken.append((m.start(), m.end()))
    clauses = _clauses(text)
    found: dict = {}
    for start, _end, domain in sorted(hits):
        clause = next(((s, e) for s, e in clauses if s <= start < e), (0, len(text)))
        gone = bool(_UNAVAILABLE.search(text[clause[0]:clause[1]]))
        if domain not in found:
            found[domain] = {'name': domain if domain in own else retailer_name(domain), 'domain': domain,
                             'at': start, 'role': 'unavailable' if gone else 'recommendation',
                             'own': domain in own, 'listed': domain in listed}
        elif not gone:
            found[domain]['role'] = 'recommendation'
    out = sorted(found.values(), key=lambda st: st['at'])
    for i, st in enumerate(out, 1):
        st['position'] = i
    return out
