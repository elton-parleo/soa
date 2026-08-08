import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'

import LiteWidget from '../LiteWidget.jsx'
import { liteApi } from '../liteApi.js'
import { PUBLIC_AUDIT_BASE_URL } from '../publicUrls.js'

vi.mock('../liteApi.js', () => ({
  liteApi: {
    submit: vi.fn(),
    getStatus: vi.fn(),
    getReport: vi.fn(),
    setEmail: vi.fn(),
  },
}))

// audit.parleo.io migration: LiteWidget branches on isAuditHost() (see
// publicUrls.js) to pick the right same-origin path prefix. Mocking the
// function directly — rather than trying to make window.location.hostname
// equal PUBLIC_AUDIT_HOSTNAME — keeps these tests correct regardless of
// what VITE_PUBLIC_AUDIT_BASE_URL happens to resolve to in this
// environment (e.g. a local .env.local pointed at a dev hostname); same
// pattern as App.test.jsx.
let mockAuditHost = false
vi.mock('../publicUrls.js', async (importOriginal) => {
  const actual = await importOriginal()
  return { ...actual, isAuditHost: () => mockAuditHost }
})

const ORIGINAL_LOCATION = window.location

// Only the marketing-host "leaves for the audit host" test needs a real
// window.location.href write/readback — jsdom's real Location throws on
// cross-origin navigation, so that one test swaps in a plain writable
// stand-in. Every other host-dependent test uses the isAuditHost() mock
// above instead of touching window.location at all.
function useWritableLocation() {
  Object.defineProperty(window, 'location', {
    value: { href: ORIGINAL_LOCATION.href },
    writable: true,
    configurable: true,
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  sessionStorage.clear()
  mockAuditHost = false
})

afterEach(() => {
  Object.defineProperty(window, 'location', {
    value: ORIGINAL_LOCATION,
    writable: true,
    configurable: true,
  })
})

describe('LiteWidget (root) — state machine', () => {
  it('renders the form when there is no stored token', () => {
    render(<LiteWidget />)
    expect(screen.getByText('Run my free diagnostic')).toBeInTheDocument()
  })

  it('stores the token and shows progress after a successful brand-only submission', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-abc', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({
      status: 'pending', phase: 'queued', scan_status: null,
      events: [{ seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'queued' }],
    })

    render(<LiteWidget />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(sessionStorage.getItem('soaLiteToken')).toBe('tok-abc'))
    await waitFor(() => expect(screen.getByText('AUDIT QUEUED')).toBeInTheDocument())
    expect(sessionStorage.getItem('soaLiteStoreUrl')).toBeNull()
  })

  it('stores the store URL and shows the scan track after a URL submission', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-url', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({
      status: 'pending', phase: 'queued', scan_status: 'running',
      events: [
        { seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'running' },
        { seq: 2, ts: '2026-01-01T00:00:01Z', kind: 'log', task: 'crawl', text: 'reading acme.com…' },
      ],
    })

    render(<LiteWidget />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'acme.com' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(sessionStorage.getItem('soaLiteStoreUrl')).toBe('acme.com'))
    await waitFor(() => expect(screen.getByText('reading acme.com…')).toBeInTheDocument())
  })

  it('resumes polling immediately when a token already exists in sessionStorage', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-existing')
    liteApi.getStatus.mockResolvedValue({
      status: 'running', phase: 'analyzing', progress: { completed_runs: 12, total_runs: 12 },
      events: [
        { seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'running' },
        { seq: 2, ts: '2026-01-01T00:00:01Z', kind: 'log', task: 'scoring', text: 'coding mentions, prices, and incentives…' },
      ],
    })

    render(<LiteWidget />)

    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalledWith('tok-existing'))
    await waitFor(() => expect(screen.getByText('coding mentions, prices, and incentives…')).toBeInTheDocument())
  })

  it('resumes with the persisted store_url domain on the scan track after a refresh', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-existing')
    sessionStorage.setItem('soaLiteStoreUrl', 'acme.com')
    liteApi.getStatus.mockResolvedValue({
      status: 'running', phase: 'running', scan_status: 'running', progress: { completed_runs: 1, total_runs: 12 },
      events: [
        { seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'running' },
        { seq: 2, ts: '2026-01-01T00:00:01Z', kind: 'log', task: 'crawl', text: 'reading acme.com…' },
      ],
    })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('reading acme.com…')).toBeInTheDocument())
  })

  it('shows the retry view on failed status and clears storage on retry', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-failed')
    liteApi.getStatus.mockResolvedValue({ status: 'failed', phase: 'failed' })

    render(<LiteWidget />)
    await waitFor(() => expect(screen.getByText('Something went wrong')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Try again'))

    expect(sessionStorage.getItem('soaLiteToken')).toBeNull()
    expect(screen.getByText('Run my free diagnostic')).toBeInTheDocument()
  })

  it('fetches and renders the full report directly once complete, with no email on file (Report redesign, Part 8, E1)', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-done')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'skipped' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{ name: 'Acme Co', role: 'primary', metrics: { som: 60 } }],
      visibility: 60, accessibility: null, composite: 60, scan_status: 'skipped',
    })

    render(<LiteWidget />)

    await waitFor(() =>
      expect(screen.getByText('Composite score')).toBeInTheDocument()
    )
    expect(screen.queryByText('Want the full report?')).not.toBeInTheDocument()
  })

  it('renders the full report directly when the report is already unlocked', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-done2')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'skipped' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{
        name: 'Acme Co', role: 'primary',
        metrics: { som: 60, mention_rate: 40, position_index: 50, rsi: 1 },
      }],
      by_stage: {},
      scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] },
      visibility: 60, accessibility: null, composite: 60, scan_status: 'skipped',
    })

    render(<LiteWidget />)

    // The full report has no separate page title — the executive tiles
    // (composite score) are the first thing distinguishing it from the teaser.
    await waitFor(() =>
      expect(screen.getByText('Composite score')).toBeInTheDocument()
    )
  })

  // Re-weighting session (Part 4): a report scored under a retired
  // scoring model never reaches the full report or the legacy fallback.
  it('shows the expired state, not the report, when report.status is "expired"', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-expired')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'complete' })
    liteApi.getReport.mockResolvedValue({
      status: 'expired',
      store_domain: 'oldstore.example.com',
      store_url: 'https://oldstore.example.com',
    })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('This report has expired')).toBeInTheDocument())
    expect(screen.queryByText('Composite score')).not.toBeInTheDocument()
    const cta = screen.getByText('Run a fresh audit')
    expect(cta.getAttribute('href')).toContain(encodeURIComponent('https://oldstore.example.com'))
  })

  it('the expired-state CTA omits the url query param when the retired run recorded no store_url', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-expired-nourl')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'complete' })
    liteApi.getReport.mockResolvedValue({ status: 'expired', store_domain: null, store_url: null })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('This report has expired')).toBeInTheDocument())
    const cta = screen.getByText('Run a fresh audit')
    expect(cta.getAttribute('href')).not.toContain('?url=')
  })
})

