import React from 'react'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { LiteProgress, LiteFailed, projectEvents, estimateRemainingMinutes } from '../LiteProgress.jsx'
import { liteApi } from '../liteApi.js'

vi.mock('../liteApi.js', () => ({
  liteApi: { setEmail: vi.fn() },
}))

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const COMPONENT_SRC = fs.readFileSync(path.join(__dirname, '../LiteProgress.jsx'), 'utf-8')

function mockMatchMedia(matches) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
}

function ev(seq, kind, task, text, extra = {}) {
  return { seq, ts: `2026-01-01T00:00:${String(seq).padStart(2, '0')}Z`, kind, task, text, ...extra }
}

// ─── projectEvents — pure projection (M0-equivalent) ─────────────────────

describe('projectEvents — pure projection of one events[] snapshot', () => {
  it('empty/absent events project to an all-empty, zero-fraction shape', () => {
    expect(projectEvents(undefined)).toEqual({
      logEvents: [], doneEvents: [], latestState: null, completedFraction: 0, latestTs: null,
    })
    expect(projectEvents([])).toEqual({
      logEvents: [], doneEvents: [], latestState: null, completedFraction: 0, latestTs: null,
    })
  })

  it('splits log/done/state events into their own buckets', () => {
    const events = [
      ev(1, 'state', 'run', 'running'),
      ev(2, 'log', 'crawl', 'reading…'),
      ev(3, 'done', 'crawl', '3 pages read'),
    ]
    const p = projectEvents(events)
    expect(p.logEvents).toHaveLength(1)
    expect(p.doneEvents).toHaveLength(1)
    expect(p.latestState).toBe('running')
  })

  it('completedFraction counts DISTINCT tasks with a done event, over the fixed 8-task denominator', () => {
    const events = [
      ev(1, 'done', 'crawl', 'x'),
      ev(2, 'done', 'competitors', 'y'),
    ]
    expect(projectEvents(events).completedFraction).toBe(2 / 8)
  })

  it('a duplicate done event for the same task is not double-counted toward the fraction', () => {
    const events = [ev(1, 'done', 'crawl', 'x'), ev(2, 'done', 'crawl', 'x again')]
    expect(projectEvents(events).completedFraction).toBe(1 / 8)
  })

  it('latestState reads the LAST state-kind event, not the first', () => {
    const events = [ev(1, 'state', 'run', 'queued'), ev(2, 'state', 'run', 'running')]
    expect(projectEvents(events).latestState).toBe('running')
  })

  it('P3: doneEvents render in prepend (reverse-arrival) order — out-of-order completion fixture', () => {
    // Probes finish before crawl in production (see worker.py's docstrings) —
    // the projection must reflect ARRIVAL order, never a fixed task sequence.
    const events = [
      ev(1, 'done', 'probe_membership', 'Program found'),
      ev(2, 'done', 'crawl', '3 pages read'),
      ev(3, 'done', 'competitors', '2 found'),
    ]
    const doneTasks = projectEvents(events).doneEvents.map((e) => e.task)
    expect(doneTasks).toEqual(['competitors', 'crawl', 'probe_membership'])
  })

  it('is idempotent: re-projecting the identical array twice yields deep-equal output', () => {
    const events = [ev(1, 'log', 'crawl', 'x'), ev(2, 'done', 'crawl', 'y')]
    expect(projectEvents(events)).toEqual(projectEvents(events))
  })

  it('latestTs reads the final event in array (seq) order, regardless of kind', () => {
    const events = [ev(1, 'log', 'crawl', 'a'), ev(2, 'done', 'crawl', 'b')]
    expect(projectEvents(events).latestTs).toBe(events[1].ts)
  })
})

