/**
 * Pure helper functions for the SoA Lite widget's Stage 4 combined
 * report: URL/brand input routing, dimension ranking/grouping, and the
 * client-side "modeled exposure" estimate. No DOM, no fetch — unit
 * tested directly.
 */
import { LITE_QUERY_COUNT } from './landing/scanDimensionsRegistry.js'

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
 * tiebreak by code. Stage 10: 'na' dimensions are excluded entirely —
 * there's no fixable gap on a dimension that isn't applicable to this
 * site type, and the server never ranks them either (see
 * public_lite.py::_build_scan_payload).
 *
 * Stage 19: also accepts v3 pillar dimension rows, which use `earned`
 * and a boolean `na` instead of `score`/`coverage` — the same top-3-
 * by-gap ranking rule the server applies in lite_pillars.py's
 * _rank_and_lock_fixes, so a v3 row's `locked` flag lines up here too.
 *
 * Part 3: the v3 fixes list itself no longer uses this function — it
 * reads the server-computed report.pillars.fixes (top 2, see
 * lite_pillars.py::_build_fixes_section) directly. This stays in use
 * for the legacy (pre-v3) fix table only, where scan.dimensions' own
 * top-3-free convention is unchanged. */
export function rankDimensionsByGap(dimensions) {
  return [...(dimensions || [])]
    .filter((d) => d.coverage !== 'na' && !d.na)
    .sort((a, b) => {
      const gapA = (a.max || 0) - (a.score ?? a.earned ?? 0)
      const gapB = (b.max || 0) - (b.score ?? b.earned ?? 0)
      if (gapB !== gapA) return gapB - gapA
      return (a.code || '').localeCompare(b.code || '')
    })
}

// ─── Exposure calculator ────────────────────────────────────────────────

export const EXPOSURE_HAIRCUT = 0.85

// Substitution channel (this session). Value leaks through TWO channels,
// and the old formula only ever sized one of them:
//   1. the direct channel — the agent omits the brand, or quotes it
//      without its real price/member value. Sized by invisibility.
//   2. the substitution channel — when the agent cannot verify what the
//      brand is worth, it does not leave the slot empty: it quotes a
//      competitor's price or deal IN THAT SAME ANSWER (the transcripts
//      this audit collects show exactly this). So the loss on an
//      affected transaction is larger than the brand's own margin leak
//      — the sale moves.
// 1.5 is a MODELED multiplier for that second channel, not a measured
// one, and the product is capped at 1 so modeled exposure can never
// exceed the AI-assisted revenue slice itself. It is deliberately a
// named constant and NOT a slider: a per-report knob would make every
// report's number incomparable to every other.
export const SUBSTITUTION_MULTIPLIER = 1.5

// The revenue slider's own range (LiteFullReport.jsx's ExposureCalculator
// <input type="range">) — annual units (Report redesign, Part 7): was
// monthly (10,000-10,000,000); the ×12 scale-up keeps the same real
// revenue ceiling the control could always represent, just in the unit
// the report now displays everywhere. Shared with seedAnnualRevenue
// below so a probe-seeded estimate is clamped to exactly what the
// control can represent, not a second, driftable copy of the same two
// numbers.
export const REVENUE_SLIDER_MIN = 120000
export const REVENUE_SLIDER_MAX = 120000000

// V4 redesign: the AI-assisted-share slider range shared by the
// landing Stakes widget and the report's ADJUST ASSUMPTIONS panel —
// matches the report mock's own slider bounds (5-40%) exactly, since
// nothing existing already owned this range.
export const AI_SHARE_SLIDER_MIN = 5
export const AI_SHARE_SLIDER_MAX = 40
export const AI_SHARE_DEFAULT_PCT = 20

/**
 * Report redesign (Part 7): the revenue probe's own annual USD estimate,
 * clamped to the slider's range — no /12 conversion anymore, since the
 * calculator's unit is now annual throughout. Null/undefined (probe
 * never ran, or came back unparseable/absurd — see revenue_probe.py)
 * returns null so the caller falls back to its existing static default,
 * unchanged.
 */
