/**
 * The run manifest — status page (Stage 20), rebuilt as a PURE
 * PROJECTION of one /status poll snapshot (M0). deriveManifestRows()
 * is the single mapping function: status payload -> six fixed-order
 * rows, each independently pending/active/done/na. No row's content
 * comes from client-side accumulated state — feeding any one snapshot
 * to this component (fresh mount, a refresh, a same-tab revisit via
 * Stage 9's /report/{token} URL) renders the correct full manifest.
 * Only the elapsed clock, the >90s stalled notice, and
 * prefers-reduced-motion are legitimately time/environment-based, not
 * manifest content — they never change WHICH state a row is in.
 *
 * Rows are independent of each other and of visual position: the scan
 * (row 0) and membership probe (row 1) both run synchronously in the
 * same worker tick as the cycle is queued (see apps/pipeline/worker.py
 * ::process_lite_requests), often finishing before query-running even
 * starts, while competitor generation (row 2) happens earlier still —
 * so real runs complete rows out of visual order constantly. Display
 * order never changes; only each row's own state does.
 *
 * membership_check and scan_pages_read (Stage 20, additive fields on
 * GET /status) are the only two pieces of manifest content this page
 * needs that weren't already on the status payload — both sourced from
 * data _run_lite_scan/_run_membership_probe already write to
 * soa_lite_scan_results (see public_lite.py::_derive_membership_check).
 * No live per-page fetch count exists anywhere server-side (the crawl
 * writes once, at the end) — row 0's active state is deliberately a
 * generic line, never an invented count (S3).
 */
import { useEffect, useRef, useState } from 'react'
import { LogoHeader, ErrorBanner, LightCard, DarkCard, Chip } from './liteTheme.jsx'
import { domainFromStoreUrl, formatElapsed, maskEmail } from './liteDerive.js'
import { liteApi } from './liteApi.js'
import { validateEmail } from './validation.js'
import { PILLAR_NAMES, PILLAR_ORDER } from './landing/scanDimensionsRegistry.js'

const STALL_THRESHOLD_MS = 90_000
const DEFAULT_TOTAL_QUERIES = 12 // fixed query count for every SoA Lite run, not registry data

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

/** R2 (Stage 12), generalized for Stage 20: tracks the last time the
 * manifest's own rendered signature actually changed — not phaseData's
 * object identity, which is fresh every 5s poll even when nothing
 * moved — and reports "stalled" once that's been >90s while the run is
 * still non-terminal. Driven by the SAME rows deriveManifestRows just
 * computed, so any visible change to any row (not just query progress)
 * correctly resets the clock. */
