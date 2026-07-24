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

  it('scan blocked still renders the visibility section fully, with the blocked badge in the why-section', async () => {
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
      by_stage: null, // deprecated Stage 7 — always null on the real API
      visibility_breakdown: {
        mention_rate: [
          { entity: 'Big Box', is_primary: true, mentioned_queries: 5, total_queries: 12, rate_pct: 42 },
          { entity: 'Rival', is_primary: false, mentioned_queries: 2, total_queries: 12, rate_pct: 17 },
        ],
        share_of_mentions: [
          { entity: 'Big Box', is_primary: true, mentions: 5, share_pct: 71.4 },
          { entity: 'Rival', is_primary: false, mentions: 2, share_pct: 28.6 },
        ],
        totals: { total_mentions: 7, total_queries: 12 },
      },
      scan: { status: 'blocked', total_score: null, dimensions: [], pages_fetched: [] },
      visibility: 60, accessibility: null, composite: 60, scan_status: 'blocked',
    })

    render(<LiteWidget />)

    // The real, unlocked visibility section (W1/W2) still renders in full —
    // a blocked scan degrades the why-section only, per rule 7.
    await waitFor(() => expect(screen.getByText('How often agents mention you — and your value')).toBeInTheDocument())
    expect(screen.getByText('42% · 5/12')).toBeInTheDocument()
    expect(screen.getByText(/blocked our reader/)).toBeInTheDocument()

    // The funnel teaser (W4) still renders as a locked, decorative tease —
    // its stage cells are fixed constants, not the real data above.
    expect(screen.getByText('Where you disappear in the funnel')).toBeInTheDocument()
    expect(screen.getByText('AWARENESS')).toBeInTheDocument()
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

// ─── Stage 9: /report/{token} — urlToken, navigate, not-found ──────────

function queryNoindexMeta() {
  return document.head.querySelector('meta[name="robots"][content="noindex"]')
}

describe('LiteWidget — Stage 9: urlToken seeds the token from the URL', () => {
  it('polls immediately using urlToken, without requiring a sessionStorage token', async () => {
    liteApi.getStatus.mockResolvedValue({
      status: 'running', phase: 'analyzing', progress: { completed_runs: 12, total_runs: 12 },
    })

    render(<LiteWidget urlToken="tok-from-url" />)

    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalledWith('tok-from-url'))
    await waitFor(() => expect(screen.getByText('Analyzing responses…')).toBeInTheDocument())
  })

  it('persists the URL token to sessionStorage so a later /lite visit resumes it', async () => {
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<LiteWidget urlToken="tok-from-url-2" />)

    await waitFor(() => expect(sessionStorage.getItem('soaLiteToken')).toBe('tok-from-url-2'))
  })

  it('renders the not-found state immediately for an empty urlToken, without polling', async () => {
    render(<LiteWidget urlToken="" />)

    expect(screen.getByText("We couldn't find this report")).toBeInTheDocument()
    expect(liteApi.getStatus).not.toHaveBeenCalled()
  })

  it('renders the not-found state on a 404 from getStatus, and stops polling', async () => {
    const err = new Error('Not found.')
    err.status = 404
    liteApi.getStatus.mockRejectedValue(err)

    render(<LiteWidget urlToken="tok-unknown" />)

    await waitFor(() => expect(screen.getByText("We couldn't find this report")).toBeInTheDocument())
    const callsAtNotFound = liteApi.getStatus.mock.calls.length
    // No further polling once terminal — same idiom as the 'failed' status check.
    await new Promise((r) => setTimeout(r, 20))
    expect(liteApi.getStatus.mock.calls.length).toBe(callsAtNotFound)
  })

  it('scrubs the dead token from sessionStorage on a 404, so it cannot poison a later /lite or /report visit', async () => {
    const err = new Error('Not found.')
    err.status = 404
    liteApi.getStatus.mockRejectedValue(err)

    render(<LiteWidget urlToken="tok-unknown-2" />)

    // The mount-time persist effect writes it optimistically; the 404 must
    // scrub it back out rather than leaving a dead token behind.
    await waitFor(() => expect(sessionStorage.getItem('soaLiteToken')).toBe('tok-unknown-2'))
    await waitFor(() => expect(screen.getByText("We couldn't find this report")).toBeInTheDocument())
    expect(sessionStorage.getItem('soaLiteToken')).toBeNull()
  })

  it('the not-found "Start a new scan" button calls navigate when provided', () => {
    const navigate = vi.fn()
    render(<LiteWidget urlToken="" navigate={navigate} />)

    fireEvent.click(screen.getByText('Start a new scan'))
    expect(navigate).toHaveBeenCalledWith('/scan')
  })
})

describe('LiteWidget — Stage 9: navigate after submit', () => {
  it('calls navigate with /report/{token} after a successful submission', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-nav', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })
    const navigate = vi.fn()

    render(<LiteWidget navigate={navigate} />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/report/tok-nav'))
  })

  it('does not throw when navigate is omitted (today\'s exact /lite behavior)', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-no-nav', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<LiteWidget />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(sessionStorage.getItem('soaLiteToken')).toBe('tok-no-nav'))
    expect(screen.queryByText(/is not a function/)).not.toBeInTheDocument()
  })
})

describe('LiteWidget — Stage 9: noindex meta (U4)', () => {
  it('adds <meta name="robots" content="noindex"> once a token exists', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-noindex')
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<LiteWidget />)

    await waitFor(() => expect(queryNoindexMeta()).not.toBeNull())
  })

  it('does not add a noindex meta for the bare form (no token, not a report route)', () => {
    render(<LiteWidget />)
    expect(queryNoindexMeta()).toBeNull()
  })

  it('adds noindex for the not-found state on an empty urlToken (still a report route)', () => {
    render(<LiteWidget urlToken="" />)
    expect(queryNoindexMeta()).not.toBeNull()
  })
})
