/**
 * FixesTable — the "RANKED IN THE FULL ANALYSIS" upsell block (shown
 * whenever fixes.remaining_count > 0) hardcoded "24-query sample" —
 * wrong when this same component renders INSIDE the Full Analysis
 * report itself (reused verbatim from FullAnalysisReport.jsx), where
 * the real cycle can run far more than 24 queries. queryCount sources
 * it from the payload instead, defaulting to the lite constant.
 */
import React from 'react'
import { render, fireEvent, screen } from '@testing-library/react'
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

// ─── 3c: sub_fixes (expandable) and also_worth_doing (strip) ─────────────
//
// Both are new, OPTIONAL fields on the same fixes payload lite's own
// _build_fixes_section never sets — every test in the section above
// (lite's exact real-world shape, no sub_fixes/also_worth_doing keys)
// still passes unchanged, proving the guard. These tests cover the
// Full Analysis shape where the fields ARE present.

function _reportWithSubFixes(subFixes) {
  return {
    pillars: {
      state: 'scored',
      fixes: {
        visible: [{ code: 'catalog_context', name: 'Catalog Context', fix_human: 'Do the thing', impact: 8, fix_owner: 'ENG', sub_fixes: subFixes }],
        remaining_count: 0,
      },
    },
    scan: { degraded_reason: null },
  }
}

describe('FixesTable — expandable sub-fixes', () => {
  it('renders no expand toggle when a row has an empty sub_fixes list', () => {
    render(<FixesTable report={_reportWithSubFixes([])} open onToggle={() => {}} brandName="Acme" reportToken={null} />)
    expect(screen.queryByRole('button', { name: /specific checks/ })).not.toBeInTheDocument()
  })

  it('renders a collapsed toggle for a row with sub_fixes, and expands to show each one on click', () => {
    const subFixes = [
      { code: 'completeness', label: 'Complete Product+Offer JSON-LD', evidence: null, fix_owner: 'ENG' },
      { code: 'identifiers', label: 'Expose a gtin/mpn/sku identifier', evidence: '0/5 pages', fix_owner: 'ENG' },
    ]
    render(<FixesTable report={_reportWithSubFixes(subFixes)} open onToggle={() => {}} brandName="Acme" reportToken={null} />)

    expect(screen.queryByText('Complete Product+Offer JSON-LD')).not.toBeInTheDocument()
    const toggle = screen.getByRole('button', { name: /Show the 2 specific checks/ })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')

    fireEvent.click(toggle)
    expect(screen.getByText('Complete Product+Offer JSON-LD')).toBeInTheDocument()
    expect(screen.getByText('Expose a gtin/mpn/sku identifier')).toBeInTheDocument()
    expect(screen.getByText(/0\/5 pages/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Hide the 2 specific checks/ })).toHaveAttribute('aria-expanded', 'true')
  })

  it('collapses again on a second click', () => {
    const subFixes = [{ code: 'completeness', label: 'Complete Product+Offer JSON-LD', evidence: null, fix_owner: 'ENG' }]
    render(<FixesTable report={_reportWithSubFixes(subFixes)} open onToggle={() => {}} brandName="Acme" reportToken={null} />)
    const toggle = screen.getByRole('button', { name: /specific checks/ })
    fireEvent.click(toggle)
    expect(screen.getByText('Complete Product+Offer JSON-LD')).toBeInTheDocument()
    fireEvent.click(toggle)
    expect(screen.queryByText('Complete Product+Offer JSON-LD')).not.toBeInTheDocument()
  })

  it('never renders an "impact" or "points" figure on a sub-fix row — no invented point split', () => {
    const subFixes = [{ code: 'completeness', label: 'Complete Product+Offer JSON-LD', evidence: null, fix_owner: 'ENG' }]
    render(<FixesTable report={_reportWithSubFixes(subFixes)} open onToggle={() => {}} brandName="Acme" reportToken={null} />)
    fireEvent.click(screen.getByRole('button', { name: /specific checks/ }))
    const subFixRow = screen.getByText('Complete Product+Offer JSON-LD').closest('.lite-fixrow-subfixes')
    expect(subFixRow.textContent).not.toMatch(/pts/)
  })
})

function _reportWithAlsoWorthDoing(alsoWorthDoing) {
  return {
    pillars: {
      state: 'scored',
      fixes: {
        visible: [{ code: 'agent_access', name: 'Fix', fix_human: 'Do the thing', impact: 12, fix_owner: 'ENG' }],
        remaining_count: 0,
        also_worth_doing: alsoWorthDoing,
      },
    },
    scan: { degraded_reason: null },
  }
}

describe('FixesTable — "Also worth doing" cross-cutting strip', () => {
  it('renders nothing when also_worth_doing is absent (lite\'s own payload shape)', () => {
    render(<FixesTable report={_report()} open onToggle={() => {}} brandName="Acme" reportToken="tok" />)
    expect(screen.queryByText('ALSO WORTH DOING')).not.toBeInTheDocument()
  })

  it('renders nothing when also_worth_doing is an empty list (the common case today)', () => {
    render(<FixesTable report={_reportWithAlsoWorthDoing([])} open onToggle={() => {}} brandName="Acme" reportToken={null} />)
    expect(screen.queryByText('ALSO WORTH DOING')).not.toBeInTheDocument()
  })

  it('renders each cross-cutting fix, unpointed, linked to its report section when one is known', () => {
    const alsoWorthDoing = [
      { play_id: 'VIS-01', pillar: 'Visibility', failure_mode: 'Absent from category queries.', play_text: 'Fix your schema markup.', owner: 'joint', section_anchor: 'viz' },
      { play_id: 'FID-02', pillar: 'Fidelity', failure_mode: 'Third-party listings drift.', play_text: 'Audit reseller PDPs.', owner: 'retailer', section_anchor: null },
    ]
    render(<FixesTable report={_reportWithAlsoWorthDoing(alsoWorthDoing)} open onToggle={() => {}} brandName="Acme" reportToken={null} />)

    expect(screen.getByText('ALSO WORTH DOING')).toBeInTheDocument()
    const linked = screen.getByRole('link', { name: 'Fix your schema markup.' })
    expect(linked).toHaveAttribute('href', '#viz')
    expect(screen.getByText('Audit reseller PDPs.')).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Audit reseller PDPs.' })).not.toBeInTheDocument()
    expect(screen.getByText('joint')).toBeInTheDocument()
    expect(screen.getByText('retailer')).toBeInTheDocument()
    // Unpointed by design — no "+N pts"/impact figure anywhere in the strip.
    const strip = screen.getByText('ALSO WORTH DOING').closest('div')
    expect(strip.textContent).not.toMatch(/pts/)
  })
})
