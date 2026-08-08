/**
 * V4 report page (R1-R3, S1-S7). Renders only for a current-version
 * (isV3Report) row — LiteWidget.jsx falls back to the legacy
 * LiteFullReport for anything older, so a pre-this-stage report keeps
 * rendering exactly as it always has rather than hitting a half-shaped
 * V4 layout built for a payload it never had.
 */
import { useState } from 'react'
import '../theme.css'
import { DegradedRunBanner } from '../DegradedRunBanner.jsx'
import { computeExposure, seedAnnualRevenue } from '../liteDerive.js'
import { ReportRail } from './ReportRail.jsx'
import { MobileReportNav } from './MobileReportNav.jsx'
import { ScoreHero } from './ScoreHero.jsx'
import { FixableHook } from './FixableHook.jsx'
import { DiscoveryFinding } from './DiscoveryFinding.jsx'
import { VisibilitySection } from './VisibilitySection.jsx'
import { AccessibilitySection } from './AccessibilitySection.jsx'
import { TrueValueSection } from './TrueValueSection.jsx'
import { EditorialBand } from './EditorialBand.jsx'
import { FunnelGate } from './FunnelGate.jsx'
import { FixesTable } from './FixesTable.jsx'
import { CompleteReadBand } from './CompleteReadBand.jsx'
import { TrueSyncBand } from './TrueSyncBand.jsx'
import { ExposureSection } from './ExposureSection.jsx'
import { ClosingFork } from './ClosingFork.jsx'
import { ReportGrounded } from './ReportGrounded.jsx'
import { ReportFooter } from './ReportFooter.jsx'
import { useReportSections } from './useReportSections.js'
import { deriveScoreHeroHeadline, isPartialRead } from './reportDerive.js'

const DEFAULT_REVENUE = 12_000_000
const DEFAULT_AI_SHARE_PCT = 20

function shareOfMentionsRank(shareOfMentions) {
  if (!shareOfMentions || shareOfMentions.length === 0) return null
  const sorted = [...shareOfMentions].sort((a, b) => (b.share_pct || 0) - (a.share_pct || 0))
  const idx = sorted.findIndex((e) => e.is_primary)
  if (idx === -1) return null
  const n = idx + 1
  const suffix = n === 1 ? 'st' : n === 2 ? 'nd' : n === 3 ? 'rd' : 'th'
  return `${n}${suffix} of ${sorted.length}`
}

export function LiteFullReportV4({ report, token }) {
  const { active, focus, isOpen, toggleSection, allLabel, toggleAll } = useReportSections()

  const [revenue, setRevenue] = useState(() => seedAnnualRevenue(report.revenue_estimate_usd) ?? DEFAULT_REVENUE)
  const [aiSharePct, setAiSharePct] = useState(DEFAULT_AI_SHARE_PCT)
  const exposure = computeExposure({ revenue, aiSharePct, visibility: report.visibility })

  const entities = report.overall || []
  const primaryEntity = entities.find((e) => e.role === 'primary')
  const shareOfMentions = report.visibility_breakdown?.share_of_mentions || []
  const rank = shareOfMentionsRank(shareOfMentions)
  const headline = deriveScoreHeroHeadline(report.pillars)
  const auditUrl = typeof window !== 'undefined' ? `${window.location.origin}/` : '/'
  const truesyncPoints = report.pillars.parleo_fixable_points
  const partial = isPartialRead(report.pillars, report.scan?.degraded_reason)

  const primaryEntityName = primaryEntity?.name || 'Your brand'

  return (
    <div className="grain-overlay lite-report-shell" style={{ minHeight: '100vh', display: 'grid', gridTemplateColumns: '222px 1fr' }}>
      <MobileReportNav report={report} primaryEntityName={primaryEntityName} exposure={exposure} active={active} />
      <ReportRail
        report={report}
        primaryEntityName={primaryEntityName}
        exposure={exposure}
        active={active}
        focus={focus}
        allLabel={allLabel}
        onToggleAll={toggleAll}
      />
      <div style={{ minWidth: 0 }}>
        <div className="lite-report-content" style={{ maxWidth: 920, margin: '0 auto', padding: '32px 28px 46px' }}>
          <DegradedRunBanner
            status={report.scan_status}
            degradedReason={report.scan?.degraded_reason}
            bannerFacts={report.scan?.degraded_banner_facts}
            partialRead={partial}
          />

          <ScoreHero report={report} exposure={exposure} shareOfMentionsRank={rank} headline={headline} />
          <FixableHook report={report} />
          {partial && <DiscoveryFinding report={report} open={isOpen('why')} onToggle={() => toggleSection('why')} />}
          <VisibilitySection report={report} open={isOpen('viz')} onToggle={() => toggleSection('viz')} shareOfMentionsRank={rank} />
          <AccessibilitySection report={report} open={isOpen('acc')} onToggle={() => toggleSection('acc')} />
          <TrueValueSection report={report} open={isOpen('tv')} onToggle={() => toggleSection('tv')} />
          <EditorialBand />
          <FunnelGate open={isOpen('fun')} onToggle={() => toggleSection('fun')} brandName={primaryEntityName} reportToken={token} />
          <FixesTable report={report} open={isOpen('fix')} onToggle={() => toggleSection('fix')} brandName={primaryEntityName} reportToken={token} />
          {partial && <CompleteReadBand />}
          <TrueSyncBand points={truesyncPoints} brandName={primaryEntityName} reportToken={token} />
          <ExposureSection
            report={report}
            revenue={revenue} onRevenueChange={setRevenue}
            aiSharePct={aiSharePct} onAiShareChange={setAiSharePct}
            exposure={exposure}
            open={isOpen('exp')} onToggle={() => toggleSection('exp')}
          />
          <ClosingFork points={truesyncPoints} brandName={primaryEntityName} reportToken={token} />
          <ReportGrounded />
          <ReportFooter auditUrl={auditUrl} report={report} />
        </div>
      </div>
    </div>
  )
}
