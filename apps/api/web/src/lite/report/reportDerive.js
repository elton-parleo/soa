/**
 * Pure report-shape helpers shared between the V4 report (src/lite/
 * report/*) and the legacy LiteFullReport.jsx it replaces. Extracted
 * rather than duplicated so both surfaces agree on what "not
 * measurable" means until the legacy file is retired.
 */
import {
  DIMENSIONS, PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE, PILLAR_VISIBILITY,
  VERDICT_AGENT_READY,
} from '../landing/scanDimensionsRegistry.js'
import { NAV_IDS } from './useReportSections.js'

// Partial-read report state (Part 2a): the ONE shared measurable-
// denominator context every surface — rail, hero, lane chart, pillar
// cards — reads from, so none of them can independently disagree about
// what "measurable" means this run. Built entirely from facts already
// serialized (each dimension's own earned/max/na/blocked), the same
// exclusion pillarEarnedMax already applies per pillar, just summed
// across all three and paired with each pillar's registry-nominal
// full_max (pillarNominalWeight) — never a second, forked definition.
export function buildMeasurableContext(pillars) {
  const vis = pillarEarnedMax(pillars.visibility)
  const acc = pillarEarnedMax(pillars.accessibility)
  const tv = pillarEarnedMax(pillars.true_value)
  const visFull = pillarNominalWeight(PILLAR_VISIBILITY)
  const accFull = pillarNominalWeight(PILLAR_ACCESSIBILITY)
  const tvFull = pillarNominalWeight(PILLAR_TRUE_VALUE)
  const full_max = visFull + accFull + tvFull
  const measurable_max = vis.max + acc.max + tv.max
  const earned = vis.earned + acc.earned + tv.earned
  return {
    earned,
    measurable_max,
    full_max,
    unmeasurable_points: Math.max(0, full_max - measurable_max),
    visibility: { earned: vis.earned, measurable_max: vis.max, full_max: visFull },
    accessibility: { earned: acc.earned, measurable_max: acc.max, full_max: accFull },
    true_value: { earned: tv.earned, measurable_max: tv.max, full_max: tvFull },
  }
}

function _hasBlockedDim(pillar) {
  return (pillar?.dimensions || []).some((d) => d.blocked || d.seen?.blocked)
}

// Part 1: partial_read is a RENDERING state, never a persisted one —
// some pillars/dimensions measured, at least one not, for a reason
// about our reach rather than the merchant's score. Gated on an actual
// `blocked` dimension existing somewhere (a reach failure) — never
// just on measurable_max falling short of full_max, since `na`
// (inapplicable, e.g. member_value_na) shrinks that same denominator
// for reasons that have nothing to do with our reach and must never
// trigger this state (Part 4a: unread is not na). 'unreachable' (total
// network/DNS failure, nothing responded — not even robots.txt) stays
// on today's failure treatment (1b): it isn't "honestly narrower," a
// run that didn't happen.
export function isPartialRead(pillars, degradedReason) {
  if (degradedReason === 'unreachable') return false
  const hasBlocked = _hasBlockedDim(pillars.visibility) || _hasBlockedDim(pillars.accessibility) || _hasBlockedDim(pillars.true_value)
  if (!hasBlocked) return false
  return buildMeasurableContext(pillars).measurable_max > 0
}

// Part 3c: which failure-point registry entry explains this run.
// 'partial' covers everything that isn't a named run-level reason —
// e.g. a complete-status run whose sampled product pages still came
// back too thin to score a dimension (per-dimension coverage='blocked'
// with no run-level degraded_reason at all).
export function partialReadFailurePoint(degradedReason) {
  if (degradedReason === 'no_product_pages_found') return 'no_product_pages_found'
  if (degradedReason === 'blocked') return 'blocked'
  return 'partial'
}

export function isV3Report(report) {
  return Boolean(report.pillars)
}

// Analytics session (report_viewed.state): the registry's closed
// vocabulary is scored/partial/blocked — 'expired' is handled entirely
// upstream in LiteWidget.jsx, which never reaches this component for
// an expired report at all. partialReadFailurePoint's own
// 'no_product_pages_found' folds into 'partial' here, matching that
// function's own doc comment ("'partial' covers everything that isn't
// a named run-level reason").
export function deriveReportViewedState(pillars, degradedReason) {
  if (!isPartialRead(pillars, degradedReason)) return 'scored'
  return partialReadFailurePoint(degradedReason) === 'blocked' ? 'blocked' : 'partial'
}

// earned = sum over every dimension row (na/blocked dims are already
// zeroed server-side); max = sum over non-na, non-blocked rows only —
// a dimension's nominal max isn't pre-zeroed the way member_value's na
// branch is, so this filter is what keeps a blocked/na dim from
// silently dragging the denominator down as a false zero.
export function pillarEarnedMax(pillar) {
  const dims = pillar?.dimensions || []
  const earned = dims.reduce((sum, d) => sum + (d.earned || 0), 0)
  const max = dims.filter((d) => !d.na && !d.blocked).reduce((sum, d) => sum + (d.max || 0), 0)
  return { earned, max }
}