describe('estimateRemainingMinutes — ESTIMATE, never a promise', () => {
  it('returns null before there is enough signal (fraction < 0.05)', () => {
    expect(estimateRemainingMinutes(60, 0)).toBeNull()
    expect(estimateRemainingMinutes(60, 0.01)).toBeNull()
  })

  it('extrapolates total time from elapsed/fraction, then subtracts elapsed', () => {
    // 100s elapsed at 25% done -> ~400s total -> ~300s remaining -> 5 min (ceil)
    expect(estimateRemainingMinutes(100, 0.25)).toBe(5)
  })

  it('never goes negative — floors remaining at 0, minutes at 1', () => {
    expect(estimateRemainingMinutes(1000, 0.99)).toBe(1)
  })
})

// ─── LiteProgress — fallback view (P7: no events[] at all) ──────────────

describe('LiteProgress — P7 fallback (pre-deploy rows with no events[])', () => {
  it('renders header + chip + email band only — no console, no feed', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued' }} token="tok-1" />)
    expect(screen.getByText('AUDIT QUEUED')).toBeInTheDocument()
    expect(screen.queryByRole('log')).not.toBeInTheDocument()
    expect(screen.queryByText(/TASKS$/)).not.toBeInTheDocument()
    expect(screen.getByText('This takes a few minutes.')).toBeInTheDocument()
  })

  it('an explicitly empty events array is treated the same as absent', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running', events: [] }} />)
    expect(screen.queryByRole('log')).not.toBeInTheDocument()
  })

  it('a non-pending fallback status reads as running, not queued', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running' }} />)
    expect(screen.getByText('AUDIT RUNNING · USUALLY 10–20 MINUTES')).toBeInTheDocument()
  })
})

// ─── Header (P1) ──────────────────────────────────────────────────────────

describe('LiteProgress — header state chip, table-driven per kind=state value', () => {
  const cases = [
    ['queued', 'AUDIT QUEUED'],
    ['running', 'AUDIT RUNNING · USUALLY 10–20 MINUTES'],
    ['done', 'AUDIT COMPLETE'],
    ['failed', 'AUDIT FAILED'],
    ['degraded-blocked', 'AUDIT COMPLETE · SITE BLOCKED OUR READER'],
    ['no-product-pages', 'AUDIT COMPLETE · PRODUCT PAGES NOT FOUND'],
  ]

  it.each(cases)('state=%s renders chip "%s"', (state, label) => {
    const events = [ev(1, 'state', 'run', state)]
    render(<LiteProgress phaseData={{ status: 'running', events }} />)
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('brand/domain headline uses the store domain, and adopts the "audit" rename', () => {
    render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'state', 'run', 'running')] }} storeUrl="https://acme.com/shoes" />)
    expect(screen.getByText(/acme\.com — agentic value audit/)).toBeInTheDocument()
  })

  it('falls back to "Your store" when no store URL was given', () => {
    render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'state', 'run', 'running')] }} />)
    expect(screen.getByText(/Your store — agentic value audit/)).toBeInTheDocument()
  })

  it('shows the ESTIMATE countdown once there is enough completed-task signal', () => {
    const events = [
      ev(1, 'done', 'crawl', 'x'), ev(2, 'done', 'competitors', 'y'),
      ev(3, 'done', 'probe_membership', 'z'), ev(4, 'done', 'probe_revenue', 'w'),
    ]
    render(<LiteProgress phaseData={{ status: 'running', events }} />)
    expect(screen.getByText(/min remaining · ESTIMATE/)).toBeInTheDocument()
  })

  it('omits the countdown before there is any completed-task signal', () => {
    render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'state', 'run', 'running')] }} />)
    expect(screen.queryByText(/ESTIMATE/)).not.toBeInTheDocument()
  })

  it('shows the elapsed clock only while active', () => {
    render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'state', 'run', 'running')] }} />)
    expect(screen.getByTestId('lite-elapsed')).toBeInTheDocument()
  })

  it('hides the elapsed clock once complete', () => {
    render(<LiteProgress phaseData={{ status: 'complete', events: [ev(1, 'state', 'run', 'done')] }} />)
    expect(screen.queryByTestId('lite-elapsed')).not.toBeInTheDocument()
  })
})

// ─── Console (P2) ──────────────────────────────────────────────────────────

