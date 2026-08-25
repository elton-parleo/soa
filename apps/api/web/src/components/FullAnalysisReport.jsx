// FullAnalysisReport — Full Analysis coexistence, Phase 4/2: the real
// report, built on the shipped audit report's own design system
// (apps/api/web/src/lite/report/*, apps/api/web/src/ds/*) per design-
// refs/FullAnalysisReportMock.jsx's structure. Route, gate, and
// fallback behavior are unchanged — FullAnalysisReportGate.jsx still
// calls this with exactly {cycleCode, report, onNavigate}.
//
// Precedence rule (per the task spec): the shipped audit report BEATS
// the mock. Wherever a shipped lite/report/* component reads generically
// off pillars/offers/competitor-share-shaped data with no lite-specific
// content, it's imported and reused directly (VisibilitySection,
// AccessibilitySection, TrueValueSection, FixesTable, EditorialBand,
// ReportSection, FixableHook, reportDerive.js's pure helpers). Where a
// shipped component hardcodes lite-only content (ScoreHero's single-
// platform tags, ReportRail's "free audit" CTA and fixed nav id set,
// ReportFooter's audit-upsell footer, TrueSyncBand's lead-gen demo-
// request modal keyed to a lite token) it is NOT modified — a sibling
// in ./full-analysis-report mirrors its markup/tokens instead, so lite
// stays byte-for-byte untouched and carries zero regression risk.
import { useEffect, useState } from 'react'
import { api } from '../api.js'
import { publicFullAnalysisApi } from '../publicFullAnalysisApi.js'
import { computeExposure, seedAnnualRevenue } from '../lite/liteDerive.js'
import { deriveScoreHeroHeadline, deriveReportViewedState } from '../lite/report/reportDerive.js'
import { track, identifyReport, captureSrcParam } from '../lite/analytics.js'
import { EVENTS } from '../lite/analyticsEvents.js'
import { VisibilitySection } from '../lite/report/VisibilitySection.jsx'
import { TranscriptSection } from '../lite/report/TranscriptSection.jsx'
import { AccessibilitySection } from '../lite/report/AccessibilitySection.jsx'
import { TrueValueSection } from '../lite/report/TrueValueSection.jsx'
import { EditorialBand } from '../lite/report/EditorialBand.jsx'
import { FixesTable } from '../lite/report/FixesTable.jsx'
import { FixableHook } from '../lite/report/FixableHook.jsx'
import { ExposureSection } from '../lite/report/ExposureSection.jsx'
import '../lite/theme.css'

import { FullAnalysisHero } from './full-analysis-report/FullAnalysisHero.jsx'
import { FullAnalysisRail } from './full-analysis-report/FullAnalysisRail.jsx'
import { FullAnalysisMobileNav } from './full-analysis-report/FullAnalysisMobileNav.jsx'
import { buildFullAnalysisNavItems } from './full-analysis-report/fullAnalysisNav.js'
import { useActiveNavId } from './full-analysis-report/useActiveNavId.js'
import { ContinuationStrip } from './full-analysis-report/ContinuationStrip.jsx'
import { DiscoverySection } from './full-analysis-report/DiscoverySection.jsx'
import { PlatformMatrixSection } from './full-analysis-report/PlatformMatrixSection.jsx'
import { CompetitorStageSection } from './full-analysis-report/CompetitorStageSection.jsx'
import { AnalystLayerSection } from './full-analysis-report/AnalystLayerSection.jsx'
import { EvidenceSection } from './full-analysis-report/EvidenceSection.jsx'
import { FullAnalysisDarkBand } from './full-analysis-report/FullAnalysisDarkBand.jsx'
import { FullAnalysisFooter } from './full-analysis-report/FullAnalysisFooter.jsx'
import { FullAnalysisShareControl } from './full-analysis-report/FullAnalysisShareControl.jsx'
import { shareOfMentionsRank } from './full-analysis-report/fullAnalysisDerive.js'
import './full-analysis-report/fullAnalysis.css'

const DEFAULT_REVENUE = 12_000_000
const DEFAULT_AI_SHARE_PCT = 20