export function pillarNominalWeight(pillar) {
  return DIMENSIONS.filter((d) => d.pillar === pillar).reduce((sum, d) => sum + d.weight, 0)
}

export function dimByCode(dims, code) {
  return (dims || []).find((d) => d.code === code) || null
}

// couldn't-read set — never na (member_value_na is "doesn't apply", a
// different concept from "we couldn't measure it this run").
export function blockedTrueValueDims(pillars) {
  return (pillars.true_value?.dimensions || []).filter((d) => d.blocked || d.seen?.blocked)
}

export function anyTrueValueEncodeBlocked(pillars) {
  return blockedTrueValueDims(pillars).length > 0
}

export function trueValueNotMeasurableCount(pillars) {
  const naCount = (pillars.true_value?.dimensions || []).filter((d) => d.na).length
  return naCount + blockedTrueValueDims(pillars).length
}

export function isAgentReady(pillars) {
  return pillars.verdict === VERDICT_AGENT_READY
}

const VISIBILITY_WEAK_THRESHOLD = 0.5
const TRUE_VALUE_STRONG_THRESHOLD = 0.75

// S1's one-line hero headline — {plain, emphasis}, rendered as
// `plain <em>emphasis</em>` — deliberately a simpler, punchier shape
// than the old file's verdict-narrative sentence (deriveHeroVerdict);
// same priority order (weak visibility overrides everything, then the
// na framing, then the zero/partial/full True Value bands) since both
// read off the same pillar ratios.
export function deriveScoreHeroHeadline(pillars) {
  const vis = pillarEarnedMax(pillars.visibility)
  const tv = pillarEarnedMax(pillars.true_value)
  const visRatio = vis.max ? vis.earned / vis.max : 0
  const tvRatio = tv.max ? tv.earned / tv.max : 0

  if (visRatio < VISIBILITY_WEAK_THRESHOLD) {
    return { plain: 'Agents barely know you exist.', emphasis: "Value isn't the first fix." }
  }
  if (pillars.member_value_na) {
    return { plain: 'Agents know you. Your value score is', emphasis: 'normalized.' }
  }
  if (tv.earned === 0) {
    return { plain: 'Agents know you. They', emphasis: "never talk about your value." }
  }
  if (tvRatio >= TRUE_VALUE_STRONG_THRESHOLD) {
    return { plain: 'Agents know you, and', emphasis: 'they get your value right.' }
  }
  return { plain: "Agents know you. They can't", emphasis: 'read your value.' }
}

// Part B: score-derived fallback headlines. Same "next to the
// readiness thresholds" placement as VISIBILITY_WEAK_THRESHOLD/
// TRUE_VALUE_STRONG_THRESHOLD above — one definition, so the bands can
// never drift between the three pillars or between this and any other
// ratio-based read of the same scores. earned/max ratio, per pillar:
//   >= .75           -> positive
//   .40 - .75        -> mixed
//   <  .40            -> negative (the pre-Part-B hardcoded line, kept
//                        verbatim so an already-published low score
//                        keeps reading exactly as it always has)
// A fallback headline must never assert a result the numbers
// contradict (the bug this replaces: DEFAULT_HEADLINES was
// unconditionally negative, rendered even on a 14/18 accessibility
// score) — every band's line is deliberately checked against its own
// ratio range before use (see the tests next to this file).
const HEADLINE_BAND_POSITIVE_THRESHOLD = 0.75
const HEADLINE_BAND_MIXED_THRESHOLD = 0.40

export const NOT_MEASURABLE_HEADLINE = "Couldn't be measured this run"

const SCORE_BAND_HEADLINES = {
  [PILLAR_VISIBILITY]: {
    positive: 'Agents recognize you and bring you up often',
    mixed: "Agents know you, but don't always mention you",
    negative: 'Agents know who you are',
  },
  [PILLAR_ACCESSIBILITY]: {
    positive: 'Agents can read most of what you publish',
    mixed: "Agents can knock, but can't read everything",
    negative: "Agents can knock, but can't read much",
  },
  [PILLAR_TRUE_VALUE]: {
    positive: 'Your value reaches agents clearly',
    mixed: "Some of your value reaches the answer, some doesn't",
    negative: 'Your value leaks before it reaches the answer',
  },
}

