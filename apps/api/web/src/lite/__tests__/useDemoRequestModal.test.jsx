/**
 * useDemoRequestModal — Part 2c context ride-along: report_token/
 * brand_name only present when the caller passed them (report
 * surfaces), page_url always read fresh from window.location.href at
 * submit time. submitDemoRequest itself is mocked; this test only
 * verifies the payload the hook builds, not the fetch.
 */
import React from 'react'
import { renderHook, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'

import { useDemoRequestModal } from '../useDemoRequestModal.js'
import * as demoRequestApi from '../demoRequestApi.js'

beforeEach(() => {
  vi.spyOn(demoRequestApi, 'submitDemoRequest').mockResolvedValue({ ok: true, status: 200, body: { ok: true } })
  window.history.pushState(null, '', '/r/tok123')
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

  it('landing (no brandName/reportToken): submits with page_url only, brand_name/report_token undefined', async () => {
    const { result } = renderHook(() => useDemoRequestModal())
    act(() => result.current.open('landing_truesync'))

    await act(async () => {
      await result.current.onSubmit({ name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '' })
    })

    expect(demoRequestApi.submitDemoRequest).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Jane', email: 'jane@company.com', company: 'Acme', message: '',
      source: 'landing_truesync',
      page_url: expect.stringContaining('/r/tok123'),
      brand_name: undefined,
      report_token: undefined,
    }))
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
})
