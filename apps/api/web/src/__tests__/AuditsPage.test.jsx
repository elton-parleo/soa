/**
 * Unit tests for AuditsPage's pure decision helpers — the logic that
 * decides what each cell says, where Open points, and whether the page
 * keeps polling. Same shape as the repo's other component tests
 * (components/__tests__/ActionsPage.test.jsx): the component exports
 * its decisions as functions, and the functions are tested directly.
 */
import { describe, it, expect } from 'vitest'

import {
  IN_PROGRESS_STATUSES,
  POLL_INTERVAL_MS,
  competitorTag,
  formatDuration,
  leadFlags,
  openUrl,
  rangeCutoff,
  rowPill,
  scoreCell,
  shouldPoll,
  statusPill,
  statusSubline,
} from '../components/AuditsPage.jsx'
import { PUBLIC_AUDIT_BASE_URL } from '../lite/publicUrls.js'

// ─── Status pill mapping ──────────────────────────────────────────────────────

describe('statusPill', () => {
  it('maps every LITE_STATUSES value to its own label', () => {
    const labels = [
      'pending', 'identifying_competitors', 'generating', 'running', 'complete', 'failed',
    ].map(s => statusPill(s).label)

    expect(labels).toEqual([
      'Pending', 'Identifying competitors', 'Generating', 'Running', 'Complete', 'Failed',
    ])
    // Every status is visually distinguishable from every other.
    expect(new Set(labels).size).toBe(6)
  })

  it('gives the three in-flight statuses the same blue treatment', () => {
    const inFlight = ['identifying_competitors', 'generating', 'running'].map(statusPill)
    expect(new Set(inFlight.map(p => p.bg)).size).toBe(1)
    expect(new Set(inFlight.map(p => p.color)).size).toBe(1)
  })

  it('only animates the running pill', () => {
    expect(statusPill('running').pulse).toBe(true)
    expect(statusPill('generating').pulse).toBe(false)
    expect(statusPill('complete').pulse).toBe(false)
  })

  it('falls back to a neutral pill for an unknown status rather than throwing', () => {
    expect(statusPill('something_new').label).toBe('something_new')
    expect(statusPill(undefined).label).toBe('Unknown')
  })
})

// ─── Lead flags ───────────────────────────────────────────────────────────────

function row(overrides = {}) {
  return {
    id: 1,
    token: 'abc123',
    status: 'complete',
    email: null,
    report_email_sent_at: null,
    lead_notified_at: null,
    score_state: 'unavailable',
    composite_score: null,
    ...overrides,
  }
}

const flagText = r => leadFlags(r).map(f => f.text)

describe('leadFlags', () => {
  it('shows "Report emailed" only once the report email has gone out', () => {
    expect(flagText(row({ email: 'a@b.com' }))).not.toContain('Report emailed')
    expect(flagText(row({ email: 'a@b.com', report_email_sent_at: '2026-09-15T08:18:00Z' })))
      .toContain('Report emailed')
  })

  it('shows "Team notified" only once the internal notification has gone out', () => {
    expect(flagText(row({ email: 'a@b.com' }))).not.toContain('Team notified')
    expect(flagText(row({ email: 'a@b.com', lead_notified_at: '2026-09-15T08:14:00Z' })))
      .toContain('Team notified')
  })

  it('flags a finished report with nobody to send it to', () => {
    expect(flagText(row({ status: 'complete', email: null })))
      .toContain('Report ready, not sent')
  })

  it('does not claim a report is ready when the run is still going', () => {
    expect(flagText(row({ status: 'running', email: null })))
      .not.toContain('Report ready, not sent')
  })

  it('flags a queued report email — complete, address on file, nothing sent yet', () => {
    expect(flagText(row({ status: 'complete', email: 'a@b.com', report_email_sent_at: null })))
      .toContain('Report email queued')
  })

  it('stops calling it queued once it has actually been sent', () => {
    const sent = row({
      status: 'complete', email: 'a@b.com', report_email_sent_at: '2026-09-15T08:18:00Z',
    })
    expect(flagText(sent)).toContain('Report emailed')
    expect(flagText(sent)).not.toContain('Report email queued')
  })

  it('does not queue-flag an incomplete run that already has an address', () => {
    expect(flagText(row({ status: 'running', email: 'a@b.com' })))
      .not.toContain('Report email queued')
  })

  it('has no flags at all for a fresh, email-less in-progress row', () => {
    expect(leadFlags(row({ status: 'pending', email: null }))).toEqual([])
  })
})

// ─── Score cell ───────────────────────────────────────────────────────────────