describe('LiteProgress — console', () => {
  afterEach(() => { delete window.matchMedia })

  it('is a role=log, aria-live=polite region', () => {
    render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'log', 'crawl', 'reading…')] }} />)
    const body = screen.getByTestId('lite-console-body')
    expect(body).toHaveAttribute('aria-live', 'polite')
    expect(screen.getByRole('log')).toBe(body)
  })

  it('renders each log line with its task tag and text', () => {
    render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'log', 'crawl', 'reading acme.com…')] }} />)
    expect(screen.getByText('READING YOUR STORE')).toBeInTheDocument()
    expect(screen.getByText('reading acme.com…')).toBeInTheDocument()
  })

  it('shows a placeholder line before any log event has landed', () => {
    render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'state', 'run', 'running')] }} />)
    expect(screen.getByText('Starting up…')).toBeInTheDocument()
  })

  it('reduced-motion: the LIVE dot loses its pulse class', () => {
    mockMatchMedia(true)
    const { container } = render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'log', 'crawl', 'x')] }} />)
    const dot = container.querySelector('.lite-console-live-dot')
    expect(dot).not.toHaveClass('lite-console-live-dot--pulse')
  })

  it('full motion (default): the LIVE dot carries the pulse class', () => {
    mockMatchMedia(false)
    const { container } = render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'log', 'crawl', 'x')] }} />)
    expect(container.querySelector('.lite-console-live-dot--pulse')).toBeInTheDocument()
  })

  it('scroll-lock: once the user scrolls away from the bottom, a new log line does not force scrollTop back down', () => {
    const running = { status: 'running', events: [ev(1, 'log', 'crawl', 'first')] }
    const { rerender } = render(<LiteProgress phaseData={running} />)
    const body = screen.getByTestId('lite-console-body')

    Object.defineProperty(body, 'scrollHeight', { value: 1000, configurable: true })
    Object.defineProperty(body, 'clientHeight', { value: 200, configurable: true })
    Object.defineProperty(body, 'scrollTop', { value: 0, configurable: true, writable: true })
    fireEvent.scroll(body) // distanceFromBottom = 800 -> not pinned

    rerender(<LiteProgress phaseData={{ status: 'running', events: [...running.events, ev(2, 'log', 'crawl', 'second')] }} />)
    expect(body.scrollTop).toBe(0) // never jumped to scrollHeight
  })
})

describe('LiteProgress — staleness (P5)', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  const running = { status: 'running', events: [ev(1, 'state', 'run', 'running'), ev(2, 'log', 'crawl', 'reading…')] }

  it('shows the quiet stalled line after 90s with no new event', async () => {
    const { rerender } = render(<LiteProgress phaseData={running} />)
    expect(screen.queryByText(/no updates for a while/)).not.toBeInTheDocument()

    await act(async () => { vi.advanceTimersByTime(91_000) })
    rerender(<LiteProgress phaseData={{ ...running }} />)
    expect(screen.getByText('no updates for a while — still checking…')).toBeInTheDocument()
  })

  it('clears once a new event lands (latestTs advances)', async () => {
    const { rerender } = render(<LiteProgress phaseData={running} />)
    await act(async () => { vi.advanceTimersByTime(91_000) })
    rerender(<LiteProgress phaseData={{ ...running }} />)
    expect(screen.getByText(/no updates for a while/)).toBeInTheDocument()

    rerender(<LiteProgress phaseData={{
      status: 'running',
      events: [...running.events, ev(3, 'log', 'crawl', 'still reading…')],
    }} />)
    expect(screen.queryByText(/no updates for a while/)).not.toBeInTheDocument()
  })

  it('never fires before the 90s threshold', async () => {
    const { rerender } = render(<LiteProgress phaseData={running} />)
    await act(async () => { vi.advanceTimersByTime(60_000) })
    rerender(<LiteProgress phaseData={{ ...running }} />)
    expect(screen.queryByText(/no updates for a while/)).not.toBeInTheDocument()
  })

  it('never shows once the run has completed', () => {
    render(<LiteProgress phaseData={{ status: 'complete', events: [ev(1, 'state', 'run', 'done')] }} />)
    expect(screen.queryByText(/no updates for a while/)).not.toBeInTheDocument()
  })
})

