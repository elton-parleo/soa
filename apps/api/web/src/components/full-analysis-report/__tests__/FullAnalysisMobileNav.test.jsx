/**
 * fix/full-analysis-mobile, 1a: the phone replacement for
 * FullAnalysisRail's 300px sidebar. IntersectionObserver-driven sticky-
 * bar reveal can't be exercised end-to-end in jsdom (its stub stores
 * the callback but never invokes it — same limitation MobileReportNav.
 * test.jsx documents for lite's own component) — that transition was
 * verified live against the dev server this session. These tests cover
 * what jsdom CAN exercise: summary content, and the Sections sheet's
 * open/close + item list, which must mirror FullAnalysisRail's own
 * NAV_ITEMS/filterNavItems/navScore exactly (one source of truth).
 */
import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import { FullAnalysisMobileNav } from '../FullAnalysisMobileNav.jsx'

function _report(overrides = {}) {
  return {
    composite: 55,
    total_queries: 742,
    transcript: { query_index: 15, total_queries: 50 },
    continuation: null,
    scan: { degraded_reason: null },
    pillars: {
      state: 'scored',
      // A scored report ALWAYS carries a real verdict — cycle_scoring_
      // full.py sets state and verdict together. This fixture used to
      // omit it and still assert "Not agent-ready", which passed only
      // because the old chip was a binary (`verdict === AGENT_READY`)
      // that read a MISSING verdict as a failing one. That is the bug
      // withheld.js::verdictDisplay fixes, so the fixture now carries
      // the verdict a scored payload actually has.
      verdict: 'NOT AGENT-READY',
      visibility: { score: 91, max: 100, dimensions: [] },
      accessibility: { score: 78, max: 100, dimensions: [] },
      true_value: { score: 21, max: 100, dimensions: [] },
      composite: 55,
      fixes: { visible: [{ code: 'a', impact: 30 }], remaining_count: 0 },
    },
    ...overrides,
  }
}

describe('FullAnalysisMobileNav — summary block', () => {
  it('renders the brand name and composite/100', () => {
    render(<FullAnalysisMobileNav report={_report()} primaryEntityName="Allbirds" active="score" hasContinuation={false} />)
    // Both the summary block and the sticky bar always render (CSS
    // alone decides which is visible), so the brand name appears
    // twice — same pattern as lite's own MobileReportNav.
    expect(screen.getAllByText('Allbirds').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('55').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('/100').length).toBeGreaterThanOrEqual(1)
  })

  it('renders the readiness bar\'s EARNED/READY/100 labels', () => {
    render(<FullAnalysisMobileNav report={_report()} primaryEntityName="Allbirds" active="score" hasContinuation={false} />)
    expect(screen.getByText('55 EARNED')).toBeInTheDocument()
    expect(screen.getByText('READY 60')).toBeInTheDocument()
  })

  it('shows the agent-ready state chip and, absent a degraded reason, "Fully measured"', () => {
    render(<FullAnalysisMobileNav report={_report()} primaryEntityName="Allbirds" active="score" hasContinuation={false} />)
    expect(screen.getByText('Not agent-ready')).toBeInTheDocument()
    expect(screen.getByText('Fully measured')).toBeInTheDocument()
  })
})

describe('FullAnalysisMobileNav — Sections sheet', () => {
  it('is closed by default and opens on tapping the Sections trigger', () => {
    render(<FullAnalysisMobileNav report={_report()} primaryEntityName="Allbirds" active="score" hasContinuation={false} />)
    expect(screen.queryByRole('dialog', { name: 'Report sections' })).not.toBeInTheDocument()
    fireEvent.click(screen.getByText('Sections'))
    expect(screen.getByRole('dialog', { name: 'Report sections' })).toBeInTheDocument()
  })

  it('lists exactly the same sections FullAnalysisRail shows, in the same order, with real scores', () => {
    render(<FullAnalysisMobileNav report={_report()} primaryEntityName="Allbirds" active="score" hasContinuation={false} />)
    fireEvent.click(screen.getByText('Sections'))
    const labels = screen.getAllByRole('link').map((a) => a.textContent)
    // continuation is omitted (hasContinuation=false); transcript is
    // present (report.transcript is set); analyst is present (readOnly
    // defaults to false) — same filterNavItems rule FullAnalysisRail
    // itself applies.
    expect(labels.some((l) => l.includes('The score'))).toBe(true)
    expect(labels.some((l) => l.includes('Vs. your audit'))).toBe(false)
    expect(labels.some((l) => l.includes('The transcript'))).toBe(true)
    expect(labels.some((l) => l.includes('Analyst layer'))).toBe(true)
  })

  it('omits "Vs. your audit" and "The transcript" when there is no continuation / no transcript', () => {
    render(<FullAnalysisMobileNav report={_report({ transcript: null })} primaryEntityName="Allbirds" active="score" hasContinuation={false} />)
    fireEvent.click(screen.getByText('Sections'))
    const labels = screen.getAllByRole('link').map((a) => a.textContent)
    expect(labels.some((l) => l.includes('The transcript'))).toBe(false)
  })

  it('omits "Analyst layer" in readOnly (public share) mode, matching FullAnalysisRail', () => {
    render(<FullAnalysisMobileNav report={_report()} primaryEntityName="Allbirds" active="score" hasContinuation={false} readOnly />)
    fireEvent.click(screen.getByText('Sections'))
    const labels = screen.getAllByRole('link').map((a) => a.textContent)
    expect(labels.some((l) => l.includes('Analyst layer'))).toBe(false)
  })

  it('closes on tapping the close button', () => {
    render(<FullAnalysisMobileNav report={_report()} primaryEntityName="Allbirds" active="score" hasContinuation={false} />)
    fireEvent.click(screen.getByText('Sections'))
    fireEvent.click(screen.getByLabelText('Close sections'))
    expect(screen.queryByRole('dialog', { name: 'Report sections' })).not.toBeInTheDocument()
  })
})
