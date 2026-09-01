/**
 * End-to-end wiring for the demo-request modal: RequestFormModal (ds/)
 * driven by the REAL useDemoRequestModal hook and the REAL
 * submitDemoRequest — only `fetch` is mocked, exactly like a CTA call
 * site (TrueSyncBand.jsx et al) actually wires the two together. Every
 * other test file in this area mocks one layer of this chain directly
 * (onSubmit in RequestFormModal.test.jsx, submitDemoRequest in
 * useDemoRequestModal.test.jsx, fetch in demoRequestApi.test.js) —
 * useful for each piece in isolation, but none of them could have
 * caught a bug where a legitimate submission never reaches fetch at
 * all, because each one starts from a point already past the break.
 * This file starts from a user's click and ends at the network call.
 *
 * This is the test that was RED before the fix: the honeypot input
 * used to be named/labeled "website", and (on a real browser) Chrome's
 * autofill would silently populate it from a saved profile, tripping
 * the anti-spam gate for real humans with zero network call — the
 * exact "success but no request" bug this file reproduces and locks in.
 */
import React, { useEffect } from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'

import { RequestFormModal } from '../../ds/RequestFormModal.jsx'
import { useDemoRequestModal } from '../useDemoRequestModal.js'
import { FORMSPREE_DEMO_ENDPOINT } from '../publicUrls.js'
import { track } from '../analytics.js'
import { EVENTS } from '../analyticsEvents.js'

vi.mock('../analytics.js', () => ({
  track: vi.fn(),
}))

function Harness({ ctaKey = 'truesync', brandName, reportToken }) {
  const demoModal = useDemoRequestModal({ brandName, reportToken })
  useEffect(() => {
    demoModal.open(ctaKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  if (!demoModal.cta) return null
  return (
    <RequestFormModal
      open={demoModal.isOpen}
      onClose={demoModal.close}
      eyebrow={demoModal.cta.eyebrow}
      title={demoModal.cta.title}
      messagePlaceholder={demoModal.cta.messagePlaceholder}
      onSubmit={demoModal.onSubmit}
    />
  )
}

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

let mockNow

beforeEach(() => {
  mockNow = 1_700_000_000_000
  vi.spyOn(Date, 'now').mockImplementation(() => mockNow)
  vi.spyOn(global, 'fetch')
  track.mockClear()
})

afterEach(() => {
  vi.restoreAllMocks()
})

function fillValidForm() {
  fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Jane Smith' } })
  fireEvent.change(screen.getByLabelText(/^Email/), { target: { value: 'jane@company.com' } })
  fireEvent.change(screen.getByLabelText(/^Company/), { target: { value: 'Acme Corp' } })
  fireEvent.change(screen.getByLabelText(/^Message/), { target: { value: 'loyalty details' } })
}

describe('demo-request modal — real end-to-end wiring, only fetch mocked', () => {
  it('a normal human submission reaches fetch exactly once, with the right request and FormData, and reports success', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, { ok: true }))

    render(<Harness />)
    await screen.findByRole('dialog')

    mockNow += 2000 // past the gate, well within a real human's fill time
    fillValidForm()
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1))
    const [url, init] = global.fetch.mock.calls[0]
    expect(url).toBe(FORMSPREE_DEMO_ENDPOINT)
    expect(init.method).toBe('POST')
    expect(init.headers).toEqual({ Accept: 'application/json' })

    const formData = init.body
    expect(formData.get('name')).toBe('Jane Smith')
    expect(formData.get('email')).toBe('jane@company.com')
    expect(formData.get('company')).toBe('Acme Corp')
    expect(formData.get('message')).toBe('loyalty details')
    expect(formData.get('source')).toBe('truesync')
    expect(formData.get('_subject')).toBe('Demo request — TrueSync')
    expect(formData.get('_gotcha')).toBe('')

    expect(await screen.findByText('Message sent')).toBeInTheDocument()
    expect(track).toHaveBeenCalledTimes(1)
    expect(track).toHaveBeenCalledWith(EVENTS.DEMO_REQUEST_SUBMITTED, expect.objectContaining({ source: 'truesync' }))
  })

  it('report context: brand_name/report_token also reach the real FormData', async () => {
    global.fetch.mockResolvedValue(jsonResponse(200, { ok: true }))

    render(<Harness ctaKey="full_analysis_walkthrough" brandName="Allbirds" reportToken="tok123" />)
    await screen.findByRole('dialog')

    mockNow += 2000
    fillValidForm()
    fireEvent.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => expect(global.fetch).toHaveBeenCalledTimes(1))
    const formData = global.fetch.mock.calls[0][1].body
    expect(formData.get('brand_name')).toBe('Allbirds')
    expect(formData.get('report_token')).toBe('tok123')
    expect(formData.get('_subject')).toBe('Demo request — walkthrough')
  })

  it('a too-fast submit never reaches fetch and never fires analytics', async () => {
    render(<Harness />)
    await screen.findByRole('dialog')

    fillValidForm()
    fireEvent.click(screen.getByRole('button', { name: 'Send message' })) // no time advance

    expect(await screen.findByText('Message sent')).toBeInTheDocument()
    expect(global.fetch).not.toHaveBeenCalled()
    expect(track).not.toHaveBeenCalled()
  })
})
