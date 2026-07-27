import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'

import { LiteProgress, LiteFailed } from '../LiteProgress.jsx'
import { liteApi } from '../liteApi.js'

vi.mock('../liteApi.js', () => ({
  liteApi: { setEmail: vi.fn() },
}))

function mockMatchMedia(matches) {
  const listeners = []
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches,
    media: query,
    addEventListener: (_, cb) => listeners.push(cb),
    removeEventListener: vi.fn(),
  }))
  return listeners
}

describe('LiteProgress — LLM query track (unchanged behavior)', () => {
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

describe('LiteProgress — scan track', () => {
  it('is omitted entirely when no store_url was submitted', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued', scan_status: null }} />)
    expect(screen.queryByText(/Reading your store/)).not.toBeInTheDocument()
  })

  it('shows a queued message before the scan has a status yet', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued', scan_status: null }} storeUrl="acme.com" />)
    expect(screen.getByText(/Queued to read acme.com/)).toBeInTheDocument()
  })

  it('shows the reading-in-progress message while scan_status is running', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running', scan_status: 'running' }} storeUrl="https://acme.com" />)
    expect(screen.getByText(/Reading acme.com like an agent/)).toBeInTheDocument()
  })

  it('shows a completion checkmark when scan_status is complete', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'analyzing', scan_status: 'complete' }} storeUrl="acme.com" />)
    expect(screen.getByText(/Finished reading acme.com/)).toBeInTheDocument()
  })

  it('shows an honest, non-error badge when the scan is blocked', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running', scan_status: 'blocked' }} storeUrl="acme.com" />)
    expect(screen.getByText(/blocked our reader — that itself is a finding/)).toBeInTheDocument()
  })

  it('shows an honest, non-error badge when the scan failed', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running', scan_status: 'failed' }} storeUrl="acme.com" />)
    expect(screen.getByText(/couldn't finish reading acme.com/)).toBeInTheDocument()
  })

  it('shows an honest, non-error badge when the scan was skipped', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running', scan_status: 'skipped' }} storeUrl="acme.com" />)
    expect(screen.getByText(/didn't get a chance to read acme.com/)).toBeInTheDocument()
  })
})

describe('LiteFailed', () => {
  it('calls onRetry when the button is clicked', () => {
    const onRetry = vi.fn()
    render(<LiteFailed onRetry={onRetry} />)
    screen.getByText('Try again').click()
    expect(onRetry).toHaveBeenCalled()
  })
})

describe('LiteProgress — Stage 12: running indicator (R1)', () => {
  afterEach(() => {
    delete window.matchMedia
  })

  it('shows a pulsing live-status dot and mono phase label while active', () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running',
      progress: { completed_runs: 4, total_runs: 12 },
    }} />)
    expect(screen.getByTestId('lite-live-dot')).toBeInTheDocument()
    expect(screen.getByText('ASKING CHATGPT — QUERY 5 OF 12')).toBeInTheDocument()
  })

  it('shows a phase-specific mono label for coding and metrics', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'coding', progress: { completed_runs: 12, total_runs: 12 } }} />)
    expect(screen.getByText('CODING RESPONSES')).toBeInTheDocument()
  })

  it('omits the live-status line once the run is complete or failed', () => {
    render(<LiteProgress phaseData={{ status: 'complete', phase: 'complete' }} />)
    expect(screen.queryByTestId('lite-live-dot')).not.toBeInTheDocument()
  })

  it('reduced motion: replaces the pulsing dot with a static glyph and RUNNING text', () => {
    mockMatchMedia(true)
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running',
      progress: { completed_runs: 4, total_runs: 12 },
    }} />)
    expect(screen.queryByTestId('lite-live-dot')).not.toBeInTheDocument()
    expect(screen.getByText('RUNNING')).toBeInTheDocument()
    expect(screen.queryByText('ASKING CHATGPT — QUERY 5 OF 12')).not.toBeInTheDocument()
  })

  it('full motion (default, no matchMedia mock): shows the animated dot, not the static fallback', () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running',
      progress: { completed_runs: 4, total_runs: 12 },
    }} />)
    expect(screen.getByTestId('lite-live-dot')).toBeInTheDocument()
    expect(screen.queryByText('RUNNING')).not.toBeInTheDocument()
  })
})

describe('LiteProgress — Stage 12: elapsed time counter', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('ticks up from 0:00 as time passes while active', async () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running', progress: { completed_runs: 1, total_runs: 12 },
    }} />)
    expect(screen.getByTestId('lite-elapsed')).toHaveTextContent('0:00')
    await act(async () => { vi.advanceTimersByTime(3000) })
    expect(screen.getByTestId('lite-elapsed')).toHaveTextContent('0:03')
  })
})

