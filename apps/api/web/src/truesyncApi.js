/**
 * API client for the Merchant Command Center's TrueSync data.
 *
 * Split by what the upstream allows, since supply's tenancy step:
 *
 *   PUBLIC READS — the published serving surface (active brand, a
 *          merchant's schema-org feed, one listing's record). Straight to
 *          TRUESYNC_API_BASE; nothing to authenticate.
 *
 *   SCOPED READS — merchants, catalog, incentives, publications,
 *          verifications, prospects, drift, channels. The upstream
 *          refuses these without the tenant's token, and the token is a
 *          server-side secret, so they go to this app's own origin
 *          (/api/truesync/*), where the authed proxy attaches it.
 *
 *   WRITES — the same proxy, via ./api.js.
 *
 * The token is never in this bundle (truesyncTokenBundle.build.test.js).
 *
 * WHOSE token (Step 1C): every proxied call carries X-Parleo-Customer — the
 * page's selected customer (customerSelection.js), or `opts.customer` when a
 * caller reads under a different org, as the Create Study modal does for
 * the brand it is grounding in. The proxy resolves the org to its token
 * server-side and refuses an org the user may not select.
 *
 * Public reads deliberately do NOT carry this app's bearer token: it is a
 * cross-origin call to a service that has never heard of this app's
 * sessions. Scoped reads DO — they hit this app's authed API, and a 401
 * there means the session ended, exactly as it does in ./api.js.
 *
 * A 403 on a scoped read means TrueSync refused this app's tenant token.
 * It throws a TrueSyncError with notAuthorized set and NOT_AUTHORIZED as
 * its message, so the page says so instead of looking empty or broken.
 *
 * Every read carries a timeout. A TrueSync outage has to render as a
 * banner, and a fetch with no AbortSignal never resolves into one.
 */
import { apiAuthHeaders, expireSession } from './api.js'
import { customerHeaders } from './customerSelection.js'
import { DEFAULT_TRUESYNC_API_BASE } from './components/merchant-command-center/truesync-host.constants.js'

export const TRUESYNC_API_BASE = (
  import.meta.env.VITE_TRUESYNC_API_BASE || DEFAULT_TRUESYNC_API_BASE
).replace(/\/$/, '')

// Reads measured at ~0.3-0.7s against production on 2026-08-22. 15s is
// far past that: long enough that a slow-but-alive API still renders,
// short enough that a dead one shows its banner while the operator is
// still looking at the page.
export const READ_TIMEOUT_MS = 15000

// What a refused tenant token reads as, on every surface that shows it.
export const NOT_AUTHORIZED = 'Not authorized for this customer'

export class TrueSyncError extends Error {
  constructor(message, { status = null, timedOut = false } = {}) {
    super(message)
    this.name = 'TrueSyncError'
    this.status = status
    this.timedOut = timedOut
    // A 403 is never an outage and never "nothing here": callers that
    // would otherwise degrade a failed read to an empty one rethrow these.
    this.notAuthorized = status === 403
  }
}

/** A public read, straight to the supply app. */
function readJson(path, opts) {
  return fetchJson(`${TRUESYNC_API_BASE}${path}`, path, opts, {})
}

/** A scoped read, through this app's proxy, which holds the tenant token. */
function proxyReadJson(path, opts) {
  return fetchJson(
    path, path, opts,
    { ...apiAuthHeaders(), ...customerHeaders(opts?.customer) },
    { sameOrigin: true },
  )
}

/**
 * A proxied write for the setup wizard (Step 1C): JSON or a multipart body,
 * the session and the customer attached. Errors read like the reads' — a
 * 403 is NOT_AUTHORIZED, a 401 ends the session — and carry the upstream's
 * detail verbatim otherwise, because the wizard shows it to the operator.
 */
