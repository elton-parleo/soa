import React from 'react'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'

import { LiteProgress, LiteFailed, deriveManifestRows, aggregatePct } from '../LiteProgress.jsx'
import { liteApi } from '../liteApi.js'

vi.mock('../liteApi.js', () => ({
  liteApi: { setEmail: vi.fn() },
}))

function mockMatchMedia(matches) {
  window.matchMedia = vi.fn().mockImplementation((query) => ({
    matches,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }))
}

const ROW_KEYS = [
  'reading_store', 'membership_check', 'competitor_set',
  'shopper_questions', 'scoring_answers', 'your_report',
]

function rowsByKey(rows) {
  const map = {}
  rows.forEach((r) => { map[r.key] = r })
  return map
}

// ─── M0: deriveManifestRows is a pure projection of one snapshot ─────────

describe('deriveManifestRows — M0 pure projection, table-driven per phase', () => {
  it('queued, no store_url: every row pending or na, nothing active', () => {
    const rows = deriveManifestRows({ status: 'pending', phase: 'queued' }, null)
    expect(rows.map((r) => r.key)).toEqual(ROW_KEYS)
    const byKey = rowsByKey(rows)
    expect(byKey.reading_store.state).toBe('na') // no store_url -> immediately na, nothing to wait for
    expect(byKey.membership_check.state).toBe('pending')
    expect(byKey.competitor_set.state).toBe('pending')
    expect(byKey.shopper_questions.state).toBe('pending')
    expect(byKey.scoring_answers.state).toBe('pending')
    expect(byKey.your_report.state).toBe('pending')
  })

  it('identifying_competitors: competitor row active, scan/membership active once the scan row exists', () => {
    const rows = deriveManifestRows({ status: 'identifying_competitors', phase: 'identifying_competitors' }, 'acme.com')
    const byKey = rowsByKey(rows)
    expect(byKey.competitor_set.state).toBe('active')
    expect(byKey.reading_store.state).toBe('pending') // scan row doesn't exist yet (no scan_status)
    expect(byKey.membership_check.state).toBe('pending')
  })

  it('regression: competitor_names starting as [] (the visitor\'s own empty manual list, present from the very first poll) never reads as an already-resolved solo run', () => {
    // Caught via a real live run (Stage 20 acceptance): competitor_names
    // is written at submission time from the visitor's manual input
    // (usually []) — only competitor_source is null until process_lite_
    // requests' auto-generation step actually writes both fields
    // together. Using competitors==null as the "resolved" signal would
    // misread this as a genuine solo run before generation even started.
    const rows = deriveManifestRows({ status: 'pending', phase: 'queued', competitors: [], competitor_source: null }, 'acme.com')
    expect(rowsByKey(rows).competitor_set.state).toBe('pending')
  })

  it('running with a store_url and scan in flight: scan/membership active, competitors done, queries active', () => {
    const rows = deriveManifestRows({
      status: 'running', phase: 'running', scan_status: 'running',
      competitors: ['Rival Co'], competitor_source: 'generated', progress: { completed_runs: 3, total_runs: 12 },
    }, 'acme.com')
    const byKey = rowsByKey(rows)
    expect(byKey.reading_store.state).toBe('active')
    expect(byKey.membership_check.state).toBe('active')
    expect(byKey.competitor_set.state).toBe('done')
    expect(byKey.competitor_set.chips).toEqual(['Rival Co'])
    expect(byKey.shopper_questions.state).toBe('active')
    expect(byKey.shopper_questions.detail).toBe('3 of 12 answers')
    expect(byKey.shopper_questions.qbarPct).toBe(25)
  })

  it('mid-run snapshot: rows 1-3 done, row 4 (shopper questions) at 7 of 12', () => {
    const rows = deriveManifestRows({
      status: 'running', phase: 'running', scan_status: 'complete', scan_pages_read: 9,
      membership_check: 'applies', competitors: ['Hoka', 'On'], competitor_source: 'generated',
      progress: { completed_runs: 7, total_runs: 12 },
    }, 'acme.com')
    const byKey = rowsByKey(rows)
    expect(byKey.reading_store.state).toBe('done')
    expect(byKey.reading_store.detail).toBe('9 pages read — catalog, loyalty, and protocol surfaces')
    expect(byKey.membership_check.state).toBe('done')
    expect(byKey.competitor_set.state).toBe('done')
    expect(byKey.shopper_questions.state).toBe('active')
    expect(byKey.shopper_questions.detail).toBe('7 of 12 answers')
    expect(byKey.scoring_answers.state).toBe('pending')
    expect(byKey.your_report.state).toBe('pending')
  })

  it('coding phase: shopper questions done, scoring active', () => {
    const rows = deriveManifestRows({
      status: 'running', phase: 'coding', progress: { completed_runs: 12, total_runs: 12 },
    }, null)
    const byKey = rowsByKey(rows)
    expect(byKey.shopper_questions.state).toBe('done')
    expect(byKey.shopper_questions.stamp).toBe('12 OF 12')
    expect(byKey.scoring_answers.state).toBe('active')
  })

  it('metrics phase: scoring done (pillar names from the registry), report assembling', () => {
    const rows = deriveManifestRows({ status: 'running', phase: 'metrics' }, null)
    const byKey = rowsByKey(rows)
    expect(byKey.scoring_answers.state).toBe('done')
    expect(byKey.scoring_answers.detail).toBe('Scored across Visibility, Accessibility, and True Value')
    expect(byKey.your_report.state).toBe('active')
  })

  it('complete: your report done and READY', () => {
    const rows = deriveManifestRows({ status: 'complete', phase: 'complete' }, null)
    const byKey = rowsByKey(rows)
    expect(byKey.your_report.state).toBe('done')
    expect(byKey.your_report.stamp).toBe('READY')
  })

  it('legacy analyzing phase fallback: treated the same as coding', () => {
    const rows = deriveManifestRows({
      status: 'running', phase: 'analyzing', progress: { completed_runs: 12, total_runs: 12 },
    }, null)
    const byKey = rowsByKey(rows)
    expect(byKey.shopper_questions.state).toBe('done')
    expect(byKey.scoring_answers.state).toBe('active')
  })
})