describe('LiteProgress — Stage 12: stalled-state honesty (R2)', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  const running = { status: 'running', phase: 'running', progress: { completed_runs: 4, total_runs: 12 } }

  it('shows a quiet stalled line after 90s with no progress change', async () => {
    const { rerender } = render(<LiteProgress phaseData={running} />)
    expect(screen.queryByText(/Still working/)).not.toBeInTheDocument()

    await act(async () => { vi.advanceTimersByTime(91_000) })
    rerender(<LiteProgress phaseData={{ ...running }} />)
    expect(screen.getByText('Still working — long queries can take a while.')).toBeInTheDocument()
  })

  it('clears the stalled line once progress actually changes', async () => {
    const { rerender } = render(<LiteProgress phaseData={running} />)
    await act(async () => { vi.advanceTimersByTime(91_000) })
    rerender(<LiteProgress phaseData={{ ...running }} />)
    expect(screen.getByText(/Still working/)).toBeInTheDocument()

    rerender(<LiteProgress phaseData={{
      status: 'running', phase: 'running', progress: { completed_runs: 5, total_runs: 12 },
    }} />)
    expect(screen.queryByText(/Still working/)).not.toBeInTheDocument()
  })

  it('never shows the stalled line before the 90s threshold', async () => {
    const { rerender } = render(<LiteProgress phaseData={running} />)
    await act(async () => { vi.advanceTimersByTime(60_000) })
    rerender(<LiteProgress phaseData={{ ...running }} />)
    expect(screen.queryByText(/Still working/)).not.toBeInTheDocument()
  })

  it('a failed request never shows the running affordances — LiteFailed takes over instead of an eternal spinner', () => {
    // LiteWidget.jsx never even mounts LiteProgress for status='failed' in
    // production (it renders LiteFailed instead) — this asserts the same
    // boundary directly on LiteProgress itself, in case it's ever reached.
    render(<LiteProgress phaseData={{ status: 'failed', phase: 'failed' }} />)
    expect(screen.queryByTestId('lite-live-dot')).not.toBeInTheDocument()
    expect(screen.queryByTestId('lite-elapsed')).not.toBeInTheDocument()
    expect(screen.queryByText(/Still working/)).not.toBeInTheDocument()
  })
})

describe('LiteProgress — Stage 12: status-page email card (E1)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('is omitted entirely when no token is available yet', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued' }} />)
    expect(screen.queryByText('This takes a few minutes.')).not.toBeInTheDocument()
  })

  it('is omitted once the run is complete or failed', () => {
    render(<LiteProgress phaseData={{ status: 'complete', phase: 'complete' }} token="tok-1" />)
    expect(screen.queryByText('This takes a few minutes.')).not.toBeInTheDocument()
  })

  it('renders the ask, submits via the existing PATCH /email endpoint, and collapses to a masked confirmation', async () => {
    liteApi.setEmail.mockResolvedValue({ status: 'running', phase: 'running' })
    render(<LiteProgress
      phaseData={{ status: 'running', phase: 'running', progress: { completed_runs: 1, total_runs: 12 } }}
      token="tok-1"
    />)

    expect(screen.getByText('This takes a few minutes.')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'visitor@example.com' } })
    fireEvent.click(screen.getByText('Email me the report'))

    await waitFor(() => expect(liteApi.setEmail).toHaveBeenCalledWith('tok-1', 'visitor@example.com'))
    await waitFor(() => expect(screen.getByText(/We'll email your report to v\*\*\*@example\.com/)).toBeInTheDocument())
    expect(screen.getByText(/You can also keep watching here/)).toBeInTheDocument()
  })

  it('shows a validation error for an invalid email and never calls the API', async () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running' }} token="tok-1" />)
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'not-an-email' } })
    fireEvent.click(screen.getByText('Email me the report'))
    await waitFor(() => expect(screen.getByText('Enter a valid email address')).toBeInTheDocument())
    expect(liteApi.setEmail).not.toHaveBeenCalled()
  })

  it('shows an inline error and stays on the form when the API call fails', async () => {
    liteApi.setEmail.mockRejectedValue(new Error('Something went wrong. Please try again.'))
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running' }} token="tok-1" />)
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'visitor@example.com' } })
    fireEvent.click(screen.getByText('Email me the report'))
    await waitFor(() => expect(screen.getByText('Something went wrong. Please try again.')).toBeInTheDocument())
    expect(screen.getByText('This takes a few minutes.')).toBeInTheDocument()
  })
})