export async function proxyWrite(method, path, { json, formData, customer, timeoutMs = MUTATION_TIMEOUT_MS } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const headers = { ...apiAuthHeaders(), ...customerHeaders(customer) }
  let body
  if (formData) body = formData
  else if (json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  }
  try {
    const res = await fetch(path, { method, headers, body, signal: controller.signal })
    if (!res.ok) {
      if (res.status === 401) await expireSession()
      let detail = `${method} ${path} → ${res.status}`
      let structured = null
      try {
        const err = await res.json()
        if (err.detail && typeof err.detail === 'object' && !Array.isArray(err.detail)) {
          structured = err.detail
        }
        if (typeof err.detail === 'string') detail = err.detail
        else if (err.detail?.message) detail = err.detail.message
        else if (Array.isArray(err.detail)) {
          // FastAPI validation, or supply's per-incentive refusals.
          detail = err.detail.map((d) => d.msg || (d.errors || []).join('; ') || JSON.stringify(d)).join(' · ')
        }
      } catch (_) {}
      const error = new TrueSyncError(res.status === 403 && !detail.startsWith(NOT_AUTHORIZED)
        ? `${NOT_AUTHORIZED} — ${detail}` : detail, { status: res.status })
      // The rest of a structured detail (e.g. the org a half-finished
      // customer creation left behind), for the caller to act on.
      error.details = structured
      throw error
    }
    return await res.json()
  } catch (err) {
    if (err instanceof TrueSyncError || err?.authExpired) throw err
    if (err?.name === 'AbortError') {
      throw new TrueSyncError(`${method} ${path} did not complete within ${Math.round(timeoutMs / 1000)}s`, { timedOut: true })
    }
    throw new TrueSyncError(err?.message || 'This app could not be reached')
  } finally {
    clearTimeout(timer)
  }
}

const slugPath = (slug) => `/api/truesync/merchants/${encodeURIComponent(slug)}`

async function fetchJson(url, path, { timeoutMs = READ_TIMEOUT_MS, signal } = {}, headers, { sameOrigin = false } = {}) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  // Caller-supplied signal (component unmount) and our timeout both have
  // to abort the same fetch, and AbortSignal.any isn't safe to assume in
  // the jsdom version the tests run under — so forward it by hand.
  const onOuterAbort = () => controller.abort()
  if (signal) signal.addEventListener('abort', onOuterAbort)

  try {
    const res = await fetch(url, { signal: controller.signal, headers })
    if (!res.ok) {
      // This app's own session ended — not TrueSync's business, and not
      // a TrueSync error. Same handling as every other authed call.
      if (sameOrigin && res.status === 401) await expireSession()
      if (res.status === 403) {
        throw new TrueSyncError(NOT_AUTHORIZED, { status: 403 })
      }
      let detail = `GET ${path} → ${res.status}`
      try {
        const err = await res.json()
        if (err.detail) detail = typeof err.detail === 'string' ? err.detail : detail
      } catch (_) {}
      throw new TrueSyncError(detail, { status: res.status })
    }
    return await res.json()
  } catch (err) {
    if (err instanceof TrueSyncError || err?.authExpired) throw err
    // An abort from the outer signal is an unmount, not a failure the
    // user should see — but it is still an abort here, so let the caller
    // distinguish via timedOut only when our own timer fired.
    if (err?.name === 'AbortError') {
      throw new TrueSyncError(
        `TrueSync did not respond within ${Math.round(timeoutMs / 1000)}s`,
        { timedOut: true },
      )
    }
    throw new TrueSyncError(err?.message || 'TrueSync is unreachable')
  } finally {
    clearTimeout(timer)
    if (signal) signal.removeEventListener('abort', onOuterAbort)
  }
}

