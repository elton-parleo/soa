"""
The catalog snapshot: the normalised shape the catalog-tier builders speak,
and build_snapshot / merge_merchant_record, which make one from supply's
stored payloads with no HTTP at all.

Moved here verbatim from apps/pipeline/clients/truesync_catalog.py (which
re-exports every name, and keeps the HTTP client) so the API can build a
snapshot for the console's study preview (2C) with the same code the
generation worker uses. Sync copies to apps/api/soa_shared/ and
apps/pipeline/soa_shared/.
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# ─── The snapshot ──────────────────────────────────────────────────────────
#
# A normalised shape the tier builders speak, rather than three raw
# payloads they would each have to re-navigate. Prices stay STRINGS all
# the way through — see soa_shared/expected_answers.py for why.

@dataclass
class CatalogVariant:
    variant_id: str
    title: Optional[str] = None
    size: Optional[str] = None
    count: Optional[int] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    list_price: Optional[str] = None
    currency: Optional[str] = None
    gtin: Optional[str] = None

    # From /incentives, merged on variant_id.
    member_price: Optional[str] = None
    member_tier_name: Optional[str] = None
    points_rules: List[dict] = field(default_factory=list)

    # 2L-2: the feed's `status` (active | retired) and, when retired, the
    # variant that replaced it ({variant_id, sku, gtin, product_name, title}),
    # as supply's catalog serves them. A record from before 2L-2 has neither:
    # active, no successor. See soa_shared/retired_lines.py.
    status: str = 'active'
    successor: Optional[dict] = None


@dataclass
class CatalogProduct:
    listing_id: int
    product_id: Optional[str] = None
    title: Optional[str] = None
    brand: Optional[str] = None
    product_url: Optional[str] = None
    published_at: Optional[str] = None
    variants: List[CatalogVariant] = field(default_factory=list)


@dataclass
class PricePoint:
    """One variant's price at one past publication. Oldest first in the
    list this belongs to, so a reader walks time forwards."""
    published_at: Optional[str] = None
    list_price: Optional[str] = None
    member_price: Optional[str] = None
    member_tier_name: Optional[str] = None


@dataclass
class PageRead:
    """2I: one page read of a variant, a row of supply's retailer-prices
    (`prices`): the page's domain and URL, the price it showed, and how the
    read went. `price` is None for a page not read yet or not readable."""
    domain: str
    url: Optional[str] = None
    price: Optional[str] = None
    currency: Optional[str] = None
    read_status: Optional[str] = None
    observed_at: Optional[str] = None
    role: Optional[str] = None

    @property
    def read(self) -> bool:
        return self.read_status in ('ok', 'empty')


@dataclass
class CatalogSnapshot:
    available: bool
    merchant_slug: Optional[str] = None
    display_name: Optional[str] = None
    domain: Optional[str] = None
    brand: Optional[str] = None
    products: List[CatalogProduct] = field(default_factory=list)
    # Every incentive the published records carry, flattened across
    # listings and de-duplicated by offer_id.
    incentives: List[dict] = field(default_factory=list)
    program_name: Optional[str] = None
    tiers: List[dict] = field(default_factory=list)
    # variant_id -> [PricePoint], oldest first. Empty for a variant with
    # only one publication, which is the honest state: with no prior
    # value on record we cannot call a mismatch stale.
    price_history: Dict[str, List[PricePoint]] = field(default_factory=dict)
    read_at: Optional[str] = None
    error: Optional[str] = None

    # ─── 2B: the merchant record ──────────────────────────────────────
    #
    # From GET /tenant (kind, hosting), /retailers (own_domain) and, for
    # an externally hosted merchant, /feed (each SKU's retailer URLs).
    # All None/empty for a snapshot built without them, which is exactly
    # the pre-2B snapshot: a hosted seller is generated as it always was.
    merchant_kind: Optional[str] = None      # seller | brand
    hosting: Optional[str] = None            # parleo | external
    own_domain: Optional[str] = None
    #: Every site that is the merchant's own, own_domain first: a brand can
    #: run a store and an informational site (W&S: trueshopstore.com and
    #: wiggleandsnug.com). From the record's own_domains when it serves
    #: one, else [own_domain]. A source at any of them is the merchant's.
    own_domains: List[str] = field(default_factory=list)
    #: The record's retailer list. A brand's: every retailer domain its
    #: feed has a product_url for. A seller's: its own domain.
    retailer_list: List[str] = field(default_factory=list)
    #: variant_id (GTIN-14 for a feed merchant) -> the retailer domains
    #: that SKU has a URL at, in the feed's order.
    variant_retailers: Dict[str, List[str]] = field(default_factory=dict)
    #: Why the record could not be read, when it could not.
    record_error: Optional[str] = None
    #: 2I: the newest retailer-prices read per variant_id, retailer pages
    #: only (comparison and own rows left out); None when it was not read (a hosted merchant, an older
    #: caller, or a failed read), {} when supply has no row for any variant.
    reads: Optional[Dict[str, List[PageRead]]] = None
    reads_error: Optional[str] = None

    @property
    def is_external(self) -> bool:
        return self.hosting == 'external'

    @property
    def study_brand(self) -> Optional[str]:
        """The name a question must carry. For an external SELLER it is the
        store (Petco), not the brand of whatever product it sells; for
        everyone else it is the brand on the records."""
        if self.is_external and self.merchant_kind == 'seller':
            return self.display_name or self.brand
        return self.brand

    # ─── Read-back, for the modal's catalog line and tier_config ──────

    @property
    def product_count(self) -> int:
        return len(self.products)

    @property
    def variant_count(self) -> int:
        return sum(len(p.variants) for p in self.products)

    @property
    def gtin_count(self) -> int:
        return sum(1 for p in self.products for v in p.variants if v.gtin)

    @property
    def code_count(self) -> int:
        """Distinct promo codes, not offers carrying one. Nineteen offers
        that all say WELCOME10 are one code a shopper can type."""
        return len({
            i.get('promo_code') for i in self.incentives if i.get('promo_code')
        })

    def variants(self):
        for product in self.products:
            for variant in product.variants:
                yield product, variant

    def find_variant(self, variant_id: str):
        for product, variant in self.variants():
            if variant.variant_id == variant_id:
                return product, variant
        return None, None


def _as_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def build_snapshot(
    catalog: dict,
    *,
    merchants: Optional[List[dict]] = None,
    incentives: Optional[dict] = None,
    price_history: Optional[dict] = None,
    merchant_slug: Optional[str] = None,
) -> CatalogSnapshot:
    """
    The four Part B payloads, merged into one snapshot.

    Only `catalog` is required. Each of the other three is a separate
    endpoint that can fail on its own, and each absence costs exactly one
    thing rather than the snapshot: no merchant list means no brand
    domain, no incentives means the value tier builds nothing, no history
    means a mismatch scores wrong rather than stale.
    """
    slug = (catalog or {}).get("merchant") or merchant_slug

    products = [
        CatalogProduct(
            listing_id=listing.get("listing_id"),
            product_id=listing.get("product_id"),
            title=listing.get("title"),
            brand=listing.get("brand"),
            product_url=listing.get("product_url"),
            published_at=listing.get("published_at"),
            variants=[
                CatalogVariant(
                    variant_id=variant.get("variant_id"),
                    title=variant.get("title"),
                    size=variant.get("size"),
                    count=_as_int(variant.get("count")),
                    attributes=variant.get("attributes") or {},
                    list_price=variant.get("list_price"),
                    currency=variant.get("currency"),
                    gtin=variant.get("gtin"),
                    status=variant.get("status") or 'active',
                    successor=variant.get("successor") or None,
                )
                for variant in listing.get("variants") or []
                if variant.get("variant_id")
            ],
        )
        for listing in ((catalog or {}).get("listings") or [])
    ]

    snapshot = CatalogSnapshot(
        available=True, merchant_slug=slug, products=products, read_at=_now(),
    )

    # The brand name comes off the published records, not off the
    # merchant row: it is what the payload says, which is what an
    # assistant reading the surface would have seen.
    for product in products:
        if product.brand:
            snapshot.brand = product.brand
            break

    for merchant in merchants or []:
        if merchant.get("slug") == slug:
            snapshot.display_name = merchant.get("display_name")
            snapshot.domain = merchant.get("domain")
            break

    if incentives:
        _merge_incentives(snapshot, incentives)
    if price_history:
        _merge_price_history(snapshot, price_history)

    return snapshot


def _domain(value) -> Optional[str]:
    from soa_shared.expected_answers import normalize_domain
    return normalize_domain(value)


def merge_merchant_record(snapshot: CatalogSnapshot, *, merchant: Optional[dict],
                          retailers: Optional[dict] = None, feed: Optional[dict] = None) -> CatalogSnapshot:
    """
    The merchant record onto a snapshot, from stored payloads (no HTTP),
    the same way build_snapshot builds the catalog — so the external mode
    is tested against recorded supply responses.

      merchant   one entry of GET /tenant's `merchants`
      retailers  GET /merchants/{slug}/retailers ({own_domain, own_domains?,
                 domains})
      feed       GET /merchants/{slug}/feed (external merchants)
    """
    merchant = merchant or {}
    snapshot.merchant_kind = merchant.get("kind")
    snapshot.hosting = merchant.get("hosting")
    if merchant.get("name") and not snapshot.display_name:
        snapshot.display_name = merchant.get("name")
    own = _domain((retailers or {}).get("own_domain")) or _domain(merchant.get("domain")) \
        or _domain(snapshot.domain)
    snapshot.own_domain = own
    listed = (retailers or {}).get("own_domains") or merchant.get("own_domains") or []
    snapshot.own_domains = []
    for domain in [own] + [_domain(d) for d in listed]:
        if domain and domain not in snapshot.own_domains:
            snapshot.own_domains.append(domain)
    if own and not snapshot.domain:
        snapshot.domain = own

    if snapshot.hosting != "external":
        return snapshot

    # A feed variant's shopper-facing name is its variant_label, which
    # supply serves as the variant's title (truesync/feed/serve.py). The
    # tier builders name variants by size and attributes, so the label is
    # carried as one. Only here: a hosted record's naming is untouched.
    for product, variant in snapshot.variants():
        if variant.title and variant.title != product.title and 'label' not in variant.attributes:
            variant.attributes = {**variant.attributes, 'label': variant.title}

    union: List[str] = []
    for row in (feed or {}).get("rows") or []:
        # 2I: the loader's identity rule, the variant's variant_key: its
        # GTIN-14, or sku:<sku> for a variant first seen without one (supply
        # feed/serve.py). Keyed by GTIN only, a GTIN-less variant found no
        # retailer and was never asked about.
        key = row.get("variant_key") or row.get("gtin14") or row.get("gtin") \
            or (f"sku:{row['sku']}" if row.get("sku") else None)
        domains = [d for d in (_domain(r.get("domain")) for r in row.get("retailers") or []
                               if r.get("url")) if d]
        if key:
            snapshot.variant_retailers[key] = domains
        for domain in domains:
            if domain not in union:
                union.append(domain)
    if snapshot.merchant_kind == "seller":
        snapshot.retailer_list = [own] if own else []
    else:
        snapshot.retailer_list = sorted(union)
    return snapshot


def _merge_incentives(snapshot: CatalogSnapshot, payload: dict) -> None:
    snapshot.program_name = payload.get("program_name")
    snapshot.tiers = payload.get("tiers") or []

    by_offer_id: Dict[str, dict] = {}
    variant_incentives: Dict[str, dict] = {}

    for listing in payload.get("listings") or []:
        for incentive in listing.get("incentives") or []:
            # An offer scoped to nineteen variants is ONE offer: the same
            # WELCOME10 on every variant is one code a shopper types, not
            # nineteen mechanics to ask about.
            key = incentive.get("offer_id") or repr(sorted(incentive.items(), key=str))
            if key not in by_offer_id:
                by_offer_id[key] = {
                    **incentive, "listing_id": listing.get("listing_id"),
                }
        for variant in listing.get("variants") or []:
            if variant.get("variant_id"):
                variant_incentives[variant["variant_id"]] = variant

    snapshot.incentives = list(by_offer_id.values())

    for _product, variant in snapshot.variants():
        merged = variant_incentives.get(variant.variant_id)
        if not merged:
            continue
        variant.member_price = merged.get("entitled_member_price")
        variant.member_tier_name = merged.get("entitled_tier_name")
        variant.points_rules = merged.get("points") or []


def _merge_price_history(snapshot: CatalogSnapshot, payload: dict) -> None:
    for listing in payload.get("listings") or []:
        for variant in listing.get("variants") or []:
            variant_id = variant.get("variant_id")
            if not variant_id:
                continue
            snapshot.price_history[variant_id] = [
                PricePoint(
                    published_at=point.get("published_at"),
                    list_price=point.get("list_price"),
                    member_price=point.get("member_price"),
                    member_tier_name=point.get("member_tier_name"),
                )
                for point in variant.get("history") or []
            ]


def _gtin14(value) -> Optional[str]:
    digits = ''.join(ch for ch in str(value or '') if ch.isdigit())
    return digits.zfill(14) if digits and len(digits) <= 14 else None


def merge_reads(snapshot: CatalogSnapshot, payload: Optional[dict], *, error: Optional[str] = None) -> CatalogSnapshot:
    """
    2I: supply's retailer-prices (the newest read of each variant x page,
    rows under `prices`) onto the snapshot, by variant: its GTIN-14, its
    sku:<sku> key, or its key as the read's variant_label. Comparison rows
    (role: comparison, 2A-4) are left out: they are read, never asked about.
    So are the brand's own pages (role: own): its own claims are the
    brand-direct tier's, and its price is asked at a retailer. A page off
    the record's retailer list is never asked about either (2B).
    """
    if error is not None or not isinstance(payload, dict):
        snapshot.reads, snapshot.reads_error = None, error
        return snapshot
    ids = {v.variant_id for _p, v in snapshot.variants()}
    reads: Dict[str, List[PageRead]] = {}
    for row in payload.get('prices') or payload.get('rows') or []:
        if not isinstance(row, dict) or row.get('role') in ('comparison', 'own'):
            continue
        domain = _domain(row.get('retailer_domain'))
        if not domain or domain == snapshot.own_domain or domain not in (snapshot.retailer_list or []):
            continue
        keys = [_gtin14(row.get('gtin')), f"sku:{row['sku']}" if row.get('sku') else None,
                row.get('variant_label'), row.get('variant_ref')]
        vid = next((k for k in keys if k and k in ids), None)
        if vid is None:
            continue
        reads.setdefault(vid, []).append(PageRead(
            domain=domain, url=row.get('url'), price=row.get('price'), currency=row.get('currency'),
            read_status=row.get('read_status'), observed_at=row.get('observed_at'), role=row.get('role')))
    snapshot.reads, snapshot.reads_error = reads, None
    return snapshot


def price_source(snapshot: CatalogSnapshot) -> List[dict]:
    """2I: per page domain, how many of the variants' pages were read and
    when (the newest read), and how many were not: what the Create Study
    modal names as the price source. [] when no page was read at all."""
    out: Dict[str, dict] = {}
    for rows in (snapshot.reads or {}).values():
        for r in rows:
            e = out.setdefault(r.domain, {'domain': r.domain, 'read_at': None, 'read_count': 0, 'unread_count': 0})
            if r.read:
                e['read_count'] += 1
                if r.observed_at and (e['read_at'] is None or str(r.observed_at) > str(e['read_at'])):
                    e['read_at'] = r.observed_at
            else:
                e['unread_count'] += 1
    if not any(e['read_count'] for e in out.values()):
        return []
    return sorted(out.values(), key=lambda e: (-e['read_count'], e['domain']))
