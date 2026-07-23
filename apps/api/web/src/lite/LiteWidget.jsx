/**
 * SoA Lite — public, unauthenticated lead-gen widget at /lite.
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
 *   'complete' fetches /report -> TEASER (locked, email null) or
 *   FULL REPORT (unlocked, email set) -> submitting email on the teaser
 *   swaps straight to FULL REPORT using PATCH /email's inline response.
 *   'failed' shows a retry-from-form view. The full report's "add your
 *   store URL" prompt (brand-only submissions) resets straight back to
 *   FORM, pre-filled with the already-confirmed brand name — there is no
 *   API to attach a URL to an existing request, so this is an honest
 *   restart rather than a silent no-op.
 *
 * This file re-exports LiteForm/LiteProgress/LiteFailed/LiteTeaser/
 * LiteFullReport from their own modules (Stage 4 split them out as the
 * combined report grew) so `import { X } from './LiteWidget.jsx'` keeps
 * working for every existing caller and test.
 */
import { useEffect, useState } from 'react'
import { liteApi } from './liteApi.js'
import { LiteForm } from './LiteForm.jsx'
import { LiteProgress, LiteFailed } from './LiteProgress.jsx'
import { LiteTeaser } from './LiteTeaser.jsx'
import { LiteFullReport } from './LiteFullReport.jsx'

export { LiteForm, LiteProgress, LiteFailed, LiteTeaser, LiteFullReport }

const STORAGE_KEY = 'soaLiteToken'
const STORAGE_KEY_STORE_URL = 'soaLiteStoreUrl'
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

export default function LiteWidget() {
  const [token, setToken] = useState(() => readSession(STORAGE_KEY))
  const [storeUrl, setStoreUrl] = useState(() => readSession(STORAGE_KEY_STORE_URL))
  const [phaseData, setPhaseData] = useState(null)
  const [report, setReport] = useState(null)
  const [pollError, setPollError] = useState(null)
  const [restartBrandName, setRestartBrandName] = useState('')

  function handleSubmitted(newToken, { storeUrl: newStoreUrl } = {}) {
    writeSession(STORAGE_KEY, newToken)
    writeSession(STORAGE_KEY_STORE_URL, newStoreUrl || null)
    setPhaseData(null)
    setReport(null)
    setPollError(null)
    setRestartBrandName('')
    setStoreUrl(newStoreUrl || null)
    setToken(newToken)
  }

  function resetToForm(prefillBrandName) {
    writeSession(STORAGE_KEY, null)
    writeSession(STORAGE_KEY_STORE_URL, null)
    setToken(null)
    setStoreUrl(null)
    setPhaseData(null)
    setReport(null)
    setPollError(null)
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
  // terminal state yet.
  useEffect(() => {
    if (!token) return undefined
    if (phaseData?.status === 'complete' || phaseData?.status === 'failed') return undefined

    let cancelled = false

    async function poll() {
      try {
        const data = await liteApi.getStatus(token)
        if (!cancelled) setPhaseData(data)
      } catch (err) {
        if (!cancelled) setPollError(err.message || 'Could not check status.')
      }
    }

    poll()
    const interval = setInterval(poll, POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [token, phaseData?.status])

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

  if (!token) {
    return <LiteForm onSubmitted={handleSubmitted} initialBrandName={restartBrandName} />
  }

  if (phaseData?.status === 'failed') {
    return <LiteFailed onRetry={handleRetry} />
  }

  if (phaseData?.status === 'complete' && report) {
    return report.locked
      ? <LiteTeaser report={report} token={token} onUnlocked={setReport} />
      : <LiteFullReport report={report} onAddStoreUrl={handleAddStoreUrl} />
  }

  return (
    <LiteProgress
      phaseData={phaseData || { status: 'pending', phase: 'queued' }}
      storeUrl={storeUrl}
      error={pollError}
    />
  )
}
