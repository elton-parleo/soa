// Pure derivation for the Merchant Command Center. Same convention as
// full-analysis-report/fullAnalysisDerive.js and lite/report/reportDerive.js:
// no DOM, no fetches, every function a straight function of payloads the
// TrueSync API already serialized.
//
// The rule this file exists to enforce: nothing on the matrix may be a
// guess. A missing publication row is "never published", not a blank; a
// listing with no verification history is "not yet verified", not a
// green tick. Every branch below has an honest terminal state.

// The two surfaces the product treats as the real ones, pinned to the
// left of the matrix in this order. A product decision about column
// order — deliberately NOT a claim about what works: whether a channel
// actually publishes is derived from its publication rows, see
// channelImplementation() below.
const PRIMARY_CHANNEL_SLUGS = ['schema_org', 'merchant_center']

// The upstream's PublicationRow.status enum, collapsed to what a matrix
// cell can say. 'validated'/'compiled' are pre-publish states and read
// the same as an explicit compiled_not_published.
const PUBLISH_STATE_BY_STATUS = {
  published: 'published',
  failed: 'failed',
  withdrawn: 'withdrawn',
  compiled: 'compiled_not_published',
  validated: 'compiled_not_published',
  compiled_not_published: 'compiled_not_published',
}

export const PUBLISH_STATE_LABEL = {
  published: 'Published',
  failed: 'Publish failed',
  withdrawn: 'Withdrawn',
  compiled_not_published: 'Compiled, not published',
  never: 'Never published',
}

// TrueSync marks a channel it has not built yet by failing the publish
// with this error rather than by any flag on the channel record — there
// is no is_stub / tier field on ChannelSpec (see the report's
// endpoint-mismatch list). Matching the marker is what lets the matrix
// tell "this surface isn't built" from "this publish broke".
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

// ─── Verification ────────────────────────────────────────────────────

/**
 * Findings out of one VerificationResponse's `drift` object, as
 * { variant, field, expected, observed } rows for the drawer's
 * master-vs-surface table.
 *
 * CAVEAT, and it is a real one: production carries zero verification
 * rows for every listing and every channel (checked 2026-08-22), and
 * the OpenAPI schema types `drift` only as a free-form object. So the
 * two shapes handled below are inferred, not observed. They are the two
 * the endpoint could plausibly emit:
 *
 *   { findings: [ {variant, field, expected, observed}, ... ] }
 *   { <field>: { expected, observed }, ... }
 *
 * Anything else counts as one opaque finding rather than being silently
 * dropped — an unreadable drift record still means drift, and losing it
 * would turn a warning cell green. Listed in the report as a shape to
 * confirm on the supply side.
 */
export function driftFindings(verification) {
  const drift = verification?.drift
  if (!drift || typeof drift !== 'object') return []

  if (Array.isArray(drift.findings)) {
    return drift.findings.map((f) => ({
      variant: f.variant ?? f.sku ?? f.variant_id ?? null,
      field: f.field ?? f.name ?? '—',
      expected: f.expected ?? f.master ?? null,
      observed: f.observed ?? f.surface ?? f.actual ?? null,
    }))
  }

  const entries = Object.entries(drift)
  if (entries.length === 0) return []

  const structured = entries.filter(
    ([, v]) => v && typeof v === 'object' && !Array.isArray(v) && ('expected' in v || 'observed' in v),
  )
  if (structured.length > 0) {
    return structured.map(([field, v]) => ({
      variant: v.variant ?? v.sku ?? null,
      field,
      expected: v.expected ?? null,
      observed: v.observed ?? v.actual ?? null,
    }))
  }

  return [{ variant: null, field: '(unparsed drift record)', expected: null, observed: null }]
}

// A verification phase that names a failure means the CHECK failed —
// which is not the same as the surface being wrong, and gets its own
// badge (✕) rather than being counted as drift.
function verificationFailed(verification) {
  const phase = String(verification?.phase || '').toLowerCase()
  return phase.includes('fail') || phase.includes('error')
}