describe('scoreCell', () => {
  it('renders the number and a bar when a score is available', () => {
    const cell = scoreCell(row({ score_state: 'available', composite_score: 58 }))
    expect(cell).toMatchObject({ kind: 'score', value: 58, low: false })
  })

  it('reads the bar amber below 40 and teal at 40 and above', () => {
    expect(scoreCell(row({ score_state: 'available', composite_score: 34 })).low).toBe(true)
    expect(scoreCell(row({ score_state: 'available', composite_score: 39.6 })).low).toBe(true)
    expect(scoreCell(row({ score_state: 'available', composite_score: 40 })).low).toBe(false)
    expect(scoreCell(row({ score_state: 'available', composite_score: 41 })).low).toBe(false)
  })

  it('shows Pending while the audit is still running', () => {
    expect(scoreCell(row({ status: 'running', score_state: 'pending' })))
      .toEqual({ kind: 'muted', label: 'Pending' })
  })

  it('shows Not measurable for a failed audit', () => {
    expect(scoreCell(row({ status: 'failed', score_state: 'not_measurable' })))
      .toEqual({ kind: 'muted', label: 'Not measurable' })
  })

  it('shows Expired for a row retired by a scorer_version bump', () => {
    expect(scoreCell(row({ score_state: 'expired' })))
      .toEqual({ kind: 'muted', label: 'Expired' })
  })

  it('falls back to an em dash when no score could be produced', () => {
    expect(scoreCell(row({ score_state: 'unavailable' })).label).toBe('—')
  })

  it('does not render a bar for an available state with a null score', () => {
    // The scorer can withhold a composite even at the current version.
    expect(scoreCell(row({ score_state: 'available', composite_score: null })))
      .toEqual({ kind: 'none', label: '—' })
  })

  it('rounds a fractional composite for display', () => {
    expect(scoreCell(row({ score_state: 'available', composite_score: 57.6 })).value).toBe(58)
  })
})

// ─── Open / copy-link URL ─────────────────────────────────────────────────────

describe('openUrl', () => {
  it('points a complete audit at its report', () => {
    expect(openUrl(row({ status: 'complete', token: 'abc123' })))
      .toBe(`${PUBLIC_AUDIT_BASE_URL}/r/abc123`)
  })

  it.each(IN_PROGRESS_STATUSES)('points a %s audit at its status page', status => {
    expect(openUrl(row({ status, token: 'abc123' })))
      .toBe(`${PUBLIC_AUDIT_BASE_URL}/s/abc123`)
  })

  it('points a failed audit at its status page, which is all that exists', () => {
    expect(openUrl(row({ status: 'failed', token: 'abc123' })))
      .toBe(`${PUBLIC_AUDIT_BASE_URL}/s/abc123`)
  })

  it('encodes the token rather than interpolating it raw', () => {
    expect(openUrl(row({ status: 'complete', token: 'a/b?c' })))
      .toBe(`${PUBLIC_AUDIT_BASE_URL}/r/a%2Fb%3Fc`)
  })

  it('returns null rather than a broken URL when there is no token', () => {
    expect(openUrl(row({ token: null }))).toBeNull()
    expect(openUrl(null)).toBeNull()
  })
})

// ─── Polling on/off ───────────────────────────────────────────────────────────

describe('shouldPoll', () => {
  it('polls while any visible row is still in progress', () => {
    expect(shouldPoll([row({ status: 'complete' }), row({ status: 'running' })])).toBe(true)
  })

  it.each(IN_PROGRESS_STATUSES)('treats %s as in progress', status => {
    expect(shouldPoll([row({ status })])).toBe(true)
  })

  it('stops polling once every visible row is terminal', () => {
    expect(shouldPoll([row({ status: 'complete' }), row({ status: 'failed' })])).toBe(false)
  })

  it('does not poll an empty or missing page', () => {
    expect(shouldPoll([])).toBe(false)
    expect(shouldPoll(undefined)).toBe(false)
  })

  it('polls on the 30 second cadence the meta line promises', () => {
    expect(POLL_INTERVAL_MS).toBe(30000)
  })
})

// ─── Supporting formatters ────────────────────────────────────────────────────

describe('statusSubline', () => {
  it('shows the current task while in flight', () => {
    expect(statusSubline(row({ status: 'running', current_task_text: 'Scoring the answers' })))
      .toBe('Scoring the answers')
  })

  it('appends query progress when the event log exposed it', () => {
    expect(statusSubline(row({
      status: 'running', current_task_text: 'Scoring', queries_done: 24, queries_total: 24,
    }))).toBe('Scoring · 24/24 queries done')
  })

  it('omits query progress entirely when it could not be parsed', () => {
    expect(statusSubline(row({
      status: 'running', current_task_text: 'Scoring', queries_done: null, queries_total: null,
    }))).toBe('Scoring')
  })

  it('shows the run duration once complete', () => {
    expect(statusSubline(row({
      status: 'complete', duration_seconds: 372, duration_is_estimate: false,
    }))).toBe('Ran in 6m 12s')
  })

  it('marks an estimated duration as approximate', () => {
    expect(statusSubline(row({
      status: 'complete', duration_seconds: 372, duration_is_estimate: true,
    }))).toBe('Ran in ~6m 12s')
  })
})

