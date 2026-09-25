/**
 * useDemoRequestModal — Part 2c context ride-along: report_token/
 * brand_name only present when the caller passed them (report
 * surfaces). No page_url — see demoRequestApi.js's docstring for why
 * that field was dropped from the payload. submitDemoRequest itself
 * is mocked; this test only verifies the payload the hook builds, not
 * the fetch.
 */
import React from 'react'
import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { useDemoRequestModal } from '../useDemoRequestModal.js'
import * as demoRequestApi from '../demoRequestApi.js'
import { track } from '../analytics.js'
import { EVENTS } from '../analyticsEvents.js'
import { trackAppointmentScheduled, newRequestId } from '../openaiPixel.js'

vi.mock('../analytics.js', () => ({
  track: vi.fn(),
}))

vi.mock('../openaiPixel.js', () => ({
  trackAppointmentScheduled: vi.fn(() => true),
  trackRegistrationCompleted: vi.fn(() => true),
  trackLeadCreated: vi.fn(() => true),
  trackReportContentsViewed: vi.fn(() => true),
  newRequestId: vi.fn(() => 'req-generated-1'),
  withOppref: vi.fn((path) => path),
  isOpenAIPixelAvailable: vi.fn(() => true),
}))

beforeEach(() => {
  vi.spyOn(demoRequestApi, 'submitDemoRequest').mockResolvedValue({ ok: true, status: 200, body: { ok: true } })
  track.mockClear()
  trackAppointmentScheduled.mockClear()
  newRequestId.mockClear()
})

describe('useDemoRequestModal', () => {
  it('starts closed, with no cta', () => {
    const { result } = renderHook(() => useDemoRequestModal())
    expect(result.current.isOpen).toBe(false)
    expect(result.current.cta).toBeNull()
  })

  it('open(key) selects that CTA\'s copy and opens', () => {
    const { result } = renderHook(() => useDemoRequestModal())
    act(() => result.current.open('truesync'))
    expect(result.current.isOpen).toBe(true)
    expect(result.current.cta.source).toBe('truesync')
    expect(result.current.cta.eyebrow).toBe('TRUESYNC')
  })

  it('close() resets to no cta', () => {
    const { result } = renderHook(() => useDemoRequestModal())
    act(() => result.current.open('truesync'))
    act(() => result.current.close())
    expect(result.current.isOpen).toBe(false)
    expect(result.current.cta).toBeNull()
  })

  it('landing (no brandName/reportToken): submits with brand_name/report_token undefined, no page_url', async () => {
    const { result } = renderHook(() => useDemoRequestModal())
    act(() => result.current.open('landing_truesync'))

    await act(async () => {
      await result.current.onSubmit({ name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '' })
    })

    expect(demoRequestApi.submitDemoRequest).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '',
      source: 'landing_truesync',
      brand_name: undefined,
      report_token: undefined,
    }))
    const payload = demoRequestApi.submitDemoRequest.mock.calls[0][0]
    expect(payload).not.toHaveProperty('page_url')
  })

  it('report context: submits with brand_name and report_token from the caller', async () => {
    const { result } = renderHook(() => useDemoRequestModal({ brandName: 'Allbirds', reportToken: 'tok123' }))
    act(() => result.current.open('truesync'))

    await act(async () => {
      await result.current.onSubmit({ name: 'Jane', email: 'jane@company.com', company: 'Acme', message: 'hi' })
    })

    expect(demoRequestApi.submitDemoRequest).toHaveBeenCalledWith(expect.objectContaining({
      source: 'truesync',
      brand_name: 'Allbirds',
      report_token: 'tok123',
    }))
  })

  it('threads the CTA\'s subject line through to submitDemoRequest (Formspree _subject)', async () => {
    const { result } = renderHook(() => useDemoRequestModal())
    act(() => result.current.open('full_analysis_walkthrough'))

    await act(async () => {
      await result.current.onSubmit({ name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '' })
    })

    expect(demoRequestApi.submitDemoRequest).toHaveBeenCalledWith(expect.objectContaining({
      subject: 'Demo request — walkthrough',
    }))
  })

  it('fires demo_request_submitted on a 200 response, with source/brand_name/report_token', async () => {
    const { result } = renderHook(() => useDemoRequestModal({ brandName: 'Allbirds', reportToken: 'tok123' }))
    act(() => result.current.open('truesync'))

    await act(async () => {
      await result.current.onSubmit({ name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '' })
    })

    expect(track).toHaveBeenCalledWith(EVENTS.DEMO_REQUEST_SUBMITTED, {
      source: 'truesync',
      brand_name: 'Allbirds',
      report_token: 'tok123',
    })
  })

  it('does not fire demo_request_submitted when the request resolves not-ok', async () => {
    demoRequestApi.submitDemoRequest.mockResolvedValue({ ok: false, status: 422, body: null })
    const { result } = renderHook(() => useDemoRequestModal({ brandName: 'Allbirds', reportToken: 'tok123' }))
    act(() => result.current.open('truesync'))

    await act(async () => {
      await result.current.onSubmit({ name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '' })
    })

    expect(track).not.toHaveBeenCalled()
  })
})


