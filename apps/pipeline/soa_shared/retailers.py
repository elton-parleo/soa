"""
The closed retailer enum and the retailer names a question uses.

Shared by the scorer (scoring/answer_flags.py, which re-exports every name
here) and the catalog-tier generator (soa_shared/catalog_tiers.py), which
the API also runs for the console's study preview (2C). Moved here
verbatim from scoring/answer_flags.py; nothing about matching changed.
Sync copies to apps/api/soa_shared/ and apps/pipeline/soa_shared/.
"""
import re
from typing import List, Optional

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
    'publiclands.com': 'Public Lands', 'scheels.com': 'Scheels',
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


_DOMAIN_IN_TEXT = re.compile(r'([a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|co|us|io|shop|store|ca|co\.uk))\b')


def _norm_name(name) -> str:
    return ' '.join(str(name or '').lower().replace('’', "'").split())
