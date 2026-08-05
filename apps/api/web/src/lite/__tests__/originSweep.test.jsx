/**
 * L4: extends the migration stage's U3 origin sweep (which covered the
 * report-ready email, Copy-link button, and SAMPLE_REPORT_URL) to the
 * canonical/og:url tags this stage adds. Generic on purpose — it walks
 * every canonical/og:url actually present in <head> after mount rather
 * than re-asserting one known value, so a future tag added anywhere in
 * this surface is covered automatically instead of needing its own
 * origin check written by hand.
 */
import React from 'react'
import { render, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import LandingPage from '../LandingPage.jsx'
import LiteWidget from '../LiteWidget.jsx'
import { liteApi } from '../liteApi.js'
import { PUBLIC_AUDIT_BASE_URL } from '../publicUrls.js'

vi.mock('../liteApi.js', () => ({
  liteApi: {
    submit: vi.fn(), getStatus: vi.fn(), getReport: vi.fn(), setEmail: vi.fn(),
  },
}))

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
})

function collectHeadUrls() {
  const urls = []
  document.head.querySelectorAll('link[rel="canonical"]').forEach((el) => urls.push(el.getAttribute('href')))
  document.head.querySelectorAll('meta[property="og:url"]').forEach((el) => urls.push(el.getAttribute('content')))
  return urls
}

describe('L4: origin sweep — every canonical/og:url in <head> is rooted at PUBLIC_AUDIT_BASE_URL', () => {
  it('LandingPage (the audit host)', () => {
    const { unmount } = render(<LandingPage navigate={vi.fn()} />)
    const urls = collectHeadUrls()
    expect(urls.length).toBeGreaterThan(0)
    urls.forEach((url) => expect(url.startsWith(PUBLIC_AUDIT_BASE_URL)).toBe(true))
    unmount()
  })

  it('LiteWidget — bare /lite form (marketing host)', () => {
    const { unmount } = render(<LiteWidget />)
    const urls = collectHeadUrls()
    expect(urls.length).toBeGreaterThan(0)
    urls.forEach((url) => expect(url.startsWith(PUBLIC_AUDIT_BASE_URL)).toBe(true))
    unmount()
  })

  it('LiteWidget — /report/{token} (marketing host)', async () => {
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })
    const { unmount } = render(<LiteWidget urlToken="tok-sweep" />)

    await waitFor(() => expect(collectHeadUrls().length).toBeGreaterThan(0))
    collectHeadUrls().forEach((url) => expect(url.startsWith(PUBLIC_AUDIT_BASE_URL)).toBe(true))
    unmount()
  })
})
