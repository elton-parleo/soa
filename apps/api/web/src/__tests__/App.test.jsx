import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import App from '../App.jsx'
import { liteApi } from '../lite/liteApi.js'

vi.mock('../lite/liteApi.js', () => ({
  liteApi: {
    submit: vi.fn(),
    getStatus: vi.fn(),
    getReport: vi.fn(),
    setEmail: vi.fn(),
  },
}))

function setPath(path) {
  window.history.pushState({}, '', path)
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  setPath('/')
})

describe('App — /bots routing (W4)', () => {
  it('renders BotsPage, unauthenticated, same pre-auth treatment as /scan and /lite', () => {
    setPath('/bots')
    render(<App />)
    expect(screen.getByRole('heading', { name: 'ParleoAuditBot' })).toBeInTheDocument()
  })
})

describe('App — /report/{token} routing renders each U1 state', () => {
  it('running request -> the live, resumable progress view', async () => {
    setPath('/report/tok-running')
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<App />)

    await waitFor(() => expect(screen.getByText('No store URL was provided this run.')).toBeInTheDocument())
    expect(liteApi.submit).not.toHaveBeenCalled()
  })

  it('complete, no email on file -> the full report renders directly (Report redesign, Part 8, E1: never gated on email)', async () => {
    setPath('/report/tok-noemail')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'skipped' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{ name: 'Acme Co', role: 'primary', metrics: { som: 60 } }],
      visibility: 60, accessibility: null, composite: 60, scan_status: 'skipped',
    })

    render(<App />)

    await waitFor(() => expect(screen.getByText('Composite score')).toBeInTheDocument())
    expect(screen.queryByText('Want the full report?')).not.toBeInTheDocument()
  })

  it('complete + unlocked -> the full report', async () => {
    setPath('/report/tok-full')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'skipped' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{
        name: 'Acme Co', role: 'primary',
        metrics: { som: 60, mention_rate: 40, position_index: 50, rsi: 1 },
      }],
      by_stage: null,
      scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] },
      visibility: 60, accessibility: null, composite: 60, scan_status: 'skipped',
    })

    render(<App />)

    await waitFor(() => expect(screen.getByText('Composite score')).toBeInTheDocument())
  })

  it('unknown/expired token -> a designed not-found state, no stack trace', async () => {
    setPath('/report/tok-unknown')
    const err = new Error('Not found.')
    err.status = 404
    liteApi.getStatus.mockRejectedValue(err)

    render(<App />)

    await waitFor(() => expect(screen.getByText("We couldn't find this report")).toBeInTheDocument())
    expect(screen.queryByText(/at Object\.|\.jsx:\d+/)).not.toBeInTheDocument()
  })

  it('a bare /report (no token segment) -> the not-found state, no request made', () => {
    setPath('/report')
    render(<App />)

    expect(screen.getByText("We couldn't find this report")).toBeInTheDocument()
    expect(liteApi.getStatus).not.toHaveBeenCalled()
  })
})

describe('App — refresh-during-run resumes, never resubmits', () => {
  it('a fresh mount at /report/{token} only calls getStatus, never submit', async () => {
    setPath('/report/tok-resume')
    liteApi.getStatus.mockResolvedValue({
      status: 'running', phase: 'running', progress: { completed_runs: 3, total_runs: 12 },
    })

    render(<App />)

    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalledWith('tok-resume'))
    expect(liteApi.submit).not.toHaveBeenCalled()
  })
})

describe('App — post-submit navigation lands on /report/{token} (U2)', () => {
  it('from /lite: pushes history to /report/{token} matching the POST response, no reload', async () => {
    setPath('/lite')
    liteApi.submit.mockResolvedValue({ token: 'tok-submitted', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<App />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(window.location.pathname).toBe('/report/tok-submitted'))
  })

  it('from /scan: pushes history to /report/{token} and the progress view takes over in place', async () => {
    setPath('/scan')
    liteApi.submit.mockResolvedValue({ token: 'tok-scan-submitted', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<App />)
    const primaryInputs = screen.getAllByLabelText('Your brand or store URL')
    fireEvent.change(primaryInputs[0], { target: { value: 'Acme Co' } })
    const submitButtons = screen.getAllByText('Get your visibility report')
    fireEvent.click(submitButtons[0])

    await waitFor(() => expect(window.location.pathname).toBe('/report/tok-scan-submitted'))
    await waitFor(() => expect(screen.getByText('No store URL was provided this run.')).toBeInTheDocument())
  })
})

describe('App — privacy (U4): no email in any URL touched by this flow', () => {
  it('the report URL never carries an email, query param, or fragment', async () => {
    setPath('/lite')
    liteApi.submit.mockResolvedValue({ token: 'tok-privacy', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<App />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(window.location.pathname).toBe('/report/tok-privacy'))
    expect(window.location.href).not.toContain('@')
    expect(window.location.search).toBe('')
    expect(window.location.hash).toBe('')
  })
})
