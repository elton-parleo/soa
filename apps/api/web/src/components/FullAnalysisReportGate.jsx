// FullAnalysisReportGate — Full Analysis coexistence, Phase 4: the
// render-gate itself. A cycle renders FullAnalysisReport.jsx only when
// it has an attached, complete crawl (the backend's own discriminator —
// see app/routers/full_analysis.py::get_full_analysis_report); every
// other cycle falls back to the classic MetricsDashboard.jsx, untouched.
// This is the ONE place that decision gets made — CycleDashboard's
// "view cycle" link and any other entry point route here rather than
// duplicating the check.
import React, { useEffect, useState } from 'react'
import { api } from '../api.js'
import FullAnalysisReport from './FullAnalysisReport.jsx'
import MetricsDashboard from './MetricsDashboard.jsx'

export default function FullAnalysisReportGate({ cycleCode, onNavigate, onViewResponses, onViewActions }) {
  const [state, setState] = useState({ loading: true, report: null, error: null })

  useEffect(() => {
    let cancelled = false
    setState({ loading: true, report: null, error: null })
    api.getFullAnalysisReport(cycleCode)
      .then(report => { if (!cancelled) setState({ loading: false, report, error: null }) })
      .catch(err => { if (!cancelled) setState({ loading: false, report: null, error: err.message }) })
    return () => { cancelled = true }
  }, [cycleCode])

  if (state.loading) {
    return <div style={{ padding: 48, textAlign: 'center', color: '#64748B', fontSize: 14 }}>Loading report…</div>
  }

  // No crawl attached, not complete yet, error resolving the gate, or
  // any other non-rendered state — fall back to the classic dashboard.
  // The classic report is always a safe fallback: it never depends on
  // the gate having succeeded.
  if (state.error || !state.report?.rendered) {
    return (
      <MetricsDashboard
        cycleCode={cycleCode}
        onNavigate={onNavigate}
        onViewResponses={onViewResponses}
        onViewActions={onViewActions}
      />
    )
  }

  return (
    <FullAnalysisReport cycleCode={cycleCode} report={state.report} onNavigate={onNavigate} />
  )
}
