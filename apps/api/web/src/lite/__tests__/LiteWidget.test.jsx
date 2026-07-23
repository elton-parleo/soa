import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import LiteWidget from '../LiteWidget.jsx'
import { liteApi } from '../liteApi.js'

vi.mock('../liteApi.js', () => ({
  liteApi: {
    submit: vi.fn(),
    getStatus: vi.fn(),
    getReport: vi.fn(),
    setEmail: vi.fn(),
  },
}))

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
})

describe('LiteWidget (root) — state machine', () => {
  it('renders the form when there is no stored token', () => {
    render(<LiteWidget />)
    expect(screen.getByText('Run my free diagnostic')).toBeInTheDocument()
  })

  it('stores the token and shows progress after a successful brand-only submission', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-abc', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<LiteWidget />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(sessionStorage.getItem('soaLiteToken')).toBe('tok-abc'))
    await waitFor(() => expect(screen.getByText(/Queued/)).toBeInTheDocument())
    expect(sessionStorage.getItem('soaLiteStoreUrl')).toBeNull()
  })

  it('stores the store URL and shows the scan track after a URL submission', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-url', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<LiteWidget />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'acme.com' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(sessionStorage.getItem('soaLiteStoreUrl')).toBe('acme.com'))
    await waitFor(() => expect(screen.getByText(/Queued to read acme.com/)).toBeInTheDocument())
  })

  it('resumes polling immediately when a token already exists in sessionStorage', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-existing')
    liteApi.getStatus.mockResolvedValue({
      status: 'running', phase: 'analyzing', progress: { completed_runs: 12, total_runs: 12 },
    })

    render(<LiteWidget />)

    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalledWith('tok-existing'))
    await waitFor(() => expect(screen.getByText('Analyzing responses…')).toBeInTheDocument())
  })

  it('resumes with the persisted store_url domain on the scan track after a refresh', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-existing')
    sessionStorage.setItem('soaLiteStoreUrl', 'acme.com')
    liteApi.getStatus.mockResolvedValue({ status: 'running', phase: 'running', scan_status: 'running', progress: { completed_runs: 1, total_runs: 12 } })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText(/Reading acme.com like an agent/)).toBeInTheDocument())
  })

  it('shows the retry view on failed status and clears storage on retry', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-failed')
    liteApi.getStatus.mockResolvedValue({ status: 'failed', phase: 'failed' })

    render(<LiteWidget />)
    await waitFor(() => expect(screen.getByText('Something went wrong')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Try again'))

    expect(sessionStorage.getItem('soaLiteToken')).toBeNull()
    expect(screen.getByText('Run my free diagnostic')).toBeInTheDocument()
  })

  it('fetches and renders the teaser once complete with no email on file', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-done')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'skipped' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: true,
      overall: [{ name: 'Acme Co', role: 'primary', som: 60 }],
      visibility: 60, accessibility: null, composite: 60, scan_status: 'skipped',
    })

    render(<LiteWidget />)

    await waitFor(() =>
      expect(screen.getByText('Want the full report?')).toBeInTheDocument()
    )
  })

  it('renders the full report directly when the report is already unlocked', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-done2')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'skipped' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{
        name: 'Acme Co', role: 'primary',
        metrics: { som: 60, mention_rate: 40, position_index: 50, rsi: 1 },
      }],
      by_stage: {},
      scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] },
      visibility: 60, accessibility: null, composite: 60, scan_status: 'skipped',
    })

    render(<LiteWidget />)

    // The full report has no separate page title — the executive tiles
    // (composite score) are the first thing distinguishing it from the teaser.
    await waitFor(() =>
      expect(screen.getByText('Composite score')).toBeInTheDocument()
    )
  })
})

// ─── Adaptive shapes ───────────────────────────────────────────────────