// ─── OpenAI ad conversion: appointment_scheduled ────────────────────────
//
// The hook already guarantees that nothing fires except on a real 200
// — a honeypot trip never reaches this closure at all, and a 422
// leaves result.ok false. These pin that the ad conversion inherits
// that guarantee rather than re-deriving it, plus the one piece of
// logic this event adds: which id becomes the dedup key, given the
// modal opens both from report surfaces (token) and from the landing
// page (nothing durable).
describe('useDemoRequestModal — appointment_scheduled', () => {
  it('a 200 from a report surface fires with that report token', async () => {
    const { result } = renderHook(() => useDemoRequestModal({ brandName: 'Allbirds', reportToken: 'tok-r' }))
    await act(async () => {
      await result.current.onSubmit({ email: 'a@b.com' })
    })

    expect(trackAppointmentScheduled).toHaveBeenCalledTimes(1)
    expect(trackAppointmentScheduled).toHaveBeenCalledWith({
      reportToken: 'tok-r',
      requestId: 'req-generated-1',
    })
  })

  it('a 200 from the landing page (no report token) fires with a generated requestId', async () => {
    const { result } = renderHook(() => useDemoRequestModal({}))
    await act(async () => {
      await result.current.onSubmit({ email: 'a@b.com' })
    })

    expect(newRequestId).toHaveBeenCalledTimes(1)
    expect(trackAppointmentScheduled).toHaveBeenCalledTimes(1)
    expect(trackAppointmentScheduled).toHaveBeenCalledWith({
      reportToken: undefined,
      requestId: 'req-generated-1',
    })
  })

  it('a non-ok result fires nothing — neither PostHog nor the pixel', async () => {
    demoRequestApi.submitDemoRequest.mockResolvedValue({ ok: false, status: 422, body: {} })
    const { result } = renderHook(() => useDemoRequestModal({ reportToken: 'tok-r' }))
    await act(async () => {
      await result.current.onSubmit({ email: 'a@b.com' })
    })

    expect(trackAppointmentScheduled).not.toHaveBeenCalled()
    expect(track).not.toHaveBeenCalled()
  })

  it('a missing result fires nothing', async () => {
    demoRequestApi.submitDemoRequest.mockResolvedValue(undefined)
    const { result } = renderHook(() => useDemoRequestModal({ reportToken: 'tok-r' }))
    await act(async () => {
      await result.current.onSubmit({ email: 'a@b.com' })
    })

    expect(trackAppointmentScheduled).not.toHaveBeenCalled()
  })

  // The id is generated before the request, so it is stable for that
  // one submission rather than regenerated per call — which is what
  // makes it usable as a dedup key at all.
  it('generates the requestId once per submission, before the request', async () => {
    const order = []
    newRequestId.mockImplementation(() => {
      order.push('generate')
      return 'req-generated-1'
    })
    demoRequestApi.submitDemoRequest.mockImplementation(async () => {
      order.push('submit')
      return { ok: true, status: 200, body: { ok: true } }
    })

    const { result } = renderHook(() => useDemoRequestModal({}))
    await act(async () => {
      await result.current.onSubmit({ email: 'a@b.com' })
    })

    expect(order).toEqual(['generate', 'submit'])
    expect(newRequestId).toHaveBeenCalledTimes(1)
  })
})
