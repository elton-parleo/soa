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

// ─── DRAFT COPY — NOT FINAL ──────────────────────────────────────────────
//
// Placeholders pending the product owner's rewrite. The framing to
// preserve: the store's edge returned HTTP 403 to a cryptographically
// verified agent reader (Web Bot Auth). That is a finding about the
// store's own configuration, not a failure of our scan, and the wording
// must not apologize for the scan or blame the reader.
export const WITHHELD_HERO_HEADLINE = {
  plain: 'DRAFT — Agents know you.',
  emphasis: 'What your store tells them could not be read this run.',
}

export const PILLAR_BAND_COPY = {
  accessibility: ({ measurable, nominal }) =>
    `DRAFT — ${measurable} of ${nominal} points measurable this run. Your bot protection returned HTTP 403 to a cryptographically verified agent reader (Web Bot Auth), including on robots.txt. Agent access is scored on that refusal — it is the measurement. Catalog and protocol checks need pages we were not served.`,
  true_value: ({ measurable, nominal }) =>
    `DRAFT — ${measurable} of ${nominal} points measurable this run. Price, member value, and deal encoding are checked on product pages your edge did not serve us, so they are unscored rather than scored zero. What agents said about your value was measured and is shown below, uncounted.`,
  visibility: ({ measurable, nominal }) =>
    `DRAFT — ${measurable} of ${nominal} points measurable this run.`,
}

export const EXPOSURE_WITHHELD_COPY =
  'DRAFT — Exposure is modeled from your True Value score, which could not be measured this run. Showing a figure here would price a number we did not observe. Re-run once a verified agent reader is allowed through.'
