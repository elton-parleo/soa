import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import '@testing-library/jest-dom'

import { LiteFullReport } from '../LiteFullReport.jsx'

function dim(code, name, score, max, overrides = {}) {
  return { code, name, score, max, evidence: [], fix: null, locked: false, linked: null, ...overrides }
}

const EIGHT_DIMENSIONS = [
  dim('F1', 'Agent Access', 8, 10),
  dim('F2', 'Catalog Context', 10, 15),
  dim('F3', 'Transaction Rails', 9, 10),
  dim('V1', 'Offer Legibility', 6, 15, { fix: 'add priceCurrency', locked: false }),
  dim('V2', 'Loyalty Surface', 6, 14, { fix: 'publish a rewards page', locked: false }),
  dim('V3', 'Member Value', 7, 14, { fix: 'expose member pricing', locked: false }),
  dim('V4', 'Value Rails', 4, 10, { fix: 'add priceValidUntil', locked: true }),
  dim('V5', 'Offer Integrity', 9, 12, { fix: 'stop fake was-prices', locked: true }),
]

const baseReport = {
  status: 'complete',
  locked: false,
  overall: [
    { name: 'Acme Co', role: 'primary', metrics: { som: 62.5, mention_rate: 50, position_index: 70, rsi: 1.2 } },
    { name: 'Rival Co', role: 'competitor', metrics: { som: 37.5, mention_rate: 30, position_index: 40, rsi: 0.4 } },
  ],
  by_stage: {
    'Research': [
      { name: 'Acme Co', role: 'primary', metrics: { mention_rate: 55 } },
      { name: 'Rival Co', role: 'competitor', metrics: { mention_rate: 25 } },
    ],
    'Awareness': [
      { name: 'Acme Co', role: 'primary', metrics: { mention_rate: 45 } },
      { name: 'Rival Co', role: 'competitor', metrics: { mention_rate: 35 } },
    ],
  },
  scan: {
    status: 'complete',
    total_score: 59,
    integrity_capped: false,
    foundation: { subtotal: 27, max: 35 },
    value: { subtotal: 32, max: 65 },
    dimensions: EIGHT_DIMENSIONS,
    pages_fetched: [{ url: 'https://acme.com', status: 'fetched' }],
  },
  visibility: 62.5,
  accessibility: 59,
  composite: 61,
  scan_status: 'complete',
}

describe('LiteFullReport — pre-Stage-4 content, unchanged', () => {
  it('renders the report heading and entity names', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('Your full Share of Algorithm report')).toBeInTheDocument()
    expect(screen.getByText('Acme Co (you)')).toBeInTheDocument()
    expect(screen.getByText('Rival Co')).toBeInTheDocument()
  })

  it('renders visibility-by-stage in canonical order regardless of payload key order', () => {
    render(<LiteFullReport report={baseReport} />)
    const awarenessIdx = screen.getByText('Awareness').compareDocumentPosition(
      screen.getByText('Research')
    )
    // Node.DOCUMENT_POSITION_FOLLOWING = 4: 'Research' node follows 'Awareness' node in the DOM.
    expect(awarenessIdx & 4).toBeTruthy()
  })

  it('omits stages that have no data at all', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText('Comparison')).not.toBeInTheDocument()
    expect(screen.queryByText('Ready to Buy')).not.toBeInTheDocument()
  })

  it('renders the working-session CTA link when VITE_LITE_CTA_URL is set', () => {
    vi.stubEnv('VITE_LITE_CTA_URL', 'https://parleo.io/demo')
    render(<LiteFullReport report={baseReport} />)
    const link = screen.getByText('Book a working session')
    expect(link.closest('a')).toHaveAttribute('href', 'https://parleo.io/demo')
    vi.unstubAllEnvs()
  })

  it('omits the CTA link when VITE_LITE_CTA_URL is unset', () => {
    vi.stubEnv('VITE_LITE_CTA_URL', '')
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText('Book a working session')).not.toBeInTheDocument()
    vi.unstubAllEnvs()
  })
})

describe('LiteFullReport — executive tiles', () => {
  it('renders composite, visibility, accessibility, and modeled exposure', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('Composite score')).toBeInTheDocument()
    expect(screen.getByText('Visibility')).toBeInTheDocument()
    expect(screen.getByText('Accessibility')).toBeInTheDocument()
    expect(screen.getByText('Modeled exposure/mo')).toBeInTheDocument()
  })
})

