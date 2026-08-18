/**
 * Public, unauthenticated Full Analysis report viewer — /fa/{token}.
 * Same pre-auth treatment as LiteWidget.jsx's /report/{token}: routed
 * in App.jsx before AuthProvider mounts, so a visitor with no session
 * never touches Supabase state or the login gate. Fetches through
 * publicFullAnalysisApi.js (its own tiny, session-less client, same
 * reasoning as lite/liteApi.js) and renders FullAnalysisReport in
 * readOnly mode — no app chrome to strip (FullAnalysisReport already
 * renders full-bleed for the authed view too; see FullAnalysisReportGate.
 * jsx), just the auth-walled affordances readOnly itself turns off.
 *
 * Unknown, revoked, and expired tokens all come back as the exact same
 * 404 from the backend (public_full_analysis.py's module docstring) —
 * so there's one not-found state here too, not three.
 */
import { useEffect, useState } from 'react'
import FullAnalysisReport from './FullAnalysisReport.jsx'
import { ReportNotFoundCard } from '../lite/ReportNotFoundCard.jsx'
import { publicFullAnalysisApi } from '../publicFullAnalysisApi.js'
import '../lite/theme.css'

function PublicFullAnalysisLoading() {
  return (
    <div className="lite-root">
      <div className="lite-shell" style={{ maxWidth: 480, textAlign: 'center', padding: '96px 0' }}>
        <div className="lite-body lite-muted">Loading report…</div>
      </div>
    </div>
  )
}

export default function PublicFullAnalysisPage({ token }) {
  const [state, setState] = useState({ loading: true, report: null, error: null })

  useEffect(() => {
    let cancelled = false
    setState({ loading: true, report: null, error: null })
    publicFullAnalysisApi.getReport(token)
      .then((report) => { if (!cancelled) setState({ loading: false, report, error: null }) })
      .catch((err) => { if (!cancelled) setState({ loading: false, report: null, error: err }) })
    return () => { cancelled = true }
  }, [token])

  if (state.loading) {
    return <PublicFullAnalysisLoading />
  }

  // A render-gate rejection (report.rendered === false) reaches this
  // page only if the cycle regressed after the share link was created
  // (crawl reset, etc.) — the backend already 404s that case the same
  // as an unknown token (public_full_analysis.py), so state.report is
  // never non-null with rendered === false here; the `!state.report?.
  // rendered` check is defensive, not a case this page expects to hit.
  if (state.error || !state.report?.rendered) {
    const rateLimited = state.error?.status === 429
    return (
      <ReportNotFoundCard
        heading={rateLimited ? "Too many requests" : "We couldn't find this report"}
        body={
          rateLimited
            ? 'This link has been opened too many times in a short period — please try again shortly.'
            : 'This link may be mistyped, revoked, or no longer available.'
        }
        ctaLabel="Go to parleo.io"
        onCta={() => { window.location.href = 'https://parleo.io' }}
      />
    )
  }

  return <FullAnalysisReport cycleCode={state.report.cycle_code} report={state.report} readOnly shareToken={token} />
}
