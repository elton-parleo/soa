import { useState } from 'react'
import CycleDashboard from './components/CycleDashboard.jsx'
import NewCycleWizard from './components/NewCycleWizard.jsx'
import EntityRegistry from './components/EntityRegistry.jsx'

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

  return (
    <CycleDashboard
      onNewCycle={() => setView('wizard')}
      onNavigate={(v) => setView(v)}
      onViewCycle={(code) => {
        setSelectedCycle(code)
        // placeholder — future detail view
      }}
    />
  )
}
