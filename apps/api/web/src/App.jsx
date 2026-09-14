import { useState, useEffect } from 'react'
import { AuthProvider, useAuth } from './AuthContext.jsx'
import LoginPage        from './components/LoginPage.jsx'
import CycleDashboard   from './components/CycleDashboard.jsx'
import NewCycleWizard   from './components/NewCycleWizard.jsx'
import NewCycleFlow     from './components/NewCycleFlow.jsx'
import FullAnalysisReportGate from './components/FullAnalysisReportGate.jsx'
import EntityRegistry   from './components/EntityRegistry.jsx'
import ResponseExplorer  from './components/ResponseExplorer.jsx'
import ActionsPage       from './components/ActionsPage.jsx'
import StudyLibrary      from './components/StudyLibrary.jsx'
import StudyDetail      from './components/StudyDetail.jsx'
import MerchantCommandCenter from './components/MerchantCommandCenter.jsx'
import LiteWidget        from './lite/LiteWidget.jsx'
import LandingPage       from './lite/LandingPage.jsx'
import BotsPage          from './lite/BotsPage.jsx'
import PublicFullAnalysisPage from './components/PublicFullAnalysisPage.jsx'
import { isAuditHost, stripAuditBase } from './lite/publicUrls.js'

// ─── Read initial view from URL hash on page load ────────────────────────────
function getInitialView() {
  const hash = window.location.hash.replace('#', '')
  const validViews = [
    'dashboard', 'wizard', 'new-cycle',
    'entities', 'metrics',
    'studies', 'study-detail',
    'responses', 'actions',
    'command-center',
  ]
  return validViews.includes(hash) ? hash : 'dashboard'
}

