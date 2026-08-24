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
 * How a verification record is read depends on the METHOD that produced
 * it, because the two methods put entirely different things in `drift`:
 *
 *   fetch_probe      fetches the live PDP and compares it to the master
 *                    record -> field-level findings
 *   gmc_diagnostics  reads Merchant Center product statuses back
 *                    -> { approved, issues[], httpStatus }
 *
 * Feeding one through the other's parser is what produced the bug this
 * layer now exists to prevent: a GMC record has no `findings` key and no
 * {expected, observed} pairs, so the field parser bottomed out at
 * "(unparsed drift record)" and every GMC row was counted as one unit of
 * catalog drift. A parse failure is not a finding, and it must never
 * reach the drift count.
 *
 * NOTE on naming: the API's own values are `gmc_diagnostics` and
 * `fetch_probe` (confirmed from the live OpenAPI's `method` query
 * description, 2026-08-24). `live_fetch` appears in the original spec
 * and is accepted as an alias so a rename on either side cannot silently
 * route records into the wrong parser.
 */
export const VERIFICATION_METHOD = {
  GMC_DIAGNOSTICS: 'gmc_diagnostics',
  FETCH_PROBE: 'fetch_probe',
}

const FETCH_PROBE_ALIASES = new Set(['fetch_probe', 'live_fetch'])

export function verificationMethod(verification) {
  const method = verification?.method
  return typeof method === 'string' ? method : null
}

export function isGmcDiagnostics(verification) {
  return verificationMethod(verification) === VERIFICATION_METHOD.GMC_DIAGNOSTICS
}

export function isFetchProbe(verification) {
  return FETCH_PROBE_ALIASES.has(verificationMethod(verification))
}

/**
 * One parsed verification record. Exactly one of these three shapes:
 *
 *   { kind: 'findings',   findings: [...] }   fetch_probe, understood
 *   { kind: 'gmc',        approved, issues, httpStatus }
 *   { kind: 'unparsed',   method, reason }    understood by nobody
 *
 * 'unparsed' is a first-class outcome rather than a fallback that
 * pretends to be a finding. Callers must treat it as "we could not
 * read this", never as evidence about the catalog.
 */
export function parseVerification(verification) {
  if (!verification || typeof verification !== 'object') {
    return { kind: 'unparsed', method: null, reason: 'record is not an object' }
  }

  const method = verificationMethod(verification)
  const drift = verification.drift

  if (isGmcDiagnostics(verification)) {
    const parsed = parseGmcDiagnostics(drift)
    if (parsed) return parsed
    return {
      kind: 'unparsed', method,
      reason: 'gmc_diagnostics record has no readable approved/issues payload',
    }
  }

  // fetch_probe, and anything else that still looks like field-level
  // drift. An unknown method with a recognisable findings shape is
  // better read than refused; an unknown method with an unrecognisable
  // one goes to the warning path, not the drift count.
  const findings = fetchProbeFindings(drift)
  if (findings !== null) return { kind: 'findings', findings }

  return {
    kind: 'unparsed',
    method,
    reason: method
      ? `no parser for method "${method}"`
      : 'record carries no method, and its drift payload is not field-level',
  }
}

/**
 * A gmc_diagnostics `drift` payload -> {approved, issues, httpStatus},
 * or null when it is not one.
 *
 * The live shape (listing 90, 2026-08-24):
 *   { "issues": [], "approved": false, "httpStatus": 404 }
 *
 * `approved` is the discriminator: `issues` alone is too generic a key
 * to key off, and an empty issues list is a real and common state (a
 * listing can be unapproved with nothing itemised, which is exactly
 * what production shows today).
 */
export function parseGmcDiagnostics(drift) {
  if (!drift || typeof drift !== 'object' || Array.isArray(drift)) return null
  if (!('approved' in drift) && !('issues' in drift)) return null

  const rawIssues = Array.isArray(drift.issues) ? drift.issues : []

  return {
    kind: 'gmc',
    approved: drift.approved === true,
    httpStatus: typeof drift.httpStatus === 'number' ? drift.httpStatus : null,
    issues: rawIssues.map(normaliseGmcIssue),
  }
}

