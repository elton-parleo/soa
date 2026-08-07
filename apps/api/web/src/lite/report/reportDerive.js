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

export function isV3Report(report) {
  return Boolean(report.pillars)
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

const DEFAULT_PILLAR_HEADLINES = {
  [PILLAR_VISIBILITY]: 'Agents know who you are',
  [PILLAR_ACCESSIBILITY]: "Agents can knock, but can't read much",
  [PILLAR_TRUE_VALUE]: 'Your value leaks before it reaches the answer',
}

// Part 3: the report's generated (or registry-default) one-line pillar
// summary. apps/pipeline/generation/pillar_headlines.py computes and
// stores this once, at run-completion time — the report only ever
// reads what's stored here, never regenerates it. Falls back to the
// pre-Part-3 hardcoded title (DEFAULT_PILLAR_HEADLINES, mirroring that
// module's own DEFAULT_HEADLINES/NOT_MEASURABLE_HEADLINE verbatim) on
// an older run, a not-measurable pillar, or a rejected/failed
// generation for that pillar alone.
export function pillarHeadline(report, pillarKey) {
  return report.generated_headlines?.[pillarKey]?.headline || DEFAULT_PILLAR_HEADLINES[pillarKey]
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

export function buildNavItems({ pillars, composite, exposure, active }) {
  const vis = pillarEarnedMax(pillars.visibility)
  const acc = pillarEarnedMax(pillars.accessibility)
  const tv = pillarEarnedMax(pillars.true_value)

  return NAV_IDS.filter((id) => id !== 'fun').map((id) => {
    if (!(id in NAV_META)) return null
    const on = active === id
    const meta = NAV_META[id]
    let score = null
    if (id === 'score') score = `${Math.round(composite ?? 0)}/100`
    else if (id === 'viz') score = `${Math.round(vis.earned)}/${Math.round(vis.max)}`
    else if (id === 'acc') score = `${Math.round(acc.earned)}/${Math.round(acc.max)}`
    else if (id === 'tv') score = `${Math.round(tv.earned)}/${Math.round(tv.max)}`
    else if (id === 'fix') score = `+${Math.round(vis.max - vis.earned + acc.max - acc.earned + tv.max - tv.earned > 0 ? Math.min(20, vis.max - vis.earned + acc.max - acc.earned + tv.max - tv.earned) : 0)}`
    else if (id === 'truesync') score = 'TrueSync'
    else if (id === 'exp') score = kLabel(exposure)
    return { id, on, meta, score }
  }).filter(Boolean)
}
