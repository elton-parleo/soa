import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import LiteWidget, {
  LiteForm,
  LiteProgress,
  LiteTeaser,
  LiteFullReport,
} from '../LiteWidget.jsx'
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

// ─── LiteForm ────────────────────────────────────────────────────────────

describe('LiteForm', () => {
  it('rejects an invalid brand name client-side without calling the API', async () => {
    render(<LiteForm onSubmitted={() => {}} />)

    fireEvent.change(screen.getByLabelText('Your brand'), { target: { value: 'A' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(screen.getByText(/2-80 characters/)).toBeInTheDocument())
    expect(liteApi.submit).not.toHaveBeenCalled()
  })

  it('rejects a competitor matching the brand name', async () => {
    render(<LiteForm onSubmitted={() => {}} />)

    fireEvent.change(screen.getByLabelText('Your brand'), { target: { value: 'Acme Co' } })
    fireEvent.change(screen.getByLabelText(/Competitor 1/), { target: { value: 'acme co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(screen.getByText(/different from the brand/)).toBeInTheDocument())
    expect(liteApi.submit).not.toHaveBeenCalled()
  })

  it('submits cleaned data and calls onSubmitted with the returned token', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-123', status: 'pending' })
    const onSubmitted = vi.fn()

    render(<LiteForm onSubmitted={onSubmitted} />)

    fireEvent.change(screen.getByLabelText('Your brand'), { target: { value: '  Acme Co  ' } })
    fireEvent.change(screen.getByLabelText(/Competitor 1/), { target: { value: 'Rival Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(onSubmitted).toHaveBeenCalledWith('tok-123'))
    expect(liteApi.submit).toHaveBeenCalledWith({
      brand_name: 'Acme Co',
      competitor_names: ['Rival Co'],
      captcha_token: expect.any(String),
    })
  })

  it('shows a rate-limit message on 429', async () => {
    const err = new Error('Too many SoA Lite requests from this IP — try again in an hour.')
    err.status = 429
    liteApi.submit.mockRejectedValue(err)

    render(<LiteForm onSubmitted={() => {}} />)
    fireEvent.change(screen.getByLabelText('Your brand'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(screen.getByText(/try again in an hour/)).toBeInTheDocument())
  })
})

// ─── LiteProgress (phase -> copy mapping) ───────────────────────────────

describe('LiteProgress', () => {
  it('maps generating_queries to the query-design message', () => {
    render(<LiteProgress phaseData={{ status: 'generating', phase: 'generating_queries' }} />)
    expect(screen.getByText('Designing your 12-query diagnostic…')).toBeInTheDocument()
  })

  it('maps queued to a waiting message', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued' }} />)
    expect(screen.getByText(/Queued/)).toBeInTheDocument()
  })

  it('maps analyzing to the analyzing message', () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'analyzing',
      progress: { completed_runs: 12, total_runs: 12 },
    }} />)
    expect(screen.getByText('Analyzing responses…')).toBeInTheDocument()
  })

  it('maps running with progress to a 1-indexed query count', () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running',
      progress: { completed_runs: 4, total_runs: 12 },
    }} />)
    expect(screen.getByText('Running query 5 of 12 against ChatGPT…')).toBeInTheDocument()
    expect(screen.getByText('4 of 12 queries complete')).toBeInTheDocument()
  })

  it('caps the displayed query number at the total when completed_runs reaches it', () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running',
      progress: { completed_runs: 12, total_runs: 12 },
    }} />)
    expect(screen.getByText('Running query 12 of 12 against ChatGPT…')).toBeInTheDocument()
  })

  it('renders a passed-in error banner', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued' }} error="Could not check status." />)
    expect(screen.getByText('Could not check status.')).toBeInTheDocument()
  })
})

// ─── LiteTeaser ──────────────────────────────────────────────────────────

describe('LiteTeaser', () => {
  const teaserReport = {
    status: 'complete',
    locked: true,
    overall: [
      { name: 'Acme Co', role: 'primary', som: 62.5 },
      { name: 'Rival Co', role: 'competitor', som: 37.5 },
    ],
  }

  it('renders overall SoA share per entity with role labeling', () => {
    render(<LiteTeaser report={teaserReport} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText('Acme Co (you)')).toBeInTheDocument()
    expect(screen.getByText('Rival Co')).toBeInTheDocument()
    expect(screen.getByText('62.5%')).toBeInTheDocument()
  })

  it('shows the unlock prompt for the stage-level detail', () => {
    render(<LiteTeaser report={teaserReport} token="tok-1" onUnlocked={() => {}} />)
    expect(screen.getByText(/unlock the full stage-by-stage diagnostic/)).toBeInTheDocument()
  })

  it('rejects an invalid email without calling the API', async () => {
    render(<LiteTeaser report={teaserReport} token="tok-1" onUnlocked={() => {}} />)
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'not-an-email' } })
    fireEvent.click(screen.getByText('Unlock full report'))

    await waitFor(() => expect(screen.getByText(/valid email/)).toBeInTheDocument())
    expect(liteApi.setEmail).not.toHaveBeenCalled()
  })

  it('unlocks and hands the full report back to the caller on valid email', async () => {
    const fullReport = { status: 'complete', locked: false, overall: [], by_stage: {} }
    liteApi.setEmail.mockResolvedValue(fullReport)
    const onUnlocked = vi.fn()

    render(<LiteTeaser report={teaserReport} token="tok-1" onUnlocked={onUnlocked} />)
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'visitor@example.com' } })
    fireEvent.click(screen.getByText('Unlock full report'))

    await waitFor(() => expect(onUnlocked).toHaveBeenCalledWith(fullReport))
    expect(liteApi.setEmail).toHaveBeenCalledWith('tok-1', 'visitor@example.com')
  })
})

