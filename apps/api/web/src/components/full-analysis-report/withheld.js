// withheld.js — ONE place to ask "was this value withheld?", for the
// Full Analysis report.
//
// Why this module exists at all. cycle_scoring_full.py's three-state
// machine (scored | composite_withheld | unverified) deliberately
// returns null for composite/verdict/tv_pct on a run where the crawl
// was blocked, because compute_composite's denominator is a static
// registry constant that never shrinks for an unmeasured dimension —
// scoring it anyway turns "we could not read your store" into an
// artificially low number and a failing verdict.
//
// That withholding only holds if every CONSUMER honors it. Six of them
// did not: each treated ABSENT as ZERO, FALSE, or WORST rather than as
// ABSENT, and between them they reconstructed the exact assertion the
// backend had just refused to make — a "$0"/"$1.7B" exposure figure, a
// "Not agent-ready" risk chip, a negative score-band headline, a
// "0/100" nav chip. Six local branches would have fixed today's six;
// this module exists so the SEVENTH consumer has one obvious thing to
// call instead of quietly re-deriving the bug.
//
// Scope: the Full Analysis report only. The lite report has its own
// (correct) handling inline in LiteFullReport.jsx, and lite's shared
// helpers in lite/report/reportDerive.js are deliberately NOT modified
// here — the wrappers below sit in front of them so lite's behavior is
// bit-for-bit unchanged.
import {
  NOT_MEASURABLE_HEADLINE,
  deriveScoreHeroHeadline,
  pillarEarnedMax,
  pillarHeadline,
  pillarNominalWeight,
} from '../../lite/report/reportDerive.js'
import { VERDICT_AGENT_READY } from '../../lite/landing/scanDimensionsRegistry.js'

/** The one glyph a withheld value renders as, everywhere on this report. */
export const WITHHELD_LABEL = '—'

/**
 * THE predicate. A value is withheld when it is absent — null,
 * undefined, or a non-finite number. Deliberately NOT `!value`: 0 is a
 * real, earned score (agent_access scores a genuine 0 when a store
 * 403s a verified reader) and must never be confused with "unmeasured".
 */
export function isWithheld(value) {
  if (value === null || value === undefined) return true
  return typeof value === 'number' && !Number.isFinite(value)
}

/** Reports built before the state machine shipped have no `state` — they
 *  predate any withholding, so they read as fully scored. */
export function reportState(pillars) {
  return pillars?.state || 'scored'
}

/** True when ANY of composite/verdict/tv_pct is withheld this run. */
export function isMeasurementWithheld(pillars) {
  return reportState(pillars) !== 'scored'
}

/** True when True Value's own applicable set was blocked — nothing about
 *  the value pipeline was measured, so no claim may be made about it. */
export function isUnverified(pillars) {
  return reportState(pillars) === 'unverified'
}

/** True when this specific pillar carries a dimension we could not read.
 *  Per-pillar rather than whole-report: a blocked crawl must not suppress
 *  Visibility, which is answer-side and fully measured either way. */
export function isPillarBlocked(pillars, pillarKey) {
  const dims = pillars?.[pillarKey]?.dimensions || []
  return dims.some((d) => d.blocked || d.seen?.blocked)
}

/**
 * #1 — the verdict chip, as a THREE-state read.
 *
 * Was `isAgentReady(pillars)`, i.e. `verdict === VERDICT_AGENT_READY`,
 * rendered as a binary. With verdict withheld that comparison is false,
 * so the chip asserted "Not agent-ready" in risk styling at the top of
 * the report — reinstating, in the most prominent element on the page,
 * the exact verdict the backend withheld. Withheld is its own outcome,
 * and it is neutral: we did not measure this, which is not the same as
 * measuring a failure.
 */
export function verdictDisplay(pillars) {
  if (isWithheld(pillars?.verdict)) {
    return { label: 'Unverified this run', tone: 'neutral', withheld: true }
  }
  const ready = pillars.verdict === VERDICT_AGENT_READY
  return { label: ready ? 'Agent-ready' : 'Not agent-ready', tone: ready ? 'success' : 'risk', withheld: false }
}

/** #5 — a composite score label. '—' when withheld, never `?? 0`. */
export function compositeLabel(composite, { withMax = false } = {}) {
  if (isWithheld(composite)) return withMax ? `${WITHHELD_LABEL}/100` : WITHHELD_LABEL
  const n = Math.round(composite)
  return withMax ? `${n}/100` : `${n}`
}

/**
 * #2 — the exposure figure.
 *
 * computeExposure models exposure as `1 - trueValue/100`, so a True
 * Value of 0 saturates it at MAXIMUM exposure. Passing a withheld score
 * through is not neutral: Number(null) is 0, so a withheld True Value
 * prices the worst case. And nulling `exposure` does not help either —
 * formatCurrency(null) is `Number(null) || 0`, which renders "$0", a
 * fabrication in the opposite direction. The figure has to be
 * SUPPRESSED at the render site, not zeroed at either end.
 *
 * Only `unverified` suppresses: under composite_withheld True Value is
 * clean and its score is real, so the model still has its input.
 */
export function exposureDisplay(pillars, exposure) {
  if (isUnverified(pillars)) return { suppressed: true, value: null }
  return { suppressed: false, value: exposure }
}

/**
 * #3 — the per-pillar score-band headline.
 *
 * deriveScoreBandHeadline picks positive/mixed/negative from
 * earned/max, and guards only on `max === 0`. That guard misses the
 * case that matters: value_protocols is real-scored even on a fully
 * blocked run (it needs no product pages), so True Value's max stays
 * 14, ratio 0/14 lands in the NEGATIVE band, and the report tells the
 * client "Your value leaks before it reaches the answer" on the
 * strength of one dimension whose own evidence cannot tell "absent"
 * from "we were refused". Gate on the pillar actually being blocked
 * instead of on max.
 */
