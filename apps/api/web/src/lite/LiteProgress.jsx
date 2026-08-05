/**
 * The run-manifest status page (Part 1), rebuilt around the append-only
 * events[] array on the /status snapshot (apps/pipeline/lite_events.py
 * writes it; apps/api/app/routers/public_lite.py passes it straight
 * through). The prior stage's fixed six-row projection is retired
 * entirely — this page now projects THREE things from events[], every
 * poll, from scratch: the header's state chip +
 * progress bar (kind=state / done-task fraction), the always-visible
 * console (kind=log, arrival order), and the completion feed (kind=done,
 * arrival order, newest first). No client-side accumulation of its own:
 * feeding any one snapshot to this component renders the correct full
 * page — a fresh mount, a refresh, or a same-tab revisit via /report/
 * {token} all reproduce identically from that snapshot's events[] alone.
 *
 * TASK_ORDER/TASK_DISPLAY_NAMES below is a manually-synced mirror of
 * apps/pipeline/lite_events.py's TASKS registry — JS can't import
 * Python (same precedent as BOT_NAME/BOT_UA in BotsPage.jsx). Task ids
 * are stable; only the 8 ids and their order need to match.
 */
import { useEffect, useRef, useState } from 'react'
import { LogoHeader, ErrorBanner, LightCard, DarkCard, Chip } from './liteTheme.jsx'
import { domainFromStoreUrl, formatElapsed, maskEmail } from './liteDerive.js'
import { liteApi } from './liteApi.js'
import { validateEmail } from './validation.js'
import { DegradedRunBanner } from './DegradedRunBanner.jsx'

const STALL_THRESHOLD_MS = 90_000
const MAX_CONSOLE_HEIGHT_PX = 260

const TASK_ORDER = [
  'crawl', 'probe_membership', 'probe_revenue', 'probe_fetch',
  'competitors', 'queries', 'scoring', 'report',
]
const TASK_DISPLAY_NAMES = {
  crawl: 'Reading your store',
  probe_membership: 'Membership check',
  probe_revenue: 'Revenue estimate',
  probe_fetch: 'Fetch probe',
  competitors: 'Competitor set',
  queries: 'Shopper questions',
  scoring: 'Scoring the answers',
  report: 'Your report',
}

const STATE_CHIP_LABEL = {
  queued: 'AUDIT QUEUED',
  running: 'AUDIT RUNNING · USUALLY 10–20 MINUTES',
  done: 'AUDIT COMPLETE',
  failed: 'AUDIT FAILED',
  'degraded-blocked': 'AUDIT COMPLETE · SITE BLOCKED OUR READER',
  'no-product-pages': 'AUDIT COMPLETE · PRODUCT PAGES NOT FOUND',
}

// ─── Shared hooks (elapsed clock, reduced-motion, staleness) ────────────

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

/** P5: tracks the last time the snapshot's latest event ts actually
 * advanced, and reports "stalled" once that's been >90s while the run
 * is still active. Client-derived only — never stored as an event, and
 * never lets a dead worker read as "almost done". */
function useStalledSince(latestTs, active) {
  const lastTsRef = useRef(latestTs)
  const lastChangeAtRef = useRef(Date.now())
  const [isStalled, setIsStalled] = useState(false)

  useEffect(() => {
    if (latestTs !== lastTsRef.current) {
      lastTsRef.current = latestTs
      lastChangeAtRef.current = Date.now()
      setIsStalled(false)
    }
  }, [latestTs])

  useEffect(() => {
    if (!active) return undefined
    const interval = setInterval(() => {
      setIsStalled(Date.now() - lastChangeAtRef.current >= STALL_THRESHOLD_MS)
    }, 2000)
    return () => clearInterval(interval)
  }, [active])

  return isStalled
}

// ─── Pure projection helpers ─────────────────────────────────────────────

function formatEventClock(ts) {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** P1: derives ~N minutes remaining from the completed-task fraction and
 * elapsed time so far — labeled ESTIMATE, never a promise. Returns null
 * until there's enough signal (avoids a wild extrapolation off one
 * early task), in which case the header falls back to the state chip's
 * own "usually 10-20 minutes" copy alone. */
