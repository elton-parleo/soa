/**
 * API client for the Merchant Command Center's TrueSync data.
 *
 * Split by direction, and the split is the whole design:
 *
 *   READS  go straight to TRUESYNC_API_BASE (the supply app). That API
 *          answers GETs with Access-Control-Allow-Origin: *, so there is
 *          nothing for this app's backend to add — see
 *          apps/api/app/routers/truesync.py's module docstring.
 *
 *   WRITES go to this app's own origin, through the authed proxy, which
 *          attaches X-TrueSync-Key server-side. The key is never in this
 *          bundle. (The upstream also rejects a browser PUT at preflight,
 *          so sync-rule writes could not work any other way.)
 *
 * Reads deliberately do NOT reuse ./api.js: that client attaches the
 * Supabase bearer token and signs the user out on any 401 — neither is
 * appropriate for a cross-origin call to a service that has never heard
 * of this app's sessions. Writes DO reuse it, because they hit this
 * app's authed API like every other mutation in the product.
 *
 * Every read carries a timeout. A TrueSync outage has to render as a
 * banner, and a fetch with no AbortSignal never resolves into one.
 */
import { DEFAULT_TRUESYNC_API_BASE } from './components/merchant-command-center/truesync-host.constants.js'

export const TRUESYNC_API_BASE = (
  import.meta.env.VITE_TRUESYNC_API_BASE || DEFAULT_TRUESYNC_API_BASE
).replace(/\/$/, '')

// Reads measured at ~0.3-0.7s against production on 2026-08-22. 15s is
// far past that: long enough that a slow-but-alive API still renders,
// short enough that a dead one shows its banner while the operator is
// still looking at the page.
export const READ_TIMEOUT_MS = 15000

export class TrueSyncError extends Error {
  constructor(message, { status = null, timedOut = false } = {}) {
    super(message)
    this.name = 'TrueSyncError'
    this.status = status
    this.timedOut = timedOut
  }
}

async function readJson(path, { timeoutMs = READ_TIMEOUT_MS, signal } = {}) {
  const url = `${TRUESYNC_API_BASE}${path}`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  // Caller-supplied signal (component unmount) and our timeout both have
  // to abort the same fetch, and AbortSignal.any isn't safe to assume in
  // the jsdom version the tests run under — so forward it by hand.
  const onOuterAbort = () => controller.abort()
  if (signal) signal.addEventListener('abort', onOuterAbort)

  try {
    const res = await fetch(url, { signal: controller.signal })
    if (!res.ok) {
      let detail = `GET ${path} → ${res.status}`
      try {
        const err = await res.json()
        if (err.detail) detail = typeof err.detail === 'string' ? err.detail : detail
      } catch (_) {}
      throw new TrueSyncError(detail, { status: res.status })
    }
    return await res.json()
  } catch (err) {
    if (err instanceof TrueSyncError) throw err
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
  // ─── Reads — cross-origin, direct ─────────────────────────────────
  getActiveBrand: (opts) =>
    readJson('/api/truesync/demo/active-brand', opts),

  getChannels: (opts) =>
    readJson('/api/truesync/channels', opts),

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

  // Every recorded publication, newest first — one call backs the whole
  // matrix. Verified 2026-08-22: rows come back strictly descending by
  // id and compiled_at, which is what lets the derive layer take the
  // first row it sees per (listing, channel) as the current state.
  getPublications: ({ limit = 500, ...opts } = {}) =>
    readJson(`/api/truesync/publications?limit=${limit}`, opts),

  // Verification history for one listing on one channel, newest first.
  // There is no bulk form and no all-channels form: the endpoint takes
  // exactly one channel (default merchant_center), so a full matrix is
  // listings x channels calls — see fetchAllVerifications below.
  getVerifications: (listingId, channelSlug, { limit = 100, ...opts } = {}) =>
    readJson(
      `/api/truesync/listings/${listingId}/verifications` +
      `?channel=${encodeURIComponent(channelSlug)}&limit=${limit}`,
      opts,
    ),
}

/**
 * Every cell's verification history, as "listingId:channelSlug" -> rows.
 *
 * One request per cell, because that is the only shape the endpoint
 * offers. Run at bounded concurrency rather than all at once: a 5x7
 * matrix is 35 requests, and firing them in a single burst is how you
 * get rate-limited by an API that was fine with the work itself.
 *
 * A cell whose request fails resolves to [] — an empty history renders
 * as ○ ("not yet verified"), which is the honest reading of "we could
 * not find out", and is never mistaken for a clean ✓.
 */
export async function fetchAllVerifications(listingIds, channelSlugs, { signal, concurrency = 8 } = {}) {
  const jobs = []
  for (const listingId of listingIds) {
    for (const channelSlug of channelSlugs) {
      jobs.push([listingId, channelSlug])
    }
  }

  const out = {}
  for (let i = 0; i < jobs.length; i += concurrency) {
    if (signal?.aborted) break
    const batch = jobs.slice(i, i + concurrency)
    await Promise.all(batch.map(async ([listingId, channelSlug]) => {
      try {
        const rows = await truesyncApi.getVerifications(listingId, channelSlug, { signal })
        out[`${listingId}:${channelSlug}`] = Array.isArray(rows) ? rows : []
      } catch (_) {
        out[`${listingId}:${channelSlug}`] = []
      }
    }))
  }
  return out
}