// ─── Adaptive shapes ───────────────────────────────────────────────────

describe('LiteWidget — adaptive shapes', () => {
  it('URL input produces the full dual report with a complete scan', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-url-shape')
    sessionStorage.setItem('soaLiteStoreUrl', 'acme.com')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'complete' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{ name: 'Acme Co', role: 'primary', metrics: { som: 60 } }],
      by_stage: {},
      scan: {
        status: 'complete', total_score: 80, integrity_capped: false,
        foundation: { subtotal: 30, max: 35 }, value: { subtotal: 50, max: 65 },
        dimensions: [{ code: 'F1', name: 'Agent Access', score: 10, max: 10, evidence: [], fix: null, locked: false, linked: null }],
        pages_fetched: [],
      },
      visibility: 60, accessibility: 80, composite: 68, scan_status: 'complete',
    })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('Composite score')).toBeInTheDocument())
    expect(screen.getByText('68')).toBeInTheDocument()
    expect(screen.queryByText('Add your store URL to see why')).not.toBeInTheDocument()
  })

  it('brand-only submission shows the "add your store URL" prompt in the why-section', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-brand-only')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'skipped' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{ name: 'Acme Co', role: 'primary', metrics: { som: 60 } }],
      by_stage: {},
      scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] },
      visibility: 60, accessibility: null, composite: 60, scan_status: 'skipped',
    })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('Add your store URL to see why')).toBeInTheDocument())
  })

  it('clicking "add your store URL" resets to the form, pre-filled with the confirmed brand name', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-brand-only-2')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'skipped' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{ name: 'Acme Co', role: 'primary', metrics: { som: 60 } }],
      by_stage: {},
      scan: { status: 'skipped', total_score: null, dimensions: [], pages_fetched: [] },
      visibility: 60, accessibility: null, composite: 60, scan_status: 'skipped',
    })

    render(<LiteWidget />)
    await waitFor(() => expect(screen.getByText('Add store URL')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Add store URL'))

    expect(sessionStorage.getItem('soaLiteToken')).toBeNull()
    expect(screen.getByLabelText('Your brand or store URL')).toHaveValue('Acme Co')
  })

  it('scan blocked still renders the visibility section fully, with the degraded-run banner (fetch-resilience stage: real pillars, v4 layout)', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-blocked')
    sessionStorage.setItem('soaLiteStoreUrl', 'bigbox.com')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete', scan_status: 'blocked' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [
        { name: 'Big Box', role: 'primary', metrics: { som: 60, mention_rate: 40 } },
        { name: 'Rival', role: 'competitor', metrics: { som: 40, mention_rate: 20 } },
      ],
      by_stage: null, // deprecated Stage 7 — always null on the real API
      visibility_breakdown: {
        mention_rate: [
          { entity: 'Big Box', is_primary: true, mentioned_queries: 5, total_queries: 12, rate_pct: 42 },
          { entity: 'Rival', is_primary: false, mentioned_queries: 2, total_queries: 12, rate_pct: 17 },
        ],
        share_of_mentions: [
          { entity: 'Big Box', is_primary: true, mentions: 5, share_pct: 71.4 },
          { entity: 'Rival', is_primary: false, mentions: 2, share_pct: 28.6 },
        ],
        totals: { total_mentions: 7, total_queries: 12 },
      },
      scan: {
        status: 'blocked', total_score: null, dimensions: [], pages_fetched: [],
        degraded_reason: 'blocked',
        degraded_banner_facts: { refusal: '429', attempts: 4, robots_included: false },
      },
      visibility: 60, accessibility: 0, composite: 60, scan_status: 'blocked',
      // Fetch-resilience stage (R1/R2): a narrow-blocked scan under the
      // current scorer version now carries a real pillars payload —
      // every crawl-derived dimension honestly blocked, never absent.
      pillars: {
        visibility: {
          score: 100, max: 100,
          dimensions: [
            { code: 'share_of_mentions', name: 'Share of Mentions', earned: 25, max: 25, na: false, evidence: [], seen: null, said: null, checks: null },
            { code: 'recommendation_strength', name: 'Recommendation Strength', earned: 15, max: 15, na: false, evidence: [], seen: null, said: null, checks: null },
          ],
        },
        accessibility: {
          score: 0, max: 100,
          dimensions: [
            { code: 'agent_access', name: 'Agent Access', earned: 0, max: 6, na: false, blocked: true, evidence: ['the store root and every sampled product page were rate-limited or blocked this run — nothing could be measured on-site'], seen: null, said: null, checks: [] },
            { code: 'catalog_context', name: 'Catalog & Context', earned: 0, max: 8, na: false, blocked: true, evidence: [], seen: null, said: null, checks: [] },
            { code: 'protocol_feed', name: 'Protocol & Feed Presence', earned: 0, max: 6, na: false, blocked: true, evidence: [], seen: null, said: null, checks: [] },
          ],
        },
        true_value: { score: 0, max: 100, dimensions: [] },
        composite: 60,
        member_value_na: false,
        fixes: { visible: [], remaining_count: 0 },
        verdict: 'NOT AGENT-READY',
      },
    })

    render(<LiteWidget />)

    // V4 report redesign: the real, unlocked Visibility section still
    // renders in full — a blocked scan degrades Accessibility/True
    // Value only, per rule 7. The degraded banner still surfaces the
    // same honest fetch-facts message it always has (blocked-run copy
    // pass: now in plain language, read from the failure-point registry).
    await waitFor(() => expect(screen.getByText(/Your site refused every request \(429\) before serving a page, across 4 attempts\./)).toBeInTheDocument())
    expect(screen.getByText('Share of Mentions')).toBeInTheDocument()
    expect(screen.getByText('Recommendation Strength')).toBeInTheDocument()

    // The funnel gate section still renders as a locked, decorative
    // tease — its stage cells are fixed constants, not the real data
    // above.
    expect(screen.getByText('Where you disappear in the funnel')).toBeInTheDocument()
    expect(screen.getAllByText('FULL ANALYSIS').length).toBeGreaterThan(0)
  })
})