export function estimateRemainingMinutes(elapsedSeconds, completedFraction) {
  if (!completedFraction || completedFraction < 0.05) return null
  const estimatedTotalSeconds = elapsedSeconds / completedFraction
  const remainingSeconds = Math.max(0, estimatedTotalSeconds - elapsedSeconds)
  return Math.max(1, Math.ceil(remainingSeconds / 60))
}

/** M0-equivalent for this stage: the single mapping from one events[]
 * array to everything the page renders — no other client state feeds
 * derivation. */
export function projectEvents(events) {
  const safeEvents = events || []
  const logEvents = safeEvents.filter((e) => e.kind === 'log')
  const doneEvents = safeEvents.filter((e) => e.kind === 'done')
  const stateEvents = safeEvents.filter((e) => e.kind === 'state')
  const latestState = stateEvents.length ? stateEvents[stateEvents.length - 1].text : null
  const completedTasks = new Set(doneEvents.map((e) => e.task))
  const completedFraction = TASK_ORDER.length ? completedTasks.size / TASK_ORDER.length : 0
  const latestTs = safeEvents.length ? safeEvents[safeEvents.length - 1].ts : null

  return {
    logEvents,
    // P3: arrival order, prepended — newest done task first.
    doneEvents: doneEvents.slice().reverse(),
    latestState,
    completedFraction,
    latestTs,
  }
}

// ─── Header ───────────────────────────────────────────────────────────────

function ProgressHeader({ brandOrDomain, latestState, fallbackStatus, completedFraction, elapsedSeconds, isActive }) {
  // P7 fallback (no events yet, e.g. a pre-deploy row, or a run that
  // just submitted and hasn't had its first event land): derive the
  // chip from the status endpoint's own `status` field instead of a
  // state event — 'pending' reads as queued, anything else active-ish
  // reads as running, matching the honest default this same status
  // value already implied on the old six-row manifest.
  const chipLabel = STATE_CHIP_LABEL[latestState]
    || (fallbackStatus === 'pending' ? STATE_CHIP_LABEL.queued : STATE_CHIP_LABEL.running)
  const remainingMin = isActive ? estimateRemainingMinutes(elapsedSeconds, completedFraction) : null
  const pct = Math.round(Math.max(0, Math.min(1, completedFraction)) * 100)

  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 6 }}>
        <div className="lite-headline" style={{ fontSize: 18 }}>
          {brandOrDomain} — agentic value audit
        </div>
        {isActive && (
          <span className="lite-mono lite-muted" style={{ fontSize: 11 }} data-testid="lite-elapsed">
            {formatElapsed(elapsedSeconds)}
          </span>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 10 }}>
        <Chip tone={latestState === 'failed' ? 'bad' : 'outline'}>{chipLabel}</Chip>
      </div>
      <div className="lite-bar-track">
        <div
          className={`lite-bar-fill${isActive ? ' lite-bar-fill--shimmer' : ''}`}
          style={{ width: `${pct}%`, background: 'var(--accent)' }}
        />
      </div>
    </div>
  )
}

// ─── Console (P2) ───────────────────────────────────────────────────────

function ConsoleLine({ event }) {
  return (
    <div className="lite-console-line">
      <span className="lite-console-ts">{formatEventClock(event.ts)}</span>
      <span className="lite-console-task">{(TASK_DISPLAY_NAMES[event.task] || event.task).toUpperCase()}</span>
      <span className="lite-console-text">{event.text}</span>
    </div>
  )
}

