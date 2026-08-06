import { Wordmark, ProvenanceLine, Button } from '../../ds/index.js'
import { LITE_QUERY_COUNT } from '../landing/scanDimensionsRegistry.js'

export function ReportFooter({ auditUrl }) {
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
        <ProvenanceLine confidence="observed" parts={[`${LITE_QUERY_COUNT} live ChatGPT queries + a crawl of your store`, 'deterministic', 'a sample, not a category study']} />
      </div>
    </>
  )
}
