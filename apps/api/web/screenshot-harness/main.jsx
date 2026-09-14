import React from 'react'
import { createRoot } from 'react-dom/client'
import CreateStudyModal from '../src/components/CreateStudyModal.jsx'
createRoot(document.getElementById('root')).render(
  <CreateStudyModal open onClose={() => {}} onCreated={() => {}} />,
)
