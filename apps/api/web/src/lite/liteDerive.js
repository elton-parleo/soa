/**
 * Pure helper functions for the SoA Lite widget's Stage 4 combined
 * report: URL/brand input routing, dimension ranking/grouping, and the
 * client-side "modeled exposure" estimate. No DOM, no fetch — unit
 * tested directly.
 */

// ─── Input routing (LiteForm) ──────────────────────────────────────────────

/** "contains a dot + no spaces" per the product spec — deliberately
 * looser than a real URL check so a bare domain like "acme.com" (no
 * scheme) still routes to URL mode. */
export function looksLikeUrl(value) {
  const v = (value || '').trim()
  if (!v) return false
  return v.includes('.') && !/\s/.test(v)
}

const IGNORED_SUBDOMAIN_LABELS = new Set(['www', 'shop', 'store', 'shopping', 'get', 'buy', 'my', 'app'])

/**
 * Best-effort brand-name guess from a URL, shown as an editable
 * confirmation field — never submitted without the visitor's chance to
 * fix it. Strips generic subdomain labels (www, shop, ...) and takes
 * the leftmost remaining label, which also happens to do the right
 * thing for compound TLDs like .co.uk without needing a public suffix
 * list (see liteDerive.test.js).
 */
export function deriveBrandFromUrl(value) {
  const raw = (value || '').trim()
  if (!raw) return ''

  const candidate = raw.includes('://') ? raw : `https://${raw}`
  let hostname
  try {
    hostname = new URL(candidate).hostname
  } catch (_) {
    return ''
  }
  if (!hostname) return ''

  const labels = hostname.split('.').filter(Boolean)
  while (labels.length > 2 && IGNORED_SUBDOMAIN_LABELS.has(labels[0].toLowerCase())) {
    labels.shift()
  }
  const brandLabel = labels[0] || ''

  return brandLabel
    .split(/[-_]+/)
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ')
}

/** Display-only hostname for the "reading {domain} like an agent" progress
 * line and its terminal-state badges — strips scheme and a leading www. */
export function domainFromStoreUrl(storeUrl) {
  if (!storeUrl) return ''
  const candidate = storeUrl.includes('://') ? storeUrl : `https://${storeUrl}`
  try {
    return new URL(candidate).hostname.replace(/^www\./, '')
  } catch (_) {
    return storeUrl
  }
}

// ─── Scan dimensions (LiteFullReport why-section / fix list) ──────────────

const FOUNDATION_CODES = new Set(['F1', 'F2', 'F3'])

/** Groups the scan's flat dimension list into Foundation/Value families,
 * preserving each dimension's original relative order within its family. */
export function groupDimensionsByFamily(dimensions) {
  const foundation = []
  const value = []
  ;(dimensions || []).forEach((d) => {
    if (FOUNDATION_CODES.has(d.code)) {
      foundation.push(d)
    } else {
      value.push(d)
    }
  })
  return { foundation, value }
}

/** Ranks dimensions by opportunity size (max - score) descending — the
 * same rule the API uses to decide which 3 fixes are unlocked, so a
 * dimension's `locked` flag lines up with its position here. Deterministic
 * tiebreak by code. */
export function rankDimensionsByGap(dimensions) {
  return [...(dimensions || [])].sort((a, b) => {
    const gapA = (a.max || 0) - (a.score || 0)
    const gapB = (b.max || 0) - (b.score || 0)
    if (gapB !== gapA) return gapB - gapA
    return (a.code || '').localeCompare(b.code || '')
  })
}

// ─── Exposure calculator ────────────────────────────────────────────────

export const EXPOSURE_HAIRCUT = 0.85

/**
 * Modeled, not measured: revenue * AI-assisted share of purchases *
 * observed mention gap * a 0.85 haircut for everything the model can't
 * account for (attribution, seasonality, funnel leakage). Mention gap
 * is 1 - visibility/100 — visibility already is the primary entity's
 * share-of-voice metric, so its complement is how often an AI answer
 * is estimated to miss the brand entirely.
 */
export function computeExposure({ revenue, aiSharePct, visibility }) {
  const rev = Number(revenue) || 0
  const share = Math.max(0, Math.min(100, Number(aiSharePct) || 0)) / 100
  const vis = visibility === null || visibility === undefined ? 0 : Number(visibility)
  const mentionGap = Math.max(0, 1 - vis / 100)
  return rev * share * mentionGap * EXPOSURE_HAIRCUT
}

/** Shared by LiteTeaser's and LiteFullReport's accessibility dial — null
 * when the dial should show at full opacity with no badge (scan complete). */
export function accessibilityBadgeText(scanStatus) {
  switch (scanStatus) {
    case 'complete': return null
    case 'blocked': return 'blocked'
    case 'failed': return 'failed'
    case 'skipped': return 'no store URL'
    case 'running': return 'scanning…'
    default: return 'scanning…'
  }
}

// ─── Score bands (hero) ─────────────────────────────────────────────────

export const SCORE_BANDS = [
  { max: 40, name: 'Invisible', range: '<40', shortLabel: 'Invisible <40', tone: 'bad' },
  { max: 60, name: 'Partially readable', range: '40-59', shortLabel: 'Partially readable 40-59', tone: 'warn' },
  { max: 80, name: 'Readable but not countable', range: '60-79', shortLabel: 'Readable but not countable 60-79', tone: 'neutral' },
  { max: Infinity, name: 'Value visible', range: '80+', shortLabel: 'Value visible 80+', tone: 'good' },
]

/**
 * Maps a 0-100 composite score to its band — the same 4-tier scale used
 * by the Parleo Scan report (see design-refs/). Bands are <40, 40-59,
 * 60-79, 80+; a missing score is treated as 0 (Invisible) rather than
 * hiding the band entirely, since the pill is always shown once a
 * composite score exists at all.
 */
export function getScoreBand(score) {
  const s = score === null || score === undefined ? 0 : Number(score)
  return SCORE_BANDS.find((band) => s < band.max) || SCORE_BANDS[SCORE_BANDS.length - 1]
}

// One line per band tier — honest and generic (derived from the band the
// composite score already falls in), never a fabricated specific claim.
// A real per-report verdict (report.verdict) always wins when present;
// no backend stage emits one yet, so this fallback is what actually
// renders today.
const BAND_VERDICT_FALLBACK = {
  bad: "Agents mostly can't find or price you yet.",
  warn: 'Agents see fragments — most of your value stays invisible.',
  neutral: "Agents can read your store, but can't yet count what it's worth.",
  good: 'Agents can find, read, and price your store end to end.',
}

export function getVerdictLine(report) {
  if (report?.verdict) return report.verdict
  const band = getScoreBand(report?.composite)
  return BAND_VERDICT_FALLBACK[band.tone] || BAND_VERDICT_FALLBACK.bad
}

// ─── Misc formatting ────────────────────────────────────────────────────

export function formatDateStamp(date = new Date()) {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function formatCurrency(value) {
  const n = Number(value) || 0
  return `$${Math.round(n).toLocaleString('en-US')}`
}
