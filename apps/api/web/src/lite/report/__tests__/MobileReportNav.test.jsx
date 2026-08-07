/**
 * RM1: the phone rail replacement — summary block, sticky bar, and
 * sections sheet. The sheet's open/close/jump behavior and the active-
 * section highlighting are pure React state + DOM, fully testable in
 * jsdom; the sticky bar's scroll-triggered reveal depends on a real
 * IntersectionObserver intersection, which jsdom's stub (src/test-
 * setup.js) never fires — that half was verified live against the dev
 * server instead (see the PR description), and here we only assert
 * MobileStickyBar renders its two states correctly given a `visible`
 * prop, not that the observer wiring flips it at the right scroll
 * position.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, fireEvent } from '@testing-library/react'
import '@testing-library/jest-dom'

import { ReportSummaryBlock, MobileStickyBar, SectionsSheet, MobileReportNav } from '../MobileReportNav.jsx'

function _report(overrides = {}) {
  return {
    brand_icon_url: null,
    store_domain: 'acme.com',
    composite: 62,
    pillars: {
      state: 'scored',
      verdict: 'agent_ready',
      visibility: { dimensions: [] },
      accessibility: { dimensions: [] },
      true_value: { dimensions: [] },
    },
    ...overrides,
  }
}

describe('ReportSummaryBlock', () => {
  it('renders brand mark, name, composite score, and verdict chip', () => {
    const { getByText } = render(<ReportSummaryBlock report={_report()} primaryEntityName="Acme Co" summaryRef={{ current: null }} />)
    expect(getByText('Acme Co')).toBeInTheDocument()
    expect(getByText('62')).toBeInTheDocument()
    expect(getByText('/100')).toBeInTheDocument()
  })

  it('omits the verdict chip when the run state is not scored — no fabricated readiness claim', () => {
    const { queryByText } = render(
      <ReportSummaryBlock report={_report({ pillars: { ...( _report().pillars), state: 'unverified' } })} primaryEntityName="Acme Co" summaryRef={{ current: null }} />
    )
    expect(queryByText('Agent-ready')).not.toBeInTheDocument()
    expect(queryByText('Not agent-ready')).not.toBeInTheDocument()
  })

  it('renders an em dash, not a fabricated number, when composite is null', () => {
    const { getByText } = render(<ReportSummaryBlock report={_report({ composite: null })} primaryEntityName="Acme Co" summaryRef={{ current: null }} />)
    expect(getByText('—')).toBeInTheDocument()
  })
})

describe('MobileStickyBar', () => {
  it('carries the --visible modifier class only when told to', () => {
    const { container, rerender } = render(
      <MobileStickyBar report={_report()} primaryEntityName="Acme Co" visible={false} sheetOpen={false} onToggleSheet={() => {}} />
    )
    expect(container.querySelector('.lite-report-mobile-stickybar').className).not.toMatch(/--visible/)

    rerender(<MobileStickyBar report={_report()} primaryEntityName="Acme Co" visible sheetOpen={false} onToggleSheet={() => {}} />)
    expect(container.querySelector('.lite-report-mobile-stickybar').className).toMatch(/--visible/)
  })

  it('the Sections button reflects sheetOpen via aria-expanded and calls onToggleSheet', () => {
    const onToggleSheet = vi.fn()
    const { getByRole } = render(
      <MobileStickyBar report={_report()} primaryEntityName="Acme Co" visible sheetOpen={false} onToggleSheet={onToggleSheet} />
    )
    const btn = getByRole('button', { name: /Sections/ })
    expect(btn).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(btn)
    expect(onToggleSheet).toHaveBeenCalledTimes(1)
  })
})

describe('SectionsSheet', () => {
  it('renders null when closed', () => {
    const { container } = render(<SectionsSheet report={_report()} exposure={1000} active="score" open={false} onClose={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('lists every nav item with its score, score/viz/acc/tv/fix/truesync/exp — the same set the desktop rail shows', () => {
    const { getByText } = render(<SectionsSheet report={_report()} exposure={1000} active="score" open onClose={() => {}} />)
    expect(getByText('Score')).toBeInTheDocument()
    expect(getByText('Visibility')).toBeInTheDocument()
    expect(getByText('Accessibility')).toBeInTheDocument()
    expect(getByText('True Value')).toBeInTheDocument()
    expect(getByText('Ranked fixes')).toBeInTheDocument()
    expect(getByText('The fix')).toBeInTheDocument()
    expect(getByText('Exposure')).toBeInTheDocument()
  })

  it('highlights the active section with the --on modifier and no other', () => {
    const { container } = render(<SectionsSheet report={_report()} exposure={1000} active="tv" open onClose={() => {}} />)
    const items = container.querySelectorAll('.lite-report-mobile-sheet-item')
    const on = Array.from(items).filter((i) => i.className.includes('--on'))
    expect(on).toHaveLength(1)
    expect(on[0].getAttribute('href')).toBe('#tv')
  })

  it('closes on overlay click, closes on the close button, and does NOT close when clicking inside the sheet itself', () => {
    const onClose = vi.fn()
    const { container, getByLabelText } = render(<SectionsSheet report={_report()} exposure={1000} active="score" open onClose={onClose} />)

    fireEvent.click(container.querySelector('.lite-report-mobile-sheet'))
    expect(onClose).not.toHaveBeenCalled()

    fireEvent.click(container.querySelector('.lite-report-mobile-sheet-overlay'))
    expect(onClose).toHaveBeenCalledTimes(1)

    onClose.mockClear()
    fireEvent.click(getByLabelText('Close sections'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('tapping a section item closes the sheet (the actual scroll is verified live, not in jsdom)', () => {
    const onClose = vi.fn()
    const { getByText } = render(<SectionsSheet report={_report()} exposure={1000} active="score" open onClose={onClose} />)
    fireEvent.click(getByText('True Value'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('MobileReportNav', () => {
  it('renders the summary block, the sticky bar, and no sheet by default', () => {
    const { container } = render(<MobileReportNav report={_report()} primaryEntityName="Acme Co" exposure={1000} active="score" />)
    expect(container.querySelector('.lite-report-mobile-summary')).toBeInTheDocument()
    expect(container.querySelector('.lite-report-mobile-stickybar')).toBeInTheDocument()
    expect(container.querySelector('.lite-report-mobile-sheet-overlay')).not.toBeInTheDocument()
  })

  it('opening the sticky bar\'s Sections button renders the sheet', () => {
    const { container, getByRole } = render(<MobileReportNav report={_report()} primaryEntityName="Acme Co" exposure={1000} active="score" />)
    fireEvent.click(getByRole('button', { name: /Sections/ }))
    expect(container.querySelector('.lite-report-mobile-sheet-overlay')).toBeInTheDocument()
  })
})
