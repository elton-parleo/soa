/**
 * SoA Lite — public, unauthenticated lead-gen widget at /lite, and (Stage
 * 9) the same state machine reused at /report/{token} on the marketing
 * host and at /r/{token} + /s/{id} on audit.parleo.io for unique,
 * revisitable report URLs (see App.jsx). '/s/' isn't a distinct
 * internal route — it's just another external name for this same
 * token-driven flow, which already renders progress or the full report
 * depending on where the run is.
 *
 * Self-contained: no Sidebar, no AuthContext, no import of the authed
 * app's api.js/supabase.js (see liteApi.js). Meant to be iframed or
 * linked directly from the marketing site, so it makes no fixed-viewport
 * assumptions and must render sensibly at widths as small as ~400px.
 *
 * State machine (mirrors soa_lite_requests server-side):
 *   FORM -> submit -> token (+ store_url, if given) stored in state and
 *   sessionStorage so a refresh mid-run doesn't lose it -> poll /status
 *   every 5s (now also carrying scan_status, Stage 3) -> PROGRESS view
 *   through phases queued/generating_queries/running/analyzing ->
 *   'complete' fetches /report -> FULL REPORT, always (Report redesign,
 *   Part 8, E1: the report is never gated on an email being on file —
 *   a valid, complete token renders the full report directly). 'failed'
 *   shows a retry-from-form view. The full report's "add your store URL"
 *   prompt (brand-only submissions) resets straight back to FORM,
 *   pre-filled with the already-confirmed brand name — there is no API
 *   to attach a URL to an existing request, so this is an honest restart
 *   rather than a silent no-op.
 *
 * Stage 9 additions, both optional props so /lite's existing embed
 * behavior is byte-for-byte unchanged when they're omitted:
 *   urlToken  — when App.jsx renders this from /report/{token}, seeds
 *     the token from the URL instead of sessionStorage (and persists it
 *     TO sessionStorage too, so a later bare /lite visit or a same-tab
 *     refresh resumes it same as any other submission). An explicitly
 *     empty urlToken ('' — /report with no token segment) skips polling
 *     entirely and goes straight to the not-found state; a 404 from
 *     /status for a real-looking-but-unknown/expired token does the same
 *     and also scrubs it from sessionStorage, so a dead token can't get
 *     stuck poisoning a later /lite or /report/{token} visit.
 *   navigate  — called with the canonical /report/{token} path right
 *     after a successful submit, so the address bar is shareable from
 *     the first second of the run (U2) without a full page reload.
 *
 * Report-first resolution (status-flash fix): a token-bearing report
 * route does NOT enter the state machine above at the /status step.
 * The render dispatch used to fall through to LiteProgress for anything
 * that wasn't yet a report, which meant EVERY /r/{token} — including a
 * report that finished last week — painted the status page first, then
 * polled /status, then fetched /report, then finally re-rendered. Two
 * sequential round trips and one wrong screen for the most common visit
 * there is. Now the route resolves before it renders: mount fires
 * getReport(token) and holds a neutral ReportResolving skeleton (no
 * queue/phase copy, never LiteProgress) until the answer arrives —
 * 200 renders the report on the first paint that has anything to say,
 * 404 is the same terminal not-found as before, and 409 ('not ready
 * yet') falls back to the unchanged /status poll + LiteProgress run.
 * Finished report: one request, one render. In-progress run: the same
 * status experience it has always had. Direct-form /lite sessions (no
 * urlToken) never enter resolving at all and are byte-for-byte
 * unchanged.
 *
 * This file re-exports LiteForm/LiteProgress/LiteFailed/LiteFullReport
 * from their own modules (Stage 4 split them out as the combined report
 * grew) so `import { X } from './LiteWidget.jsx'` keeps working for
 * every existing caller and test. LiteTeaser (the pre-Part-8 email gate)
 * is deleted entirely — see the state-machine note above.
 */
