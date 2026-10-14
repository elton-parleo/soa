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
    #: The record's retailer list. A brand's: every retailer domain its
    #: feed has a product_url for. A seller's: its own domain.
    retailer_list: List[str] = field(default_factory=list)
    #: variant_id (GTIN-14 for a feed merchant) -> the retailer domains
    #: that SKU has a URL at, in the feed's order.
    variant_retailers: Dict[str, List[str]] = field(default_factory=dict)
    #: Why the record could not be read, when it could not.
    record_error: Optional[str] = None

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
      retailers  GET /merchants/{slug}/retailers
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
        key = row.get("gtin14") or row.get("gtin")
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
