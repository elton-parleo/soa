// Pure derivation for the Merchant Command Center: channels,
// publications, catalog rows, timestamps and Merchant Center links.
//
// Verification and drift semantics deliberately do NOT live here — they
// live in verificationModel.js, the executable form of
// docs/verification-semantics.md. This file used to carry them too, and
// the result was three bugs in three days from rules that existed in
// one place and were re-derived, differently, in another. Anything that
// classifies or counts a verification record belongs there.
//
// Same convention as full-analysis-report/fullAnalysisDerive.js: no
// DOM, no fetches, every function a straight function of payloads the
// TrueSync API already serialized.

// The two surfaces the product treats as the real ones, pinned to the
// left of the matrix in this order. A product decision about column
// order — deliberately NOT a claim about what works: whether a channel
// actually publishes is derived from its publication rows, see
// channelImplementation() below.
const PRIMARY_CHANNEL_SLUGS = ['schema_org', 'merchant_center']

// The upstream's PublicationRow.status enum, collapsed to what a matrix
// cell can say. 'validated'/'compiled' are pre-publish states and read
// the same as an explicit compiled_not_published.
const NOT_IMPLEMENTED_RE = /not implemented/i

// ─── Channels ────────────────────────────────────────────────────────

// Real-first column order. Anything not named in PRIMARY_CHANNEL_SLUGS
// keeps the order the API returned it in.
export function orderChannels(channels) {
  if (!Array.isArray(channels)) return []
  const primary = []
  for (const slug of PRIMARY_CHANNEL_SLUGS) {
    const found = channels.find((c) => c.slug === slug)
    if (found) primary.push(found)
  }
  const rest = channels.filter((c) => !PRIMARY_CHANNEL_SLUGS.includes(c.slug))
  return [...primary, ...rest]
}

/**
 * What a channel's own publication history says about whether it is
 * actually built, per channel slug:
 *
 *   'live'            at least one row reached published
 *   'not_implemented' rows exist, none published, and every failure
 *                     carries TrueSync's "not implemented" marker
 *   'failing'         rows exist, none published, failures are real ones
 *   'no_data'         no publication rows at all
 *
 * Evidence-based on purpose. A hardcoded stub list would have been
 * wrong the day it was written: as of 2026-08-22 production has
 * merchant_center failing "not implemented in Step 2" while deals_api,
 * mcp and deal_directory publish cleanly — the opposite of what the
 * channel names suggest. This self-corrects as the supply app ships.
 */
export function channelImplementation(channelSlug, publications) {
  const rows = (publications || []).filter((p) => p.channel_slug === channelSlug)
  if (rows.length === 0) return 'no_data'
  if (rows.some((r) => r.status === 'published')) return 'live'
  const errors = rows.map((r) => r.error || '').filter(Boolean)
  if (errors.length > 0 && errors.every((e) => NOT_IMPLEMENTED_RE.test(e))) {
    return 'not_implemented'
  }
  return 'failing'
}

// Channels that get the muted treatment: nothing has ever published, so
// a normal-weight cell would overstate them.
export function isMutedImplementation(state) {
  return state === 'not_implemented' || state === 'no_data'
}

// ─── Publications ────────────────────────────────────────────────────

/**
 * "listingId:channelSlug" -> the current publication row for that cell.
 *
 * Takes the FIRST row seen per key, which is correct only because the
 * upstream returns publications strictly newest-first. Verified against
 * production 2026-08-22 (350 rows, descending by both id and
 * compiled_at). Re-sorted here anyway rather than trusted: the cost is
 * nothing and the failure mode — silently showing a stale cell — would
 * be invisible.
 */
export function latestPublicationByCell(publications) {
  const byCell = new Map()
  for (const row of publications || []) {
    if (row.listing_id == null || !row.channel_slug) continue
    const key = `${row.listing_id}:${row.channel_slug}`
    const existing = byCell.get(key)
    if (!existing || publicationIsNewer(row, existing)) byCell.set(key, row)
  }
  return byCell
}

function publicationIsNewer(a, b) {
  if (a.id != null && b.id != null) return a.id > b.id
  return String(a.compiled_at || '') > String(b.compiled_at || '')
}

// Every publication row for one cell, newest first — the drawer's
// publish timeline. This is where the mock's separate Publications tab
// ended up living.
export function publicationHistoryForCell(publications, listingId, channelSlug) {
  return (publications || [])
    .filter((p) => p.listing_id === listingId && p.channel_slug === channelSlug)
    .sort((a, b) => (publicationIsNewer(a, b) ? -1 : 1))
}

// ─── Catalog rows ────────────────────────────────────────────────────

/**
 * Matrix rows from the catalog spine (GET /merchants/{slug}/schema-org)
 * joined to each listing's canonical record (GET /listings/{id}).
 *
 * The detail fetch is what supplies variant count, GTIN'd count and
 * catalog_product_id — the sync-rule API is keyed by the latter, and
 * nothing else on the page carries it. A listing whose detail fetch
 * failed still gets a row, with nulls where the detail would have gone,
 * rather than vanishing from the matrix.
 */