// ─── Out-of-order completion (S1) ─────────────────────────────────────────

describe('deriveManifestRows — rows complete out of visual order (S1)', () => {
  it('scan complete while querying is still in progress: row 0 done + row 3 active simultaneously', () => {
    const rows = deriveManifestRows({
      status: 'running', phase: 'running', scan_status: 'complete', scan_pages_read: 5,
      progress: { completed_runs: 2, total_runs: 12 },
    }, 'acme.com')
    const byKey = rowsByKey(rows)
    expect(byKey.reading_store.state).toBe('done')
    expect(byKey.shopper_questions.state).toBe('active')
    // Display order is always fixed, regardless of which finished first.
    expect(rows.map((r) => r.key)).toEqual(ROW_KEYS)
  })

  it('multiple rows active at once each carry their own independent detail', () => {
    const rows = deriveManifestRows({
      status: 'running', phase: 'running', scan_status: 'running',
      progress: { completed_runs: 1, total_runs: 12 },
    }, 'acme.com')
    const byKey = rowsByKey(rows)
    expect(byKey.reading_store.state).toBe('active')
    expect(byKey.membership_check.state).toBe('active')
    expect(byKey.shopper_questions.state).toBe('active')
    expect(byKey.reading_store.detail).not.toBe(byKey.membership_check.detail)
  })
})

// ─── Membership-check row variants ────────────────────────────────────────

describe('deriveManifestRows — membership-check row (applies / na / pending)', () => {
  it('applies: matches the report\'s scoring language', () => {
    const rows = deriveManifestRows({ status: 'running', phase: 'running', membership_check: 'applies' }, 'acme.com')
    expect(rowsByKey(rows).membership_check.detail).toBe('Program found — Member Value will be scored')
    expect(rowsByKey(rows).membership_check.state).toBe('done')
  })

  it('na: matches the report\'s normalization language', () => {
    const rows = deriveManifestRows({ status: 'running', phase: 'running', membership_check: 'na' }, 'acme.com')
    expect(rowsByKey(rows).membership_check.detail).toBe('No program found — scoring normalized')
    expect(rowsByKey(rows).membership_check.state).toBe('na')
  })

  it('pending/unresolved probe never renders applies or na copy', () => {
    const rows = deriveManifestRows({ status: 'running', phase: 'running', scan_status: 'running' }, 'acme.com')
    const row = rowsByKey(rows).membership_check
    expect(row.state).toBe('active')
    expect(row.detail).not.toMatch(/Program found|scoring normalized/)
  })
})

