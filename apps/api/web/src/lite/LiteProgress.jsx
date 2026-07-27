/**
 * Two parallel progress tracks: the existing LLM-query track (driven by
 * phaseData.phase/progress) and the Agent Scan track (driven by
 * phaseData.scan_status — added to GET /status in Stage 3). The scan
 * track only renders when a store_url was actually submitted; a
 * blocked/failed/skipped scan is always shown as an honest, neutral
 * finding, never styled as an error (rule 7 in spirit — no error state
 * for a degraded scan).
 *
 * Stage 12 (R1/R2): a live-status line (pulsing dot + mono phase label),
 * an elapsed-time counter, and a stalled-state notice make a running
 * pipeline visibly alive rather than looking frozen — all CSS-driven
 * (theme.css's lite-live-dot/lite-bar-fill--shimmer), no animation
 * library. prefers-reduced-motion swaps the dot for a static glyph via
 * usePrefersReducedMotion() below (in ADDITION to theme.css's existing
 * blanket animation-duration override, so the fallback is real,
 * assertable markup, not just an imperceptibly-fast animation).
 *
 * Stage 12 (E1): the email-first ask moves to this page — a dark-band
 * card wired to the existing PATCH /email endpoint (already accepts an
 * email mid-run, see public_lite.py::set_lite_email). The post-run
 * teaser/gate on LiteTeaser.jsx is unchanged; this is an earlier,
 * additional ask, not a replacement.
 *
 * No screenshot in design-refs/ shows a progress view (the reference
 * captures are all completed reports) — this applies the same card/
 * label tokens as the rest of the widget for consistency.
 *
 * Stage 13 (W2): a new 'identifying_competitors' phase (worker-side
 * competitor auto-generation, ahead of query generation) gets its own
 * phase copy, and once phaseData.competitors populates, CompetitorChips
 * renders "COMPARING AGAINST" + one outlined chip per name — the run's
 * one visible moment of the tool deciding who to compare against.
 */
import { useEffect, useRef, useState } from 'react'
import { LogoHeader, ErrorBanner, InfoBadge, LightCard, DarkCard, Chip } from './liteTheme.jsx'
import { domainFromStoreUrl, formatElapsed, maskEmail } from './liteDerive.js'
import { liteApi } from './liteApi.js'
import { validateEmail } from './validation.js'

const PHASE_COPY = {
  queued: 'Queued — starting shortly…',
  identifying_competitors: 'Identifying your closest competitors…',
  generating_queries: 'Designing your 12-query diagnostic…',
  running: 'Running query {n} of {total} against ChatGPT…',
  coding: 'Reading and coding every answer…',
  metrics: 'Calculating your score…',
  analyzing: 'Analyzing responses…', // pre-Stage-12 backend fallback during a rolling deploy
}

const LIVE_LABEL_COPY = {
  queued: 'QUEUED',
  identifying_competitors: 'IDENTIFYING COMPETITORS',
  generating_queries: 'DESIGNING YOUR DIAGNOSTIC',
  coding: 'CODING RESPONSES',
  metrics: 'CALCULATING YOUR SCORE',
  analyzing: 'ANALYZING RESPONSES',
}

const STALL_THRESHOLD_MS = 90_000

function phaseMessage(phaseData) {
  const template = PHASE_COPY[phaseData?.phase] || 'Working on it…'
  if (phaseData?.phase !== 'running' || !phaseData.progress) {
    return template
  }
  const { completed_runs, total_runs } = phaseData.progress
  const n = Math.min(completed_runs + 1, total_runs)
  return template.replace('{n}', n).replace('{total}', total_runs)
}

function liveStatusLabel(phaseData) {
  if (phaseData?.phase === 'running' && phaseData.progress) {
    const { completed_runs, total_runs } = phaseData.progress
    const n = Math.min(completed_runs + 1, total_runs)
    return `ASKING CHATGPT — QUERY ${n} OF ${total_runs}`
  }
  return LIVE_LABEL_COPY[phaseData?.phase] || 'WORKING ON IT'
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() => (
    typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false
  ))
  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return undefined
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    const handler = (e) => setReduced(e.matches)
    if (mq.addEventListener) mq.addEventListener('change', handler)
    return () => { if (mq.removeEventListener) mq.removeEventListener('change', handler) }
  }, [])
  return reduced
}

function useElapsedSeconds(active) {
  const [elapsed, setElapsed] = useState(0)
  const startRef = useRef(null)

  useEffect(() => {
    if (!active) return undefined
    if (startRef.current === null) startRef.current = Date.now()
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000))
    }, 1000)
    return () => clearInterval(interval)
  }, [active])

  return elapsed
}

/** R2: tracks the last time phaseData actually changed (by value, not by
 * object identity — a fresh poll returns a new object every 5s even
 * when nothing moved) and reports "stalled" once that's been >90s
 * while the run is still non-terminal. */
function useStalledState(phaseData, active) {
  const signature = JSON.stringify([
    phaseData?.phase, phaseData?.progress?.completed_runs, phaseData?.scan_status,
  ])
  const lastSignatureRef = useRef(signature)
  const lastChangeAtRef = useRef(Date.now())
  const [isStalled, setIsStalled] = useState(false)

  useEffect(() => {
    if (signature !== lastSignatureRef.current) {
      lastSignatureRef.current = signature
      lastChangeAtRef.current = Date.now()
      setIsStalled(false)
    }
  }, [signature])

  useEffect(() => {
    if (!active) return undefined
    const interval = setInterval(() => {
      setIsStalled(Date.now() - lastChangeAtRef.current >= STALL_THRESHOLD_MS)
    }, 2000)
    return () => clearInterval(interval)
  }, [active])

  return isStalled
}

