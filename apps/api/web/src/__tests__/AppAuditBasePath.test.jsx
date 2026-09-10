/**
 * parleo.io/audit migration: App.jsx's audit routes under a base path.
 *
 * A sibling to App.test.jsx rather than another describe inside it,
 * because the thing under test is decided at MODULE-EVAL time —
 * publicUrls.js reads import.meta.env.BASE_URL and VITE_AUDIT_BUILD
 * once, on import. Stubbing the env and importing App dynamically in
 * beforeAll is what gives this file a genuine prefixed build to route
 * against; App.test.jsx keeps covering the default build unchanged,
 * including '/', '/r/{token}' and '/s/{id}' at the host root.
 *
 * Note what is NOT mocked here: isAuditHost. App.test.jsx has to mock
 * it because jsdom won't let a test redefine window.location.hostname,
 * but under VITE_AUDIT_BUILD=1 the real function answers true from the
 * build flag alone — which is exactly the behavior this file exists to
 * prove.
 */
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeAll, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

vi.mock('../lite/liteApi.js', () => ({
  liteApi: {
    submit: vi.fn(),
    getStatus: vi.fn(),
    getReport: vi.fn(),
    setEmail: vi.fn(),
  },
}))

let App
let liteApi

beforeAll(async () => {
  vi.stubEnv('BASE_URL', '/audit/')
  vi.stubEnv('VITE_AUDIT_BUILD', '1')
  vi.stubEnv('VITE_PUBLIC_AUDIT_BASE_URL', 'https://parleo.io/audit')
  vi.resetModules()
  ;({ liteApi } = await import('../lite/liteApi.js'))
  App = (await import('../App.jsx')).default
})

function setPath(path) {
  window.history.pushState({}, '', path)
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  setPath('/audit/')
  // Report-first resolution (see LiteWidget.jsx): a token-bearing
  // route fires getReport(token) on mount before rendering anything,
  // and a bare vi.fn() returning undefined throws inside .then().
  // The 409 falls through to the /status poll these tests assert on.
  liteApi.getReport.mockRejectedValue(Object.assign(new Error('Report is not ready yet'), { status: 409 }))
})

describe('App under VITE_BASE_PATH=/audit/ — the prefixed audit surface', () => {
  it("renders the landing at '/audit/'", () => {
    setPath('/audit/')
    render(<App />)
    expect(screen.getByRole('navigation', { name: 'Parleo Audit' })).toBeInTheDocument()
  })

  it("renders the landing at '/audit' with no trailing slash", () => {
    setPath('/audit')
    render(<App />)
    expect(screen.getByRole('navigation', { name: 'Parleo Audit' })).toBeInTheDocument()
  })

  it('renders the LiteWidget progress view at /audit/r/{token}', async () => {
    setPath('/audit/r/tok-prefixed-r')
    liteApi.getStatus.mockResolvedValue({
      status: 'pending', phase: 'queued', scan_status: null,
      events: [{ seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'queued' }],
    })

    render(<App />)

    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalledWith('tok-prefixed-r'))
    expect(liteApi.submit).not.toHaveBeenCalled()
  })

  it('renders the same flow at /audit/s/{id} — the token is sliced off the stripped path', async () => {
    setPath('/audit/s/tok-prefixed-s')
    liteApi.getStatus.mockResolvedValue({
      status: 'pending', phase: 'queued', scan_status: null,
      events: [{ seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'queued' }],
    })

    render(<App />)

    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalledWith('tok-prefixed-s'))
  })

  // H1 still holds under the prefix, and the client-side backstop must
  // not be fooled by the unprefixed forms either: on this build,
  // '/r/tok' is not an audit route, it is an unknown path.
  it('H1: anything else under the prefix is not found', () => {
    for (const path of ['/audit/nothing', '/audit/lite', '/audit/bots', '/auditorium']) {
      setPath(path)
      const { unmount } = render(<App />)
      expect(screen.getByText('Not found.')).toBeInTheDocument()
      unmount()
    }
  })

  // stripAuditBase leaves a path that isn't under the base alone, so an
  // unprefixed report path still resolves on this build. Deliberate
  // leniency, not an oversight: the edge never produces one (vercel
  // .json routes /audit/r/* and 404s the rest), but a proxy
  // misconfigured to strip the prefix on the way through would
  // otherwise turn every report link into a not-found page.
  it('still resolves an unprefixed /r/{token}, in case a proxy strips the prefix', async () => {
    setPath('/r/tok-unprefixed')
    liteApi.getStatus.mockResolvedValue({
      status: 'pending', phase: 'queued', scan_status: null,
      events: [{ seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'queued' }],
    })

    render(<App />)

    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalledWith('tok-unprefixed'))
  })

  it('post-submit navigation lands on /audit/r/{token}, prefix included', async () => {
    const { fireEvent } = await import('@testing-library/react')
    setPath('/audit/')
    liteApi.submit.mockResolvedValue({ token: 'tok-prefixed-submitted', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({
      status: 'pending', phase: 'queued', scan_status: null,
      events: [{ seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'queued' }],
    })

    render(<App />)
    const inputs = screen.getAllByLabelText('Your brand or store URL')
    fireEvent.change(inputs[0], { target: { value: 'Acme Co' } })
    const submitButtons = screen
      .getAllByRole('button', { name: 'Run my free audit' })
      .filter((btn) => btn.closest('form'))
    fireEvent.click(submitButtons[0])

    await waitFor(() => expect(window.location.pathname).toBe('/audit/r/tok-prefixed-submitted'))
    await waitFor(() => expect(screen.getByText('AUDIT QUEUED')).toBeInTheDocument())
  })
})
