"""
TrueSyncCatalogClient — the published catalog a study grounds its
questions in.

Reads four GETs on TRUESYNC_API_BASE, all of which serve stored
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

The tenant token goes on every read. Since supply's tenancy step these
routes are scoped to one customer and refuse a request without that
customer's token, sent as X-TrueSync-Key. Since Step 1C the token is the
STUDY'S CUSTOMER'S: TrueSyncCatalogClient.for_study() reads the study's
generation job for its customer org and opens that org's stored token
(soa_shared/customers.py), falling back to TRUESYNC_TENANT_TOKEN only for
a linked org with none stored, or a pre-1C study the backfill did not
stamp. A refusal names which of those it was.

Two kinds of failure, handled in opposite ways on purpose:

  * An OUTAGE — network error, 5xx, a merchant that is not there — never
    raises. The caller gets a snapshot with available=False and an error
    string, and the study degrades to its ungrounded form: fifty good
    AI-written questions are worth more than a failed job because a
    third-party endpoint was down for thirty seconds.

  * A REFUSAL — 401 or 403, the upstream saying this app's token is not
    authorized for this customer — raises TrueSyncNotAuthorized. That is
    a configuration fault, not weather: it will be true on every retry,
    and degrading silently would turn every study into an ungrounded one
    while reporting success. The generation job fails, saying why.

Canonical copy lives here (apps/pipeline/clients/), same as
deal_engine_client.py. The API app does NOT mirror this one: the Create
Study modal reads the same endpoints through the API app's TrueSync proxy
(apps/api/app/routers/truesync.py), which holds the token server-side.
"""
import logging
from typing import Any, Dict, List, Optional

import httpx

import soa_shared.config as config

logger = logging.getLogger(__name__)


class TrueSyncNotAuthorized(RuntimeError):
    """
    The upstream refused this app's tenant token (401/403).

    Raised, never folded into a snapshot: see the module docstring. The
    message is what the failed generation job records, so it says what
    to fix, and it never contains the token.
    """

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
# In soa_shared/catalog_snapshot.py (2C), with build_snapshot and the merges,
# so the API's study preview builds it with the same code. Re-exported.
from soa_shared.catalog_snapshot import (  # noqa: E402,F401
    CatalogProduct, CatalogSnapshot, CatalogVariant, PricePoint, _as_int, _domain, _merge_incentives,
    _merge_price_history, _now, build_snapshot, merge_merchant_record, merge_reads,
)