// ─── LiteFullReport ──────────────────────────────────────────────────────

describe('LiteFullReport', () => {
  const fullReport = {
    status: 'complete',
    locked: false,
    overall: [
      {
        name: 'Acme Co', role: 'primary',
        metrics: { som: 62.5, mention_rate: 50, position_index: 70, rsi: 1.2 },
      },
      {
        name: 'Rival Co', role: 'competitor',
        metrics: { som: 37.5, mention_rate: 30, position_index: 40, rsi: 0.4 },
      },
    ],
    by_stage: {
      // Deliberately out of funnel order — the component must reorder to
      // Awareness -> Research -> Comparison -> Ready to Buy regardless of
      // key insertion order.
      'Research': [
        { name: 'Acme Co', role: 'primary', metrics: { mention_rate: 55 } },
        { name: 'Rival Co', role: 'competitor', metrics: { mention_rate: 25 } },
      ],
      'Awareness': [
        { name: 'Acme Co', role: 'primary', metrics: { mention_rate: 45 } },
        { name: 'Rival Co', role: 'competitor', metrics: { mention_rate: 35 } },
      ],
    },
  }

  it('renders overall SoA share and the position/RSI table', () => {
    render(<LiteFullReport report={fullReport} />)
    expect(screen.getByText('Acme Co (you)')).toBeInTheDocument()
    expect(screen.getByText('1.20')).toBeInTheDocument() // RSI formatted to 2dp
  })

  it('renders funnel stages in canonical order regardless of payload key order', () => {
    render(<LiteFullReport report={fullReport} />)
    const awarenessIdx = screen.getByText('Awareness').compareDocumentPosition(
      screen.getByText('Research')
    )
    // Node.DOCUMENT_POSITION_FOLLOWING = 4: 'Research' node follows 'Awareness' node in the DOM.
    expect(awarenessIdx & 4).toBeTruthy()
  })

  it('omits stages that have no data at all', () => {
    render(<LiteFullReport report={fullReport} />)
    expect(screen.queryByText('Comparison')).not.toBeInTheDocument()
    expect(screen.queryByText('Ready to Buy')).not.toBeInTheDocument()
  })

  it('renders the closing CTA link when VITE_LITE_CTA_URL is set', () => {
    vi.stubEnv('VITE_LITE_CTA_URL', 'https://parleo.io/demo')
    render(<LiteFullReport report={fullReport} />)
    const link = screen.getByText('See the full Parleo diagnostic')
    expect(link.closest('a')).toHaveAttribute('href', 'https://parleo.io/demo')
    vi.unstubAllEnvs()
  })

  it('omits the CTA link when VITE_LITE_CTA_URL is unset', () => {
    vi.stubEnv('VITE_LITE_CTA_URL', '')
    render(<LiteFullReport report={fullReport} />)
    expect(screen.queryByText('See the full Parleo diagnostic')).not.toBeInTheDocument()
    vi.unstubAllEnvs()
  })
})

// ─── LiteWidget root — state machine ────────────────────────────────────

describe('LiteWidget (root)', () => {
  it('renders the form when there is no stored token', () => {
    render(<LiteWidget />)
    expect(screen.getByText('Run my free diagnostic')).toBeInTheDocument()
  })

  it('stores the token and shows progress after a successful submission', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-abc', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued' })

    render(<LiteWidget />)
    fireEvent.change(screen.getByLabelText('Your brand'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(sessionStorage.getItem('soaLiteToken')).toBe('tok-abc'))
    await waitFor(() => expect(screen.getByText(/Queued/)).toBeInTheDocument())
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
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: true,
      overall: [{ name: 'Acme Co', role: 'primary', som: 60 }],
    })

    render(<LiteWidget />)

    await waitFor(() =>
      expect(screen.getByText(/unlock the full stage-by-stage diagnostic/)).toBeInTheDocument()
    )
  })

  it('renders the full report directly when the report is already unlocked', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-done2')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{
        name: 'Acme Co', role: 'primary',
        metrics: { som: 60, mention_rate: 40, position_index: 50, rsi: 1 },
      }],
      by_stage: {},
    })

    render(<LiteWidget />)

    await waitFor(() =>
      expect(screen.getByText('Your full Share of Algorithm report')).toBeInTheDocument()
    )
  })
})
