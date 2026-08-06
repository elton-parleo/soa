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

// audit.parleo.io migration (H1): App.jsx branches on isAuditHost()
// before anything else. Mocking that function (rather than trying to
// redefine window.location.hostname, which jsdom's real Location
// instance won't allow — it throws "Cannot redefine property") means
// pushState-driven pathname/history behavior, which the rest of this
// file's tests depend on, keeps working against the real jsdom Location
// unchanged.
let mockAuditHost = false
vi.mock('../lite/publicUrls.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, isAuditHost: () => mockAuditHost }
})

function setPath(path) {
  window.history.pushState({}, '', path)
}

function setHostname(hostname) {
  mockAuditHost = hostname === 'audit.parleo.io'
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  mockAuditHost = false
  setPath('/')
})

describe('App — /bots routing (W4)', () => {
  it('renders BotsPage, unauthenticated, same pre-auth treatment as /lite', () => {
    setPath('/bots')
    render(<App />)
    expect(screen.getByRole('heading', { name: 'ParleoAuditBot' })).toBeInTheDocument()
  })
})

describe('App — /report/{token} routing renders each U1 state', () => {
  it('running request -> the live, resumable progress view', async () => {
    setPath('/report/tok-running')
    liteApi.getStatus.mockResolvedValue({
      status: 'pending', phase: 'queued', scan_status: null,
      events: [{ seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'queued' }],
    })

    render(<App />)

    await waitFor(() => expect(screen.getByText('AUDIT QUEUED')).toBeInTheDocument())
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

  it('from the audit host landing page (/): pushes history to /r/{token} and the progress view takes over in place', async () => {
    setHostname('audit.parleo.io')
    setPath('/')
    liteApi.submit.mockResolvedValue({ token: 'tok-audit-submitted', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({
      status: 'pending', phase: 'queued', scan_status: null,
      events: [{ seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'queued' }],
    })

    render(<App />)
    const primaryInputs = screen.getAllByLabelText('Your brand or store URL')
    fireEvent.change(primaryInputs[0], { target: { value: 'Acme Co' } })
    // LandingNav also has a "Run my free audit" button, but it's a plain
    // #run anchor, not a form submit — filter down to the real ones.
    const submitButtons = screen.getAllByRole('button', { name: 'Run my free audit' }).filter((btn) => btn.closest('form'))
    fireEvent.click(submitButtons[0])

    await waitFor(() => expect(window.location.pathname).toBe('/r/tok-audit-submitted'))
    await waitFor(() => expect(screen.getByText('AUDIT QUEUED')).toBeInTheDocument())
  })
})

describe('App — H1/H2: audit.parleo.io hostname routing', () => {
  it('renders LandingPage at \'/\' on the audit host', () => {
    setHostname('audit.parleo.io')
    setPath('/')
    render(<App />)
    expect(screen.getByRole('navigation', { name: 'Parleo Audit' })).toBeInTheDocument()
  })

  it('renders the LiteWidget progress view at /r/{token} on the audit host', async () => {
    setHostname('audit.parleo.io')
    setPath('/r/tok-audit-r')
    liteApi.getStatus.mockResolvedValue({
      status: 'pending', phase: 'queued', scan_status: null,
      events: [{ seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'queued' }],
    })

    render(<App />)

    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalledWith('tok-audit-r'))
    expect(liteApi.submit).not.toHaveBeenCalled()
  })

  it('renders the same LiteWidget flow at /s/{id} on the audit host — not a distinct internal route', async () => {
    setHostname('audit.parleo.io')
    setPath('/s/tok-audit-s')
    liteApi.getStatus.mockResolvedValue({
      status: 'pending', phase: 'queued', scan_status: null,
      events: [{ seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'queued' }],
    })

    render(<App />)

    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalledWith('tok-audit-s'))
  })

  it('H1: any other path on the audit host is not found — no dashboard, no /lite, no /bots', () => {
    setHostname('audit.parleo.io')
    for (const path of ['/lite', '/bots', '/scan', '/report/tok-x', '/dashboard']) {
      setPath(path)
      const { unmount } = render(<App />)
      expect(screen.getByText('Not found.')).toBeInTheDocument()
      unmount()
    }
  })

  it('H2: /scan on the main host no longer renders the landing page (route deleted, not redirected)', () => {
    setHostname('localhost')
    setPath('/scan')
    render(<App />)
    expect(screen.queryByRole('navigation', { name: 'Parleo Audit' })).not.toBeInTheDocument()
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