export function seedAnnualRevenue(annualRevenueUsd) {
  if (annualRevenueUsd === null || annualRevenueUsd === undefined) return null
  const annual = Number(annualRevenueUsd)
  if (!Number.isFinite(annual)) return null
  return Math.max(REVENUE_SLIDER_MIN, Math.min(REVENUE_SLIDER_MAX, annual))
}

/**
 * Modeled, not measured:
 *
 *   invisibility  = 1 - trueValueScore / 100
 *   channelFactor = min(1, invisibility * SUBSTITUTION_MULTIPLIER)
 *   exposure      = revenue * aiShare * channelFactor * EXPOSURE_HAIRCUT
 *
 * `trueValueScore` is the True Value pillar's NORMALIZED 0-100 score
 * (earned / applicable_max * 100 — the same normalization
 * lite_pillars._pillar already applies, so a Member Value N/A run does
 * not distort it). This input used to be the VISIBILITY pillar, which
 * made the whole figure wrong in the one way that mattered: it was
 * driven by the thing every AEO monitor already measures, while True
 * Value — what this audit exists to measure and what TrueSync exists to
 * fix — had no influence on the dollar number at all. A brand agents
 * mention constantly but cannot price scored a small exposure; worse,
 * recovering True Value points moved the number not at all, so the one
 * property the figure has to have (fix the gap, watch the number fall)
 * was silently false. It is now monotonic in trueValueScore and exactly
 * 0 at 100.
 *
 * The 0.85 haircut is unchanged — everything the model can't account
 * for (attribution, seasonality, funnel leakage). SUBSTITUTION_
 * MULTIPLIER covers the competitor-substitution channel; see its own
 * comment above.
 *
 * Worked examples, at $100M revenue and 20% AI-assisted share:
 *   True Value  10/100 -> 0.90 * 1.5 = 1.35, capped 1.0 -> $17,000,000
 *   True Value  40/100 -> 0.60 * 1.5 = 0.90              -> $15,300,000
 *   True Value  80/100 -> 0.20 * 1.5 = 0.30              -> $ 5,100,000
 *   True Value 100/100 -> 0                              -> $         0
 * Note the cap binds for every trueValueScore at or below 33.3 — those
 * runs all model the full AI-assisted slice, less the haircut.
 *
 * A null/absent trueValueScore (a legacy row with no pillars payload,
 * and the landing estimator, which has no scored brand at all) means
 * maximum gap — invisibility 1. Callers showing a number built that way
 * must say so; they are not showing a measurement. Revenue is annual
 * (Report redesign, Part 7), so the result is annual exposure.
 */
export function computeExposure({ revenue, aiSharePct, trueValueScore }) {
  const rev = Number(revenue) || 0
  const share = Math.max(0, Math.min(100, Number(aiSharePct) || 0)) / 100
  const raw = Number(trueValueScore)
  const tv = Number.isFinite(raw) ? raw : 0
  const invisibility = Math.max(0, 1 - tv / 100)
  const channelFactor = Math.min(1, invisibility * SUBSTITUTION_MULTIPLIER)
  return rev * share * channelFactor * EXPOSURE_HAIRCUT
}

/** LiteFullReport's accessibility dial — null when the dial should show
 * at full opacity with no badge (scan complete). */