describe('LiteFullReport — why-section, all 8 dimensions', () => {
  it('renders all 8 dimensions grouped Foundation/Value with correct subtotals', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('Foundation (27/35)')).toBeInTheDocument()
    expect(screen.getByText('Value (32/65)')).toBeInTheDocument()
    // Each dimension's name legitimately renders twice — once in the
    // why-section score row, once in the ranked-fixes list.
    EIGHT_DIMENSIONS.forEach((d) => {
      expect(screen.getAllByText(d.name).length).toBeGreaterThanOrEqual(1)
    })
  })

  it('renders an integrity-cap banner when integrity_capped is true', () => {
    const report = { ...baseReport, scan: { ...baseReport.scan, integrity_capped: true } }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/capped this store's total score at 59/)).toBeInTheDocument()
  })

  it('omits the integrity-cap banner when false', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText(/capped this store's total score/)).not.toBeInTheDocument()
  })

  it('renders a linked-reason chip on the matching dimension', () => {
    const dims = EIGHT_DIMENSIONS.map((d) =>
      d.code === 'V1' ? { ...d, linked: { reason: 'mentioned but no price surfaced' } } : d
    )
    const report = { ...baseReport, scan: { ...baseReport.scan, dimensions: dims } }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText('Linked: mentioned but no price surfaced')).toBeInTheDocument()
  })

  it('shows the "add your store URL" prompt when scan is skipped (brand-only submission)', () => {
    const report = { ...baseReport, scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] }, scan_status: 'skipped' }
    const onAddStoreUrl = vi.fn()
    render(<LiteFullReport report={report} onAddStoreUrl={onAddStoreUrl} />)

    expect(screen.getByText('Add your store URL to see why')).toBeInTheDocument()
    screen.getByText('Add store URL').click()
    expect(onAddStoreUrl).toHaveBeenCalled()
  })

  it('shows the same prompt when there is no scan object at all (legacy/no row)', () => {
    const report = { ...baseReport, scan: null, scan_status: null }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText('Add your store URL to see why')).toBeInTheDocument()
  })

  it('shows the blocked badge + F1 explanation when scan is blocked, without hiding visibility sections', () => {
    const report = { ...baseReport, scan: { status: 'blocked', total_score: null, dimensions: [], pages_fetched: [] }, scan_status: 'blocked' }
    render(<LiteFullReport report={report} />)

    expect(screen.getByText(/blocked our reader — that's itself a finding/)).toBeInTheDocument()
    expect(screen.getByText(/Agent Access \(F1\)/)).toBeInTheDocument()
    // Visibility sections still render fully.
    expect(screen.getByText('Visibility by purchase stage')).toBeInTheDocument()
    expect(screen.getByText('Awareness')).toBeInTheDocument()
  })

  it('shows an honest explanation when scan failed', () => {
    const report = { ...baseReport, scan: { status: 'failed', total_score: null, dimensions: [], pages_fetched: [] }, scan_status: 'failed' }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText(/couldn't finish reading your store this time/)).toBeInTheDocument()
  })
})

describe('LiteFullReport — ranked fixes', () => {
  it('shows a code block for unlocked fixes', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText('add priceCurrency')).toBeInTheDocument()
  })

  it('shows a lock icon and no fix text for locked dimensions', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText('stop fake was-prices')).not.toBeInTheDocument()
    expect(screen.getAllByText(/Full diagnostic/).length).toBeGreaterThan(0)
  })

  it('renders nothing when the scan is not complete', () => {
    const report = { ...baseReport, scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] } }
    render(<LiteFullReport report={report} />)
    expect(screen.queryByText('Free fix')).not.toBeInTheDocument()
  })
})

describe('LiteFullReport — evidence gallery (speculative field)', () => {
  it('renders nothing when evidence_examples is absent (todays real API)', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.queryByText('Evidence')).not.toBeInTheDocument()
  })

  it('renders entries when evidence_examples is present', () => {
    const report = {
      ...baseReport,
      evidence_examples: [{ excerpt: 'Acme Co was not mentioned in this answer.', platform: 'chatgpt', stage: 'Research' }],
    }
    render(<LiteFullReport report={report} />)
    expect(screen.getByText('Evidence')).toBeInTheDocument()
    expect(screen.getByText(/Acme Co was not mentioned/)).toBeInTheDocument()
  })
})

describe('LiteFullReport — exposure calculator', () => {
  it('renders the sliders and modeled-exposure disclaimer', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByLabelText('Monthly revenue')).toBeInTheDocument()
    expect(screen.getByLabelText('AI-assisted share of purchases')).toBeInTheDocument()
    expect(screen.getByText(/Modeled, not measured/)).toBeInTheDocument()
  })

  it('updates the modeled exposure figure when a slider moves', () => {
    render(<LiteFullReport report={baseReport} />)
    const revenueSlider = screen.getByLabelText('Monthly revenue')
    const before = screen.getByText('Modeled monthly exposure').parentElement.textContent
    revenueSlider.dispatchEvent(new Event('change', { bubbles: true }))
    Object.defineProperty(revenueSlider, 'value', { value: '10000000', configurable: true })
    revenueSlider.dispatchEvent(new Event('change', { bubbles: true }))
    const after = screen.getByText('Modeled monthly exposure').parentElement.textContent
    expect(after).not.toBe(before)
  })
})

describe('LiteFullReport — locked panels grid', () => {
  it('renders all 6 locked panels', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText(/3 more AI platforms/)).toBeInTheDocument()
    expect(screen.getByText(/Full category run/)).toBeInTheDocument()
    expect(screen.getByText(/Net price accuracy/)).toBeInTheDocument()
    expect(screen.getByText(/Persona-level breakdowns/)).toBeInTheDocument()
    expect(screen.getByText(/Trend over time/)).toBeInTheDocument()
    expect(screen.getByText(/Retail shelf comparison/)).toBeInTheDocument()
  })
})

describe('LiteFullReport — footer', () => {
  it('renders the re-run cadence line and methodology stamp', () => {
    render(<LiteFullReport report={baseReport} />)
    expect(screen.getByText(/re-run this diagnostic monthly/)).toBeInTheDocument()
    expect(screen.getByText(/12 queries · 1 platform · 1 run each/)).toBeInTheDocument()
    expect(screen.getByText(/sample, not a category study/)).toBeInTheDocument()
  })
})
