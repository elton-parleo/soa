import { useState } from 'react'
import CycleDashboard   from './components/CycleDashboard.jsx'
import NewCycleWizard   from './components/NewCycleWizard.jsx'
import EntityRegistry   from './components/EntityRegistry.jsx'
import MetricsDashboard from './components/MetricsDashboard.jsx'

export default function App() {
  const [view,          setView]          = useState('dashboard')
  const [selectedCycle, setSelectedCycle] = useState(null)

  if (view === 'wizard') {
    return (
      <NewCycleWizard
        onComplete={() => setView('dashboard')}
        onCancel={() => setView('dashboard')}
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
