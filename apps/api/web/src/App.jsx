import { useState, useEffect } from 'react'
import { AuthProvider, useAuth } from './AuthContext.jsx'
import LoginPage      from './components/LoginPage.jsx'
import CycleDashboard from './components/CycleDashboard.jsx'
import NewCycleWizard from './components/NewCycleWizard.jsx'
import EntityRegistry from './components/EntityRegistry.jsx'
import MetricsDashboard from './components/MetricsDashboard.jsx'

// ─── Read initial view from URL hash on page load ────────────────────────────
function getInitialView() {
  const hash = window.location.hash.replace('#', '')
  const validViews = ['dashboard', 'wizard', 'entities', 'metrics']
  return validViews.includes(hash) ? hash : 'dashboard'
}

// ─── Inner app — reads auth state and routes accordingly ─────────────────────
function AppContent() {
  const { session } = useAuth()
  const [view,          setView]          = useState(getInitialView)
  const [selectedCycle, setSelectedCycle] = useState(null)

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

// ─── Root — wraps everything in AuthProvider ─────────────────────────────────
export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  )
}