// ─── Blocked/failed/skipped scan completes honestly, never as an error ────

describe('deriveManifestRows — reading-your-store row degrades honestly (rule 7)', () => {
  it.each(['blocked', 'failed', 'skipped'])('scan_status=%s completes the row with honest text, styled na not error', (scanStatus) => {
    const rows = deriveManifestRows({ status: 'running', phase: 'running', scan_status: scanStatus }, 'acme.com')
    const row = rowsByKey(rows).reading_store
    expect(row.state).toBe('na')
    expect(row.fraction).toBe(1) // counts toward the aggregate bar — never stuck
    expect(row.detail).toMatch(/acme\.com/)
  })

  it('no store_url at all renders na immediately, not pending forever', () => {
    const rows = deriveManifestRows({ status: 'pending', phase: 'queued' }, null)
    expect(rowsByKey(rows).reading_store.state).toBe('na')
  })
})

// ─── Failed run: no row keeps pulsing ─────────────────────────────────────

describe('deriveManifestRows — failed run never leaves a pulsing row', () => {
  it('an in-flight row collapses to na (no active state survives a failed status)', () => {
    const rows = deriveManifestRows({
      status: 'failed', phase: 'failed', scan_status: 'running',
      progress: { completed_runs: 3, total_runs: 12 },
    }, 'acme.com')
    expect(rows.every((r) => r.state !== 'active')).toBe(true)
  })

  it('rows already done before the failure keep their done state', () => {
    const rows = deriveManifestRows({
      status: 'failed', phase: 'failed', scan_status: 'complete', scan_pages_read: 4,
      membership_check: 'applies',
    }, 'acme.com')
    const byKey = rowsByKey(rows)
    expect(byKey.reading_store.state).toBe('done')
    expect(byKey.membership_check.state).toBe('done')
  })
})

// ─── Aggregate bar ─────────────────────────────────────────────────────────

describe('aggregatePct — weighted step completion', () => {
  it('0% at the very start (a real request always has a store_url — nothing na yet)', () => {
    expect(aggregatePct(deriveManifestRows({ status: 'pending', phase: 'queued' }, 'acme.com'))).toBe(0)
  })

  it('a brand-only submission (no store_url) starts above 0% — that row resolves na immediately, not stuck', () => {
    expect(aggregatePct(deriveManifestRows({ status: 'pending', phase: 'queued' }, null))).toBe(14)
  })

  it('100% once every row has genuinely resolved (a real complete run always has by then)', () => {
    const rows = deriveManifestRows({
      status: 'complete', phase: 'complete', scan_status: 'complete', scan_pages_read: 9,
      membership_check: 'applies', competitors: ['Rival Co'], competitor_source: 'generated',
      progress: { completed_runs: 12, total_runs: 12 },
    }, 'acme.com')
    expect(aggregatePct(rows)).toBe(100)
  })

  it('reflects partial query progress proportionally within the queries weight', () => {
    const half = aggregatePct(deriveManifestRows({
      status: 'running', phase: 'running', progress: { completed_runs: 6, total_runs: 12 },
    }, null))
    const none = aggregatePct(deriveManifestRows({
      status: 'running', phase: 'running', progress: { completed_runs: 0, total_runs: 12 },
    }, null))
    expect(half).toBeGreaterThan(none)
  })
})

// ─── Leak rule ─────────────────────────────────────────────────────────────

