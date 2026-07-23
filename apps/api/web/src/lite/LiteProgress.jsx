/**
 * Two parallel progress tracks: the existing LLM-query track (driven by
 * phaseData.phase/progress) and the Agent Scan track (driven by
 * phaseData.scan_status — added to GET /status in Stage 3). The scan
 * track only renders when a store_url was actually submitted; a
 * blocked/failed/skipped scan is always shown as an honest, neutral
 * finding, never styled as an error (rule 7 in spirit — no error state
 * for a degraded scan).
 */
import { T, outerStyle, cardStyle, LogoHeader, ErrorBanner, InfoBadge } from './liteTheme.jsx'
import { domainFromStoreUrl } from './liteDerive.js'

const PHASE_COPY = {
  queued: 'Queued — starting shortly…',
  generating_queries: 'Designing your 12-query diagnostic…',
  running: 'Running query {n} of {total} against ChatGPT…',
  analyzing: 'Analyzing responses…',
}

function phaseMessage(phaseData) {
  const template = PHASE_COPY[phaseData?.phase] || 'Working on it…'
  if (phaseData?.phase !== 'running' || !phaseData.progress) {
    return template
  }
  const { completed_runs, total_runs } = phaseData.progress
  const n = Math.min(completed_runs + 1, total_runs)
  return template.replace('{n}', n).replace('{total}', total_runs)
}

const SCAN_RUNNING_COPY = {
  pending: 'Queued to read {domain}…',
  running: 'Reading {domain} like an agent…',
}

const SCAN_INFO_COPY = {
  blocked: (domain) => `${domain} blocked our reader — that itself is a finding, and it's in your report.`,
  failed: (domain) => `We couldn't finish reading ${domain} this time — noted honestly in your report.`,
  skipped: (domain) => `We didn't get a chance to read ${domain} this run.`,
}

function ScanTrack({ scanStatus, storeUrl }) {
  const domain = domainFromStoreUrl(storeUrl)
  if (!storeUrl) return null

  if (scanStatus === 'complete') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: T.textMid }}>
        <span style={{ color: T.green, fontWeight: 700 }}>✓</span>
        Finished reading {domain} like an agent
      </div>
    )
  }

  if (scanStatus === 'blocked' || scanStatus === 'failed' || scanStatus === 'skipped') {
    return <InfoBadge message={SCAN_INFO_COPY[scanStatus](domain)} />
  }

  const template = SCAN_RUNNING_COPY[scanStatus] || SCAN_RUNNING_COPY.pending
  return (
    <div style={{ fontSize: 13, color: T.textMid, display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ width: 8, height: 8, borderRadius: '50%', background: T.indigo, display: 'inline-block' }} />
      {template.replace('{domain}', domain)}
    </div>
  )
}

export function LiteProgress({ phaseData, storeUrl, error }) {
  const progress = phaseData?.progress
  const pct = progress && progress.total_runs
    ? Math.round((progress.completed_runs / progress.total_runs) * 100)
    : 0

  return (
    <div style={outerStyle}>
      <div style={cardStyle}>
        <LogoHeader />
        <ErrorBanner message={error} />

        <div style={{ fontSize: 12, fontWeight: 700, color: T.slate, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 6 }}>
          Asking agents about your brand
        </div>
        <div style={{ fontSize: 16, fontWeight: 700, color: T.text, marginBottom: 12 }}>
          {phaseMessage(phaseData)}
        </div>
        <div style={{ height: 8, background: T.border, borderRadius: 4, overflow: 'hidden' }}>
          <div style={{
            height: '100%',
            width: `${pct}%`,
            background: T.indigo,
            borderRadius: 4,
            transition: 'width 0.6s ease',
          }} />
        </div>
        {progress && (
          <div style={{ fontSize: 12, color: T.slate, marginTop: 8 }}>
            {progress.completed_runs} of {progress.total_runs} queries complete
          </div>
        )}

        {storeUrl && (
          <div style={{ marginTop: 20, paddingTop: 20, borderTop: `1px solid ${T.border}` }}>
            <div style={{ fontSize: 12, fontWeight: 700, color: T.slate, textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: 8 }}>
              Reading your store like an agent
            </div>
            <ScanTrack scanStatus={phaseData?.scan_status} storeUrl={storeUrl} />
          </div>
        )}
      </div>
    </div>
  )
}

export function LiteFailed({ onRetry }) {
  return (
    <div style={outerStyle}>
      <div style={cardStyle}>
        <LogoHeader />
        <div style={{ fontSize: 16, fontWeight: 700, color: T.text, marginBottom: 8 }}>
          Something went wrong
        </div>
        <div style={{ fontSize: 13, color: T.slate, marginBottom: 20, lineHeight: 1.5 }}>
          We couldn't finish your diagnostic. This is on us — please try again.
        </div>
        <button
          onClick={onRetry}
          style={{
            width: '100%',
            height: 46,
            background: T.navy,
            color: T.white,
            fontSize: 14,
            fontWeight: 700,
            fontFamily: 'inherit',
            border: 'none',
            borderRadius: 8,
            cursor: 'pointer',
          }}
        >
          Try again
        </button>
      </div>
    </div>
  )
}