// ─── Inner app — reads auth state and routes accordingly ─────────────────────
function AppContent() {
  const { session } = useAuth()
  const [view,          setView]          = useState(getInitialView)
  const [selectedCycle, setSelectedCycle] = useState(null)
  const [selectedStudy, setSelectedStudy] = useState(null)
  const [selectedRunId, setSelectedRunId] = useState(null)
  const [selectedAuditToken, setSelectedAuditToken] = useState(null)

  // Replace the initial history entry with a proper state object so
  // popstate fires correctly on the first back press.
  useEffect(() => {
    window.history.replaceState(
      { view: 'dashboard' },
      '',
      '/',
    )
  }, [])

  // Listen for browser back/forward button presses.
  useEffect(() => {
    function handlePopState(event) {
      if (event.state?.view) {
        setView(event.state.view)
        if (event.state.cycleCode !== undefined) {
          setSelectedCycle(event.state.cycleCode)
        }
        if (event.state.studyType !== undefined) {
          setSelectedStudy(event.state.studyType)
        }
        setSelectedRunId(event.state.runId ?? null)
        setSelectedAuditToken(event.state.auditToken ?? null)
      } else {
        // No state — at the initial history entry: go to dashboard.
        setView('dashboard')
      }
    }

    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  // Push a history entry AND update React state.
  // Hash-based URLs so Vercel's SPA catch-all serves index.html for all paths.
  function navigateTo(newView, params = {}) {
    window.history.pushState(
      { view: newView, ...params },
      '',
      newView === 'dashboard' ? '/' : `/#${newView}`,
    )
    setView(newView)
    if (params.cycleCode !== undefined) {
      setSelectedCycle(params.cycleCode)
    }
    if (params.studyType !== undefined) {
      setSelectedStudy(params.studyType)
    }
    setSelectedRunId(params.runId ?? null)
    setSelectedAuditToken(params.auditToken ?? null)
  }

  // Still loading session from storage — prevent flash of login page
  if (session === undefined) {
    return (
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        background: '#F1F5F9',
        fontFamily: "'DM Sans', sans-serif",
        fontSize: 14,
        color: '#64748B',
      }}>
        Loading...
      </div>
    )
  }

  // Not authenticated — show login page
  if (!session) {
    return <LoginPage />
  }

  // Authenticated — show the app
  if (view === 'wizard') {
    return (
      <NewCycleWizard
        onComplete={() => navigateTo('dashboard')}
        onCancel={() => navigateTo('dashboard')}
        onNavigate={(v) => navigateTo(v)}
      />
    )
  }

  // Full Analysis coexistence, Phase 2: the 3-step flow is the default
  // "+ New Cycle" destination (see CycleDashboard below); the classic
  // wizard stays reachable from its own "advanced setup" link.
  if (view === 'new-cycle') {
    return (
      <NewCycleFlow
        auditToken={selectedAuditToken}
        onComplete={() => navigateTo('dashboard')}
        onCancel={() => navigateTo('dashboard')}
        onNavigate={(v, params) => navigateTo(v, params)}
      />
    )
  }

  if (view === 'entities') {
    return (
      <EntityRegistry
        onNavigate={(v) => navigateTo(v)}
      />
    )
  }

  if (view === 'metrics') {
    // Full Analysis coexistence, Phase 4: the render-gate decides
    // between the new Full Analysis report and the classic
    // MetricsDashboard for this cycle — see FullAnalysisReportGate.jsx.
    // MetricsDashboard.jsx itself is unchanged; the gate renders it
    // directly (same props) whenever the discriminator says to.
    return (
      <FullAnalysisReportGate
        cycleCode={selectedCycle}
        onNavigate={(v, params) => {
          if (v === 'metrics' && params?.cycleCode) {
            navigateTo('metrics', { cycleCode: params.cycleCode })
          } else {
            navigateTo(v)
          }
        }}
        onViewResponses={() => navigateTo('responses', { cycleCode: selectedCycle })}
        onViewActions={() => navigateTo('actions', { cycleCode: selectedCycle })}
      />
    )
  }

  if (view === 'responses') {
    return (
      <ResponseExplorer
        cycleCode={selectedCycle}
        initialRunId={selectedRunId}
        onNavigate={(v, params) => {
          if (v === 'metrics') {
            navigateTo('metrics', { cycleCode: params?.cycleCode || selectedCycle })
          } else {
            navigateTo(v, params)
          }
        }}
      />
    )
  }

  if (view === 'actions') {
    return (
      <ActionsPage
        cycleCode={selectedCycle}
        onNavigate={(v, params) => {
          if (v === 'metrics' || v === 'responses') {
            navigateTo(v, { cycleCode: params?.cycleCode || selectedCycle, ...params })
          } else {
            navigateTo(v, params)
          }
        }}
      />
    )
  }

  if (view === 'command-center') {
    return (
      <MerchantCommandCenter
        onNavigate={(v) => navigateTo(v)}
      />
    )
  }

  if (view === 'studies') {
    return (
      <StudyLibrary
        onNavigate={navigateTo}
        onSelectStudy={(studyType) => {
          setSelectedStudy(studyType)
          navigateTo('study-detail', { studyType })
        }}
      />
    )
  }

  if (view === 'study-detail') {
    return (
      <StudyDetail
        studyType={selectedStudy}
        onNavigate={(v, params) => {
          if (v === 'studies') {
            navigateTo('studies')
          } else {
            navigateTo(v, params)
          }
        }}
      />
    )
  }

  // Default: dashboard
  return (
    <CycleDashboard
      onNewCycle={() => navigateTo('new-cycle')}
      onNavigate={(v) => navigateTo(v)}
      onViewCycle={(code) => navigateTo('metrics', { cycleCode: code })}
    />
  )
}