describe('LiteProgress — leak rule: no purchase-stage names anywhere', () => {
  it('a rich, multi-row-active snapshot never surfaces a stage name', () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running', scan_status: 'running',
      membership_check: 'pending', competitors: ['Rival Co'], competitor_source: 'generated',
      progress: { completed_runs: 5, total_runs: 12 },
    }} storeUrl="acme.com" token="tok-1" />)
    const text = document.body.textContent.toLowerCase()
    ;['awareness', 'research', 'comparison', 'ready to buy', 'stage-by-stage'].forEach((word) => {
      expect(text).not.toContain(word)
    })
  })
})

// ─── Component rendering ───────────────────────────────────────────────────

describe('LiteProgress — renders the manifest rows', () => {
  it('renders all six row names in fixed order', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued' }} />)
    const names = screen.getAllByText(/Reading your store|Membership check|Competitor set|Shopper questions|Scoring the answers|Your report/)
    expect(names.map((n) => n.textContent)).toEqual([
      'Reading your store', 'Membership check', 'Competitor set',
      'Shopper questions', 'Scoring the answers', 'Your report',
    ])
  })

  it('renders competitor chips once populated', () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running', competitors: ['Rival Co', 'Gen One'], competitor_source: 'generated',
      progress: { completed_runs: 1, total_runs: 12 },
    }} />)
    expect(screen.getByText('Rival Co')).toBeInTheDocument()
    expect(screen.getByText('Gen One')).toBeInTheDocument()
    expect(screen.getByText('2 FOUND')).toBeInTheDocument()
  })

  it('renders the solo-run copy when competitors resolves to an empty set', () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running', competitors: [], competitor_source: 'none',
      progress: { completed_runs: 1, total_runs: 12 },
    }} />)
    expect(screen.getByText('Running solo — no close rivals identified')).toBeInTheDocument()
  })

  it('renders an error banner when passed', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued' }} error="Could not check status." />)
    expect(screen.getByText('Could not check status.')).toBeInTheDocument()
  })
})

describe('LiteFailed', () => {
  it('calls onRetry when the button is clicked', () => {
    const onRetry = vi.fn()
    render(<LiteFailed onRetry={onRetry} />)
    screen.getByText('Try again').click()
    expect(onRetry).toHaveBeenCalled()
  })
})

describe('LiteProgress — elapsed time counter (Stage 12, unchanged)', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('ticks up from 0:00 as time passes while active', async () => {
    render(<LiteProgress phaseData={{
      status: 'running', phase: 'running', progress: { completed_runs: 1, total_runs: 12 },
    }} />)
    expect(screen.getByTestId('lite-elapsed')).toHaveTextContent('0:00')
    await act(async () => { vi.advanceTimersByTime(3000) })
    expect(screen.getByTestId('lite-elapsed')).toHaveTextContent('0:03')
  })

  it('omits the elapsed clock once the run is complete or failed', () => {
    render(<LiteProgress phaseData={{ status: 'complete', phase: 'complete' }} />)
    expect(screen.queryByTestId('lite-elapsed')).not.toBeInTheDocument()
  })
})