import { useEffect, useState } from 'react'
import './theme.css'
import { liteApi } from './liteApi.js'
import { LiteForm } from './LiteForm.jsx'
import { LiteProgress, LiteFailed } from './LiteProgress.jsx'
import { LiteFullReport } from './LiteFullReport.jsx'
import { LiteFullReportV4 } from './report/LiteFullReportV4.jsx'
import { LightCard } from './liteTheme.jsx'
import { ReportNotFoundCard } from './ReportNotFoundCard.jsx'
import { Wordmark } from '../ds/Wordmark.jsx'
import { PUBLIC_AUDIT_BASE_URL, isAuditHost, reportUrl } from './publicUrls.js'
import { upsertMeta, upsertLink, restoreOrRemove } from './headMeta.js'
import { track, identifyReport, captureSrcParam, isTokenOwned } from './analytics.js'
import { EVENTS } from './analyticsEvents.js'

export { LiteForm, LiteProgress, LiteFailed, LiteFullReport }

// Exported so the landing page (Stage 6) can hand off a submission to
// this widget's resume-from-sessionStorage behavior without duplicating
// the state machine.
export const STORAGE_KEY = 'soaLiteToken'
export const STORAGE_KEY_STORE_URL = 'soaLiteStoreUrl'
const POLL_INTERVAL_MS = 5000

function readSession(key) {
  try {
    return sessionStorage.getItem(key) || null
  } catch (_) {
    return null
  }
}

function writeSession(key, value) {
  try {
    if (value === null || value === undefined) {
      sessionStorage.removeItem(key)
    } else {
      sessionStorage.setItem(key, value)
    }
  } catch (_) {}
}

// ─── Resolving state (report routes only) ──────────────────────────────
// Opening /r/{token} used to render LiteProgress for EVERY token before
// the first response came back, so a finished report flashed the status
// page on its way in — and paid two sequential round trips (/status,
// then /report) to get there. The route now resolves before anything
// renders: this neutral skeleton holds the report's own frame (rail +
// main, DS tokens) for the single request it takes to learn what this
// token is. Deliberately carries no queue/phase copy and no progress
// affordance of any kind — it must never read as "your audit is
// running" for a report that finished hours ago, which is exactly the
// thing LiteProgress-as-fallthrough got wrong. Direct-form /lite
// sessions (no urlToken) never reach it.
function ReportResolving() {
  return (
    <div
      className="grain-overlay lite-report-shell lite-resolving"
      data-testid="lite-resolving"
      aria-busy="true"
      style={{
        minHeight: '100vh',
        display: 'grid',
        gridTemplateColumns: '222px 1fr',
        background: 'var(--canvas)',
      }}
    >
      <div
        className="lite-report-rail lite-resolving-rail"
        style={{ borderRight: '1px solid var(--border)', background: 'var(--canvas-dim)', padding: '22px 18px' }}
      >
        <Wordmark size={14} />
        <div className="lite-resolving-block" style={{ height: 12, width: '72%', marginTop: 28 }} />
        <div className="lite-resolving-block" style={{ height: 12, width: '86%', marginTop: 12 }} />
        <div className="lite-resolving-block" style={{ height: 12, width: '58%', marginTop: 12 }} />
      </div>
      <div
        className="lite-report-content"
        style={{ width: '100%', maxWidth: 920, margin: '0 auto', padding: '32px 28px 46px' }}
      >
        {/* The rail (and its wordmark) is hidden on phone, exactly as it
            is on the report itself — so the mark repeats here, shown
            only at that width, rather than leaving the narrow frame
            unbranded. */}
        <div className="lite-resolving-mark" style={{ marginBottom: 22 }}>
          <Wordmark size={14} />
        </div>
        <div className="lite-resolving-block" style={{ height: 18, width: 180 }} />
        <div className="lite-resolving-block" style={{ height: 148, marginTop: 24 }} />
        <div className="lite-resolving-block" style={{ height: 96, marginTop: 18 }} />
      </div>
      <span className="lite-visually-hidden" role="status">Loading report</span>
    </div>
  )
}