// GMC issue codes carry their severity in the payload on some surfaces
// and only in the code on others (e.g.
// "pending_initial_policy_review_free_listings"). Both are read; an
// issue that declares nothing is 'info', never an invented error.
const GMC_SEVERITY_BY_KEYWORD = [
  [/disapprov|error|invalid|missing|violat/i, 'error'],
  [/pending|review|crawl|processing/i, 'pending'],
  [/warn|suggest|recommend|opportunit/i, 'warning'],
]

export function normaliseGmcIssue(issue) {
  if (typeof issue === 'string') {
    return { code: issue, description: null, detail: null, severity: gmcSeverity(issue, null) }
  }
  if (!issue || typeof issue !== 'object') {
    return { code: String(issue), description: null, detail: null, severity: 'info' }
  }

  const code = issue.code ?? issue.issueCode ?? issue.id ?? issue.title ?? null
  return {
    code: code == null ? null : String(code),
    description: issue.description ?? issue.title ?? issue.shortDescription ?? null,
    detail: issue.detail ?? issue.detailedDescription ?? issue.documentation ?? null,
    severity: gmcSeverity(code, issue.severity ?? issue.resolution ?? null),
  }
}

function gmcSeverity(code, declared) {
  if (typeof declared === 'string' && declared.trim()) {
    const value = declared.toLowerCase()
    if (value.includes('error') || value.includes('disapprov')) return 'error'
    if (value.includes('pending')) return 'pending'
    if (value.includes('warn') || value.includes('suggest')) return 'warning'
    return value
  }
  for (const [pattern, severity] of GMC_SEVERITY_BY_KEYWORD) {
    if (pattern.test(String(code || ''))) return severity
  }
  return 'info'
}

/**
 * A fetch_probe `drift` payload -> field-level findings, or **null**
 * when the payload is not field-level drift at all.
 *
 * The null return is the whole point of the rewrite. This used to
 * return a single synthetic "(unparsed drift record)" finding, which
 * read downstream as one unit of real drift. Now "I cannot read this"
 * and "I read it and found one problem" are different values, and only
 * the second reaches the badge.
 *
 * An empty object / null drift is "ran, found nothing" — [], not null.
 */
export function fetchProbeFindings(drift) {
  if (drift == null) return []
  if (typeof drift !== 'object' || Array.isArray(drift)) return null

  if (Array.isArray(drift.findings)) {
    return drift.findings.map((f) => ({
      variant: f?.variant ?? f?.sku ?? f?.variant_id ?? null,
      field: f?.field ?? f?.name ?? '—',
      expected: f?.expected ?? f?.master ?? null,
      observed: f?.observed ?? f?.surface ?? f?.actual ?? null,
    }))
  }

  const entries = Object.entries(drift)
  if (entries.length === 0) return []

  const structured = entries.filter(
    ([, v]) => v && typeof v === 'object' && !Array.isArray(v) && ('expected' in v || 'observed' in v),
  )
  if (structured.length === 0) return null

  return structured.map(([field, v]) => ({
    variant: v.variant ?? v.sku ?? null,
    field,
    expected: v.expected ?? null,
    observed: v.observed ?? v.actual ?? null,
  }))
}

/**
 * Field-level findings for a record, for callers that only want the
 * comparison table. An unreadable record yields [] here — ask
 * parseVerification() if you need to tell that from "no drift".
 */