// Exported for direct testing — computes the band straight from the
// pillar's own earned/max (the SAME pillarEarnedMax every other score
// display on the report already uses), so the headline can never
// contradict the number sitting right next to it. max === 0 (nothing
// measured) reads as not-measurable, not a fabricated negative band.
export function deriveScoreBandHeadline(report, pillarKey) {
  const { earned, max } = pillarEarnedMax(report?.pillars?.[pillarKey])
  if (!max) return NOT_MEASURABLE_HEADLINE
  const ratio = earned / max
  const band = ratio >= HEADLINE_BAND_POSITIVE_THRESHOLD ? 'positive' : ratio >= HEADLINE_BAND_MIXED_THRESHOLD ? 'mixed' : 'negative'
  return SCORE_BAND_HEADLINES[pillarKey][band]
}

// Part 3 (generation) + Part B (score-derived fallback): the report's
// per-pillar one-line summary, in priority order —
//   1. 'generated'     — apps/pipeline/generation/pillar_headlines.py's
//                         own OpenAI-written, fact-grounded line for
//                         this run. Stored once, at completion; never
//                         regenerated here.
//   2. 'not_measurable' — nothing about this pillar was measured this
//                         run; the backend already knows this (empty
//                         facts) and says so directly.
//   3. 'derived'        — anything else: no generated_headlines at all
//                         (an older run, or Full Analysis before Part A
//                         shipped), or the backend's own source says
//                         generation didn't produce a usable line
//                         (legacy 'default', or 'derived' — both mean
//                         "compute a score-derived line here", which is
//                         the one place that has this pillar's REAL,
//                         fully-computed score to derive a band from —
//                         pillar_headlines.py deliberately doesn't
//                         duplicate that scoring formula, see its own
//                         module docstring).
export function resolvePillarHeadline(report, pillarKey) {
  const gen = report.generated_headlines?.[pillarKey]
  if (gen?.source === 'generated') return { headline: gen.headline, source: 'generated' }
  if (gen?.source === 'not_measurable') return { headline: gen.headline || NOT_MEASURABLE_HEADLINE, source: 'not_measurable' }
  const derived = deriveScoreBandHeadline(report, pillarKey)
  return { headline: derived, source: derived === NOT_MEASURABLE_HEADLINE ? 'not_measurable' : 'derived' }
}

export function pillarHeadline(report, pillarKey) {
  return resolvePillarHeadline(report, pillarKey).headline
}

export { PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE, PILLAR_VISIBILITY }

// Mobile rail replacement (RM1): the desktop rail (ReportRail.jsx) and
// the phone sections sheet (MobileReportNav.jsx) both need the same
// per-section score labels ("62/100", "14/20", "+9") — extracted here
// so the two renderers can never drift on what a given id's score
// means. `active` is the currently scroll-spied section id from
// useReportSections; this only computes what to SHOW, not the
// scroll-spy itself.
export const NAV_META = {
  score: { icon: 'chart', label: 'Score' },
  // Partial-read report state (Part 2b): only ever included in the
  // built list when `partial` is passed to buildNavItems below.
  why: { icon: 'eye', label: 'Why we stopped short' },
  viz: { icon: 'eye', label: 'Visibility' },
  acc: { icon: 'globe', label: 'Accessibility' },
  tv: { icon: 'tag', label: 'True Value' },
  fix: { icon: 'check', label: 'Ranked fixes' },
  truesync: { icon: 'refresh', label: 'The fix' },
  exp: { icon: 'card', label: 'Exposure' },
}

function kLabel(n) {
  if (n == null) return '—'
  return n >= 1e6 ? `$${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M` : `$${Math.round(n / 1e3)}K`
}

export function buildNavItems({ pillars, composite, exposure, active, partial }) {
  const vis = pillarEarnedMax(pillars.visibility)
  const acc = pillarEarnedMax(pillars.accessibility)
  const tv = pillarEarnedMax(pillars.true_value)

  return NAV_IDS.filter((id) => id !== 'fun' && (id !== 'why' || partial)).map((id) => {
    if (!(id in NAV_META)) return null
    const on = active === id
    const meta = NAV_META[id]
    let score = null
    if (id === 'why') score = '↓'
    else if (id === 'score') score = `${Math.round(composite ?? 0)}/100`
    else if (id === 'viz') score = `${Math.round(vis.earned)}/${Math.round(vis.max)}`
    else if (id === 'acc') score = `${Math.round(acc.earned)}/${Math.round(acc.max)}`
    else if (id === 'tv') score = `${Math.round(tv.earned)}/${Math.round(tv.max)}`
    else if (id === 'fix') score = `+${Math.round(vis.max - vis.earned + acc.max - acc.earned + tv.max - tv.earned > 0 ? Math.min(20, vis.max - vis.earned + acc.max - acc.earned + tv.max - tv.earned) : 0)}`
    else if (id === 'truesync') score = 'TrueSync'
    else if (id === 'exp') score = kLabel(exposure)
    return { id, on, meta, score }
  }).filter(Boolean)
}