function LiveStatusLine({ phaseData }) {
  const reducedMotion = usePrefersReducedMotion()
  const label = reducedMotion ? 'RUNNING' : liveStatusLabel(phaseData)

  return (
    <div className="lite-mono lite-muted" style={{ fontSize: 11, display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
      {reducedMotion
        ? <span aria-hidden="true">●</span>
        : <span className="lite-live-dot" aria-hidden="true" data-testid="lite-live-dot" />}
      <span>{label}</span>
    </div>
  )
}

// ─── Competitor chips (Stage 13, W2) ─────────────────────────────────────
// Renders once competitors first populate on the status payload — the
// run's one visible moment of the tool deciding who to compare against.
// The lite-chip-row--enter fade-in (theme.css) fires naturally on this
// block's first mount, since it's absent from the tree until then.
function CompetitorChips({ competitors }) {
  if (!competitors || competitors.length === 0) return null
  return (
    <div className="lite-chip-row--enter" style={{ marginTop: 14, marginBottom: 2 }}>
      <div className="lite-label" style={{ marginBottom: 8 }}>Comparing against</div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {competitors.map((name) => (
          <Chip key={name} tone="outline">{name}</Chip>
        ))}
      </div>
    </div>
  )
}

// ─── Status-page email card (Stage 12, E1) ──────────────────────────────
// The primary ask, moved earlier — not a replacement for LiteTeaser's
// post-run gate, which is unchanged (E2: no previously-gated content
// becomes visible any earlier; only the ASK moves earlier in time).
function StatusEmailCard({ token }) {
  const [email, setEmail] = useState('')
  const [emailError, setEmailError] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState(null)
  const [submittedEmail, setSubmittedEmail] = useState(null)

  if (!token) return null

  if (submittedEmail) {
    return (
      <DarkCard>
        <div className="lite-body--inv">
          We'll email your report to {maskEmail(submittedEmail)}. You can also keep watching here.
        </div>
      </DarkCard>
    )
  }

  async function handleSubmit(e) {
    e.preventDefault()
    const err = validateEmail(email)
    setEmailError(err)
    if (err) return

    setSubmitting(true)
    setSubmitError(null)
    try {
      await liteApi.setEmail(token, email.trim())
      setSubmittedEmail(email.trim())
    } catch (err2) {
      setSubmitError(err2.message || 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <DarkCard>
      <div className="lite-headline lite-headline--inv" style={{ fontSize: 17, marginBottom: 6 }}>
        This takes a few minutes.
      </div>
      <div className="lite-body--inv" style={{ marginBottom: 16 }}>
        Leave your email and we'll send your report the moment it's ready — no need to keep this tab open.
      </div>
      <ErrorBanner message={submitError} />
      {/* noValidate: validateEmail()'s message renders inline, same
          reasoning as LiteTeaser's unlock form. */}
      <form onSubmit={handleSubmit} noValidate>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <input
            type="email"
            placeholder="you@company.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="lite-input lite-input--pill lite-input--inv lite-mono"
            style={{ flex: '1 1 200px' }}
          />
          <button type="submit" disabled={submitting} className="lite-pill lite-pill--solid">
            {submitting ? 'Saving…' : 'Email me the report'}
          </button>
        </div>
        <div className="lite-muted--inv" style={{ fontSize: 12, marginTop: 8, minHeight: 16 }}>
          {emailError || "Your report link is private until you share it."}
        </div>
      </form>
    </DarkCard>
  )
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

export function LiteProgress({ phaseData, storeUrl, error, token }) {
  const progress = phaseData?.progress
  const pct = progress && progress.total_runs
    ? Math.round((progress.completed_runs / progress.total_runs) * 100)
    : 0

  const isActive = phaseData?.status !== 'complete' && phaseData?.status !== 'failed'
  const elapsedSeconds = useElapsedSeconds(isActive)
  const isStalled = useStalledState(phaseData, isActive)

  return (
    <div className="lite-root">
      <div className="lite-shell" style={{ maxWidth: 480 }}>
        <LightCard>
          <LogoHeader />
          <ErrorBanner message={error} />

          {isActive && (
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
              <LiveStatusLine phaseData={phaseData} />
              <span className="lite-mono lite-muted" style={{ fontSize: 11 }} data-testid="lite-elapsed">
                {formatElapsed(elapsedSeconds)}
              </span>
            </div>
          )}

          <div className="lite-label" style={{ marginBottom: 6 }}>Asking agents about your brand</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', marginBottom: 12 }}>
            {phaseMessage(phaseData)}
          </div>
          <CompetitorChips competitors={phaseData?.competitors} />
          <div className="lite-bar-track">
            <div
              className={`lite-bar-fill${isActive ? ' lite-bar-fill--shimmer' : ''}`}
              style={{ width: `${pct}%`, background: 'var(--accent)' }}
            />
          </div>
          {progress && (
            <div className="lite-muted" style={{ fontSize: 12, marginTop: 8 }}>
              {progress.completed_runs} of {progress.total_runs} queries complete
            </div>
          )}
          {isStalled && (
            <div className="lite-muted" style={{ fontSize: 12, marginTop: 8 }}>
              Still working — long queries can take a while.
            </div>
          )}

          {storeUrl && (
            <div style={{ marginTop: 20, paddingTop: 20, borderTop: '1px solid var(--line)' }}>
              <div className="lite-label" style={{ marginBottom: 8 }}>Reading your store like an agent</div>
              <ScanTrack scanStatus={phaseData?.scan_status} storeUrl={storeUrl} />
            </div>
          )}
        </LightCard>

        {isActive && (
          <div style={{ marginTop: 16 }}>
            <StatusEmailCard token={token} />
          </div>
        )}
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