// ─── Additive fields absent (old API) ───────────────────────────────────

describe('LiteWidget — old API shape (additive fields absent)', () => {
  it('renders the pre-scan progress experience without errors when scan_status/events are absent', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-old-api')
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued' }) // no scan_status/events keys at all — P7 fallback

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('AUDIT QUEUED')).toBeInTheDocument())
  })

  it('renders the old-shape full report without errors when scan is absent', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-old-api-3')
    liteApi.getStatus.mockResolvedValue({ status: 'complete', phase: 'complete' })
    liteApi.getReport.mockResolvedValue({
      status: 'complete',
      locked: false,
      overall: [{ name: 'Acme Co', role: 'primary', metrics: { som: 60, mention_rate: 40, position_index: 50, rsi: 1 } }],
      by_stage: {},
      // no scan/visibility/accessibility/composite/scan_status — pre-Stage-3 shape
    })

    render(<LiteWidget />)

    await waitFor(() => expect(screen.getByText('Composite score')).toBeInTheDocument())
    expect(screen.getByText('Add your store URL to see why')).toBeInTheDocument()
  })
})

// ─── Stage 9: /report/{token} — urlToken, navigate, not-found ──────────

function queryNoindexMeta() {
  return document.head.querySelector('meta[name="robots"][content="noindex,nofollow"]')
}