export function driftFindings(verification) {
  const parsed = parseVerification(verification)
  return parsed.kind === 'findings' ? parsed.findings : []
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
 *   { kind: 'none'      }  ○  no verification run recorded
 *   { kind: 'failed'    }  ✕  the newest check itself failed
 *   { kind: 'drift', findingCount: n }  ⚠  real, parsed findings
 *   { kind: 'unparsed'  }  ?  the record could not be read
 *   { kind: 'verified'  }  ✓  ran, found nothing wrong
 *
 * `findingCount` counts ONLY findings from records that parsed. An
 * unreadable record gets its own kind and its own glyph so it can never
 * masquerade as catalog drift — the page must not report a problem with
 * the merchant's data when what it actually has is a problem reading
 * its own input.
 */
export function verificationBadge(verifications) {
  const list = verifications || []
  if (list.length === 0) return { kind: 'none', findingCount: 0 }

  const newest = list[0]
  if (verificationFailed(newest)) return { kind: 'failed', findingCount: 0 }

  const parsed = parseVerification(newest)

  if (parsed.kind === 'unparsed') {
    return { kind: 'unparsed', findingCount: 0, reason: parsed.reason }
  }

  if (parsed.kind === 'gmc') {
    // GMC has no field-level drift to count. Approved is clean; not
    // approved is a surface problem, reported by its issue count —
    // which is legitimately 0 when Merchant Center rejected the item
    // without itemising why (a 404, as production shows today).
    if (parsed.approved) return { kind: 'verified', findingCount: 0 }
    return { kind: 'drift', findingCount: parsed.issues.length, gmc: true }
  }

  if (parsed.findings.length > 0) {
    return { kind: 'drift', findingCount: parsed.findings.length }
  }
  return { kind: 'verified', findingCount: 0 }
}

export const VERIFICATION_GLYPH = {
  none: '○',
  verified: '✓',
  drift: '⚠',
  failed: '✕',
  // Deliberately not a warning triangle: this is "the page could not
  // read this", which must look different from "the catalog is wrong".
  unparsed: '?',
}

export const VERIFICATION_LABEL = {
  none: 'Not yet verified',
  verified: 'Verified — no drift',
  drift: 'Drift found',
  failed: 'Verification failed',
  unparsed: 'Verification record could not be read',
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
    // The newest record's timestamp. `created_at` shipped on
    // VerificationResponse with the 2026-08-24 verification work;
    // absent on older deployments, in which case this stays null and
    // the header says so rather than guessing from a publish time.
    verifiedAt: (verifications || [])[0]?.created_at || null,
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
 * `driftCells` counts only cells whose newest verification actually
 * parsed. Cells the page could not read are counted separately as
 * `unreadableCells` and surfaced as their own indicator — a parse
 * failure is a problem with this page, not evidence about the catalog,
 * and rolling it into "drifting" would overstate the merchant's
 * problems with our own bug.
 *
 * `lastVerifiedAt` is the newest `created_at` across every record. That
 * field did not exist when this page was written (see
 * VERIFIED_AT_UNAVAILABLE, now unused by the header); it shipped with
 * the 2026-08-24 verification work, so the stat is real.
 */
export function summarize(rows, channels, cellFor) {
  let publishedCells = 0
  let verifiedCells = 0
  let driftCells = 0
  let unreadableCells = 0
  let totalCells = 0
  let lastVerifiedAt = null

  for (const row of rows || []) {
    for (const channel of channels || []) {
      const cell = cellFor(row, channel)
      if (!cell) continue
      totalCells += 1
      if (cell.isPublished) publishedCells += 1
      if (cell.verification.kind === 'verified') verifiedCells += 1
      if (cell.verification.kind === 'drift') driftCells += 1
      if (cell.verification.kind === 'unparsed') unreadableCells += 1
      if (cell.verifiedAt && (!lastVerifiedAt || cell.verifiedAt > lastVerifiedAt)) {
        lastVerifiedAt = cell.verifiedAt
      }
    }
  }

  return { publishedCells, verifiedCells, driftCells, unreadableCells, totalCells, lastVerifiedAt }
}

// Kept for the case where a deployment predates created_at on
// VerificationResponse: the header falls back to this wording rather
// than showing a blank where a timestamp should be.
export const VERIFIED_AT_UNAVAILABLE =
  'No verification run has recorded a timestamp'

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