export const truesyncApi = {
  // ─── Public reads — cross-origin, direct ──────────────────────────
  getActiveBrand: (opts) =>
    readJson('/api/truesync/demo/active-brand', opts),

  // The catalog spine. Returns one entry per listing this merchant has
  // published to schema.org: { listing_id, product_url, published_at,
  // spec_version, payload }.
  getMerchantSchemaOrg: (merchantSlug, opts) =>
    readJson(`/api/truesync/merchants/${encodeURIComponent(merchantSlug)}/schema-org`, opts),

  // The canonical record for one listing — title, images, variants
  // (each with its own gtin), and the catalog_product_id the sync-rule
  // API is keyed by. The matrix needs this per listing; there is no
  // bulk form of it (see the report's endpoint-mismatch list).
  getListing: (listingId, opts) =>
    readJson(`/api/truesync/listings/${listingId}`, opts),

  // ─── Scoped reads — same-origin, through the proxy ───────────────

  getChannels: (opts) =>
    proxyReadJson('/api/truesync/channels', opts),

  // Every recorded publication, newest first — one call backs the whole
  // matrix. Verified 2026-08-22: rows come back strictly descending by
  // id and compiled_at, which is what lets the derive layer take the
  // first row it sees per (listing, channel) as the current state.
  getPublications: ({ limit = 500, ...opts } = {}) =>
    proxyReadJson(`/api/truesync/publications?limit=${limit}`, opts),

  // ─── The study generator's catalog reads ────────────────────────
  //
  // GETs that serve stored artifacts and never assemble, compile or
  // reach the Deal Engine. That serve-on-read property is what makes
  // them groundable: a generator reading a freshly recomputed price
  // would be checking the system against itself.
  //
  // These are the same endpoints apps/pipeline/clients/truesync_catalog.py
  // reads server-side at generation time. The modal reads them here so
  // its examples can be true for the selected brand BEFORE anything is
  // generated — see components/catalogTiers.js on why that is a mirror
  // and not a server round-trip.

  // Every merchant with a published TrueSync catalog. Not
  // /demo/active-brand, which is scoped to whichever storefront is
  // currently up: a brand swap changes the demo, not which records were
  // published, and a study must keep reading its brand's catalog after
  // the demo moves on.
  getMerchants: (opts) =>
    proxyReadJson('/api/truesync/merchants', opts),

  getMerchantCatalog: (merchantSlug, opts) =>
    proxyReadJson(`/api/truesync/merchants/${encodeURIComponent(merchantSlug)}/catalog`, opts),

  getMerchantIncentives: (merchantSlug, opts) =>
    proxyReadJson(`/api/truesync/merchants/${encodeURIComponent(merchantSlug)}/incentives`, opts),

  // Prospects — brands we observe but have no authorization to publish
  // for. Slug-keyed, and config rather than DB rows on the supply side,
  // so the list is small and cheap.
  getProspects: (opts) =>
    proxyReadJson('/api/truesync/prospects', opts),

  // The surface-vs-surface drift report for one prospect. Read-only
  // observation of public surfaces; nothing here publishes.
  getProspectDrift: (slug, opts) =>
    proxyReadJson(`/api/truesync/prospects/${encodeURIComponent(slug)}/drift`, opts),

  // Verification history for one listing on one channel, newest first.
  // The drawer's single-cell read; the matrix uses the bulk form below.
  getVerifications: (listingId, channelSlug, { limit = 100, ...opts } = {}) =>
    proxyReadJson(
      `/api/truesync/listings/${listingId}/verifications` +
      `?channel=${encodeURIComponent(channelSlug)}&limit=${limit}`,
      opts,
    ).then(unwrapVerifications),

  // Every listing's history on one channel, in one call (supply 1B's bulk
  // route): {merchant, listings: [{listing_id, lineage, verifications}]}.
  getMerchantVerifications: (merchantSlug, channelSlug, { limit = 100, ...opts } = {}) =>
    proxyReadJson(
      `${slugPath(merchantSlug)}/verifications` +
      `?channel=${encodeURIComponent(channelSlug)}&limit=${limit}`,
      opts,
    ),

  // ─── Step 1C: the customer's tenant and its SKU feed ─────────────

  // The selected customer's tenant and every merchant it owns.
  getTenant: (opts) =>
    proxyReadJson('/api/truesync/tenant', opts),

  getRetailers: (merchantSlug, opts) =>
    proxyReadJson(`${slugPath(merchantSlug)}/retailers`, opts),

  getFeed: (merchantSlug, opts) =>
    proxyReadJson(`${slugPath(merchantSlug)}/feed`, opts),

  getFeedHistory: (merchantSlug, opts) =>
    proxyReadJson(`${slugPath(merchantSlug)}/feed/history`, opts),

  getOwnedIncentives: (merchantSlug, opts) =>
    proxyReadJson(`${slugPath(merchantSlug)}/incentives/owned`, opts),

  // Writes (the wizard), through the same proxy.
  putRetailers: (merchantSlug, domains, opts = {}) =>
    proxyWrite('PUT', `${slugPath(merchantSlug)}/retailers`, { ...opts, json: { domains } }),

  validateFeed: (merchantSlug, files, { skipReachability = false, ...opts } = {}) => {
    const form = new FormData()
    for (const file of files) form.append('files', file, file.name)
    return proxyWrite(
      'POST',
      `${slugPath(merchantSlug)}/feed/validate?skip_reachability=${skipReachability ? 'true' : 'false'}`,
      { ...opts, formData: form },
    )
  },

  commitFeed: (merchantSlug, uploadId, mode, opts = {}) =>
    proxyWrite('POST', `${slugPath(merchantSlug)}/feed/commit`,
      { ...opts, json: { upload_id: uploadId, mode } }),

  putOwnedIncentives: (merchantSlug, incentives, opts = {}) =>
    proxyWrite('PUT', `${slugPath(merchantSlug)}/incentives/owned`,
      { ...opts, json: { incentives } }),

  // 1B's SKU-feed template, proxied. A Blob: the page saves it as a file.
  // Fetched rather than linked, because a plain link would not carry the
  // session this app's API requires.
  downloadTemplate: async (ext) => {
    const res = await fetch(`/api/truesync/feed/template.${ext}`, { headers: apiAuthHeaders() })
    if (!res.ok) {
      if (res.status === 401) await expireSession()
      throw new TrueSyncError(`The template could not be downloaded (${res.status})`, { status: res.status })
    }
    return res.blob()
  },
}