describe('LiteWidget — Stage 9: urlToken seeds the token from the URL', () => {
  it('polls immediately using urlToken, without requiring a sessionStorage token', async () => {
    liteApi.getStatus.mockResolvedValue({
      status: 'running', phase: 'analyzing', progress: { completed_runs: 12, total_runs: 12 },
      events: [
        { seq: 1, ts: '2026-01-01T00:00:00Z', kind: 'state', task: 'run', text: 'running' },
        { seq: 2, ts: '2026-01-01T00:00:01Z', kind: 'log', task: 'scoring', text: 'coding mentions, prices, and incentives…' },
      ],
    })

    render(<LiteWidget urlToken="tok-from-url" />)

    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalledWith('tok-from-url'))
    await waitFor(() => expect(screen.getByText('coding mentions, prices, and incentives…')).toBeInTheDocument())
  })

  it('persists the URL token to sessionStorage so a later /lite visit resumes it', async () => {
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<LiteWidget urlToken="tok-from-url-2" />)

    await waitFor(() => expect(sessionStorage.getItem('soaLiteToken')).toBe('tok-from-url-2'))
  })

  it('renders the not-found state immediately for an empty urlToken, without polling', async () => {
    render(<LiteWidget urlToken="" />)

    expect(screen.getByText("We couldn't find this report")).toBeInTheDocument()
    expect(liteApi.getStatus).not.toHaveBeenCalled()
  })

  it('renders the not-found state on a 404 from getStatus, and stops polling', async () => {
    const err = new Error('Not found.')
    err.status = 404
    liteApi.getStatus.mockRejectedValue(err)

    render(<LiteWidget urlToken="tok-unknown" />)

    await waitFor(() => expect(screen.getByText("We couldn't find this report")).toBeInTheDocument())
    const callsAtNotFound = liteApi.getStatus.mock.calls.length
    // No further polling once terminal — same idiom as the 'failed' status check.
    await new Promise((r) => setTimeout(r, 20))
    expect(liteApi.getStatus.mock.calls.length).toBe(callsAtNotFound)
  })

  it('scrubs the dead token from sessionStorage on a 404, so it cannot poison a later /lite or /report visit', async () => {
    const err = new Error('Not found.')
    err.status = 404
    liteApi.getStatus.mockRejectedValue(err)

    render(<LiteWidget urlToken="tok-unknown-2" />)

    // The mount-time persist effect writes it optimistically; the 404 must
    // scrub it back out rather than leaving a dead token behind.
    await waitFor(() => expect(sessionStorage.getItem('soaLiteToken')).toBe('tok-unknown-2'))
    await waitFor(() => expect(screen.getByText("We couldn't find this report")).toBeInTheDocument())
    expect(sessionStorage.getItem('soaLiteToken')).toBeNull()
  })

  it('the not-found "Start a new audit" button navigates to \'/\' on the audit host', () => {
    mockAuditHost = true
    const navigate = vi.fn()
    render(<LiteWidget urlToken="" navigate={navigate} />)

    fireEvent.click(screen.getByText('Start a new audit'))
    expect(navigate).toHaveBeenCalledWith('/')
  })

  it('the not-found "Start a new audit" button does a full navigation to PUBLIC_AUDIT_BASE_URL on the marketing host', () => {
    // A plain mutable stand-in, not jsdom's real Location — assigning
    // .href below must not trigger jsdom's unimplemented cross-origin
    // navigation warning.
    useWritableLocation()
    const navigate = vi.fn()
    render(<LiteWidget urlToken="" navigate={navigate} />)

    fireEvent.click(screen.getByText('Start a new audit'))
    // A dead /report/{token} link on the marketing host has no local
    // landing page to send the visitor to anymore (H2 removed /scan) —
    // it must leave for the audit host's own landing page instead.
    expect(navigate).not.toHaveBeenCalled()
    expect(window.location.href).toBe(PUBLIC_AUDIT_BASE_URL)
  })
})

