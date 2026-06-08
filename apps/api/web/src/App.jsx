import { useState } from 'react'
import CycleDashboard from './components/CycleDashboard.jsx'
import NewCycleWizard from './components/NewCycleWizard.jsx'

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

  return (
    <CycleDashboard
      onNewCycle={() => setView('wizard')}
      onViewCycle={(code) => {
        setSelectedCycle(code)
        // placeholder — future detail view
      }}
    />
  )
}
