import React from 'react'
import { createRoot } from 'react-dom/client'
import CreateStudyModal from '../src/components/CreateStudyModal.jsx'
import MerchantCommandCenter from '../src/components/MerchantCommandCenter.jsx'
import CustomerSetupWizard from '../src/components/customer-setup/CustomerSetupWizard.jsx'
import { CUSTOMERS } from './stub-customers.js'

// ?view=study (default) | commandcenter | wizard
const view = new URLSearchParams(window.location.search).get('view') || 'study'

function App() {
  if (view === 'commandcenter') return <MerchantCommandCenter onNavigate={() => {}} />
  if (view === 'wizard') {
    return (
      <CustomerSetupWizard open customers={CUSTOMERS.customers}
        onClose={() => {}} onDone={() => {}} />
    )
  }
  return <CreateStudyModal open onClose={() => {}} onCreated={() => {}} />
}

createRoot(document.getElementById('root')).render(<App />)