function Console({ logEvents, isStalled, reducedMotion }) {
  const bodyRef = useRef(null)
  const [pinnedToBottom, setPinnedToBottom] = useState(true)

  useEffect(() => {
    const el = bodyRef.current
    if (el && pinnedToBottom) {
      el.scrollTop = el.scrollHeight
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [logEvents.length, isStalled])

  function handleScroll() {
    const el = bodyRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    setPinnedToBottom(distanceFromBottom < 24)
  }

  return (
    <div className="lite-console">
      <div className="lite-console-titlebar">
        <span className={`lite-console-live-dot${reducedMotion ? '' : ' lite-console-live-dot--pulse'}`} aria-hidden="true" />
        <span className="lite-mono" style={{ fontSize: 11, letterSpacing: '0.06em' }}>LIVE</span>
      </div>
      <div
        ref={bodyRef}
        className="lite-console-body"
        style={{ maxHeight: MAX_CONSOLE_HEIGHT_PX }}
        onScroll={handleScroll}
        role="log"
        aria-live="polite"
        data-testid="lite-console-body"
      >
        {logEvents.length === 0 ? (
          <div className="lite-console-line lite-console-line--muted">Starting up…</div>
        ) : (
          logEvents.map((e) => <ConsoleLine key={e.seq} event={e} />)
        )}
        {isStalled && (
          <div className="lite-console-line lite-console-line--muted">
            no updates for a while — still checking…
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Completion feed (P3) ───────────────────────────────────────────────

function CompletionCard({ event }) {
  const name = TASK_DISPLAY_NAMES[event.task] || event.task
  return (
    <div className="lite-feed-card">
      <span className="lite-feed-check" aria-hidden="true">✓</span>
      <div style={{ flex: 1 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text)' }}>{name}</span>
          <span className="lite-mono lite-muted" style={{ fontSize: 10.5, letterSpacing: '0.06em' }}>DONE</span>
        </div>
        <div className="lite-body lite-muted" style={{ fontSize: 13, marginTop: 2 }}>{event.text}</div>
        {event.chips && event.chips.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
            {event.chips.map((c) => <Chip key={c} tone="outline">{c}</Chip>)}
          </div>
        )}
      </div>
    </div>
  )
}

function CompletionFeed({ doneEvents, reducedMotion }) {
  return (
    <div className="lite-feed">
      <div className="lite-mono lite-muted" style={{ fontSize: 11, marginBottom: 10 }}>
        {doneEvents.length} OF {TASK_ORDER.length} TASKS
      </div>
      {doneEvents.length === 0 ? (
        <div className="lite-body lite-muted" style={{ fontSize: 13 }}>
          Tasks will appear here as they finish…
        </div>
      ) : (
        <div className="lite-feed-list">
          {doneEvents.map((e) => (
            <div key={e.task} className={reducedMotion ? '' : 'lite-feed-card--enter'}>
              <CompletionCard event={e} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Status-page email card (Stage 12, E1) — unchanged (P6) ─────────────
// Report redesign (Part 8, E2): this stays exactly what it always was —
// a notification-capture address only. The report itself is no longer
// gated on email at all, so this card was never "the same ask, moved
// earlier" — it never gated content, only requested where to send a
// completion notice.
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
        Leave your email and we'll send your report the moment it's ready — no need to keep this tab open. We won't spam you or share your email.
      </div>
      <ErrorBanner message={submitError} />
      {/* noValidate: validateEmail()'s message renders inline instead of
          relying on the browser's native email-input validation. */}
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

  const events = phaseData?.events
  const hasEvents = Array.isArray(events) && events.length > 0
  const { logEvents, doneEvents, latestState, completedFraction, latestTs } = projectEvents(events)
  const isStalled = useStalledSince(latestTs, isActive && latestState === 'running')

  const brandOrDomain = storeUrl ? domainFromStoreUrl(storeUrl) : 'Your store'
  const showDegradedBanner = latestState === 'degraded-blocked' || latestState === 'no-product-pages'

  return (
    <div className="lite-root">
      <div className="lite-shell" style={{ maxWidth: 560 }}>
        <LightCard>
          <LogoHeader />
          <ErrorBanner message={error} />

          <ProgressHeader
            brandOrDomain={brandOrDomain}
            latestState={latestState}
            fallbackStatus={phaseData?.status}
            completedFraction={completedFraction}
            elapsedSeconds={elapsedSeconds}
            isActive={isActive}
          />

          {showDegradedBanner && (
            <div style={{ marginBottom: 16 }}>
              <DegradedRunBanner
                status={phaseData?.scan_status}
                degradedReason={phaseData?.degraded_reason}
                bannerFacts={phaseData?.degraded_banner_facts}
              />
            </div>
          )}

          {hasEvents ? (
            <>
              <div style={{ marginBottom: 16 }}>
                <Console logEvents={logEvents} isStalled={isStalled} reducedMotion={reducedMotion} />
              </div>
              <CompletionFeed doneEvents={doneEvents} reducedMotion={reducedMotion} />
            </>
          ) : null}
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