function useStalledState(signature, active) {
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

// ─── Row derivation (pure) ───────────────────────────────────────────────

const SCAN_INFO_COPY = {
  blocked: (domain) => `${domain} blocked our reader — that itself is a finding, and it's in your report.`,
  failed: (domain) => `We couldn't finish reading ${domain} this time — noted honestly in your report.`,
  skipped: (domain) => `We didn't get a chance to read ${domain} this run.`,
}

function deriveReadingStoreRow(phaseData, storeUrl) {
  if (!storeUrl) {
    return { state: 'na', detail: 'No store URL was provided this run.', stamp: null, fraction: 1 }
  }
  const domain = domainFromStoreUrl(storeUrl)
  const scanStatus = phaseData?.scan_status

  if (scanStatus === 'complete') {
    const pages = phaseData?.scan_pages_read
    const detail = pages !== null && pages !== undefined
      ? `${pages} pages read — catalog, loyalty, and protocol surfaces`
      : 'Finished reading your store'
    return { state: 'done', detail, stamp: 'DONE', fraction: 1 }
  }
  if (scanStatus === 'blocked' || scanStatus === 'failed' || scanStatus === 'skipped') {
    return { state: 'na', detail: SCAN_INFO_COPY[scanStatus](domain), stamp: null, fraction: 1 }
  }
  if (!scanStatus) {
    return { state: 'pending', detail: '', stamp: null, fraction: 0 }
  }
  return { state: 'active', detail: 'fetching pages…', stamp: null, fraction: 0 }
}

function deriveMembershipRow(phaseData) {
  const check = phaseData?.membership_check
  if (check === 'applies') {
    return { state: 'done', detail: 'Program found — Member Value will be scored', stamp: 'SCORED', fraction: 1 }
  }
  if (check === 'na') {
    return { state: 'na', detail: 'No program found — scoring normalized', stamp: null, fraction: 1 }
  }
  if (phaseData?.scan_status) {
    return { state: 'active', detail: 'asking whether a membership program exists…', stamp: null, fraction: 0 }
  }
  return { state: 'pending', detail: '', stamp: null, fraction: 0 }
}

function deriveCompetitorRow(phaseData) {
  // competitor_source (not competitors.length) is the real "has this
  // resolved yet" signal: competitor_names starts as the visitor's own
  // manual list (often []) from the very first poll, at submission time
  // — only competitor_source is null until process_lite_requests'
  // auto-generation step actually runs and writes both fields together
  // (see worker.py). Using competitors==null here would misread an
  // unresolved solo submission as an already-resolved one.
  const source = phaseData?.competitor_source
  if (source == null) {
    if (phaseData?.phase === 'identifying_competitors') {
      return { state: 'active', detail: 'identifying your closest rivals…', stamp: null, fraction: 0 }
    }
    return { state: 'pending', detail: '', stamp: null, fraction: 0 }
  }
  const competitors = phaseData?.competitors || []
  if (competitors.length === 0) {
    return { state: 'na', detail: 'Running solo — no close rivals identified', stamp: null, fraction: 1 }
  }
  return { state: 'done', detail: null, chips: competitors, stamp: `${competitors.length} FOUND`, fraction: 1 }
}

const QUESTIONS_DONE_PHASES = new Set(['coding', 'analyzing', 'metrics', 'complete'])

function deriveQuestionsRow(phaseData) {
  const phase = phaseData?.phase
  const progress = phaseData?.progress

  if (phase === 'running') {
    const total = progress?.total_runs || DEFAULT_TOTAL_QUERIES
    const completed = progress?.completed_runs ?? 0
    return {
      state: 'active', stamp: null, fraction: total ? completed / total : 0,
      detail: `${completed} of ${total} answers`,
      qbarPct: total ? Math.round((completed / total) * 100) : 0,
    }
  }
  if (QUESTIONS_DONE_PHASES.has(phase)) {
    const total = progress?.total_runs || DEFAULT_TOTAL_QUERIES
    return { state: 'done', stamp: `${total} OF ${total}`, detail: 'All 12 answers collected', fraction: 1 }
  }
  return { state: 'pending', detail: '', stamp: null, fraction: 0 }
}

function pillarScoredCopy() {
  const names = PILLAR_ORDER.map((p) => PILLAR_NAMES[p])
  const last = names[names.length - 1]
  return `Scored across ${names.slice(0, -1).join(', ')}, and ${last}`
}

function deriveScoringRow(phaseData) {
  const phase = phaseData?.phase
  if (phase === 'coding' || phase === 'analyzing') {
    return { state: 'active', detail: 'coding mentions, prices, and incentives…', stamp: null, fraction: 0 }
  }
  if (phase === 'metrics' || phase === 'complete') {
    return { state: 'done', detail: pillarScoredCopy(), stamp: 'DONE', fraction: 1 }
  }
  return { state: 'pending', detail: '', stamp: null, fraction: 0 }
}

function deriveReportRow(phaseData) {
  if (phaseData?.status === 'complete') {
    return { state: 'done', detail: 'Three pillars, ranked fixes, private link', stamp: 'READY', fraction: 1 }
  }
  if (phaseData?.phase === 'metrics') {
    return { state: 'active', detail: 'assembling your report…', stamp: null, fraction: 0 }
  }
  return { state: 'pending', detail: '', stamp: null, fraction: 0 }
}

const ROW_DEFS = [
  { key: 'reading_store', name: 'Reading your store', weight: 14, derive: deriveReadingStoreRow, needsStoreUrl: true },
  { key: 'membership_check', name: 'Membership check', weight: 6, derive: deriveMembershipRow },
  { key: 'competitor_set', name: 'Competitor set', weight: 6, derive: deriveCompetitorRow },
  { key: 'shopper_questions', name: 'Shopper questions', weight: 40, derive: deriveQuestionsRow },
  { key: 'scoring_answers', name: 'Scoring the answers', weight: 24, derive: deriveScoringRow },
  { key: 'your_report', name: 'Your report', weight: 10, derive: deriveReportRow },
]

/**
 * The single mapping function (M0): one status snapshot -> the full
 * six-row manifest, in fixed display order. A row's `fraction` (0-1)
 * feeds the aggregate bar; `state` is always one of pending/active/
 * done/na. Rule S2/test requirement: an overall status of 'failed'
 * must never leave a row pulsing — any row still active collapses to
 * 'na' with no detail (LiteWidget.jsx routes 'failed' to <LiteFailed>
 * instead of this component in production; this is a defensive
 * invariant on the pure function itself).
 */
export function deriveManifestRows(phaseData, storeUrl) {
  const rows = ROW_DEFS.map(({ key, name, weight, derive, needsStoreUrl }) => ({
    key,
    name,
    weight,
    ...derive(phaseData, needsStoreUrl ? storeUrl : undefined),
  }))

  if (phaseData?.status === 'failed') {
    return rows.map((row) => (
      row.state === 'active'
        ? { ...row, state: 'na', detail: '', chips: undefined, qbarPct: undefined }
        : row
    ))
  }
  return rows
}

export function aggregatePct(rows) {
  const total = rows.reduce((sum, row) => sum + row.weight * (row.fraction || 0), 0)
  return Math.max(0, Math.min(100, Math.round(total)))
}

// ─── Row rendering ───────────────────────────────────────────────────────

const GLYPH_BY_STATE = { done: '✓', na: '—', active: '●', pending: '●' }
const GLYPH_COLOR_BY_STATE = {
  done: 'var(--good)', na: 'var(--text-2)', active: 'var(--accent)', pending: 'var(--line)',
}

function ManifestRow({ row, reducedMotion }) {
  const pulse = row.state === 'active' && !reducedMotion
  const glyphClasses = ['lite-manifest-glyph']
  if (pulse) glyphClasses.push('lite-manifest-glyph--pulse')

  return (
    <div className="lite-manifest-row">
      <span
        className={glyphClasses.join(' ')}
        style={{ color: GLYPH_COLOR_BY_STATE[row.state] }}
        aria-hidden="true"
      >
        {GLYPH_BY_STATE[row.state]}
      </span>
      <span style={{ fontSize: 14.5, fontWeight: 600, color: row.state === 'pending' ? 'var(--text-2)' : 'var(--text)' }}>
        {row.name}
      </span>
      {row.stamp && (
        <span
          className="lite-mono"
          style={{ fontSize: 11, letterSpacing: '0.06em', color: row.state === 'done' ? 'var(--good-ink)' : 'var(--text-2)' }}
        >
          {row.stamp}
        </span>
      )}
      <div className="lite-manifest-detail">
        {row.chips ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 2 }}>
            {row.chips.map((name) => <Chip key={name} tone="outline">{name}</Chip>)}
          </div>
        ) : row.qbarPct !== undefined ? (
          <span>
            <span className="lite-manifest-qbar" aria-hidden="true"><span style={{ width: `${row.qbarPct}%` }} /></span>
            <span className="lite-mono">{row.detail}</span>
          </span>
        ) : row.state === 'active' ? (
          <span className="lite-mono">{row.detail}</span>
        ) : (
          row.detail || null
        )}
      </div>
    </div>
  )
}