/**
 * The verifications endpoint's payload -> a plain array of records.
 *
 * It has shipped in two shapes. On 2026-08-22 it returned a bare
 * VerificationResponse[]. By 2026-08-24 it returns an envelope:
 *
 *   { listing_id, lineage: { <channel>: {...} }, verifications: [...] }
 *
 * Both are accepted, because pinning to either one means the page
 * silently shows an empty verification history the next time the supply
 * app moves — which is exactly what the envelope change already did:
 * the old `Array.isArray(rows) ? rows : []` guard turned every response
 * into [], so the drawer would have kept saying "no verification runs
 * recorded" even once real runs existed.
 *
 * Anything unrecognised resolves to [], which the badge layer reads as
 * ○ "not yet verified" — the honest reading of "we could not tell".
 *
 * The envelope's other half, `lineage` (per-channel publication_id /
 * status / compiled_at / published_at / spec_version), is deliberately
 * dropped here: the drawer already gets all of it from the publications
 * payload it loads for the timeline. Worth revisiting only if the two
 * ever disagree.
 */
export function unwrapVerifications(payload) {
  if (Array.isArray(payload)) return payload
  if (payload && Array.isArray(payload.verifications)) return payload.verifications
  return []
}


/**
 * Every cell's verification history, as "listingId:channelSlug" -> rows.
 *
 * One request per CHANNEL, against supply's bulk route, which answers for
 * every listing of the merchant at once. That retires the old sweep of one
 * request per listing x channel (~35, each a Vercel invocation). Per
 * channel rather than one all-channels call because the per-listing route
 * capped each (listing, channel) at `limit` rows and the bulk route caps
 * each listing; asking per channel keeps the cap exactly where it was, so
 * the cells hold the same rows they always did.
 *
 * Every listing asked for gets an entry for every channel — [] when the
 * bulk answer has nothing for it. A channel whose request fails resolves to
 * [] for every listing: an empty history renders as ○ ("not yet
 * verified"), the honest reading of "we could not find out".
 *
 * Except a refusal. A 403 is "not allowed to look", and a matrix of ○
 * would hide it — so it stops the load and rethrows, for the page to say
 * so. A 401 (session ended) rethrows for the same reason.
 */
export async function fetchAllVerifications(merchantSlug, listingIds, channelSlugs, { signal, limit = 100 } = {}) {
  const out = {}
  for (const listingId of listingIds) {
    for (const channelSlug of channelSlugs) out[`${listingId}:${channelSlug}`] = []
  }
  if (!merchantSlug || listingIds.length === 0) return out

  const wanted = new Set(listingIds.map(String))
  await Promise.all(channelSlugs.map(async (channelSlug) => {
    if (signal?.aborted) return
    try {
      const payload = await truesyncApi.getMerchantVerifications(merchantSlug, channelSlug, { signal, limit })
      for (const entry of payload?.listings || []) {
        if (!wanted.has(String(entry.listing_id))) continue
        out[`${entry.listing_id}:${channelSlug}`] = unwrapVerifications(entry)
      }
    } catch (err) {
      if (err?.notAuthorized || err?.authExpired) throw err
    }
  }))
  return out
}


// How long a proxied mutation may run before the page gives up on it.
// Publishing compiles a record to every enabled channel before it
// answers — measured at ~37s against production — so this is generous.
// It exists because api.js's shared request() has no timeout of its
// own: without it, a hung backend leaves a button reading "Publishing…"
// forever, which is a dead control by a slower route.
export const MUTATION_TIMEOUT_MS = 90000

export function withMutationTimeout(promise, label, timeoutMs = MUTATION_TIMEOUT_MS) {
  let timer
  const timeout = new Promise((_, reject) => {
    timer = setTimeout(
      () => reject(new TrueSyncError(
        `${label} did not complete within ${Math.round(timeoutMs / 1000)}s — it may still be running server-side`,
        { timedOut: true },
      )),
      timeoutMs,
    )
  })
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer))
}
