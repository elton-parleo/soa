"""
Resolves a coder-extracted merchant_name (free text, e.g. "Walmart's
Pampers Size 3 listing") against the known merchants table, and classifies
each price observation's attribution status for pass-2 coding
(soa_price_observations.attribution_status).

Deliberately simple name resolution: case-insensitive exact match first,
then substring containment either direction, after normalizing
apostrophe variants (curly '/'  vs straight ' vs dropped entirely, e.g.
"Sam's Club" / "Sam's Club" / "Sams Club") and trailing punctuation/
whitespace. No fuzzy matching beyond that, no guessing — a name that
doesn't match any known merchant stays unresolved (the 'unmapped'
bucket), which is the signal for which merchants to add next.

classify_attribution additionally guards against a real failure mode
found in validation: the coder sometimes fills merchant_name with the
BRAND under discussion (e.g. "Pampers") rather than the actual retailer,
and because "Pampers" is also a legitimate merchant (the D2C site), that
silently resolves as if correct. When the resolved merchant equals the
observed entity's own brand, this function only keeps it as 'mapped' if
there's an explicit D2C signal (domain wording, or a citation to that
merchant's own domain in the same run) — otherwise it's downgraded to
the distinct 'brand_self_reference' status.
"""
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from soa_shared.models.merchant_ref import Merchant


@dataclass
class KnownMerchant:
    id: int
    name: str
    slug: str
    domain: Optional[str] = None


def _domain_of(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc or None


def load_known_merchants(session: Session) -> List[KnownMerchant]:
    rows = session.query(Merchant.id, Merchant.name, Merchant.slug, Merchant.url).all()
    return [
        KnownMerchant(id=r.id, name=r.name, slug=r.slug, domain=_domain_of(r.url))
        for r in rows if r.slug
    ]


_APOSTROPHES = ("’", "‘", "'", "`")


def _normalize(s: str) -> str:
    """Case, apostrophe-variant, and trailing-punctuation/whitespace
    normalization — "Sam's Club", "Sam's Club", and "Sams Club." all
    reduce to the same key."""
    s = s.strip().lower()
    for ch in _APOSTROPHES:
        s = s.replace(ch, "")
    s = s.rstrip(".,;:!?")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def resolve_merchant_slug(merchant_name: Optional[str], known_merchants: List[KnownMerchant]) -> Optional[str]:
    if not merchant_name:
        return None
    needle = _normalize(merchant_name)
    if not needle:
        return None

    for m in known_merchants:
        if needle == _normalize(m.slug.replace("-", " ")) or needle == _normalize(m.name):
            return m.slug

    for m in known_merchants:
        norm_slug = _normalize(m.slug.replace("-", " "))
        norm_name = _normalize(m.name)
        if norm_slug in needle or norm_name in needle:
            return m.slug

    return None


_D2C_SIGNAL_PHRASES = (".com", "website", "official site", "own site", "d2c")


def classify_attribution(
    entity_name: str,
    merchant_name: Optional[str],
    known_merchants: List[KnownMerchant],
    run_citation_domains: Iterable[str] = (),
) -> Tuple[Optional[str], str]:
    """
    Returns (merchant_slug_or_None, attribution_status), where status is
    one of 'mapped' | 'unmapped' | 'unattributed' | 'brand_self_reference'.
    """
    if not merchant_name or not merchant_name.strip():
        return None, "unattributed"

    resolved_slug = resolve_merchant_slug(merchant_name, known_merchants)
    if resolved_slug is None:
        return None, "unmapped"

    entity_brand_slug = resolve_merchant_slug(entity_name, known_merchants)
    if resolved_slug != entity_brand_slug:
        return resolved_slug, "mapped"

    # Self-reference: the resolved merchant IS the entity's own brand.
    # Keep as 'mapped' only with an explicit D2C signal.
    text_lower = merchant_name.strip().lower()
    if any(phrase in text_lower for phrase in _D2C_SIGNAL_PHRASES):
        return resolved_slug, "mapped"

    merchant = next((m for m in known_merchants if m.slug == resolved_slug), None)
    citation_domains = {d.lower() for d in run_citation_domains}
    if merchant and merchant.domain and merchant.domain.lower() in citation_domains:
        return resolved_slug, "mapped"

    return None, "brand_self_reference"