describe('LiteWidget — Stage 9: navigate after submit', () => {
  it('calls navigate with /report/{token} after a successful submission on the marketing host', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-nav', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })
    const navigate = vi.fn()

    render(<LiteWidget navigate={navigate} />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/report/tok-nav'))
  })

  it('calls navigate with /r/{token} after a successful submission on the audit host', async () => {
    mockAuditHost = true
    liteApi.submit.mockResolvedValue({ token: 'tok-audit-nav', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })
    const navigate = vi.fn()

    render(<LiteWidget navigate={navigate} />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('/r/tok-audit-nav'))
  })

  it('does not throw when navigate is omitted (today\'s exact /lite behavior)', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-no-nav', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<LiteWidget />)
    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(sessionStorage.getItem('soaLiteToken')).toBe('tok-no-nav'))
    expect(screen.queryByText(/is not a function/)).not.toBeInTheDocument()
  })
})

describe('LiteWidget — Stage 9: noindex meta (U4)', () => {
  it('adds <meta name="robots" content="noindex,nofollow"> once a token exists', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-noindex')
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<LiteWidget />)

    await waitFor(() => expect(queryNoindexMeta()).not.toBeNull())
  })

  it('does not add a noindex meta for the bare form (no token, not a report route)', () => {
    render(<LiteWidget />)
    expect(queryNoindexMeta()).toBeNull()
  })

  it('adds noindex for the not-found state on an empty urlToken (still a report route)', () => {
    render(<LiteWidget urlToken="" />)
    expect(queryNoindexMeta()).not.toBeNull()
  })

  it('S3: is a no-op on the audit host — audit-report.html already bakes noindex in statically', async () => {
    mockAuditHost = true
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<LiteWidget urlToken="tok-audit-noindex" />)
    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalled())
    expect(queryNoindexMeta()).toBeNull()
  })

  it('S2: does not duplicate a noindex tag the static document already has, on the audit host', async () => {
    mockAuditHost = true
    const staticMeta = document.createElement('meta')
    staticMeta.name = 'robots'
    staticMeta.content = 'noindex,nofollow'
    document.head.appendChild(staticMeta)
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })

    render(<LiteWidget urlToken="tok-audit-noindex-2" />)
    await waitFor(() => expect(liteApi.getStatus).toHaveBeenCalled())
    expect(document.head.querySelectorAll('meta[name="robots"]')).toHaveLength(1)

    document.head.removeChild(staticMeta)
  })
})

