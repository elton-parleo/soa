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
import { useState } from 'react'
import { api } from '../api.js'
import { computeExposure, seedAnnualRevenue } from '../lite/liteDerive.js'
import { deriveScoreHeroHeadline } from '../lite/report/reportDerive.js'
import { VisibilitySection } from '../lite/report/VisibilitySection.jsx'
import { TranscriptSection } from '../lite/report/TranscriptSection.jsx'
import { AccessibilitySection } from '../lite/report/AccessibilitySection.jsx'
import { TrueValueSection } from '../lite/report/TrueValueSection.jsx'
import { EditorialBand } from '../lite/report/EditorialBand.jsx'
import { FixesTable } from '../lite/report/FixesTable.jsx'
import { FixableHook } from '../lite/report/FixableHook.jsx'
import '../lite/theme.css'

import { FullAnalysisHero } from './full-analysis-report/FullAnalysisHero.jsx'
import { FullAnalysisRail } from './full-analysis-report/FullAnalysisRail.jsx'
import { ContinuationStrip } from './full-analysis-report/ContinuationStrip.jsx'
import { DiscoverySection } from './full-analysis-report/DiscoverySection.jsx'
import { PlatformMatrixSection } from './full-analysis-report/PlatformMatrixSection.jsx'
import { CompetitorStageSection } from './full-analysis-report/CompetitorStageSection.jsx'
import { AnalystLayerSection } from './full-analysis-report/AnalystLayerSection.jsx'
import { EvidenceSection } from './full-analysis-report/EvidenceSection.jsx'
import { FullAnalysisDarkBand } from './full-analysis-report/FullAnalysisDarkBand.jsx'
import { FullAnalysisFooter } from './full-analysis-report/FullAnalysisFooter.jsx'
import { shareOfMentionsRank } from './full-analysis-report/fullAnalysisDerive.js'
import './full-analysis-report/fullAnalysis.css'

const DEFAULT_REVENUE = 12_000_000
const DEFAULT_AI_SHARE_PCT = 20

export default function FullAnalysisReport({ cycleCode, report, onNavigate }) {
  const [open, setOpen] = useState({})
  const isOpen = (key) => open[key] !== false
  const toggle = (key) => setOpen((s) => ({ ...s, [key]: s[key] === false ? true : false }))

  const pillars = report.pillars
  const platformMatrix = report.platform_matrix || []
  const platforms = platformMatrix.map((r) => r.platform)
  const competitorSet = report.competitor_set
  const primaryEntity = competitorSet?.overall?.find((e) => e.is_primary)
  const primaryEntityName = primaryEntity?.entity || 'Your brand'

  const revenue = seedAnnualRevenue(report.revenue_estimate_usd) ?? DEFAULT_REVENUE
  const exposure = computeExposure({ revenue, aiSharePct: DEFAULT_AI_SHARE_PCT, visibility: pillars.visibility.score })
  const rank = shareOfMentionsRank(competitorSet?.overall)
  const headline = deriveScoreHeroHeadline(pillars)

  // VisibilitySection.jsx (reused verbatim below) reads its competitor
  // rows from report.visibility_breakdown.share_of_mentions — lite's
  // own field name for exactly the row shape ({entity, is_primary,
  // share_pct, domain}) this report carries at competitor_set.overall
  // instead (both come from the same lite_visibility.py::
  // build_visibility_payload). Shaping a local adapter object here,
  // rather than changing VisibilitySection.jsx itself, keeps that
  // shared component reading the one field name lite always has.
  const reportForVisibility = { ...report, visibility_breakdown: { share_of_mentions: competitorSet?.overall || [] } }

  const handleViewResponse = (runId) => {
    if (onNavigate) onNavigate('response', { runId, cycleCode })
  }

  return (
    <div className="grain-overlay fa-report-shell" style={{ minHeight: '100vh', display: 'grid', gridTemplateColumns: '222px 1fr' }}>
      <FullAnalysisRail
        report={report} primaryEntityName={primaryEntityName} exposure={exposure}
        active="score" hasContinuation={!!report.continuation}
      />
      <div style={{ minWidth: 0 }}>
        <div className="fa-report-content" style={{ maxWidth: 960, margin: '0 auto', padding: '32px 28px 46px' }}>
          <button
            onClick={() => onNavigate && onNavigate('dashboard')}
            style={{ background: 'none', border: 'none', color: 'var(--faint)', fontSize: 12, cursor: 'pointer', padding: 0, marginBottom: 16 }}
          >
            ← Back to dashboard
          </button>

          <FullAnalysisHero report={report} exposure={exposure} shareOfMentionsRank={rank} headline={headline} platforms={platforms} />

          {report.continuation && (
            <ContinuationStrip continuation={report.continuation} platformsNote={report.continuation.audit_platforms_note} />
          )}

          <FixableHook report={report} />

          <DiscoverySection scan={report.scan} open={isOpen('discovery')} onToggle={() => toggle('discovery')} />
          <PlatformMatrixSection matrix={platformMatrix} open={isOpen('matrix')} onToggle={() => toggle('matrix')} />

          <VisibilitySection report={reportForVisibility} open={isOpen('viz')} onToggle={() => toggle('viz')} shareOfMentionsRank={rank} />
          <CompetitorStageSection competitorSet={competitorSet} />
          <TranscriptSection report={report} open={isOpen('transcript')} onToggle={() => toggle('transcript')} />
          <AccessibilitySection report={report} open={isOpen('acc')} onToggle={() => toggle('acc')} />
          <TrueValueSection report={report} open={isOpen('tv')} onToggle={() => toggle('tv')} />

          <EditorialBand />

          <FixesTable report={report} open={isOpen('fix')} onToggle={() => toggle('fix')} brandName={primaryEntityName} reportToken={null} />

          <AnalystLayerSection cycleCode={cycleCode} open={isOpen('analyst')} onToggle={() => toggle('analyst')} />
          <EvidenceSection evidence={report.evidence} onViewResponse={handleViewResponse} open={isOpen('evidence')} onToggle={() => toggle('evidence')} />

          <FullAnalysisDarkBand fixCount={(pillars.fixes?.visible || []).filter((f) => f.fix_owner === 'TRUESYNC').length} />

          <FullAnalysisFooter report={report} platformsLabel={platformMatrix.map((r) => r.platform_name).join(', ')} />
        </div>
      </div>
    </div>
  )
}
