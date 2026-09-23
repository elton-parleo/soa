/**
 * FullAnalysisShareControl.test.jsx checks the copied link against the
 * PUBLIC_APP_BASE_URL constant itself, so a wrong default host can't
 * fail it — and one didn't: the default pointed at app.parleo.io, which
 * has no DNS record, and every copied share link was dead. These pin
 * the default to the host the SoA app is actually served from, and pin
 * the env override's behaviour.
 *
 * The module reads import.meta.env once at load, so each case stubs the
 * env and re-imports it fresh.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

async function loadUrls() {
  vi.resetModules()
  return import('../publicFullAnalysisUrls.js')
}

describe('publicFullAnalysisUrls', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
  })

  it('defaults to soa-app.parleo.io when VITE_PUBLIC_APP_BASE_URL is empty', async () => {
    vi.stubEnv('VITE_PUBLIC_APP_BASE_URL', '')
    const { fullAnalysisReportUrl } = await loadUrls()
    expect(fullAnalysisReportUrl('abc')).toBe('https://soa-app.parleo.io/fa/abc')
  })

  it('respects an env override and strips its trailing slash', async () => {
    vi.stubEnv('VITE_PUBLIC_APP_BASE_URL', 'https://preview.example.com/')
    const { PUBLIC_APP_BASE_URL, fullAnalysisReportUrl } = await loadUrls()
    expect(PUBLIC_APP_BASE_URL).toBe('https://preview.example.com')
    expect(fullAnalysisReportUrl('abc')).toBe('https://preview.example.com/fa/abc')
  })
})