describe('LiteWidget — L1/L2: canonical link on the marketing host', () => {
  function queryCanonical() {
    return document.head.querySelector('link[rel="canonical"]')
  }

  it('L2: bare /lite form (no token) canonicalizes to PUBLIC_AUDIT_BASE_URL root', () => {
    render(<LiteWidget />)
    expect(queryCanonical()).toHaveAttribute('href', `${PUBLIC_AUDIT_BASE_URL}/`)
  })

  it('L1: /report/{token} canonicalizes to the audit host\'s /r/{token}', async () => {
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })
    render(<LiteWidget urlToken="tok-canonical" />)
    await waitFor(() => expect(queryCanonical()).toHaveAttribute('href', `${PUBLIC_AUDIT_BASE_URL}/r/tok-canonical`))
  })

  it('L1: a /lite session resumed from sessionStorage (token, but not a report route) also canonicalizes to /r/{token}', async () => {
    sessionStorage.setItem('soaLiteToken', 'tok-resumed')
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })
    render(<LiteWidget />)
    await waitFor(() => expect(queryCanonical()).toHaveAttribute('href', `${PUBLIC_AUDIT_BASE_URL}/r/tok-resumed`))
  })

  it('no canonical while showing the not-found state', () => {
    render(<LiteWidget urlToken="" />)
    expect(queryCanonical()).toBeNull()
  })

  it('no canonical added on the audit host itself — already canonical there', () => {
    mockAuditHost = true
    render(<LiteWidget urlToken="tok-on-audit" />)
    expect(queryCanonical()).toBeNull()
  })

  it('updates the canonical href in place across a state transition, without leaving a stale duplicate', async () => {
    liteApi.submit.mockResolvedValue({ token: 'tok-transition', status: 'pending' })
    liteApi.getStatus.mockResolvedValue({ status: 'pending', phase: 'queued', scan_status: null })
    render(<LiteWidget />)

    expect(queryCanonical()).toHaveAttribute('href', `${PUBLIC_AUDIT_BASE_URL}/`)

    fireEvent.change(screen.getByLabelText('Your brand or store URL'), { target: { value: 'Acme Co' } })
    fireEvent.click(screen.getByText('Run my free diagnostic'))

    await waitFor(() => expect(queryCanonical()).toHaveAttribute('href', `${PUBLIC_AUDIT_BASE_URL}/r/tok-transition`))
    expect(document.head.querySelectorAll('link[rel="canonical"]')).toHaveLength(1)
  })
})