// ─── Pathname routing for the public lite/audit/report surfaces ──────────────
// Stage 9: unlike AppContent's hash-based view state (unaffected, reads
// the hash independently), the public pages need real pathname changes
// so a submit on the landing page can land on /r/{token} (audit host) or
// /report/{token} (/lite embed) without a full reload (U2) — pushState
// alone doesn't re-render React, so this pairs it with a pathname state
// + a popstate listener for back/forward.
function useLitePathname() {
  const [pathname, setPathname] = useState(window.location.pathname)

  useEffect(() => {
    function onPopState() {
      setPathname(window.location.pathname)
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [])

  function navigate(path) {
    window.history.pushState({}, '', path)
    // Read the pathname back off history rather than trusting the
    // argument: callers may pass a path WITH a query string (see
    // withOppref in lite/openaiPixel.js), and this state feeds the
    // route matching below — where '/r/' + '/s/' slice the token
    // straight out of it. Storing the raw argument would make
    // navigate('/r/tok?oppref=x') yield the token "tok?oppref=x" and
    // 404 the report, with a perfectly correct-looking address bar.
    setPathname(window.location.pathname)
  }

  return [pathname, navigate]
}

// Non-audit paths on the audit surface must 404, not redirect (H1) —
// the edge (vercel.json) already returns a real HTTP 404 for everything
// but the landing, '/r/*' and '/s/*' (under the surface's base path,
// wherever that is) before the SPA bundle even loads; this is a
// client-side backstop for the same rule (e.g. local dev without the
// edge config in front of it).
function AuditHostNotFound() {
  return (
    <div className="lite-root">
      <div className="lite-shell" style={{ maxWidth: 480 }}>
        <p className="lite-body">Not found.</p>
      </div>
    </div>
  )
}

// ─── Root — wraps everything in AuthProvider ─────────────────────────────────
export default function App() {
  const [pathname, navigate] = useLitePathname()

  // audit.parleo.io migration (H1), extended for parleo.io/audit: the
  // audit surface serves ONLY the public audit tool — landing at '/',
  // report/status at '/r/<token>' and '/s/<id>' (both are the same
  // token-driven LiteWidget state machine; 'status' isn't a distinct
  // internal route, see LiteWidget.jsx). No other path on this surface
  // reaches the authed dashboard, /lite, or /bots — checked first and
  // exclusively, before any other routing.
  //
  // Matched against the base-stripped path, not the raw pathname, so
  // the same three routes hold whether the surface is served at the
  // root of audit.parleo.io or under parleo.io/audit (stripAuditBase
  // is the identity under the default build, and reads both '/audit'
  // and '/audit/' as '/' under the prefixed one). Every navigation
  // back out goes through auditPath() at its own call site.
  if (isAuditHost()) {
    const auditRoute = stripAuditBase(pathname)
    if (auditRoute === '/') {
      return <LandingPage navigate={navigate} />
    }
    if (auditRoute.startsWith('/r/') || auditRoute.startsWith('/s/')) {
      const token = decodeURIComponent(auditRoute.slice(3))
      return <LiteWidget urlToken={token} navigate={navigate} />
    }
    return <AuditHostNotFound />
  }

  // SoA Lite: a public, unauthenticated widget iframed/linked from the
  // marketing site. Checked before AuthProvider mounts so this path never
  // touches Supabase session state, the login gate, or any authed-app
  // global state — see lite/LiteWidget.jsx's module docstring.
  if (pathname === '/lite') {
    return <LiteWidget navigate={navigate} />
  }

  // W4: ParleoAuditBot's public documentation page — same pre-auth,
  // standalone treatment as /lite above.
  if (pathname === '/bots') {
    return <BotsPage />
  }

  // Stage 9: unique, revisitable report URLs. /report alone (no token
  // segment) still renders LiteWidget with an empty urlToken so it goes
  // straight to the not-found state (U1) rather than falling through to
  // the authed login gate, which would be a confusing experience for a
  // visitor following a broken public link.
  if (pathname === '/report' || pathname.startsWith('/report/')) {
    const token = pathname === '/report' ? '' : decodeURIComponent(pathname.slice('/report/'.length))
    return <LiteWidget urlToken={token} navigate={navigate} />
  }

  // Shareable Full Analysis reports: /fa/{token}, mirroring /report/
  // {token}'s naming and same pre-auth treatment — a visitor opening a
  // shared link has no session either. Not host-gated like the audit
  // tool's /r/, /s/ (isAuditHost() above) — Full Analysis lives on this
  // app's own single host, not the dedicated audit.parleo.io host, so
  // it needs no host branch of its own.
  if (pathname === '/fa' || pathname.startsWith('/fa/')) {
    const token = pathname === '/fa' ? '' : decodeURIComponent(pathname.slice('/fa/'.length))
    return <PublicFullAnalysisPage token={token} />
  }

  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}