// ─── Not-found state (U1) — unknown/expired token, or a bare /report ────
// Thin wrapper over the shared ReportNotFoundCard (lite's own copy/CTA
// unchanged) — see ReportNotFoundCard.jsx for why this is shared with
// the Full Analysis public route now too.
function ReportNotFound({ navigate }) {
  return (
    <ReportNotFoundCard
      onCta={() => {
        // On the audit host, '/' is the landing page — a fast
        // client-side transition. A dead /report/{token} link on
        // the marketing host (H2: /scan no longer exists there)
        // has nowhere local to send the visitor, so it does a
        // full navigation out to the audit host's landing page.
        if (isAuditHost()) {
          if (navigate) navigate('/')
          else window.location.href = '/'
        } else {
          window.location.href = PUBLIC_AUDIT_BASE_URL
        }
      }}
    />
  )
}

// ─── Expired-report state (Part 4, re-weighting session) — a report
// scored under a retired scoring model. Never partial rendering, never
// the stale score alongside a warning, never a recompute — just an
// honest dead end with a way forward, same design system as
// ReportNotFound above (a distinct case: this token is real and was
// real once, it just can't be shown against the current model anymore).
function ReportExpired({ storeUrl, token }) {
  const runFreshHref = `${PUBLIC_AUDIT_BASE_URL}/${storeUrl ? `?url=${encodeURIComponent(storeUrl)}` : ''}`

  useEffect(() => {
    identifyReport(token)
    track(EVENTS.REPORT_VIEWED, {
      state: 'expired',
      viewer: isTokenOwned(token) ? 'owner' : 'visitor',
      src: captureSrcParam(),
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="lite-root">
      <div className="lite-shell" style={{ maxWidth: 480 }}>
        <LightCard>
          <div className="lite-headline" style={{ fontSize: 20, marginBottom: 8 }}>
            This report has expired
          </div>
          <div className="lite-body lite-muted" style={{ marginBottom: 20 }}>
            We've updated how the audit scores stores since this report ran — its
            numbers were measured against an earlier model and are no longer
            comparable to a current one. Run a fresh audit to see where you
            stand today.
          </div>
          <a
            href={runFreshHref}
            onClick={() => track(EVENTS.CTA_CLICKED, { cta: 'rerun', placement: 'expired_card' })}
            className="lite-pill lite-pill--solid"
            style={{ textDecoration: 'none', display: 'inline-block' }}
          >
            Run a fresh audit
          </a>
        </LightCard>
      </div>
    </div>
  )
}

export default function LiteWidget({ urlToken, navigate } = {}) {
  // urlToken !== undefined means App.jsx rendered us from /report/{...} —
  // even an explicitly empty string (a bare /report) is a real, distinct
  // signal from "no prop passed at all" (the /lite embed, sessionStorage-driven).
  const isReportRoute = urlToken !== undefined

  const [token, setToken] = useState(() => (
    isReportRoute ? (urlToken || null) : readSession(STORAGE_KEY)
  ))
  const [storeUrl, setStoreUrl] = useState(() => readSession(STORAGE_KEY_STORE_URL))
  const [phaseData, setPhaseData] = useState(null)
  const [report, setReport] = useState(null)
  const [pollError, setPollError] = useState(null)
  const [notFound, setNotFound] = useState(isReportRoute && !urlToken)
  const [restartBrandName, setRestartBrandName] = useState('')
  // Report-first resolution: a token-bearing report route starts in an
  // explicit 'resolving' phase and renders nothing but the neutral
  // skeleton until the first response says what this token is. Seeded
  // false for every other entry point, so the /lite direct-form path
  // never enters it.
  const [resolving, setResolving] = useState(isReportRoute && !!urlToken)

  // A URL-borne token becomes the resumable one — a bare /lite visit or
  // a same-tab refresh later should find it exactly like any other
  // submission would have left it.
  useEffect(() => {
    if (isReportRoute && urlToken) {
      writeSession(STORAGE_KEY, urlToken)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Report-first resolution (mount-only, report routes with a token).
  // /report is the ONE request a finished audit needs: it already
  // carries the complete payload, and the router distinguishes the
  // three outcomes on its own, so no status call is made to find out
  // which one this is —
  //   200  → the report (complete, or the expired shape) renders
  //          immediately; the poll effect below never starts.
  //   404  → the token is unknown/malformed. Terminal, exactly as a 404
  //          from /status is: scrub it and show the not-found view.
  //   409  → 'Report is not ready yet' (public_lite.py::get_lite_report).
  //          The run is real and still going, so this falls through to
  //          the unchanged /status poll + LiteProgress experience.
  // Anything else (500, offline) also falls through to polling, which
  // owns the retry/error surface it always has.
  useEffect(() => {
    if (!resolving) return undefined
    let cancelled = false
    liteApi.getReport(urlToken)
      .then((data) => {
        if (cancelled) return
        setReport(data)
        setResolving(false)
      })
      .catch((err) => {
        if (cancelled) return
        if (err.status === 404) {
          writeSession(STORAGE_KEY, null)
          writeSession(STORAGE_KEY_STORE_URL, null)
          setNotFound(true)
        }
        setResolving(false)
      })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Stage 9 (U4), audit.parleo.io migration (S2/S3): noindex whenever a
  // real report/progress view could be showing — /report/* always, or
  // /lite once a token exists. Marketing host only: audit-report.html
  // already bakes noindex into the served document for /r/ and /s/
  // (S3), so adding a second tag here on the audit host would just
  // duplicate it.
  useEffect(() => {
    if (isAuditHost()) return undefined
    if (!token && !isReportRoute) return undefined
    const handle = upsertMeta('name', 'robots', 'noindex,nofollow')
    return () => restoreOrRemove(handle)
  }, [token, isReportRoute])

  // L1/L2: on the marketing host, this page is always a duplicate of
  // something the audit host owns — declare that canonical explicitly.
  // A bare /lite form (no token yet) canonicalizes to the audit host's
  // root (L2); once a token exists — via /report/{token}, or a /lite
  // session resumed from sessionStorage — it canonicalizes to that
  // report's /r/ URL (L1). Skipped on the audit host itself (already
  // canonical there, see S3) and while showing the not-found state
  // (nothing real to declare a canonical identity for).
  useEffect(() => {
    if (isAuditHost() || notFound) return undefined
    const href = token ? reportUrl(token) : `${PUBLIC_AUDIT_BASE_URL}/`
    const handle = upsertLink('canonical', href)
    return () => restoreOrRemove(handle)
  }, [token, notFound])

  function handleSubmitted(newToken, { storeUrl: newStoreUrl } = {}) {
    writeSession(STORAGE_KEY, newToken)
    writeSession(STORAGE_KEY_STORE_URL, newStoreUrl || null)
    setPhaseData(null)
    setReport(null)
    setPollError(null)
    setNotFound(false)
    setRestartBrandName('')
    setStoreUrl(newStoreUrl || null)
    setToken(newToken)
    // U2: canonical, shareable URL from the first second of the run —
    // history push, no reload (navigate is a no-op-free optional prop so
    // any caller/test that doesn't pass one keeps today's exact behavior).
    // This widget renders on both hosts (the /lite embed on the
    // marketing host, and /r//s on the audit host), so the prefix has
    // to match whichever one is actually serving the page.
    if (navigate) navigate(isAuditHost() ? `/r/${newToken}` : `/report/${newToken}`)
  }

  function resetToForm(prefillBrandName) {
    writeSession(STORAGE_KEY, null)
    writeSession(STORAGE_KEY_STORE_URL, null)
    setToken(null)
    setStoreUrl(null)
    setPhaseData(null)
    setReport(null)
    setPollError(null)
    setNotFound(false)
    setRestartBrandName(prefillBrandName || '')
  }

  function handleRetry() {
    resetToForm('')
  }

  function handleAddStoreUrl() {
    const primary = (report?.overall || []).find((e) => e.role === 'primary')
    resetToForm(primary?.name || '')
  }

  // Poll /status every 5s while a token exists and we haven't reached a
  // terminal state yet. A 404 (unknown/expired token) is not a transient
  // pollError — it's terminal, so it stops polling and shows the
  // not-found view (Stage 9, U1) instead of spinning forever.
  useEffect(() => {
    if (!token || notFound) return undefined
    // Nothing to poll for while the route is still resolving, or once
    // report-first resolution has already produced the report — the
    // status page's whole job is covering an in-progress run.
    if (resolving || report) return undefined
    if (phaseData?.status === 'complete' || phaseData?.status === 'failed') return undefined

    let cancelled = false

    async function poll() {
      try {
        const data = await liteApi.getStatus(token)
        if (!cancelled) setPhaseData(data)
      } catch (err) {
        if (cancelled) return
        if (err.status === 404) {
          // Terminal and permanent — an unknown/expired token can never
          // resolve, so scrub it rather than leaving it to poison the
          // next /lite resume or /report/{token} visit in this tab.
          writeSession(STORAGE_KEY, null)
          writeSession(STORAGE_KEY_STORE_URL, null)
          setNotFound(true)
        } else {
          setPollError(err.message || 'Could not check status.')
        }
      }
    }

    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [token, phaseData?.status, notFound, resolving, report])

  // Once complete, fetch the report (teaser or full, decided server-side
  // by whether an email is already on file).
  useEffect(() => {
    if (phaseData?.status !== 'complete' || report || !token) return undefined
    let cancelled = false
    liteApi.getReport(token)
      .then((data) => { if (!cancelled) setReport(data) })
      .catch((err) => { if (!cancelled) setPollError(err.message || 'Could not load report.') })
    return () => { cancelled = true }
  }, [phaseData?.status, report, token])

  if (notFound) {
    return <ReportNotFound navigate={navigate} />
  }

  // Before anything else that could be wrong for this token: hold the
  // frame until the route has resolved. LiteProgress is never rendered
  // from here, so a finished report has no status frame to flash and
  // status_viewed never fires for a run that isn't in progress.
  if (resolving) {
    return <ReportResolving />
  }

  if (!token) {
    return <LiteForm onSubmitted={handleSubmitted} initialBrandName={restartBrandName} />
  }

  if (phaseData?.status === 'failed') {
    return <LiteFailed onRetry={handleRetry} />
  }

  // `report` is only ever set by a completed run — report-first
  // resolution above, or the post-'complete' fetch below — so it alone
  // decides the report branch, and the dispatch order inside it is
  // unchanged: expired first, then V4 (pillars), then legacy.
  if (report) {
    // Re-weighting session (Part 4): a report scored under a retired
    // scoring model never reaches pillars OR the legacy fallback below
    // — checked first, since report.status is 'expired' instead of
    // 'complete' and carries no score/pillar/verdict data at all.
    if (report.status === 'expired') {
      return <ReportExpired storeUrl={report.store_url} token={token} />
    }
    // V4 report redesign: the new rail+focus-mode layout renders only
    // for a current-version (pillars-bearing) report — a pre-this-stage
    // row falls back to the legacy template exactly as it always has,
    // rather than hitting a V4 layout built for a payload shape it
    // never had.
    if (report.pillars) {
      return <LiteFullReportV4 report={report} token={token} />
    }
    return <LiteFullReport report={report} onAddStoreUrl={handleAddStoreUrl} token={token} />
  }

  return (
    <LiteProgress
      phaseData={phaseData || { status: 'pending', phase: 'queued' }}
      storeUrl={storeUrl}
      error={pollError}
      token={token}
    />
  )
}
