/**
 * Footer — mirrors ReportFooter.jsx's provenance-line treatment, not
 * reused directly: ReportFooter hardcodes "This report took one URL
 * and 20 minutes" + a "Run yours free" audit-upsell CTA, both wrong for
 * a paid report a customer is already inside of. Provenance content is
 * assembled entirely from real fields on the report — scorer version,
 * platforms, run counts, crawl timestamp, observation counts — never a
 * literal.
 */
import { Wordmark, ProvenanceLine } from '../../ds/index.js'
import { pillarNominalWeight, PILLAR_VISIBILITY, PILLAR_ACCESSIBILITY, PILLAR_TRUE_VALUE } from '../../lite/report/reportDerive.js'

export function FullAnalysisFooter({ report, platformsLabel }) {
  const parts = [
    `VISIBILITY ${pillarNominalWeight(PILLAR_VISIBILITY)} · ACCESSIBILITY ${pillarNominalWeight(PILLAR_ACCESSIBILITY)} · TRUE VALUE ${pillarNominalWeight(PILLAR_TRUE_VALUE)}`,
    'straight sum, no black box',
    `${report.total_queries} queries measured`,
  ]
  if (platformsLabel) parts.push(platformsLabel)
  if (report.scan?.status) parts.push(`storefront crawl: ${report.scan.status}`)
  parts.push(`this report renders only under scorer version ${report.scorer_version}`)

  return (
    <div style={{ borderTop: '1px solid var(--hairline)', paddingTop: 18, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14, flexWrap: 'wrap', marginTop: 8 }}>
      <Wordmark size={12} />
      <ProvenanceLine confidence="observed" parts={parts} />
    </div>
  )
}