export function buildCatalogRows(spine, detailsById) {
  return (spine || []).map((entry) => {
    const detail = detailsById?.[entry.listing_id] || null
    const variants = detail?.variants || []
    const payload = entry.payload || {}

    return {
      listingId: entry.listing_id,
      catalogProductId: detail?.catalog_product_id ?? null,
      name: detail?.title || payload.name || `Listing ${entry.listing_id}`,
      productUrl: detail?.product_url || entry.product_url || null,
      image: (detail?.images || payload.image || [])[0] || null,
      category: detail?.category || null,
      variantCount: variants.length,
      gtinCount: variants.filter((v) => v.gtin).length,
      // The product-level GTIN only. Deliberately NOT falling back to
      // "the first variant that has one": a 12-variant product whose
      // GTIN line showed a single variant's code would read as the
      // product's identifier, which it is not. Products that genuinely
      // have one (the single-variant listings) show it; the rest are
      // described by the "n with GTIN" count instead.
      gtin: detail?.gtin || null,
      detailAvailable: detail != null,
    }
  })
}

// ─── Formatting ──────────────────────────────────────────────────────

// Relative freshness for a cell. Returns null (not "—", not "unknown")
// when there is no timestamp, so callers decide how absence reads.
export function relativeTime(iso, now = Date.now()) {
  if (!iso) return null
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return null

  const seconds = Math.round((now - then) / 1000)
  if (seconds < 0) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 30) return `${days}d ago`
  const months = Math.round(days / 30)
  if (months < 12) return `${months}mo ago`
  return `${Math.round(months / 12)}y ago`
}

export function absoluteTime(iso) {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return d.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

/**
 * merchants.google.com deep links for a Merchant Center publication.
 *
 * The real `external_ref` TrueSync records (verified 2026-08-24) is a
 * SEMICOLON-SEPARATED list of Content API resource names, one per
 * variant that was sent:
 *
 *   accounts/5841611055/productInputs/en~US~90:snug-fit-diapers-s3-small;
 *   accounts/5841611055/productInputs/en~US~90:snug-fit-diapers-s3-big
 *
 * The trailing segment is `{contentLanguage}~{feedLabel}~{offerId}`, and
 * the offerId is what Merchant Center's item-details view is keyed by.
 *
 * An earlier guess at this format (`accounts/{n}/products/{id}`) never
 * matched, so the drawer silently rendered no link at all. The
 * null-for-unmappable behaviour is kept deliberately — a link built out
 * of a ref we did not understand lands the operator on an error page,
 * which is worse than no link — but the shapes we DO understand now
 * actually resolve.
 */
const GMC_REF_PATTERNS = [
  // Current: accounts/{account}/productInputs/{lang}~{feedLabel}~{offerId}
  /^accounts\/(\d+)\/productInputs\/([^~]+)~([^~]+)~(.+)$/,
  // Older/simpler: accounts/{account}/products/{offerId}
  /^accounts\/(\d+)\/products\/(.+)$/,
]

export function gmcDeepLink(externalRef) {
  const parsed = parseGmcRef(externalRef)
  return parsed ? parsed.url : null
}

/**
 * One resource name -> { ref, account, offerId, language, country, url },
 * or null when it is not a resource name we can map.
 */
export function parseGmcRef(ref) {
  if (!ref || typeof ref !== 'string') return null
  const trimmed = ref.trim()
  if (!trimmed) return null

  const full = GMC_REF_PATTERNS[0].exec(trimmed)
  if (full) {
    const [, account, language, country, offerId] = full
    return { ref: trimmed, account, offerId, language, country, url: gmcItemUrl({ account, offerId, language, country }) }
  }

  const simple = GMC_REF_PATTERNS[1].exec(trimmed)
  if (simple) {
    const [, account, offerId] = simple
    return { ref: trimmed, account, offerId, language: null, country: null, url: gmcItemUrl({ account, offerId }) }
  }

  return null
}

function gmcItemUrl({ account, offerId, language = null, country = null }) {
  const params = new URLSearchParams({ a: account, offerId })
  if (language) params.set('language', language)
  if (country) params.set('country', country)
  return `https://merchants.google.com/mc/items/details?${params.toString()}`
}

/**
 * A publication's whole `external_ref` -> one entry per variant.
 *
 * Unmappable refs are kept with `url: null` rather than dropped: the
 * operator should still see that a ref exists, just without a link they
 * cannot trust.
 */
export function gmcExternalRefs(externalRef) {
  if (!externalRef || typeof externalRef !== 'string') return []
  return externalRef
    .split(';')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((ref) => parseGmcRef(ref) || { ref, account: null, offerId: null, language: null, country: null, url: null })
}

/**
 * The Merchant Center account id a publication was sent to, taken from
 * whichever of its refs parses. Lets a diagnostics record — which knows
 * its own offerId but not the account — build a link of its own.
 */
export function gmcAccountId(externalRef) {
  for (const entry of gmcExternalRefs(externalRef)) {
    if (entry.account) return entry.account
  }
  return null
}

// A diagnostics record's own offerId + the account from the publication
// -> a link straight to that item. Null if either half is missing.
export function gmcOfferLink(accountId, offerId) {
  if (!accountId || !offerId) return null
  return gmcItemUrl({ account: String(accountId), offerId: String(offerId) })
}
