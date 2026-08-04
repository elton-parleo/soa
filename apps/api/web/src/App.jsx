import { useState, useEffect } from 'react'
import { AuthProvider, useAuth } from './AuthContext.jsx'
import LoginPage        from './components/LoginPage.jsx'
import CycleDashboard   from './components/CycleDashboard.jsx'
import NewCycleWizard   from './components/NewCycleWizard.jsx'
import EntityRegistry   from './components/EntityRegistry.jsx'
import MetricsDashboard  from './components/MetricsDashboard.jsx'
import ResponseExplorer  from './components/ResponseExplorer.jsx'
import ActionsPage       from './components/ActionsPage.jsx'
import StudyLibrary      from './components/StudyLibrary.jsx'
import StudyDetail      from './components/StudyDetail.jsx'
import LiteWidget        from './lite/LiteWidget.jsx'
import LandingPage       from './lite/LandingPage.jsx'
import BotsPage          from './lite/BotsPage.jsx'

// ─── Read initial view from URL hash on page load ────────────────────────────
function getInitialView() {
  const hash = window.location.hash.replace('#', '')
  const validViews = [
    'dashboard', 'wizard',
    'entities', 'metrics',
    'studies', 'study-detail',
    'responses', 'actions',
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

  if (view === 'entities') {
    return (
      <EntityRegistry
        onNavigate={(v) => navigateTo(v)}
      />
    )
  }

  if (view === 'metrics') {
    return (
      <MetricsDashboard
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
      onNewCycle={() => navigateTo('wizard')}
      onNavigate={(v) => navigateTo(v)}
      onViewCycle={(code) => navigateTo('metrics', { cycleCode: code })}
    />
  )
}

// ─── Pathname routing for the public lite/scan/report surfaces ───────────────
// Stage 9: unlike AppContent's hash-based view state (unaffected, reads
// the hash independently), the public pages need real pathname changes
// so a submit on /scan can land on /report/{token} without a full
// reload (U2) — pushState alone doesn't re-render React, so this pairs
// it with a pathname state + a popstate listener for back/forward.
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
    setPathname(path)
  }

  return [pathname, navigate]
}

// ─── Root — wraps everything in AuthProvider ─────────────────────────────────
export default function App() {
  const [pathname, navigate] = useLitePathname()

  // SoA Lite: a public, unauthenticated widget iframed/linked from the
  // marketing site. Checked before AuthProvider mounts so this path never
  // touches Supabase session state, the login gate, or any authed-app
  // global state — see lite/LiteWidget.jsx's module docstring.
  if (pathname === '/lite') {
    return <LiteWidget navigate={navigate} />
  }

  // Parleo Scan landing page — same pre-auth, standalone treatment as
  // /lite (see above); /lite itself is untouched for existing embeds.
  if (pathname === '/scan') {
    return <LandingPage navigate={navigate} />
  }

  // W4: ParleoAuditBot's public documentation page — same pre-auth,
  // standalone treatment as /scan/lite above.
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

  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}
