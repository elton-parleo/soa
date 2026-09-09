"""
TrueSyncCatalogClient — the published catalog a study grounds its
questions in.

Reads four public GETs on TRUESYNC_API_BASE, all of which serve stored
artifacts and none of which assembles, compiles or reaches the Deal
Engine:

    GET /api/truesync/merchants                       the brand list
    GET /api/truesync/merchants/{slug}/catalog        products and variants
    GET /api/truesync/merchants/{slug}/incentives     codes, member prices, points
    GET /api/truesync/merchants/{slug}/price-history   what staleness is scored against

That serve-on-read property is the whole reason this grounds anything. A
generator that read a freshly recomputed price would be checking the
system against itself and would agree with it by construction; what it
reads instead is what was actually published, with the published_at that
says when.

No admin key. These are unauthenticated reads, deliberately — a
generator holding the key that gates publishing could also publish.

Never raises on network or HTTP failure. A caller gets a snapshot with
available=False and an error string, because a TrueSync outage must
degrade a study to its ungrounded form rather than fail the generation
job outright: fifty good AI-written questions are worth more than a
failed job.

Canonical copy lives here (apps/pipeline/clients/), same as
deal_engine_client.py. The API app does NOT mirror this one: the Create
Study modal reads the same endpoints straight from the browser (they
answer with Access-Control-Allow-Origin: *), so a proxy hop through this
app's backend would add latency and buy nothing — the same split
truesyncApi.js already documents.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

import soa_shared.config as config

logger = logging.getLogger(__name__)

# Generous, and matched to the fact that this runs inside a generation
# job that has already decided to spend a minute on model calls. The
# reads themselves measure well under a second.
DEFAULT_TIMEOUT_SECONDS = 30.0

# How many publications per listing the price-history read walks. The
# staleness comparison only needs enough history to recognise a value we
# published before; a merchant republished nightly for a year should not
# have to serve the year.
PRICE_HISTORY_LIMIT = 50


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


class TrueSyncCatalogClient:

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.base_url = (
            config.TRUESYNC_API_BASE if base_url is None else base_url
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds

    # ─── Transport ────────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[dict] = None):
        """
        One read. Returns (payload, error) — never raises.

        Synchronous on purpose. Every caller is inside the generation
        worker, which is a synchronous loop processing one job at a time;
        an async client here would need an event loop spun up around
        three sequential reads to save nothing.
        """
        url = f"{self.base_url}{path}"
        try:
            response = httpx.get(url, params=params, timeout=self.timeout_seconds)
        except Exception as exc:
            logger.warning("[truesync-catalog] GET %s failed: %s", url, exc)
            return None, str(exc)

        if response.status_code == 404:
            return None, f"no TrueSync merchant at {path}"
        if response.status_code >= 400:
            detail = (response.text or "")[:300]
            logger.warning(
                "[truesync-catalog] GET %s -> %d: %s", url, response.status_code, detail,
            )
            return None, detail or f"upstream returned {response.status_code}"

        try:
            return response.json(), None
        except ValueError:
            return None, f"GET {path} returned a non-JSON body"

    # ─── The brand list ───────────────────────────────────────────────

    def list_merchants(self) -> tuple:
        """
        Every merchant with a published TrueSync catalog, as
        (merchants, error).

        Deliberately not /demo/active-brand, which is the only other
        merchant surface: a brand swap changes which storefront is up,
        not which records were published, and a study grounded in a brand
        must keep reading that brand's catalog after the demo moves on.
        """
        payload, error = self._get("/api/truesync/merchants")
        if error is not None:
            return [], error
        if not isinstance(payload, list):
            return [], "unexpected /merchants payload"
        return payload, None

    # ─── The snapshot ─────────────────────────────────────────────────

    def snapshot(self, merchant_slug: str, *, with_history: bool = True) -> CatalogSnapshot:
        """
        One merchant's published catalog, incentives and (optionally)
        price history, merged.

        with_history=False is for the generation path, which writes
        expectations against the CURRENT record and has no use for prior
        values. The scorer is what needs history, and it reads it at
        scoring time — history fetched at generation time would be a
        snapshot of the past as it looked before anything republished.
        """
        catalog, error = self._get(
            f"/api/truesync/merchants/{merchant_slug}/catalog"
        )
        if error is not None:
            return CatalogSnapshot(
                available=False, merchant_slug=merchant_slug,
                read_at=_now(), error=error,
            )

        merchants, merchants_error = self.list_merchants()
        if merchants_error is not None:
            # Not a failed snapshot. The domain is what a brand_mention
            # expectation cites, so its absence costs that one
            # expectation its domain half — which the vocabulary already
            # keeps as a separate bit precisely so it can be absent
            # without taking the brand half down with it.
            logger.warning(
                "[truesync-catalog] merchant list unavailable (%s); the study "
                "keeps its catalog but loses the brand domain", merchants_error,
            )
            merchants = []

        incentives, incentives_error = self._get(
            f"/api/truesync/merchants/{merchant_slug}/incentives"
        )
        if incentives_error is not None:
            logger.warning(
                "[truesync-catalog] incentives unavailable (%s); the value "
                "tier will build no questions rather than guess at any",
                incentives_error,
            )

        history = None
        if with_history:
            history, history_error = self._get(
                f"/api/truesync/merchants/{merchant_slug}/price-history",
                params={"limit": PRICE_HISTORY_LIMIT},
            )
            if history_error is not None:
                # The conservative direction, and the honest one: without
                # a record saying a value was once published we cannot
                # claim it was, so a mismatch scores wrong, not stale.
                logger.warning(
                    "[truesync-catalog] price history unavailable (%s); a "
                    "mismatch will score wrong rather than stale", history_error,
                )

        return build_snapshot(
            catalog,
            merchants=merchants,
            incentives=incentives,
            price_history=history,
            merchant_slug=merchant_slug,
        )


# ─── Merging ───────────────────────────────────────────────────────────────
#
# A module function rather than client methods, so a snapshot can be built
# from stored payloads with no HTTP at all — which is how the tier
# builders are tested against a real Wiggle & Snug catalog rather than a
# hand-typed approximation of one.

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
