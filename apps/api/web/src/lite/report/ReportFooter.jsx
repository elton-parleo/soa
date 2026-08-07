import { Wordmark, ProvenanceLine, Button } from '../../ds/index.js'
import { LITE_QUERY_COUNT } from '../landing/scanDimensionsRegistry.js'
import { LOGO_PROVIDER_CONFIGURED } from '../../ds/logoProvider.js'
import { isPartialRead, buildMeasurableContext } from './reportDerive.js'

// Part 5d: report is optional so any pre-existing caller that never
// passed one keeps rendering byte-identically — the extra provenance
// part only ever appears when a real partial-read report is passed in.
export function ReportFooter({ auditUrl, report }) {
  const partialRead = report ? isPartialRead(report.pillars || {}, report.scan?.degraded_reason) : false
  const measurable = partialRead ? buildMeasurableContext(report.pillars) : null
  const provenanceParts = [`${LITE_QUERY_COUNT} live ChatGPT queries + a crawl of your store`, 'deterministic', 'a sample, not a category study']
  if (partialRead) provenanceParts.push(`${Math.round(measurable.measurable_max)} of ${Math.round(measurable.full_max)} points measurable this run`)
  return (
    <>
      <div style={{ textAlign: 'center', padding: '6px 0 22px' }}>
        <div style={{ fontSize: 16, color: 'var(--text)', fontWeight: 540 }}>This report took one URL and 20 minutes.</div>
        <div style={{ marginTop: 14 }}>
          <a href={auditUrl} style={{ textDecoration: 'none' }}>
            <Button variant="blue" size="lg" arrow>Run yours free</Button>
          </a>
        </div>
      </div>
      <div style={{ borderTop: '1px solid var(--hairline)', paddingTop: 18, display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 14, flexWrap: 'wrap' }}>
        <Wordmark size={12} />
        <ProvenanceLine confidence="observed" parts={provenanceParts} />
      </div>
      {LOGO_PROVIDER_CONFIGURED ? (
        <div style={{ textAlign: 'center', marginTop: 12, fontSize: 11, color: 'var(--faint)' }}>
          Logos by <a href="https://logo.dev" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>Logo.dev</a>
        </div>
      ) : null}
    </>
  )
}
