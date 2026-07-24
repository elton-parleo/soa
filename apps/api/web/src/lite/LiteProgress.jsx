/**
 * Two parallel progress tracks: the existing LLM-query track (driven by
 * phaseData.phase/progress) and the Agent Scan track (driven by
 * phaseData.scan_status — added to GET /status in Stage 3). The scan
 * track only renders when a store_url was actually submitted; a
 * blocked/failed/skipped scan is always shown as an honest, neutral
 * finding, never styled as an error (rule 7 in spirit — no error state
 * for a degraded scan).
 *
 * No screenshot in design-refs/ shows a progress view (the reference
 * captures are all completed reports) — this applies the same card/
 * label tokens as the rest of the widget for consistency.
 */
import { LogoHeader, ErrorBanner, InfoBadge, LightCard } from './liteTheme.jsx'
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
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--text)' }}>
        <span style={{ color: 'var(--good)', fontWeight: 700 }} aria-hidden="true">✓</span>
        Finished reading {domain} like an agent
      </div>
    )
  }

  if (scanStatus === 'blocked' || scanStatus === 'failed' || scanStatus === 'skipped') {
    return <InfoBadge message={SCAN_INFO_COPY[scanStatus](domain)} />
  }

  const template = SCAN_RUNNING_COPY[scanStatus] || SCAN_RUNNING_COPY.pending
  return (
    <div style={{ fontSize: 13, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 8 }}>
      <span className="lite-badge-dot" aria-hidden="true" />
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
    <div className="lite-root">
      <div className="lite-shell" style={{ maxWidth: 480 }}>
        <LightCard>
          <LogoHeader />
          <ErrorBanner message={error} />

          <div className="lite-label" style={{ marginBottom: 6 }}>Asking agents about your brand</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', marginBottom: 12 }}>
            {phaseMessage(phaseData)}
          </div>
          <div className="lite-bar-track">
            <div className="lite-bar-fill" style={{ width: `${pct}%`, background: 'var(--accent)' }} />
          </div>
          {progress && (
            <div className="lite-muted" style={{ fontSize: 12, marginTop: 8 }}>
              {progress.completed_runs} of {progress.total_runs} queries complete
            </div>
          )}

          {storeUrl && (
            <div style={{ marginTop: 20, paddingTop: 20, borderTop: '1px solid var(--line)' }}>
              <div className="lite-label" style={{ marginBottom: 8 }}>Reading your store like an agent</div>
              <ScanTrack scanStatus={phaseData?.scan_status} storeUrl={storeUrl} />
            </div>
          )}
        </LightCard>
      </div>
    </div>
  )
}

export function LiteFailed({ onRetry }) {
  return (
    <div className="lite-root">
      <div className="lite-shell" style={{ maxWidth: 480 }}>
        <LightCard>
          <LogoHeader />
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>
            Something went wrong
          </div>
          <div className="lite-body lite-muted" style={{ marginBottom: 20 }}>
            We couldn't finish your diagnostic. This is on us — please try again.
          </div>
          <button onClick={onRetry} className="lite-pill lite-pill--solid" style={{ width: '100%', height: 46, fontSize: 14 }}>
            Try again
          </button>
        </LightCard>
      </div>
    </div>
  )
}
