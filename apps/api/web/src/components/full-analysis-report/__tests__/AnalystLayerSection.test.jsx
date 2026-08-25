/**
 * fix/full-analysis-mobile, 1f: the analyst layer's slice-tab row
 * scrolls horizontally instead of wrapping (5 tabs plus, on some
 * tabs, a sub-value row would otherwise wrap into a tall stack at
 * 375px), and the six-metric table gets the same overflow-wrapper +
 * sticky-first-column treatment as the platform matrix (1c) — it can
 * carry as many entity columns as the cycle's competitor scope has.
 */
import React from 'react'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import { AnalystLayerSection } from '../AnalystLayerSection.jsx'
import { api } from '../../../api.js'

vi.mock('../../../api.js', () => ({
  api: { getMetrics: vi.fn() },
}))

function _metricsPayload() {
  return {
    entities: [
      { code: 'M001', name: 'Allbirds', role: 'primary' },
      { code: 'M002', name: 'Nike', role: 'competitor' },
      { code: 'M003', name: 'Rothy\'s', role: 'competitor' },
    ],
    slices: {
      overall: { M001: { mention_rate: 74.6, som: 50, rsi: 3, position_index: 1, pdi: 0.8, deal_citation_rate: 20 }, M002: {}, M003: {} },
      by_stage: {},
      by_category: {},
      by_platform: {},
      by_persona: {},
    },
  }
}

beforeEach(() => {
  api.getMetrics.mockReset()
})

describe('AnalystLayerSection — loading/error states', () => {
  it('renders a loading placeholder before the fetch resolves', () => {
    api.getMetrics.mockReturnValue(new Promise(() => {}))
    render(<AnalystLayerSection cycleCode="fc-1" open onToggle={() => {}} />)
    expect(screen.getByText(/Loading analyst metrics/)).toBeInTheDocument()
  })

  it('renders nothing on a fetch error rather than a broken table', async () => {
    api.getMetrics.mockRejectedValue(new Error('boom'))
    const { container } = render(<AnalystLayerSection cycleCode="fc-1" open onToggle={() => {}} />)
    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })
})

describe('AnalystLayerSection — mobile-safe table and tabs', () => {
  it('wraps the six-metric table in a horizontal-scroll container', async () => {
    api.getMetrics.mockResolvedValue(_metricsPayload())
    const { container } = render(<AnalystLayerSection cycleCode="fc-1" open onToggle={() => {}} />)
    await waitFor(() => expect(screen.getByText('Allbirds (you)')).toBeInTheDocument())
    const wrapper = container.querySelector('table').parentElement
    expect(wrapper).toHaveStyle({ overflowX: 'auto' })
  })

  it('the Metric header cell and every metric-name cell carry position:sticky, left:0', async () => {
    api.getMetrics.mockResolvedValue(_metricsPayload())
    render(<AnalystLayerSection cycleCode="fc-1" open onToggle={() => {}} />)
    await waitFor(() => expect(screen.getByText('Mention Rate')).toBeInTheDocument())
    expect(screen.getByText('Metric')).toHaveStyle({ position: 'sticky', left: '0px' })
    expect(screen.getByText('Mention Rate')).toHaveStyle({ position: 'sticky', left: '0px' })
  })

  it('the slice-tab row carries the fa-analyst-tabs className (horizontal-scroll on phone, see fullAnalysis.css)', async () => {
    api.getMetrics.mockResolvedValue(_metricsPayload())
    const { container } = render(<AnalystLayerSection cycleCode="fc-1" open onToggle={() => {}} />)
    await waitFor(() => expect(screen.getByText('Overall')).toBeInTheDocument())
    expect(container.querySelector('.fa-analyst-tabs')).toBeInTheDocument()
  })

  it('every tab button meets the 44px tap-target minimum', async () => {
    api.getMetrics.mockResolvedValue(_metricsPayload())
    render(<AnalystLayerSection cycleCode="fc-1" open onToggle={() => {}} />)
    await waitFor(() => expect(screen.getByText('By Stage')).toBeInTheDocument())
    for (const label of ['Overall', 'By Stage', 'By Category', 'By Platform', 'By Persona']) {
      expect(screen.getByText(label)).toHaveStyle({ minHeight: '44px' })
    }
  })

  it('switching tabs still shows the same sticky-column table shape (re-slicing, not a different table)', async () => {
    const payload = _metricsPayload()
    payload.slices.by_stage = { 'Ready to Buy': { M001: { mention_rate: 60 }, M002: {}, M003: {} } }
    api.getMetrics.mockResolvedValue(payload)
    const { container } = render(<AnalystLayerSection cycleCode="fc-1" open onToggle={() => {}} />)
    await waitFor(() => expect(screen.getByText('By Stage')).toBeInTheDocument())
    fireEvent.click(screen.getByText('By Stage'))
    await waitFor(() => expect(screen.getByText('Ready to Buy')).toBeInTheDocument())
    expect(container.querySelector('table').parentElement).toHaveStyle({ overflowX: 'auto' })
  })
})