// readOnly (the public /fa/{token} viewer, PublicFullAnalysisPage.jsx):
// strips every path that would otherwise lead into the authed SoA app —
// AnalystLayerSection calls the authenticated /api/cycles/{code}/metrics
// directly (the one component in this tree that fetches on its own
// rather than reading off `report`), so it's the one section omitted
// outright rather than degraded; "Back to dashboard" and EvidenceSection's
// "View in Response Explorer" both go through onNavigate, so passing it
// through as undefined is enough to make both no-ops/hidden (see
// EvidenceSection.jsx's own `onViewResponse &&` guard). The owner-only
// FullAnalysisShareControl (create/copy/revoke) is likewise never shown
// to a visitor who has no session to own anything with.
//
// shareToken (readOnly only, from PublicFullAnalysisPage.jsx's URL
// param): the one allowed pseudonymous analytics id, same registry rule
// lite's report_token already follows — anyone with the link already
// has it. The owner view never has an equivalent public handle in
// scope, so it's simply never passed there, and identifyReport below
// is skipped rather than reaching for cycleCode as a substitute.
export default function FullAnalysisReport({ cycleCode, report, onNavigate, readOnly = false, shareToken }) {
  const [open, setOpen] = useState({})
  const isOpen = (key) => open[key] !== false
  const toggle = (key) => setOpen((s) => ({ ...s, [key]: s[key] === false ? true : false }))

  // Transcript browsing (2b/2c) — same owner-vs-visitor split as every
  // other fetch in this file: the authed cycleCode path when readOnly is
  // false, the public share-token path (rate-limited, no session) when
  // it's true. TranscriptSection never sees cycleCode/shareToken itself,
  // only these two functions.
  const fetchTranscriptIndex = readOnly
    ? (page) => publicFullAnalysisApi.getTranscriptIndex(shareToken, page)
    : (page) => api.getTranscriptIndex(cycleCode, page)
  const fetchTranscriptDetail = readOnly
    ? (runId) => publicFullAnalysisApi.getTranscriptDetail(shareToken, runId)
    : (runId) => api.getTranscriptDetail(cycleCode, runId)

  // Q5 (analyticsEvents.js): one report_viewed per mount, mirroring
  // lite's own owner|visitor split — here it's determined by readOnly
  // (real auth state) rather than lite's localStorage-ownership
  // heuristic, since this product actually has an authenticated view to
  // check against.
  useEffect(() => {
    if (readOnly && shareToken) identifyReport(shareToken)
    track(EVENTS.REPORT_VIEWED, {
      state: deriveReportViewedState(report.pillars, report.scan?.degraded_reason),
      viewer: readOnly ? 'visitor' : 'owner',
      report_type: 'full_analysis',
      src: captureSrcParam(),
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cycleCode])

  const pillars = report.pillars
  const platformMatrix = report.platform_matrix || []
  const platforms = platformMatrix.map((r) => r.platform)
  const competitorSet = report.competitor_set
  const primaryEntity = competitorSet?.overall?.find((e) => e.is_primary)
  const primaryEntityName = primaryEntity?.entity || 'Your brand'

  // 1b: controlled exactly like LiteFullReportV4.jsx's own revenue/
  // aiSharePct state — the Adjust Assumptions sliders in ExposureSection
  // below own these via onRevenueChange/onAiShareChange, so the figure
  // recomputes live as they're dragged, not just once at mount.
  const [revenue, setRevenue] = useState(() => seedAnnualRevenue(report.revenue_estimate_usd) ?? DEFAULT_REVENUE)
  const [aiSharePct, setAiSharePct] = useState(DEFAULT_AI_SHARE_PCT)
  // Exposure-model fix: True Value, not Visibility. This report builds
  // its own pillars payload (cycle_scoring_full.py) and reads the score
  // straight off it — no true_value_score field needed on this side.
  const exposure = computeExposure({ revenue, aiSharePct, trueValueScore: pillars.true_value.score })
  const rank = shareOfMentionsRank(competitorSet?.overall)
  const headline = deriveScoreHeroHeadline(pillars)

  // fix/full-analysis-rail-nav, 2c: real scroll-spy, same mechanism as
  // lite's own useReportSections (computeActiveSectionId — same ids-
  // in-order scan, same 140px threshold), parameterized by this
  // report's own rendered nav ids instead of a hardcoded 'score'
  // literal that never updated as the reader scrolled.
  const navCtx = {
    pillars, composite: report.composite, totalQueries: report.total_queries, transcript: report.transcript,
    exposure, hasContinuation: !!report.continuation, readOnly,
    scan: report.scan, platformMatrix, evidence: report.evidence,
  }
  const navIds = buildFullAnalysisNavItems(navCtx).map((item) => item.id)
  const active = useActiveNavId(navIds)

  // 2e: a shared or bookmarked link can carry a hash (…/fa/{token}#tv)
  // — report is already a prop (not fetched inside this component), so
  // every section is already in the DOM by this component's first
  // paint; native browser hash-scroll-on-load fires too early for an
  // async-rendered SPA (the target doesn't exist yet at that moment),
  // so this does it explicitly instead of assuming it "just worked".
  useEffect(() => {
    if (!window.location.hash) return
    const el = document.getElementById(window.location.hash.slice(1))
    if (el) el.scrollIntoView({ block: 'start' })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // VisibilitySection.jsx (reused verbatim below) reads its competitor
  // rows from report.visibility_breakdown.share_of_mentions — lite's
  // own field name for exactly the row shape ({entity, is_primary,
  // share_pct, domain}) this report carries at competitor_set.overall
  // instead (both come from the same lite_visibility.py::
  // build_visibility_payload). Shaping a local adapter object here,
  // rather than changing VisibilitySection.jsx itself, keeps that
  // shared component reading the one field name lite always has.
  const reportForVisibility = { ...report, visibility_breakdown: { share_of_mentions: competitorSet?.overall || [] } }

  // ExposureSection.jsx reads report.true_value_score (lite's own flat
  // field) and report.pillars.exposure_reasons/report.scan?.
  // degraded_reason (both already the same shape here) — only the
  // first needs adapting, same pattern as reportForVisibility above.
  const reportForExposure = { ...report, true_value_score: pillars.true_value.score }

  const handleViewResponse = readOnly ? undefined : (runId) => {
    if (onNavigate) onNavigate('response', { runId, cycleCode })
  }

  return (
    <div className="grain-overlay fa-report-shell" style={{ minHeight: '100vh', display: 'grid', gridTemplateColumns: '222px 1fr' }}>
      <FullAnalysisRail
        report={report} primaryEntityName={primaryEntityName} exposure={exposure}
        active={active} hasContinuation={!!report.continuation} readOnly={readOnly}
      />
      <FullAnalysisMobileNav
        report={report} primaryEntityName={primaryEntityName} exposure={exposure}
        active={active} hasContinuation={!!report.continuation} readOnly={readOnly}
      />
      <div style={{ minWidth: 0 }}>
        <div className="fa-report-content" style={{ maxWidth: 960, margin: '0 auto', padding: '32px 28px 46px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, gap: 12 }}>
            {readOnly ? (
              <span />
            ) : (
              <button
                onClick={() => onNavigate && onNavigate('dashboard')}
                style={{ background: 'none', border: 'none', color: 'var(--faint)', fontSize: 12, cursor: 'pointer', padding: 0 }}
              >
                ← Back to dashboard
              </button>
            )}
            {!readOnly && <FullAnalysisShareControl cycleCode={cycleCode} />}
          </div>

          <FullAnalysisHero report={report} exposure={exposure} shareOfMentionsRank={rank} headline={headline} platforms={platforms} />

          {report.continuation && (
            <ContinuationStrip continuation={report.continuation} platformsNote={report.continuation.audit_platforms_note} />
          )}

          <FixableHook report={report} />

          <DiscoverySection scan={report.scan} open={isOpen('discovery')} onToggle={() => toggle('discovery')} />
          <PlatformMatrixSection matrix={platformMatrix} open={isOpen('matrix')} onToggle={() => toggle('matrix')} />

          <VisibilitySection report={reportForVisibility} open={isOpen('viz')} onToggle={() => toggle('viz')} shareOfMentionsRank={rank} queryCount={report.total_queries} />
          <CompetitorStageSection competitorSet={competitorSet} />
          <TranscriptSection
            report={report} open={isOpen('transcript')} onToggle={() => toggle('transcript')}
            browsable fetchIndex={fetchTranscriptIndex} fetchDetail={fetchTranscriptDetail}
          />
          <AccessibilitySection report={report} open={isOpen('acc')} onToggle={() => toggle('acc')} />
          <TrueValueSection report={report} open={isOpen('tv')} onToggle={() => toggle('tv')} />

          <EditorialBand />

          <FixesTable report={report} open={isOpen('fix')} onToggle={() => toggle('fix')} brandName={primaryEntityName} reportToken={null} queryCount={report.total_queries} />

          {!readOnly && (
            <AnalystLayerSection cycleCode={cycleCode} open={isOpen('analyst')} onToggle={() => toggle('analyst')} />
          )}
          <EvidenceSection evidence={report.evidence} onViewResponse={handleViewResponse} open={isOpen('evidence')} onToggle={() => toggle('evidence')} />

          <ExposureSection
            report={reportForExposure}
            revenue={revenue} onRevenueChange={setRevenue}
            aiSharePct={aiSharePct} onAiShareChange={setAiSharePct}
            exposure={exposure}
            open={isOpen('exp')} onToggle={() => toggle('exp')}
          />

          <FullAnalysisDarkBand fixCount={(pillars.fixes?.visible || []).filter((f) => f.fix_owner === 'TRUESYNC').length} />

          <FullAnalysisFooter report={report} platformsLabel={platformMatrix.map((r) => r.platform_name).join(', ')} />
        </div>
      </div>
    </div>
  )
}