/**
 * The cell's verification badge, from that cell's verification history
 * (newest first):
 *
 *   { kind: 'none'     }  ○  no verification run recorded
 *   { kind: 'failed'   }  ✕  the newest check itself failed
 *   { kind: 'drift', findingCount: n }  ⚠
 *   { kind: 'verified' }  ✓  ran, found no drift
 *
 * 'none' is the honest default and the one production currently always
 * produces. It is never inferred from a successful publish — publishing
 * says what was sent, verification says what the surface shows back.
 */
export function verificationBadge(verifications) {
  const list = verifications || []
  if (list.length === 0) return { kind: 'none', findingCount: 0 }

  const newest = list[0]
  if (verificationFailed(newest)) return { kind: 'failed', findingCount: 0 }

  const findings = driftFindings(newest)
  if (findings.length > 0) return { kind: 'drift', findingCount: findings.length }

  return { kind: 'verified', findingCount: 0 }
}

export const VERIFICATION_GLYPH = {
  none: '○',
  verified: '✓',
  drift: '⚠',
  failed: '✕',
}

export const VERIFICATION_LABEL = {
  none: 'Not yet verified',
  verified: 'Verified — no drift',
  drift: 'Drift found',
  failed: 'Verification failed',
}

// ─── Cells ───────────────────────────────────────────────────────────

/**
 * One matrix cell. `publication` is undefined when the API has no row
 * for this listing/channel pair at all — which renders "never
 * published", never an empty or optimistic cell.
 */
export function buildCell({ publication, verifications, implementation }) {
  const publishState = publication
    ? PUBLISH_STATE_BY_STATUS[publication.status] || 'compiled_not_published'
    : 'never'

  return {
    publishState,
    publishLabel: PUBLISH_STATE_LABEL[publishState],
    // Freshness is the publish timestamp when there is one, and the
    // compile timestamp otherwise — a cell that compiled but never
    // published still has a real "as of", and showing nothing there
    // would read as "no activity", which is wrong.
    at: publication?.published_at || publication?.compiled_at || null,
    isPublished: publishState === 'published',
    externalRef: publication?.external_ref || null,
    error: publication?.error || null,
    specVersion: publication?.spec_version || null,
    expressiveness: publication?.expressiveness || [],
    validation: publication?.validation || null,
    verification: verificationBadge(verifications),
    implementation,
    muted: isMutedImplementation(implementation),
  }
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

// ─── Header counts ───────────────────────────────────────────────────

/**
 * The header strip's numbers, counted over cells rather than listings:
 * "published" is surface cells, not products, because a product is
 * rarely all-or-nothing across seven channels.
 *
 * There is deliberately no last-verified-at here. VerificationResponse
 * carries no timestamp field of any kind — not created_at, not
 * checked_at (confirmed against the live OpenAPI schema 2026-08-22) —
 * so the header renders that stat as explicitly unavailable rather than
 * borrowing a publish timestamp and calling it a verification time.
 * See VERIFIED_AT_UNAVAILABLE below and the report's mismatch list.
 */
export function summarize(rows, channels, cellFor) {
  let publishedCells = 0
  let verifiedCells = 0
  let driftCells = 0
  let totalCells = 0

  for (const row of rows || []) {
    for (const channel of channels || []) {
      const cell = cellFor(row, channel)
      if (!cell) continue
      totalCells += 1
      if (cell.isPublished) publishedCells += 1
      if (cell.verification.kind === 'verified') verifiedCells += 1
      if (cell.verification.kind === 'drift') driftCells += 1
    }
  }

  return { publishedCells, verifiedCells, driftCells, totalCells }
}

export const VERIFIED_AT_UNAVAILABLE =
  'The verification API returns no timestamps'

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

// merchants.google.com deep link for a GMC publication, when its
// external_ref actually looks like a Merchant Center resource name
// (accounts/{account}/products/{product}). Returns null otherwise —
// a link built out of a ref that isn't one lands on an error page,
// which is worse than no link.
export function gmcDeepLink(externalRef) {
  if (!externalRef) return null
  const match = /accounts\/(\d+)\/products\/(.+)$/.exec(externalRef)
  if (!match) return null
  return `https://merchants.google.com/mc/items/details?a=${match[1]}&offerId=${encodeURIComponent(match[2])}`
}