describe('LiteProgress — stalled-state honesty, driven by the manifest signature (Stage 12/20)', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  const running = { status: 'running', phase: 'running', progress: { completed_runs: 4, total_runs: 12 } }

  it('shows a quiet stalled line after 90s with no change to any row', async () => {
    const { rerender } = render(<LiteProgress phaseData={running} />)
    expect(screen.queryByText(/Still working/)).not.toBeInTheDocument()

    await act(async () => { vi.advanceTimersByTime(91_000) })
    rerender(<LiteProgress phaseData={{ ...running }} />)
    expect(screen.getByText('Still working — long queries can take a while.')).toBeInTheDocument()
  })

  it('clears once query progress changes', async () => {
    const { rerender } = render(<LiteProgress phaseData={running} />)
    await act(async () => { vi.advanceTimersByTime(91_000) })
    rerender(<LiteProgress phaseData={{ ...running }} />)
    expect(screen.getByText(/Still working/)).toBeInTheDocument()

    rerender(<LiteProgress phaseData={{
      status: 'running', phase: 'running', progress: { completed_runs: 5, total_runs: 12 },
    }} />)
    expect(screen.queryByText(/Still working/)).not.toBeInTheDocument()
  })

  it('also resets when a non-query row changes (e.g. membership_check resolves)', async () => {
    const { rerender } = render(<LiteProgress phaseData={running} storeUrl="acme.com" />)
    await act(async () => { vi.advanceTimersByTime(91_000) })
    rerender(<LiteProgress phaseData={{ ...running }} storeUrl="acme.com" />)
    expect(screen.getByText(/Still working/)).toBeInTheDocument()

    rerender(<LiteProgress phaseData={{ ...running, membership_check: 'applies' }} storeUrl="acme.com" />)
    expect(screen.queryByText(/Still working/)).not.toBeInTheDocument()
  })

  it('never shows before the 90s threshold', async () => {
    const { rerender } = render(<LiteProgress phaseData={running} />)
    await act(async () => { vi.advanceTimersByTime(60_000) })
    rerender(<LiteProgress phaseData={{ ...running }} />)
    expect(screen.queryByText(/Still working/)).not.toBeInTheDocument()
  })

  it('a failed run never shows the stalled line or the elapsed clock', () => {
    render(<LiteProgress phaseData={{ status: 'failed', phase: 'failed' }} />)
    expect(screen.queryByTestId('lite-elapsed')).not.toBeInTheDocument()
    expect(screen.queryByText(/Still working/)).not.toBeInTheDocument()
  })
})

describe('LiteProgress — reduced motion (S5)', () => {
  afterEach(() => { delete window.matchMedia })

  it('full motion (default): the active row glyph carries the pulse class', () => {
    const { container } = render(<LiteProgress phaseData={{
      status: 'running', phase: 'running', progress: { completed_runs: 1, total_runs: 12 },
    }} />)
    expect(container.querySelector('.lite-manifest-glyph--pulse')).not.toBeNull()
  })

  it('reduced motion: no glyph carries the pulse class, active row still renders its state', () => {
    mockMatchMedia(true)
    const { container } = render(<LiteProgress phaseData={{
      status: 'running', phase: 'running', progress: { completed_runs: 1, total_runs: 12 },
    }} />)
    expect(container.querySelector('.lite-manifest-glyph--pulse')).toBeNull()
    expect(screen.getByText('1 of 12 answers')).toBeInTheDocument()
  })
})

describe('LiteProgress — refresh/revisit is idempotent (M0)', () => {
  it('the same snapshot renders identical manifest content on a fresh mount', () => {
    const snapshot = {
      status: 'running', phase: 'running', scan_status: 'complete', scan_pages_read: 6,
      membership_check: 'na', competitors: ['Hoka'], competitor_source: 'generated',
      progress: { completed_runs: 4, total_runs: 12 },
    }
    const first = render(<LiteProgress phaseData={snapshot} storeUrl="acme.com" />)
    const firstText = first.container.textContent
    first.unmount()

    const second = render(<LiteProgress phaseData={snapshot} storeUrl="acme.com" />)
    expect(second.container.textContent).toBe(firstText)
  })
})