describe('LiteWidget — adaptive shapes', () => {
  it('URL input produces the full dual report with a complete scan', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-url-shape')
    sessionStorage.setItem('soaLiteStoreUrl', 'acme.com')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'complete' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{ name: 'Acme Co', role: 'primary', metrics: { som: 60 } }],
      by_stage: {},
      scan: {
        status: 'complete', total_score: 80, integrity_capped: false,
        foundation: { subtotal: 30, max: 35 }, value: { subtotal: 50, max: 65 },
        dimensions: [{ code: 'F1', name: 'Agent Access', score: 10, max: 10, evidence: [], fix: null, locked: false, linked: null }],
        pages_fetched: [],
      },
      visibility: 60, accessibility: 80, composite: 68, scan_status: 'complete',
    })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('FOUNDATION · 30/35')).toBeInTheDocument())
    expect(screen.queryByText('Add your store URL to see why')).not.toBeInTheDocument()
  })

  it('brand-only submission shows the "add your store URL" prompt in the why-section', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-brand-only')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'skipped' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{ name: 'Acme Co', role: 'primary', metrics: { som: 60 } }],
      by_stage: {},
      scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] },
      visibility: 60, accessibility: null, composite: 60, scan_status: 'skipped',
    })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('Add your store URL to see why')).toBeInTheDocument())
  })

  it('clicking "add your store URL" resets to the form, pre-filled with the confirmed brand name', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-brand-only-2')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'skipped' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{ name: 'Acme Co', role: 'primary', metrics: { som: 60 } }],
      by_stage: {},
      scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] },
      visibility: 60, accessibility: null, composite: 60, scan_status: 'skipped',
    })

    render(<LiteWidget />)
    await waitFor(() => expect(screen.getByText('Add store URL')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Add store URL'))

    expect(sessionStorage.getItem('soaLiteToken')).toBeNull()
    expect(screen.getByLabelText('Your brand or store URL')).toHaveValue('Acme Co')
  })

  it('scan blocked still renders visibility sections fully, with the blocked badge in the why-section', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-blocked')
    sessionStorage.setItem('soaLiteStoreUrl', 'bigbox.com')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'blocked' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [
        { name: 'Big Box', role: 'primary', metrics: { som: 60, mention_rate: 40 } },
        { name: 'Rival', role: 'competitor', metrics: { som: 40, mention_rate: 20 } },
      ],
      by_stage: { Awareness: [
        { name: 'Big Box', role: 'primary', metrics: { mention_rate: 40 } },
        { name: 'Rival', role: 'competitor', metrics: { mention_rate: 20 } },
      ] },
      scan: { status: 'blocked', total_score: null, dimensions: [], pages_fetched: [] },
      visibility: 60, accessibility: null, composite: 60, scan_status: 'blocked',
    })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('Where you disappear in the funnel')).toBeInTheDocument())
    expect(screen.getByText('AWARENESS')).toBeInTheDocument()
    expect(screen.getByText(/blocked our reader/)).toBeInTheDocument()
  })
})

// ─── Additive fields absent (old API) ───────────────────────────────────

describe('LiteWidget — old API shape (additive fields absent)', () => {
  it('renders the pre-scan progress experience without errors when scan_status is absent', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-old-api')
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued' }) // no scan_status key at all

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText(/Queued/)).toBeInTheDocument())
  })

  it('renders the old-shape teaser without errors when visibility/accessibility/composite are absent', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-old-api-2')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: true,
      overall: [{ name: 'Acme Co', role: 'primary', som: 60 }],
      // no visibility/accessibility/composite/scan_status — pre-Stage-3 shape
    })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('Acme Co (you)')).toBeInTheDocument())
  })

  it('renders the old-shape full report without errors when scan is absent', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-old-api-3')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{ name: 'Acme Co', role: 'primary', metrics: { som: 60, mention_rate: 40, position_index: 50, rsi: 1 } }],
      by_stage: {},
      // no scan/visibility/accessibility/composite/scan_status — pre-Stage-3 shape
    })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('Composite score')).toBeInTheDocument())
    expect(screen.getByText('Add your store URL to see why')).toBeInTheDocument()
  })
})
