/**
 * FixesTable — the "RANKED IN THE FULL ANALYSIS" upsell block (shown
 * whenever fixes.remaining_count > 0) hardcoded "24-query sample" —
 * wrong when this same component renders INSIDE the Full Analysis
 * report itself (reused verbatim from FullAnalysisReport.jsx), where
 * the real cycle can run far more than 24 queries. queryCount sources
 * it from the payload instead, defaulting to the lite constant.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import '@testing-library/jest-dom'

import { FixesTable } from '../FixesTable.jsx'

vi.mock('../../analytics.js', () => ({ track: vi.fn() }))

function _report() {
  return {
    pillars: {
      state: 'scored',
      fixes: {
        visible: [{ code: 'agent_access', name: 'Fix', fix_human: 'Do the thing', impact: 12, fix_owner: 'ENG' }],
        remaining_count: 2,
      },
    },
    scan: { degraded_reason: null },
  }
}

describe('FixesTable — query count sourced from the payload', () => {
  it('defaults to the lite query count (24) when no queryCount prop is passed', () => {
    render(<FixesTable report={_report()} open onToggle={() => {}} brandName="Acme" reportToken="tok" />)
    expect(screen.getByText(/Ranked across your full catalog instead of a 24-query sample/)).toBeInTheDocument()
  })

  it('renders the real cycle query count when passed (Full Analysis, e.g. 50 queries)', () => {
    render(<FixesTable report={_report()} open onToggle={() => {}} brandName="Acme" reportToken={null} queryCount={50} />)
    expect(screen.getByText(/Ranked across your full catalog instead of a 50-query sample/)).toBeInTheDocument()
    expect(screen.queryByText(/24-query sample/)).not.toBeInTheDocument()
  })
})