// ─── Acceptance artifact: real GET /status responses ──────────────────────
// Captured verbatim from public_lite.get_lite_status against two real
// production tokens (a v3 allbirds row and an older, pre-membership-probe
// row) — proves membership_check/scan_pages_read compute correctly (and
// degrade honestly) against real data, not just synthetic fixtures.
describe('LiteProgress — acceptance artifacts: real status responses', () => {
  it('a real, fully-resolved v3 row renders every row done, nothing stuck', () => {
    const status = {
      status: 'complete', phase: 'complete', progress: null, scan_status: 'complete',
      competitors: ["Rothy's", 'Veja', 'Cariuma', 'Skechers', 'Cole Haan'],
      competitor_source: 'generated', membership_check: 'applies', scan_pages_read: 11,
    }
    render(<LiteProgress phaseData={status} storeUrl="https://allbirds.com" />)
    expect(screen.getByText('11 pages read — catalog, loyalty, and protocol surfaces')).toBeInTheDocument()
    expect(screen.getByText('Program found — Member Value will be scored')).toBeInTheDocument()
    expect(screen.getByText('5 FOUND')).toBeInTheDocument()
    expect(screen.getByText('READY')).toBeInTheDocument()

    const rows = deriveManifestRows(status, 'https://allbirds.com')
    expect(rows.every((r) => r.state === 'done')).toBe(true)
  })

  it('a real pre-membership-probe row (probe never ran) degrades honestly, never crashes', () => {
    const status = {
      status: 'complete', phase: 'complete', progress: null, scan_status: 'complete',
      competitors: ["Rothy's", 'Veja', 'Cariuma', 'Vessi', 'Birdies'],
      competitor_source: 'generated', membership_check: 'pending', scan_pages_read: 11,
    }
    expect(() => render(<LiteProgress phaseData={status} storeUrl="https://allbirds.com" />)).not.toThrow()
    // Every other row still resolves correctly even though this one field
    // is stuck pending on an old row the probe predates.
    expect(screen.getByText('11 pages read — catalog, loyalty, and protocol surfaces')).toBeInTheDocument()
    expect(screen.getByText('READY')).toBeInTheDocument()
  })
})

describe('LiteProgress — status-page email card (E1, unchanged)', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('is omitted entirely when no token is available yet', () => {
    render(<LiteProgress phaseData={{ status: 'pending', phase: 'queued' }} />)
    expect(screen.queryByText('This takes a few minutes.')).not.toBeInTheDocument()
  })

  it('is omitted once the run is complete or failed', () => {
    render(<LiteProgress phaseData={{ status: 'complete', phase: 'complete' }} token="tok-1" />)
    expect(screen.queryByText('This takes a few minutes.')).not.toBeInTheDocument()
  })

  it('renders the ask, submits via the existing PATCH /email endpoint, and collapses to a masked confirmation', async () => {
    liteApi.setEmail.mockResolvedValue({ status: 'running', phase: 'running' })
    render(<LiteProgress
      phaseData={{ status: 'running', phase: 'running', progress: { completed_runs: 1, total_runs: 12 } }}
      token="tok-1"
    />)

    expect(screen.getByText('This takes a few minutes.')).toBeInTheDocument()
    const input = screen.getByPlaceholderText('you@company.com')
    fireEvent.change(input, { target: { value: 'visitor@example.com' } })
    fireEvent.click(screen.getByText('Email me the report'))

    await waitFor(() => expect(liteApi.setEmail).toHaveBeenCalledWith('tok-1', 'visitor@example.com'))
    await waitFor(() => expect(screen.getByText(/We'll email your report to v\*\*\*@example\.com/)).toBeInTheDocument())
    expect(screen.getByText(/You can also keep watching here/)).toBeInTheDocument()
  })

  it('shows a validation error for an invalid email and never calls the API', async () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running' }} token="tok-1" />)
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'not-an-email' } })
    fireEvent.click(screen.getByText('Email me the report'))
    await waitFor(() => expect(screen.getByText('Enter a valid email address')).toBeInTheDocument())
    expect(liteApi.setEmail).not.toHaveBeenCalled()
  })

  it('shows an inline error and stays on the form when the API call fails', async () => {
    liteApi.setEmail.mockRejectedValue(new Error('Something went wrong. Please try again.'))
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running' }} token="tok-1" />)
    fireEvent.change(screen.getByPlaceholderText('you@company.com'), { target: { value: 'visitor@example.com' } })
    fireEvent.click(screen.getByText('Email me the report'))
    await waitFor(() => expect(screen.getByText('Something went wrong. Please try again.')).toBeInTheDocument())
    expect(screen.getByText('This takes a few minutes.')).toBeInTheDocument()
  })

  it('the email input is keyboard-accessible with an accessible name', () => {
    render(<LiteProgress phaseData={{ status: 'running', phase: 'running' }} token="tok-1" />)
    const input = screen.getByPlaceholderText('you@company.com')
    expect(input.tagName).toBe('INPUT')
    expect(input).toHaveAttribute('type', 'email')
    const button = screen.getByText('Email me the report')
    expect(button.tagName).toBe('BUTTON')
  })
})
