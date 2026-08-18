/**
 * C2/D: the running-cycle card used to sit at "0/N runs" the entire time
 * a cycle was executing (soa_cycles.completed_runs is written once, at
 * the very end — see cycles.py::_live_completed_runs) and never polled
 * while running. These tests lock in: the card reflects live run counts
 * as they change, polling starts/stops based on whether a cycle is
 * RUNNING, the total is whatever the cycle-derived payload says (never a
 * hardcoded lite constant), and "View Progress" is disabled with a hint
 * while running, re-enabling as "View Report" on completion.
 *
 * Fake timers drive both the poll interval and the initial fetch's own
 * promise resolution here — @testing-library's waitFor/findBy poll via
 * real setTimeout internally and hang under fake timers, so each step
 * is flushed explicitly with `act(() => vi.advanceTimersByTimeAsync(...))`
 * instead.
 */
import React from 'react'
import { act, render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'

import CycleDashboard from '../CycleDashboard.jsx'
import { api } from '../../api.js'

vi.mock('../../api.js', () => ({
  api: {
    getCycles: vi.fn(),
    resumeCycle: vi.fn(),
  },
}))

// Sidebar reads auth context (Supabase session) that's out of scope for
// this component's own tests — stub it out rather than standing up a
// real AuthProvider/Supabase client.
vi.mock('../Sidebar.jsx', () => ({ default: () => null }))

function cycle(overrides = {}) {
  return {
    cycle_code: 'q-2026-08-acme',
    status: 'running',
    study_type: 'retailer_sephora',
    total_runs_planned: 150,
    completed_runs: 0,
    created_at: '2026-08-18T00:00:00',
    updated_at: '2026-08-18T00:00:00',
    platforms: ['chatgpt', 'gemini'],
    runs_per_query: 5,
    cycle_mode: 'query',
    id: 1,
    ...overrides,
  }
}

async function flush(ms = 0) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms) })
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

describe('CycleDashboard — running-cycle progress card', () => {
  it('renders the cycle-derived total, not a hardcoded lite value', async () => {
    api.getCycles.mockResolvedValue([cycle({ total_runs_planned: 150, completed_runs: 40 })])
    render(<CycleDashboard />)
    await flush()

    expect(screen.getByText('40/150 runs')).toBeInTheDocument()
  })

  it('reflects an updated run count on the next poll while the cycle is running', async () => {
    api.getCycles.mockResolvedValueOnce([cycle({ completed_runs: 10 })])
    render(<CycleDashboard />)
    await flush()
    expect(screen.getByText('10/150 runs')).toBeInTheDocument()

    api.getCycles.mockResolvedValueOnce([cycle({ completed_runs: 25 })])
    await flush(5_000)

    expect(screen.getByText('25/150 runs')).toBeInTheDocument()
  })

  it('stops polling once no cycle is running', async () => {
    api.getCycles.mockResolvedValueOnce([cycle({ status: 'complete', completed_runs: 150 })])
    render(<CycleDashboard />)
    await flush()
    expect(api.getCycles).toHaveBeenCalledTimes(1)

    await flush(20_000)

    expect(api.getCycles).toHaveBeenCalledTimes(1)
  })

  it('keeps polling every 5s while a cycle is running', async () => {
    api.getCycles.mockResolvedValue([cycle({ completed_runs: 5 })])
    render(<CycleDashboard />)
    await flush()
    expect(api.getCycles).toHaveBeenCalledTimes(1)

    await flush(5_000)
    expect(api.getCycles).toHaveBeenCalledTimes(2)

    await flush(5_000)
    expect(api.getCycles).toHaveBeenCalledTimes(3)
  })
})

describe('CycleDashboard — "View Progress" disabled while running', () => {
  it('renders the button disabled with an honest hint, not clickable through to an empty report', async () => {
    api.getCycles.mockResolvedValue([cycle()])
    render(<CycleDashboard />)
    await flush()

    const button = screen.getByRole('button', { name: 'View Progress' })
    expect(button).toBeDisabled()
    expect(screen.getByText('Progress updates here; report available when complete')).toBeInTheDocument()
  })

  it('does not show an est.-remaining figure before enough progress has been observed', async () => {
    api.getCycles.mockResolvedValue([cycle({ completed_runs: 5 })])
    render(<CycleDashboard />)
    await flush()

    expect(screen.getByText('5/150 runs')).toBeInTheDocument()
    expect(screen.queryByText(/Est\..*remaining/)).not.toBeInTheDocument()
  })

  it('derives est.-remaining from the observed run rate once progress has advanced', async () => {
    api.getCycles.mockResolvedValueOnce([cycle({ completed_runs: 0 })])
    render(<CycleDashboard />)
    await flush()
    expect(screen.getByText('0/150 runs')).toBeInTheDocument()

    // 10 runs land over the next 5s poll tick — a real, observed rate.
    api.getCycles.mockResolvedValueOnce([cycle({ completed_runs: 10 })])
    await flush(5_000)
    expect(screen.getByText('10/150 runs')).toBeInTheDocument()

    expect(screen.getByText(/Est\..*remaining/)).toBeInTheDocument()
  })
})

describe('CycleDashboard — complete cycle re-enables the report link', () => {
  it('renders "View Report", not the disabled progress button', async () => {
    api.getCycles.mockResolvedValue([cycle({ status: 'complete', completed_runs: 150 })])
    render(<CycleDashboard />)
    await flush()

    const button = screen.getByRole('button', { name: 'View Report' })
    expect(button).not.toBeDisabled()
    expect(screen.queryByRole('button', { name: 'View Progress' })).not.toBeInTheDocument()
  })
})