export function pillarHeadlineSafe(report, pillarKey) {
  if (isPillarBlocked(report?.pillars, pillarKey)) return NOT_MEASURABLE_HEADLINE
  return pillarHeadline(report, pillarKey)
}

/**
 * #4 — the hero headline.
 *
 * `if (tv.earned === 0) -> "They never talk about your value."` reads a
 * withheld True Value as a measured silence. It is also contradicted by
 * our own payload: a blocked run can still carry a real said-side
 * signal (deal_citability said 4/5 from 310 run signals on cycle 163),
 * attached and uncounted. Suppressed whenever anything is withheld.
 */
export function heroHeadlineSafe(pillars) {
  if (isMeasurementWithheld(pillars)) return WITHHELD_HERO_HEADLINE
  return deriveScoreHeroHeadline(pillars)
}

/**
 * The measurable fraction behind a pillar's score — "5 of 18 points
 * measurable". A blocked pillar's score is honest arithmetic over what
 * we could read (earned / applicable_max), but the number ALONE reads
 * as "we checked everything and you scored zero". This is what the
 * per-pillar band puts next to it.
 */
export function measurableFraction(pillars, pillarKey) {
  const { max } = pillarEarnedMax(pillars?.[pillarKey])
  return { measurable: max, nominal: pillarNominalWeight(pillarKey) }
}

/**
 * The band a blocked pillar renders inline with its score, or null when
 * that pillar was fully measured. Resolves the degraded_reason itself so
 * no call site has to remember that the cause is part of the copy —
 * forgetting it is how a "your edge returned 403" line would end up on
 * a store that responded normally.
 */
export function pillarBand(report, pillarKey) {
  const pillars = report?.pillars
  if (!isPillarBlocked(pillars, pillarKey)) return null
  const build = PILLAR_BAND_COPY[pillarKey]
  if (!build) return null
  const reason = report?.scan?.degraded_reason || report?.reason || 'unknown'
  return build(reason, measurableFraction(pillars, pillarKey))
}

// ─── User-facing copy ───────────────────────────────────────────────────
//
// Keyed by degraded_reason, not just by pillar. Three reasons reach a
// withheld report (scan/engine.py::_derive_status) and they are NOT
// interchangeable:
//
//   blocked                 robots/sitemap/pages answered 403 or 429.
//                           Naming the refusal is accurate — we have the
//                           response codes.
//   no_product_pages_found  the store responded NORMALLY; discovery just
//                           found no product URLs to sample. engine.py is
//                           explicit that this is "never a site-blame"
//                           and "can be our reader's limitation" — so
//                           this copy must not imply the store refused
//                           anything. 11 cycles in the database are this
//                           case today.
//   unreachable             nothing answered at all (network/DNS).
//
// `null` covers rows written before degraded_reason existed (14 cycles):
// we know the crawl degraded but not why, so the copy states the effect
// and asserts no cause.
//
// Asserting one cause for all four would be the same failure this module
// exists to prevent — claiming something specific we did not observe —
// so the reason is threaded through rather than assumed.

const ACCESSIBILITY_CAUSE = {
  blocked: 'Your edge returned HTTP 403 to a cryptographically verified agent reader, robots.txt included. That refusal is itself the Agent Access result, and it is scored as one.',
  no_product_pages_found: 'Your store responded normally, but our reader could not locate product pages to sample — that may be a limit of our discovery rather than anything about your setup.',
  unreachable: 'Nothing answered at this address while the analysis ran, so no on-site check could be attempted.',
  unknown: 'Some of your on-site pages could not be read during this run.',
}

const TRUE_VALUE_CAUSE = {
  blocked: 'Price, member value and deal encoding are read from product pages your edge did not serve us.',
  no_product_pages_found: 'Price, member value and deal encoding are read from product pages our reader could not locate this run.',
  unreachable: 'Price, member value and deal encoding are read from product pages that never responded this run.',
  unknown: 'Price, member value and deal encoding are read from product pages that could not be read this run.',
}

export const WITHHELD_HERO_HEADLINE = {
  plain: 'We measured how agents talk about you.',
  emphasis: 'We could not measure what your store tells them.',
}

export const PILLAR_BAND_COPY = {
  accessibility: (reason, { measurable, nominal }) => (
    `${measurable} of ${nominal} points measurable this run. ${ACCESSIBILITY_CAUSE[reason] || ACCESSIBILITY_CAUSE.unknown} `
    + 'The catalog and protocol checks read pages we never saw, so they are unscored rather than scored zero.'
  ),
  true_value: (reason, { measurable, nominal }) => (
    `${measurable} of ${nominal} points measurable this run. ${TRUE_VALUE_CAUSE[reason] || TRUE_VALUE_CAUSE.unknown} `
    + 'They are unscored rather than scored zero. What agents actually said about your value was measured across every '
    + 'query in this run — shown below, and deliberately left out of the score rather than counted on half its evidence.'
  ),
  // Visibility is scored entirely from what agents said, so it has no
  // crawl-derived dimension and never reaches this band today. Kept as a
  // cause-neutral fallback so a future crawl-fed visibility dimension
  // cannot render an empty string.
  visibility: (reason, { measurable, nominal }) => (
    `${measurable} of ${nominal} points measurable this run.`
  ),
}

export const EXPOSURE_WITHHELD_COPY =
  'Exposure is modeled from your True Value score, and True Value could not be measured this run. Putting a figure '
  + 'here would price something we did not observe. Your answer-side results above are unaffected — they were measured '
  + 'normally. Re-run once those pages can be read and this estimate has its input back.'