// ─── Completion feed (P3) ──────────────────────────────────────────────────

describe('LiteProgress — completion feed', () => {
  afterEach(() => { delete window.matchMedia })

  it('starts empty with the exact placeholder copy', () => {
    render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'state', 'run', 'running')] }} />)
    expect(screen.getByText('Tasks will appear here as they finish…')).toBeInTheDocument()
  })

  it('renders arrival order (newest first / prepended), not a fixed task sequence', () => {
    const events = [
      ev(1, 'done', 'probe_membership', 'Program found'),
      ev(2, 'done', 'crawl', '3 pages read'),
    ]
    const { container } = render(<LiteProgress phaseData={{ status: 'running', events }} />)
    const names = Array.from(container.querySelectorAll('.lite-feed-card')).map((el) => el.textContent)
    expect(names[0]).toMatch(/Reading your store/)
    expect(names[1]).toMatch(/Membership check/)
  })

  it('renders chips on a done event that carries them', () => {
    const events = [ev(1, 'done', 'competitors', '2 found', { chips: ['Rival', 'OtherCo'] })]
    render(<LiteProgress phaseData={{ status: 'running', events }} />)
    expect(screen.getByText('Rival')).toBeInTheDocument()
    expect(screen.getByText('OtherCo')).toBeInTheDocument()
  })

  it('the counter reads "n OF 8 TASKS", derived from distinct done tasks', () => {
    const events = [ev(1, 'done', 'crawl', 'x'), ev(2, 'done', 'competitors', 'y')]
    render(<LiteProgress phaseData={{ status: 'running', events }} />)
    expect(screen.getByText('2 OF 8 TASKS')).toBeInTheDocument()
  })

  it('reduced-motion: cards render without the arrival-animation class', () => {
    mockMatchMedia(true)
    const events = [ev(1, 'done', 'crawl', 'x')]
    const { container } = render(<LiteProgress phaseData={{ status: 'running', events }} />)
    expect(container.querySelector('.lite-feed-card--enter')).not.toBeInTheDocument()
  })

  it('full motion (default): cards carry the arrival-animation class', () => {
    mockMatchMedia(false)
    const events = [ev(1, 'done', 'crawl', 'x')]
    const { container } = render(<LiteProgress phaseData={{ status: 'running', events }} />)
    expect(container.querySelector('.lite-feed-card--enter')).toBeInTheDocument()
  })
})

// ─── Terminal banners (P4) ──────────────────────────────────────────────────