describe('formatDuration', () => {
  it('formats minutes and zero-padded seconds', () => {
    expect(formatDuration(372)).toBe('6m 12s')
    expect(formatDuration(480)).toBe('8m 00s')
  })

  it('drops the minutes component under a minute', () => {
    expect(formatDuration(42)).toBe('42s')
  })

  it('returns null rather than "0s" when there is no duration', () => {
    expect(formatDuration(null)).toBeNull()
    expect(formatDuration(undefined)).toBeNull()
  })
})

describe('competitorTag', () => {
  it('shows the manual count where the API could derive it exactly', () => {
    expect(competitorTag(row({ competitor_source: 'manual', manual_competitor_count: 2 })))
      .toBe('manual · all 2')
  })

  it('does not stutter the source word back as the count unit', () => {
    // "manual · 2 manual" read as a bug in the rendered table.
    expect(competitorTag(row({ competitor_source: 'manual', manual_competitor_count: 5 })))
      .not.toContain('manual · 5 manual')
  })

  it('shows only the source for a mixed row, whose split is unknowable', () => {
    expect(competitorTag(row({ competitor_source: 'mixed', manual_competitor_count: null })))
      .toBe('mixed')
  })

  it('shows only the source when none of the names were visitor-entered', () => {
    expect(competitorTag(row({ competitor_source: 'generated', manual_competitor_count: 0 })))
      .toBe('generated')
  })

  it('has no tag before the competitor stage has run', () => {
    expect(competitorTag(row({ competitor_source: null }))).toBeNull()
  })
})

describe('rangeCutoff', () => {
  const now = Date.parse('2026-09-15T10:00:00Z')

  it('converts a day count into an ISO cutoff', () => {
    expect(rangeCutoff('7', now)).toBe('2026-09-08T10:00:00.000Z')
  })

  it('returns null for all time, so no bound is sent at all', () => {
    expect(rangeCutoff('all', now)).toBeNull()
    expect(rangeCutoff('', now)).toBeNull()
  })
})


// ─── Partial read (degraded crawl) ────────────────────────────────────────────

const DEGRADED = 'every sampled product URL returned a challenge page'

describe('rowPill', () => {
  it('shows the amber Partial read pill when the crawl came up short', () => {
    const pill = rowPill(row({ status: 'complete', score_state: 'partial_read' }))
    expect(pill.label).toBe('Partial read')
    // The mock's amber pair, not the green "Complete" one.
    expect(pill.bg).toBe('#FEF3C7')
    expect(pill.color).toBe('#92400E')
  })

  it('leaves a healthy row on its own status pill', () => {
    const healthy = rowPill(row({ status: 'complete', score_state: 'available' }))
    expect(healthy).toEqual(statusPill('complete'))
    expect(healthy.label).toBe('Complete')
  })

  it.each([
    ['running', 'pending'],
    ['failed', 'not_measurable'],
    ['complete', 'expired'],
    ['complete', 'unavailable'],
  ])('leaves a %s row in state %s on its status pill', (status, score_state) => {
    expect(rowPill(row({ status, score_state }))).toEqual(statusPill(status))
  })

  it('does not throw on a missing row', () => {
    expect(() => rowPill(undefined)).not.toThrow()
  })
})

describe('scoreCell for a partial read', () => {
  it('says Partial read when the degraded crawl left no composite', () => {
    expect(scoreCell(row({ score_state: 'partial_read', composite_score: null })))
      .toEqual({ kind: 'muted', label: 'Partial read' })
  })

  it('still shows a number when one survived, and reads the bar amber', () => {
    // A legacy-scorer row produces a visibility-only figure even from a
    // degraded crawl — the mock shows exactly this (a score beside a
    // Partial read pill).
    const cell = scoreCell(row({ score_state: 'partial_read', composite_score: 62 }))
    expect(cell).toMatchObject({ kind: 'score', value: 62, partial: true })
  })

  it('does not mark a healthy row partial', () => {
    expect(scoreCell(row({ score_state: 'available', composite_score: 62 })).partial)
      .toBeUndefined()
  })
})

describe('statusSubline for a partial read', () => {
  it('names the reason the crawl came up short, ahead of the duration', () => {
    expect(statusSubline(row({
      status: 'complete', score_state: 'partial_read',
      degraded_reason: DEGRADED, duration_seconds: 372,
    }))).toBe(DEGRADED)
  })

  it('still shows the duration for a row whose crawl read the store', () => {
    expect(statusSubline(row({
      status: 'complete', score_state: 'available',
      degraded_reason: null, duration_seconds: 372, duration_is_estimate: false,
    }))).toBe('Ran in 6m 12s')
  })
})
