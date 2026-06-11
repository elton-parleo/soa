import { useState } from 'react'
import { AuthProvider, useAuth } from './AuthContext.jsx'
import LoginPage      from './components/LoginPage.jsx'
import CycleDashboard from './components/CycleDashboard.jsx'
import NewCycleWizard from './components/NewCycleWizard.jsx'
import EntityRegistry from './components/EntityRegistry.jsx'
import MetricsDashboard from './components/MetricsDashboard.jsx'

// ─── Inner app — reads auth state and routes accordingly ─────────────────────
function AppContent() {
  const { session } = useAuth()
  const [view,          setView]          = useState('dashboard')
  const [selectedCycle, setSelectedCycle] = useState(null)

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
        onComplete={() => setView('dashboard')}
        onCancel={() => setView('dashboard')}
        onNavigate={(v) => setView(v)}
      />
    )
  }

  if (view === 'entities') {
    return (
      <EntityRegistry
        onNavigate={(v) => setView(v)}
      />
    )
  }

  if (view === 'metrics') {
    return (
      <MetricsDashboard
        cycleCode={selectedCycle}
        onNavigate={(v, params) => {
          if (v === 'metrics' && params?.cycleCode) {
            setSelectedCycle(params.cycleCode)
          } else {
            setView(v)
          }
        }}
      />
    )
  }

  // Default: dashboard
  return (
    <CycleDashboard
      onNewCycle={() => setView('wizard')}
      onNavigate={(v) => setView(v)}
      onViewCycle={(code) => {
        setSelectedCycle(code)
        setView('metrics')
      }}
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
