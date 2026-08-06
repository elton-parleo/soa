import { Wordmark, ProvenanceLine, Button } from '../../ds/index.js'
import { LITE_QUERY_COUNT } from '../landing/scanDimensionsRegistry.js'
import { LOGO_PROVIDER_CONFIGURED } from '../../ds/logoProvider.js'

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
      {LOGO_PROVIDER_CONFIGURED ? (
        <div style={{ textAlign: 'center', marginTop: 12, fontSize: 11, color: 'var(--faint)' }}>
          Logos by <a href="https://logo.dev" target="_blank" rel="noopener noreferrer" style={{ color: 'inherit' }}>Logo.dev</a>
        </div>
      ) : null}
    </>
  )
}