// ─── Status-page email card (Stage 12, E1) — unchanged ──────────────────
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

// ─── Root ────────────────────────────────────────────────────────────────

export function LiteProgress({ phaseData, storeUrl, error, token }) {
  const isActive = phaseData?.status !== 'complete' && phaseData?.status !== 'failed'
  const reducedMotion = usePrefersReducedMotion()
  const elapsedSeconds = useElapsedSeconds(isActive)

  const rows = deriveManifestRows(phaseData, storeUrl)
  const pct = aggregatePct(rows)
  const signature = JSON.stringify(rows.map((r) => [r.key, r.state, r.detail, r.stamp, r.chips, r.qbarPct]))
  const isStalled = useStalledState(signature, isActive)

  return (
    <div className="lite-root">
      <div className="lite-shell" style={{ maxWidth: 480 }}>
        <LightCard>
          <LogoHeader />
          <ErrorBanner message={error} />

          {isActive && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
              <span className="lite-mono lite-muted" style={{ fontSize: 11 }} data-testid="lite-elapsed">
                {formatElapsed(elapsedSeconds)}
              </span>
            </div>
          )}

          <div className="lite-bar-track" style={{ marginBottom: 18 }}>
            <div
              className={`lite-bar-fill${isActive ? ' lite-bar-fill--shimmer' : ''}`}
              style={{ width: `${pct}%`, background: 'var(--accent)' }}
            />
          </div>

          <div className="lite-manifest">
            {rows.map((row) => <ManifestRow key={row.key} row={row} reducedMotion={reducedMotion} />)}
          </div>

          {isStalled && (
            <div className="lite-muted" style={{ fontSize: 12, marginTop: 12 }}>
              Still working — long queries can take a while.
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