class TrueSyncCatalogClient:

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        token: Optional[str] = None,
        token_source: Optional[str] = None,
    ) -> None:
        self.base_url = (
            config.TRUESYNC_API_BASE if base_url is None else base_url
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.token = config.TRUESYNC_TENANT_TOKEN if token is None else token
        # Where the token came from, for the refusal message: the variable,
        # or which customer org's stored token. Never the token itself.
        self.token_source = token_source or "TRUESYNC_TENANT_TOKEN"

    @classmethod
    def for_study(cls, study_type: str, **kwargs) -> "TrueSyncCatalogClient":
        """
        A client holding the token of the customer this study was generated
        for. A study whose customer has no usable token raises
        TrueSyncNotAuthorized here, before any read: the same configuration
        fault as a refused token, named the same way.
        """
        from soa_shared import customers

        try:
            token, source = customers.token_and_source_for_study(study_type)
        except customers.CustomerError as exc:
            raise TrueSyncNotAuthorized(
                f"Not authorized for this customer: {exc}. Nothing was read, "
                f"rather than read without the customer's catalog."
            ) from exc
        return cls(token=token, token_source=source, **kwargs)

    def _headers(self) -> dict:
        # No token -> no header, so the upstream reports "no credential",
        # which TrueSyncNotAuthorized then names as an unset variable.
        return {"X-TrueSync-Key": self.token} if self.token else {}

    # ─── Transport ────────────────────────────────────────────────────

    def _get(self, path: str, params: Optional[dict] = None):
        """
        One read. Returns (payload, error) — never raises on an outage;
        raises TrueSyncNotAuthorized on a refused token.

        Synchronous on purpose. Every caller is inside the generation
        worker, which is a synchronous loop processing one job at a time;
        an async client here would need an event loop spun up around
        three sequential reads to save nothing.
        """
        url = f"{self.base_url}{path}"
        try:
            response = httpx.get(
                url, params=params, timeout=self.timeout_seconds, headers=self._headers(),
            )
        except Exception as exc:
            logger.warning("[truesync-catalog] GET %s failed: %s", url, exc)
            return None, str(exc)

        if response.status_code in (401, 403):
            if not self.token:
                reason = f"{self.token_source} is not set on this service"
            else:
                reason = f"TrueSync refused {self.token_source}"
            logger.error(
                "[truesync-catalog] GET %s -> %d: %s", url, response.status_code, reason,
            )
            raise TrueSyncNotAuthorized(
                f"Not authorized for this customer: {reason} (GET {path} -> "
                f"{response.status_code}). The study was not generated, rather "
                f"than generated without its catalog."
            )

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

    # ─── 2B: the merchant record and the reference ────────────────────

    def tenant(self) -> tuple:
        """(payload, error) for GET /api/truesync/tenant: every merchant the
        tenant owns, with its kind (seller | brand), hosting and domain."""
        return self._get("/api/truesync/tenant")

    def merchant_record(self, merchant_slug: str) -> tuple:
        """(merchant view from /tenant, error): kind, hosting, domain."""
        payload, error = self.tenant()
        if error is not None:
            return None, error
        for merchant in (payload or {}).get("merchants") or []:
            if merchant.get("slug") == merchant_slug:
                return merchant, None
        return None, f"merchant {merchant_slug!r} is not in this tenant"

    def retailers(self, merchant_slug: str) -> tuple:
        """(payload, error) for GET /merchants/{slug}/retailers:
        {own_domain, domains} — the retailer sites the feed may name."""
        return self._get(f"/api/truesync/merchants/{merchant_slug}/retailers")

    def tenant_own_domains(self) -> tuple:
        """
        2D: (every own domain of every merchant in this tenant, error).

        A tenant can hold a store and its brand as two merchants (Wiggle &
        Snug: trueshopstore.com and wiggleandsnug.com), and the brand-direct
        classifier treats a source at any of them as the brand's own. One
        GET /tenant, then GET /merchants/{slug}/retailers per merchant: its
        own_domains list, else the deprecated single own_domain. Normalized,
        in tenant order, each once. A merchant whose read fails is left out
        and named in the error; a refusal raises, as every read does.
        """
        from soa_shared.expected_answers import normalize_domain

        payload, error = self.tenant()
        if error is not None:
            return [], error
        domains, errors = [], []
        for merchant in (payload or {}).get("merchants") or []:
            slug = merchant.get("slug")
            if not slug:
                continue
            retailers, read_error = self.retailers(slug)
            if read_error is not None:
                errors.append(f"{slug}: {read_error}")
                continue
            listed = (retailers or {}).get("own_domains")
            if not listed:
                listed = [(retailers or {}).get("own_domain")]
            for domain in (normalize_domain(d) for d in listed):
                if domain and domain not in domains:
                    domains.append(domain)
        return domains, ("; ".join(errors) or None)

    def feed(self, merchant_slug: str) -> tuple:
        """(payload, error) for GET /merchants/{slug}/feed: the current feed
        version, row by row, each row with its retailers [{domain, url}]."""
        return self._get(f"/api/truesync/merchants/{merchant_slug}/feed")

    def retailer_prices(self, merchant_slug: str, *, as_of: Optional[str] = None) -> tuple:
        """(payload, error) for GET /merchants/{slug}/retailer-prices?as_of=.
        One row per variant x retailer page; see scoring/retailer_reference.py."""
        params = {"as_of": as_of} if as_of else None
        return self._get(f"/api/truesync/merchants/{merchant_slug}/retailer-prices", params=params)

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

        snapshot = build_snapshot(
            catalog,
            merchants=merchants,
            incentives=incentives,
            price_history=history,
            merchant_slug=merchant_slug,
        )
        self._merge_merchant_record(snapshot, merchant_slug)
        return snapshot

    def _merge_merchant_record(self, snapshot: "CatalogSnapshot", merchant_slug: str) -> None:
        """
        2B: kind, hosting, own domain and retailer list, onto the snapshot.

        An outage here costs the external mode, never the snapshot: the
        study is generated as the hosted form, and tier_config says why
        (record_error). A refusal still raises, as every read does.
        """
        merchant, error = self.merchant_record(merchant_slug)
        if error is not None:
            snapshot.record_error = error
            logger.warning("[truesync-catalog] merchant record unavailable for %s (%s); "
                           "generated as a hosted merchant", merchant_slug, error)
            return
        retailers = feed = None
        retailers, retailers_error = self.retailers(merchant_slug)
        if merchant.get("hosting") == "external":
            feed, feed_error = self.feed(merchant_slug)
            if feed_error is not None:
                snapshot.record_error = feed_error
        merge_merchant_record(snapshot, merchant=merchant, retailers=retailers, feed=feed)
        if snapshot.is_external and snapshot.merchant_kind != "seller":
            # 2I: a brand's price questions come from the newest page reads.
            prices, prices_error = self.retailer_prices(merchant_slug)
            merge_reads(snapshot, prices, error=prices_error)


# ─── Merging ───────────────────────────────────────────────────────────────
#
# A module function rather than client methods, so a snapshot can be built
# from stored payloads with no HTTP at all — which is how the tier
# builders are tested against a real Wiggle & Snug catalog rather than a
# hand-typed approximation of one.
