/**
 * fix/full-analysis-rail-nav: the ONE registry that drives the "IN THIS
 * REPORT" rail (FullAnalysisRail.jsx), its phone replacement
 * (FullAnalysisMobileNav.jsx), and — via NAV_IDS — every section
 * component's own DOM id. Before this, FullAnalysisRail.jsx carried a
 * NAV_ITEMS array (id/icon/label), a navScore() switch (score text),
 * and a filterNavItems() predicate (render-condition) as three
 * SEPARATE, hand-kept-in-sync lists — and one entry (truesync) was
 * already wired into the rail and into FixableHook.jsx's own headline-
 * finding link (`#truesync`, shared with lite) with NO matching id
 * anywhere in the Full Analysis DOM at all: FullAnalysisDarkBand.jsx
 * (the sibling of lite's own id="truesync" TrueSyncBand.jsx) never
 * carried one. A dead link, confirmed live — clicking "TrueSync" in
 * the rail did nothing.
 *
 * One registry entry per section: {id, icon, label, render, value}.
 * `render(ctx)` decides whether this section (and therefore its nav
 * row) exists at all this render; `value(ctx)` computes the right-side
 * score text from the SAME payload field the section itself displays
 * — never a hardcoded number. Full-analysis-only section components
 * import NAV_IDS and use it as their own `id` prop, so a nav item and
 * its target can never diverge again for the pieces this file actually
 * owns. Shared lite/report/* sections (Visibility/Accessibility/
 * TrueValue/Fixes/Exposure/Transcript) keep their own long-standing
 * literal ids — this registry's entries for those six reference the
 * SAME literal strings by convention (lite already uses them), not by
 * import (the dependency only ever runs full-analysis -> lite, never
 * the other way); the registry<->DOM tests are what actually verify
 * the two sides still agree.
 */
import { pillarEarnedMax } from '../../lite/report/reportDerive.js'
import { formatCompactCurrency } from '../../lite/liteDerive.js'
import { buildDiscoverySteps } from './fullAnalysisDerive.js'

export const NAV_IDS = {
  SCORE: 'score',
  CONTINUATION: 'continuation',
  DISCOVERY: 'discovery',
  MATRIX: 'matrix',
  VIZ: 'viz',
  TRANSCRIPT: 'transcript',
  ACC: 'acc',
  TV: 'tv',
  FIX: 'fix',
  ANALYST: 'analyst',
  EVIDENCE: 'evidence',
  TRUESYNC: 'truesync',
  EXP: 'exp',
}

// ctx shape: { report, pillars, composite, totalQueries, transcript,
// exposure, hasContinuation, readOnly, scan, platformMatrix, evidence }
// — every field already computed once in FullAnalysisReport.jsx and
// threaded through, never re-derived per nav item.
export const NAV_REGISTRY = [
  {
    id: NAV_IDS.SCORE, icon: 'chart', label: 'The score',
    render: () => true,
    value: (ctx) => `${Math.round(ctx.composite ?? 0)}/100`,
  },
  {
    id: NAV_IDS.CONTINUATION, icon: 'refresh', label: 'Vs. your audit',
    render: (ctx) => !!ctx.hasContinuation,
    value: () => null,
  },
  {
    id: NAV_IDS.DISCOVERY, icon: 'search', label: 'Discovery',
    // DiscoverySection itself renders nothing when buildDiscoverySteps
    // comes back empty (no discovery_trace on this scan) — calling the
    // SAME pure function here, not a second "does discovery exist"
    // guess, is what keeps this in sync with the section by
    // construction rather than by two people remembering to agree.
    render: (ctx) => buildDiscoverySteps(ctx.scan).length > 0,
    value: () => null,
  },
  {
    id: NAV_IDS.MATRIX, icon: 'grid', label: 'Platform matrix',
    // PlatformMatrixSection returns null on an empty matrix (a cycle
    // with no scored platforms) — same shape of gap as discovery/
    // transcript above.
    render: (ctx) => !!ctx.platformMatrix && ctx.platformMatrix.length > 0,
    value: () => null,
  },
  {
    id: NAV_IDS.VIZ, icon: 'eye', label: 'Visibility',
    render: () => true,
    value: (ctx) => { const v = pillarEarnedMax(ctx.pillars.visibility); return `${Math.round(v.earned)}/${Math.round(v.max)}` },
  },
  {
    id: NAV_IDS.TRANSCRIPT, icon: 'doc', label: 'The transcript',
    // The section itself is null-safe on a missing transcript
    // (TranscriptSection.jsx returns null), but without this gate the
    // nav row would still render and link to an id nothing produces —
    // the exact "conditional section, unconditional nav item" failure
    // mode step 1b calls out.
    render: (ctx) => !!ctx.transcript,
    value: (ctx) => ctx.transcript ? `${ctx.transcript.query_index}/${ctx.transcript.total_queries}` : null,
  },
  {
    id: NAV_IDS.ACC, icon: 'globe', label: 'Accessibility',
    render: () => true,
    value: (ctx) => { const a = pillarEarnedMax(ctx.pillars.accessibility); return `${Math.round(a.earned)}/${Math.round(a.max)}` },
  },
  {
    id: NAV_IDS.TV, icon: 'tag', label: 'True Value',
    render: () => true,
    value: (ctx) => { const t = pillarEarnedMax(ctx.pillars.true_value); return `${Math.round(t.earned)}/${Math.round(t.max)}` },
  },
  {
    id: NAV_IDS.FIX, icon: 'check', label: 'Ranked fixes',
    render: () => true,
    value: (ctx) => ctx.pillars.fixes ? `+${Math.round(ctx.pillars.fixes.visible.reduce((s, f) => s + f.impact, 0))}` : null,
  },
  {
    id: NAV_IDS.ANALYST, icon: 'layers', label: 'Analyst layer',
    // AnalystLayerSection is the one component FullAnalysisReport.jsx
    // omits outright in readOnly mode (it fetches the authed
    // /api/cycles/{code}/metrics directly, no public equivalent) — the
    // nav row must be gone too, or it's a dead link on the public
    // share route specifically.
    render: (ctx) => !ctx.readOnly,
    value: () => null,
  },
  {
    id: NAV_IDS.EVIDENCE, icon: 'doc', label: 'Evidence',
    // select_evidence_exemplar (backend) returns None when no run
    // qualifies as the worst-offender exemplar — "never a fabricated
    // example" — and EvidenceSection.jsx renders nothing in that case.
    render: (ctx) => ctx.evidence != null,
    value: (ctx) => ctx.totalQueries ? `${ctx.totalQueries}` : null,
  },
  {
    id: NAV_IDS.TRUESYNC, icon: 'refresh', label: 'TrueSync',
    render: () => true,
    value: () => 'TrueSync',
  },
  {
    id: NAV_IDS.EXP, icon: 'card', label: 'Exposure',
    render: () => true,
    value: (ctx) => ctx.exposure == null ? '—' : formatCompactCurrency(ctx.exposure),
  },
]

// The one function both FullAnalysisRail.jsx and FullAnalysisMobileNav.
// jsx call — replaces the old NAV_ITEMS/navScore()/filterNavItems()
// trio with a single pass over one list, so a nav row's presence,
// label, icon, and score can never come from three separately-edited
// places again.
export function buildFullAnalysisNavItems(ctx) {
  return NAV_REGISTRY
    .filter((entry) => entry.render(ctx))
    .map((entry) => ({ id: entry.id, icon: entry.icon, label: entry.label, score: entry.value(ctx) }))
}
