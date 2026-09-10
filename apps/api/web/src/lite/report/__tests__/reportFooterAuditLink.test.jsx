/**
 * The report footer's "Run yours free" link.
 *
 * It used to be built from window.location.origin, which was right
 * only while the audit tool owned a whole host. Under /audit/ on
 * parleo.io the origin's root is the MARKETING home, and on
 * soa-app.parleo.io's /report/{token} it is the authed dashboard — so
 * origin-based construction sent a reader of the report somewhere
 * other than the audit landing in both of the places it actually
 * renders. This file pins the replacement in both.
 *
 * Its own file rather than another case in LiteFullReportV4.test.jsx
 * because the audit-surface variant has to be decided at module-eval
 * time (publicUrls.js reads import.meta.env once, on import), which
 * means stubbing the env and importing dynamically.
 */
import React from 'react'
import { render, screen } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'

vi.mock('../../analytics.js', () => ({
  track: vi.fn(),
  identifyReport: vi.fn(),
  captureSrcParam: vi.fn(() => 'direct'),
  isTokenOwned: vi.fn(() => true),
}))

vi.mock('../../openaiPixel.js', () => ({
  trackAuditScoreRendered: vi.fn(() => true),
  withOppref: vi.fn((p) => p),
  isOpenAIPixelAvailable: vi.fn(() => true),
}))

const REPORT = {
  status: 'complete',
  locked: false,
  overall: [{ name: 'Allbirds', role: 'primary', metrics: { som: 35, mention_rate: 42 } }],
  scan: { status: 'complete', degraded_reason: null, degraded_banner_facts: null },
  scan_status: 'complete',
  visibility: 62.5,
  accessibility: 40,
  composite: 40,
  visibility_breakdown: {
    mention_rate: [{ entity: 'Allbirds', is_primary: true, mentioned_queries: 10, total_queries: 24, rate_pct: 42 }],
    share_of_mentions: [{ entity: 'Allbirds', is_primary: true, mentions: 8, share_pct: 35 }],
  },
  pillars: {
    visibility_score: 25, visibility_max: 32,
    accessibility_score: 8, accessibility_max: 18,
    true_value_score: 7, true_value_max: 50,
    parleo_fixable_points: 12,
  },
}

async function renderWith(env) {
  vi.resetModules()
  for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value)
  const { LiteFullReportV4 } = await import('../LiteFullReportV4.jsx')
  return render(<LiteFullReportV4 report={REPORT} token="tok-footer" />)
}

function footerCtaHref() {
  const link = screen.getByRole('link', { name: /run yours free/i })
  return link.getAttribute('href')
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('report footer "Run yours free" link', () => {
  it('is the canonical audit address off the audit surface (/report/{token})', async () => {
    await renderWith({ VITE_PUBLIC_AUDIT_BASE_URL: '' })
    // Not the origin: jsdom serves this from localhost, and the reader
    // of a /report/{token} page must be sent to the audit tool, not to
    // whatever happens to sit at this host's root.
    expect(footerCtaHref()).toBe('https://parleo.io/audit/')
    expect(footerCtaHref()).not.toContain(window.location.origin)
  })

  it('is a same-origin path under the prefixed build, not the marketing root', async () => {
    await renderWith({ VITE_AUDIT_BUILD: '1', BASE_URL: '/audit/', VITE_PUBLIC_AUDIT_BASE_URL: 'https://parleo.io/audit' })
    // The bug this replaces: window.location.origin + '/' resolves to
    // https://parleo.io/ here — the marketing home, one level above
    // the audit landing.
    expect(footerCtaHref()).toBe('/audit/')
  })

  it('stays root-relative on an audit surface served at a host root', async () => {
    await renderWith({ VITE_AUDIT_BUILD: '1', VITE_PUBLIC_AUDIT_BASE_URL: 'https://parleo.io/audit' })
    expect(footerCtaHref()).toBe('/')
  })
})