describe('LiteProgress — terminal banners reuse the hotfix-3/5 DegradedRunBanner', () => {
  it('degraded-blocked state renders the honest blocked banner', () => {
    const events = [ev(1, 'state', 'run', 'degraded-blocked')]
    render(<LiteProgress phaseData={{
      status: 'complete', scan_status: 'blocked',
      degraded_reason: 'blocked',
      degraded_banner_facts: { refusal: '429', attempts: 3, robots_included: false },
      events,
    }} />)
    expect(screen.getByText(/rate-limited our identified reader on every page we tried/)).toBeInTheDocument()
  })

  it('no-product-pages state renders the sampler-scoped banner', () => {
    const events = [ev(1, 'state', 'run', 'no-product-pages')]
    render(<LiteProgress phaseData={{
      status: 'complete', scan_status: 'blocked',
      degraded_reason: 'no_product_pages_found',
      degraded_banner_facts: { sitemaps_read: 2 },
      events,
    }} />)
    expect(screen.getByText(/couldn't locate product pages to sample/)).toBeInTheDocument()
  })

  it('a normal "done" state never renders the banner', () => {
    const events = [ev(1, 'state', 'run', 'done')]
    render(<LiteProgress phaseData={{ status: 'complete', scan_status: 'complete', events }} />)
    expect(screen.queryByText(/NOT MEASURABLE/)).not.toBeInTheDocument()
  })

  it('a running state never renders the banner', () => {
    const events = [ev(1, 'state', 'run', 'running')]
    render(<LiteProgress phaseData={{ status: 'running', events }} />)
    expect(screen.queryByText(/NOT MEASURABLE/)).not.toBeInTheDocument()
  })
})

// ─── Email band (P6) — unchanged behavior ──────────────────────────────────

describe('LiteProgress — email band, verbatim copy, unchanged (P6)', () => {
  it('renders while active, with the exact notify-only copy', () => {
    render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'state', 'run', 'running')] }} token="tok-1" />)
    expect(screen.getByText('This takes a few minutes.')).toBeInTheDocument()
    expect(screen.getByText(
      /Leave your email and we'll send your report the moment it's ready — no need to keep this tab open\./,
    )).toBeInTheDocument()
  })

  it('is absent once the run is no longer active', () => {
    render(<LiteProgress phaseData={{ status: 'complete', events: [ev(1, 'state', 'run', 'done')] }} token="tok-1" />)
    expect(screen.queryByText('This takes a few minutes.')).not.toBeInTheDocument()
  })

  it('is absent with no token, even while active', () => {
    render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'state', 'run', 'running')] }} />)
    expect(screen.queryByText('This takes a few minutes.')).not.toBeInTheDocument()
  })

  it('submitting an email swaps to the exact masked confirmation copy', async () => {
    liteApi.setEmail.mockResolvedValue({})
    render(<LiteProgress phaseData={{ status: 'running', events: [ev(1, 'state', 'run', 'running')] }} token="tok-1" />)
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'visitor@example.com' } })
    await act(async () => { fireEvent.click(screen.getByText('Email me the report')) })
    expect(await screen.findByText(/We'll email your report to/)).toBeInTheDocument()
  })
})

// ─── LiteFailed — unchanged ─────────────────────────────────────────────────

describe('LiteFailed', () => {
  it('renders the honest retry view and calls onRetry', () => {
    const onRetry = vi.fn()
    render(<LiteFailed onRetry={onRetry} />)
    screen.getByText('Try again').click()
    expect(onRetry).toHaveBeenCalled()
  })
})

// ─── Mobile 360 ─────────────────────────────────────────────────────────────

describe('LiteProgress — mobile render at 360px', () => {
  const originalInnerWidth = window.innerWidth
  afterEach(() => { Object.defineProperty(window, 'innerWidth', { value: originalInnerWidth, configurable: true }) })

  it('renders the full console + feed without throwing at a 360px viewport', () => {
    Object.defineProperty(window, 'innerWidth', { value: 360, configurable: true })
    const events = [
      ev(1, 'state', 'run', 'running'),
      ev(2, 'log', 'crawl', 'reading a-very-long-example-storefront-domain-name.example.com…'),
      ev(3, 'done', 'competitors', '2 found', { chips: ['Rival', 'OtherCo'] }),
    ]
    expect(() => render(<LiteProgress phaseData={{ status: 'running', events }} storeUrl="acme.com" />)).not.toThrow()
    expect(screen.getByText('READING YOUR STORE')).toBeInTheDocument()
    expect(screen.getByText('1 OF 8 TASKS')).toBeInTheDocument()
  })
})

// ─── Grep sweeps ────────────────────────────────────────────────────────────

describe('LiteProgress — grep sweeps', () => {
  it('the retired six-row manifest is fully gone from the source', () => {
    expect(COMPONENT_SRC).not.toMatch(/\bderiveManifestRows\b/)
    expect(COMPONENT_SRC).not.toMatch(/\bManifestRow\b/)
    expect(COMPONENT_SRC).not.toMatch(/\bROW_DEFS\b/)
  })

  it('the retired "No store URL was provided this run." copy is gone', () => {
    expect(COMPONENT_SRC).not.toContain('No store URL was provided this run.')
  })

  it('no literal "scan" in any new user-facing string — this surface is "audit"-branded', () => {
    const userFacingScanMatches = COMPONENT_SRC.match(/>[^<]*\bscan\b[^<]*</gi) || []
    expect(userFacingScanMatches).toEqual([])
  })
})