export function accessibilityBadgeText(scanStatus) {
  switch (scanStatus) {
    case 'complete': return null
    case 'blocked': return 'blocked'
    case 'failed': return 'failed'
    case 'skipped': return 'no store URL'
    case 'running': return 'auditing…'
    default: return 'auditing…'
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

/** Best rival's share_pct, from either report shape: the teaser's flat
 * entity.som or the full report's entity.metrics.som. */
function _topRivalSom(entities) {
  return (entities || [])
    .filter((e) => e.role !== 'primary')
    .map((e) => ({ name: e.name, som: e.som ?? e.metrics?.som ?? null }))
    .filter((e) => e.som !== null && e.som !== undefined)
    .sort((a, b) => b.som - a.som)[0] || null
}

/**
 * Stage 7 (W5): data-driven, never stage-based, pre- or post-gate.
 * Priority: an explicit report.verdict (unchanged) -> the full report's
 * richer visibility_breakdown (mention-rate gap + top rival's share) ->
 * a share-only line from report.overall (all that's available pre-gate,
 * since the teaser never receives visibility_breakdown) -> the generic
 * band-based fallback (old API shape, or no rival data at all).
 */
export function getVerdictLine(report) {
  if (report?.verdict) return report.verdict

  const vb = report?.visibility_breakdown
  if (vb) {
    const primaryRate = (vb.mention_rate || []).find((r) => r.is_primary)
    const topRivalShare = [...(vb.share_of_mentions || [])]
      .filter((s) => !s.is_primary)
      .sort((a, b) => (b.share_pct || 0) - (a.share_pct || 0))[0]
    if (primaryRate) {
      let line = `Named in ${primaryRate.mentioned_queries} of ${primaryRate.total_queries} answers.`
      if (topRivalShare) {
        line += ` ${topRivalShare.entity} took ${Math.round(topRivalShare.share_pct)}% of all mentions.`
      }
      return line
    }
  }

  const topRival = _topRivalSom(report?.overall)
  if (topRival) {
    return `${topRival.name} took ${Math.round(topRival.som)}% of all mentions.`
  }

  const band = getScoreBand(report?.composite)
  return BAND_VERDICT_FALLBACK[band.tone] || BAND_VERDICT_FALLBACK.bad
}

/**
 * W3's payoff line — only when a single rival holds >=50% of all
 * mentions; omitted otherwise (no fabricated drama). visibilityBreakdown
 * is report.visibility_breakdown (undefined/null-safe).
 */
export function getDominantRivalPayoff(visibilityBreakdown) {
  const shares = visibilityBreakdown?.share_of_mentions || []
  const topRival = [...shares]
    .filter((s) => !s.is_primary)
    .sort((a, b) => (b.share_pct || 0) - (a.share_pct || 0))[0]
  if (!topRival || (topRival.share_pct || 0) < 50) return null

  const totalMentions = visibilityBreakdown?.totals?.total_mentions ?? 0
  const totalQueries = visibilityBreakdown?.totals?.total_queries ?? LITE_QUERY_COUNT
  return `${totalMentions} brand mentions across ${totalQueries} answers. Half went to one rival.`
}

/**
 * Stage 8 (W5) — the incentive-citation card's footer payoff line. Only
 * when the primary's rate is literally 0 (with >=2 mentions, so it's not
 * a thin sample) AND some rival's rate is >=25%; omitted otherwise (no
 * fabricated drama). incentiveCitation is
 * report.visibility_breakdown.incentive_citation.
 */
export function getIncentiveCitationPayoff(incentiveCitation) {
  const primary = (incentiveCitation || []).find((e) => e.is_primary)
  if (!primary || primary.rate_pct !== 0 || primary.mentions < 2) return null

  const topRival = (incentiveCitation || [])
    .filter((e) => !e.is_primary && e.rate_pct !== null && e.rate_pct !== undefined)
    .sort((a, b) => b.rate_pct - a.rate_pct)[0]
  if (!topRival || topRival.rate_pct < 25) return null

  return (
    `Agents mention you without your value: 0 of ${primary.mentions} mentions cited a ` +
    `deal or offer. ${topRival.entity}'s mentions carried one ${Math.round(topRival.rate_pct)}% of the time.`
  )
}

// ─── Misc formatting ────────────────────────────────────────────────────

export function formatDateStamp(date = new Date()) {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

/** Stage 12 (E4): display-only masking for the status-page email
 * confirmation ("a***@company.com") — the address itself is never put
 * in a URL; this is purely so the on-screen confirmation doesn't show
 * the visitor's own input back in full for anyone glancing at the
 * screen. Never used for the value actually sent to the API. */
export function maskEmail(email) {
  const value = (email || '').trim()
  if (!value.includes('@')) return value
  const [local, domain] = value.split('@')
  const maskedLocal = local.length <= 1 ? `${local}***` : `${local[0]}***`
  return `${maskedLocal}@${domain}`
}

/** Stage 12: formats whole seconds as "m:ss" for the elapsed-time counter. */
export function formatElapsed(totalSeconds) {
  const safe = Math.max(0, Math.floor(totalSeconds || 0))
  const m = Math.floor(safe / 60)
  const s = safe % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

export function formatCurrency(value) {
  const n = Number(value) || 0
  return `$${Math.round(n).toLocaleString('en-US')}`
}
