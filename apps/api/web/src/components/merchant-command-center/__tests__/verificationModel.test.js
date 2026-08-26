/**
 * The executable form of docs/verification-semantics.md.
 *
 * This file and that document are the only sources of truth for
 * verification semantics. If they disagree, the document wins and this
 * file is the bug. No rule may live in a React component.
 *
 * The table below enumerates the cross product of the dimensions that
 * can interact, each row asserting ALL FOUR dimensions plus the badge
 * glyph — because the failure mode this model exists to prevent is one
 * dimension leaking into another's count, and you cannot catch that by
 * asserting one dimension at a time.
 */
import { describe, it, expect } from 'vitest'

import REAL from '../__fixtures__/verification-records.json'
import {
  classifyRecord, aggregateCell, summarize, isFresh, isLifecycleCode,
  normaliseIssue, parseFindings, publishStateOf,
  PUBLISH_STATE, ACCEPTANCE, ACCEPTANCE_TONE, DRIFT_GLYPH,
} from '../verificationModel.js'

// ─── Shared timeline ─────────────────────────────────────────────────
// One publish, with records on either side of it, so freshness is
// exercised by every row rather than tested once in a corner.
const PUBLISHED_AT = '2026-08-24T22:30:00Z'
const AFTER = '2026-08-24T23:00:00Z'   // fresh
const BEFORE = '2026-08-24T21:00:00Z'  // stale

const PUBLISHED = { status: 'published', published_at: PUBLISHED_AT, compiled_at: BEFORE }
const NEVER_PUBLISHED = null
const FAILED_PUBLISH = { status: 'failed', published_at: null, compiled_at: BEFORE, error: 'not implemented in Step 2' }
const COMPILED_ONLY = { status: 'compiled', published_at: null, compiled_at: BEFORE }

// ─── Record builders ─────────────────────────────────────────────────
const at = (createdAt, record) => ({ ...record, created_at: createdAt })

const probeClean = (t) => at(t, REAL.fetch_probe_clean)
const probeDrift = (t, n = 2) => at(t, {
  ...REAL.fetch_probe_clean,
  drift: {
    ...REAL.fetch_probe_clean.drift, integrity: false,
    findings: Array.from({ length: n }, (_, i) => ({
      field: `field_${i}`, variant: 'WS-1', expected: 'a', observed: 'b',
    })),
  },
})
const probeFailed = (t) => at(t, {
  ...REAL.fetch_probe_clean,
  outcome: 'fetch_failed',
  drift: { ...REAL.fetch_probe_clean.drift, outcome: 'fetch_failed', error: 'connection reset', findings: [] },
})

const gmcPending = (t) => at(t, REAL.gmc_pending_review)
const gmcGhost = (t) => at(t, REAL.gmc_not_found_ghost)
const gmcPublishFailed = (t) => at(t, REAL.gmc_publish_failed)
const gmcApproved = (t) => at(t, {
  ...REAL.gmc_pending_review, outcome: 'approved',
  drift: { approved: true, issues: [], httpStatus: 200 },
})
const gmcDisapproved = (t) => at(t, {
  ...REAL.gmc_pending_review,
  drift: { approved: false, issues: [{ code: 'missing_required_gtin', severity: 'DISAPPROVED' }] },
})
const gmcMixed = (t) => at(t, {
  ...REAL.gmc_pending_review,
  drift: { approved: false, issues: [
    { code: 'image_link_pending_crawl', severity: 'DISAPPROVED' },
    { code: 'policy_violation_adult', severity: 'DISAPPROVED' },
  ] },
})
const unparsed = (t) => at(t, {
  id: 900, method: 'sidecar_audit', outcome: 'unknown', drift: { nothing: 'recognisable' },
})
const noMethod = (t) => at(t, { id: 901, method: null, drift: { some: 'payload' } })

// ─── THE TABLE ───────────────────────────────────────────────────────
//
// Dimensions crossed:
//   method            fetch_probe | gmc_diagnostics | unknown | none
//   parseable         yes | no
//   freshness         fresh | stale
//   gmc acceptance    approved | pending | disapproved | not_found | unavailable
//   publish state     published | failed | compiled | never
//
// Each row asserts all four dimensions plus the glyph.
const CHANNEL_GMC = 'merchant_center'
const CHANNEL_PLAIN = 'schema_org'
const CHANNEL_NONE = 'mcp'

// What the API declares for each channel. The model never decides this
// itself, so the tests must state it exactly as /channels would.
const SURFACE_BY_CHANNEL = {
  [CHANNEL_PLAIN]: 'fetch_probe',
  acp: 'fetch_probe',
  [CHANNEL_GMC]: 'acceptance',
  [CHANNEL_NONE]: 'none',
}

const TABLE = [
  // ── no records at all ───────────────────────────────────────────
  { name: 'published, no records — drift unknown, nothing else claimed',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', unreadable: 0, stale: 0, glyph: '○' } },

  { name: 'never published, no records',
    channel: CHANNEL_PLAIN, publication: NEVER_PUBLISHED, records: [],
    expect: { publishState: 'never', drift: null, acceptance: 'unknown', unreadable: 0, stale: 0, glyph: '○' } },

  // ── fetch_probe × freshness × publish state ─────────────────────
  { name: 'fresh clean probe — drift 0, ✓',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [probeClean(AFTER)],
    expect: { publishState: 'published', drift: 0, acceptance: 'unknown', unreadable: 0, stale: 0, glyph: '✓' } },

  { name: 'fresh drifting probe — drift 2, ⚠',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [probeDrift(AFTER, 2)],
    expect: { publishState: 'published', drift: 2, acceptance: 'unknown', unreadable: 0, stale: 0, glyph: '⚠' } },

  // The freshness rule. A green tick sourced from a superseded artifact
  // is a lie with a timestamp on it.
  { name: 'STALE clean probe — drift unknown again, counts for nothing',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [probeClean(BEFORE)],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', unreadable: 0, stale: 1, glyph: '○' } },

  { name: 'STALE drifting probe — drift unknown, not 2',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [probeDrift(BEFORE, 2)],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', unreadable: 0, stale: 1, glyph: '○' } },

  { name: 'stale and fresh probes together — the fresh one wins',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [probeDrift(AFTER, 3), probeClean(BEFORE)],
    expect: { publishState: 'published', drift: 3, acceptance: 'unknown', unreadable: 0, stale: 1, glyph: '⚠' } },

  { name: 'never published — nothing supersedes, so an old probe is fresh',
    channel: CHANNEL_PLAIN, publication: NEVER_PUBLISHED, records: [probeClean(BEFORE)],
    expect: { publishState: 'never', drift: 0, acceptance: 'unknown', unreadable: 0, stale: 0, glyph: '✓' } },

  { name: 'failed publish has no published_at — probe still fresh',
    channel: CHANNEL_PLAIN, publication: FAILED_PUBLISH, records: [probeClean(BEFORE)],
    expect: { publishState: 'failed', drift: 0, acceptance: 'unknown', unreadable: 0, stale: 0, glyph: '✓' } },

  { name: 'compiled but not published — probe fresh, publish state intact',
    channel: CHANNEL_PLAIN, publication: COMPILED_ONLY, records: [probeClean(BEFORE)],
    expect: { publishState: 'compiled_not_published', drift: 0, acceptance: 'unknown', unreadable: 0, stale: 0, glyph: '✓' } },

  // A probe that never ran measured nothing. Dimension 4, not 2.
  { name: 'failed probe — unreadable, drift stays unknown',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [probeFailed(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', unreadable: 1, stale: 0, glyph: '○' } },

  { name: 'record with no created_at is stale — cannot be shown current',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [{ ...REAL.fetch_probe_clean, created_at: null }],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', unreadable: 0, stale: 1, glyph: '○' } },

  // ── gmc_diagnostics × acceptance state ──────────────────────────
  // THE case: Google reports a lifecycle code as DISAPPROVED.
  { name: 'GMC pending review (severity DISAPPROVED) — amber pending, drift untouched',
    channel: CHANNEL_GMC, publication: PUBLISHED, records: [gmcPending(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'pending', issues: 1, unreadable: 0, stale: 0, glyph: '–', tone: 'drift' } },

  { name: 'GMC approved',
    channel: CHANNEL_GMC, publication: PUBLISHED, records: [gmcApproved(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'approved', issues: 0, unreadable: 0, stale: 0, glyph: '–', tone: 'sync' } },

  { name: 'GMC genuine disapproval — red',
    channel: CHANNEL_GMC, publication: PUBLISHED, records: [gmcDisapproved(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'disapproved', issues: 1, unreadable: 0, stale: 0, glyph: '–', tone: 'fail' } },

  { name: 'GMC lifecycle + genuine together — cell is disapproved',
    channel: CHANNEL_GMC, publication: PUBLISHED, records: [gmcMixed(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'disapproved', issues: 2, unreadable: 0, stale: 0, glyph: '–', tone: 'fail' } },

  { name: 'GMC 404 ghost — not_found, no issues, no drift',
    channel: CHANNEL_GMC, publication: PUBLISHED, records: [gmcGhost(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'not_found', issues: 0, unreadable: 0, stale: 0, glyph: '–', tone: 'hold' } },

  { name: 'GMC publish_failed — unavailable, counted nowhere',
    channel: CHANNEL_GMC, publication: FAILED_PUBLISH, records: [gmcPublishFailed(AFTER)],
    expect: { publishState: 'failed', drift: null, acceptance: 'unavailable', issues: 0, unreadable: 0, stale: 0, glyph: '–', tone: 'hold' } },

  { name: 'STALE GMC pending — acceptance unknown again',
    channel: CHANNEL_GMC, publication: PUBLISHED, records: [gmcPending(BEFORE)],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', issues: 0, unreadable: 0, stale: 1, glyph: '–' } },

  // Acceptance authority is a property of the channel.
  { name: 'GMC-shaped record on a channel with no acceptance authority — ignored',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [gmcPending(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', issues: 0, unreadable: 0, stale: 0, glyph: '○' } },

  // ── both dimensions at once, the whole point ────────────────────
  // A stray probe record on an acceptance channel is IGNORED for drift. Drift
  // at our layer is not measurable against Google's surface, so a probe that
  // somehow landed there answers a question the channel cannot be asked —
  // and the acceptance verdict still comes through untouched.
  { name: 'acceptance channel: a stray probe record does not become a drift number',
    channel: CHANNEL_GMC, publication: PUBLISHED, records: [probeClean(AFTER), gmcPending(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'pending', issues: 1, unreadable: 0, stale: 0, glyph: '–', tone: 'drift' } },

  { name: 'acceptance channel: a drifting probe record still yields no drift, and approval stands',
    channel: CHANNEL_GMC, publication: PUBLISHED, records: [probeDrift(AFTER, 1), gmcApproved(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'approved', issues: 0, unreadable: 0, stale: 0, glyph: '–', tone: 'sync' } },

  { name: 'acceptance channel: acceptance and unreadable stay separate, drift stays absent',
    channel: CHANNEL_GMC, publication: PUBLISHED,
    records: [probeClean(AFTER), gmcDisapproved(AFTER), unparsed(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'disapproved', issues: 1, unreadable: 1, stale: 0, glyph: '–', tone: 'fail' } },

  // The same no-contamination property, on a channel where dimension 2 does
  // apply: a probe and an unreadable record must not reach each other.
  { name: 'fetch_probe channel: a clean probe alongside an unreadable record — separate counts',
    channel: CHANNEL_PLAIN, publication: PUBLISHED,
    records: [probeClean(AFTER), unparsed(AFTER)],
    expect: { publishState: 'published', drift: 0, acceptance: 'unknown', issues: 0, unreadable: 1, stale: 0, glyph: '✓' } },

  // ── the three surface kinds ────────────────────────────────────────────
  { name: 'surface none: published, no probe, no verdict — a muted dash, never ○',
    channel: CHANNEL_NONE, publication: PUBLISHED, records: [],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', issues: 0, unreadable: 0, stale: 0, glyph: '–' } },

  { name: 'surface none: even a probe record cannot give it a drift number',
    channel: CHANNEL_NONE, publication: PUBLISHED, records: [probeClean(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', issues: 0, unreadable: 0, stale: 0, glyph: '–' } },

  { name: 'surface fetch_probe: published with no probe yet — ○, the actionable unknown',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', issues: 0, unreadable: 0, stale: 0, glyph: '○' } },

  // ── unparseable ─────────────────────────────────────────────────
  { name: 'unknown method — unreadable, never drift',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [unparsed(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', unreadable: 1, stale: 0, glyph: '○' } },

  { name: 'record with no method at all — unreadable',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [noMethod(AFTER)],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', unreadable: 1, stale: 0, glyph: '○' } },

  { name: 'STALE unreadable — excluded by freshness like everything else',
    channel: CHANNEL_PLAIN, publication: PUBLISHED, records: [unparsed(BEFORE)],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', unreadable: 0, stale: 1, glyph: '○' } },

  { name: 'GMC record with an unreadable payload — unreadable, not an acceptance verdict',
    channel: CHANNEL_GMC, publication: PUBLISHED,
    records: [at(AFTER, { method: 'gmc_diagnostics', drift: { unexpected: 'shape' } })],
    expect: { publishState: 'published', drift: null, acceptance: 'unknown', issues: 0, unreadable: 1, stale: 0, glyph: '–' } },
]

describe('the cell model — full matrix', () => {
  it.each(TABLE.map((row) => [row.name, row]))('%s', (_name, row) => {
    const cell = aggregateCell(row.publication, row.records, {
      channelSlug: row.channel,
      verificationSurface: row.surface || SURFACE_BY_CHANNEL[row.channel],
    })

    // All four dimensions asserted on every row. A leak between them
    // shows up here or nowhere.
    expect(cell.publishState).toBe(row.expect.publishState)
    expect(cell.drift).toBe(row.expect.drift)
    expect(cell.acceptance).toBe(row.expect.acceptance)
    expect(cell.unreadableCount).toBe(row.expect.unreadable)
    expect(cell.staleCount).toBe(row.expect.stale)
    expect(cell.badge.glyph).toBe(row.expect.glyph)

    if (row.expect.issues !== undefined) expect(cell.issueCount).toBe(row.expect.issues)
    if (row.expect.tone !== undefined) expect(ACCEPTANCE_TONE[cell.acceptance]).toBe(row.expect.tone)
  })

  it('covers every dimension value the model defines', () => {
    const seen = {
      publish: new Set(TABLE.map((r) => r.expect.publishState)),
      drift: new Set(TABLE.map((r) => (r.expect.drift == null ? 'null' : r.expect.drift > 0 ? 'positive' : 'zero'))),
      acceptance: new Set(TABLE.map((r) => r.expect.acceptance)),
    }
    expect(seen.publish).toEqual(new Set(Object.values(PUBLISH_STATE)))
    expect(seen.drift).toEqual(new Set(['null', 'zero', 'positive']))
    expect(seen.acceptance).toEqual(new Set(Object.values(ACCEPTANCE)))
  })
})

// ─── The real payloads, classified ───────────────────────────────────

describe('every real payload this system has produced', () => {
  const CASES = [
    ['fetch_probe_clean', 'probe'],
    ['gmc_pending_review', 'acceptance'],
    ['gmc_not_found_ghost', 'acceptance'],
    ['gmc_publish_failed', 'acceptance'],
  ]

  it.each(CASES)('%s classifies as %s', (key, kind) => {
    expect(classifyRecord(REAL[key], null).kind).toBe(kind)
  })

  it('the pending-review record is amber despite Google saying DISAPPROVED', () => {
    const classified = classifyRecord(REAL.gmc_pending_review, null)
    expect(classified.state).toBe(ACCEPTANCE.PENDING)
    expect(classified.issues[0].reportedSeverity).toBe('DISAPPROVED')
    expect(classified.issues[0].lifecycle).toBe(true)
    expect(classified.issues[0].tone).toBe('pending')
    expect(ACCEPTANCE_TONE[classified.state]).toBe('drift')   // amber, not fail
  })

  it('the 404 ghost is not_found, not a disapproval', () => {
    expect(classifyRecord(REAL.gmc_not_found_ghost, null).state).toBe(ACCEPTANCE.NOT_FOUND)
  })

  it('the publish_failed record yields no verdict and no blame', () => {
    const classified = classifyRecord(REAL.gmc_publish_failed, null)
    expect(classified.state).toBe(ACCEPTANCE.UNAVAILABLE)
    expect(classified.reason).toBe('not implemented in Step 2')
  })

  it('the captured probe is a clean run', () => {
    const classified = classifyRecord(REAL.fetch_probe_clean, null)
    expect(classified.findings).toEqual([])
    expect(classified.integrity).toBe(true)
    expect(classified.bytesIdentical).toBe(false)
  })
})

// ─── Lifecycle codes ─────────────────────────────────────────────────

describe('lifecycle codes', () => {
  it.each([
    ['pending_initial_policy_review_free_listings', true],
    ['pending_initial_policy_review_shopping_ads', true],
    ['image_link_pending_crawl', true],
    ['item_processing', true],
    ['missing_required_gtin', false],
    ['policy_violation_adult', false],
    ['image_link_broken', false],
    ['', false],
  ])('%s -> lifecycle=%s', (code, lifecycle) => {
    expect(isLifecycleCode(code)).toBe(lifecycle)
  })

  it('never lets the severity field override a lifecycle code', () => {
    for (const severity of ['DISAPPROVED', 'ERROR', 'CRITICAL']) {
      expect(normaliseIssue({ code: 'image_link_pending_crawl', severity }).tone).toBe('pending')
    }
  })

  it('treats an unrecognised code as genuine even when severity is soft', () => {
    expect(normaliseIssue({ code: 'mystery_rejection', severity: 'INFO' }).tone).toBe('error')
  })
})

// ─── Freshness ───────────────────────────────────────────────────────

describe('freshness', () => {
  it.each([
    ['record after publish', AFTER, PUBLISHED_AT, true],
    ['record before publish', BEFORE, PUBLISHED_AT, false],
    ['exactly equal is fresh', PUBLISHED_AT, PUBLISHED_AT, true],
    ['no publish timestamp', BEFORE, null, true],
    ['no record timestamp', null, PUBLISHED_AT, false],
    ['neither timestamp — missing created_at wins', null, null, false],
  ])('%s', (_n, createdAt, publishedAt, expected) => {
    expect(isFresh(createdAt, publishedAt)).toBe(expected)
  })
})

// ─── parseFindings: absence vs zero ──────────────────────────────────

describe('parseFindings distinguishes "cannot read" from "found nothing"', () => {
  it('returns [] for found-nothing', () => {
    expect(parseFindings(null)).toEqual([])
    expect(parseFindings({})).toEqual([])
    expect(parseFindings({ findings: [] })).toEqual([])
  })

  it('returns null for cannot-read', () => {
    expect(parseFindings({ issues: [], approved: false })).toBeNull()
    expect(parseFindings('nonsense')).toBeNull()
    expect(parseFindings([])).toBeNull()
  })
})

// ─── publishStateOf ──────────────────────────────────────────────────

describe('publish state carries its reason', () => {
  it.each([
    [null, 'never', null],
    [{ status: 'published' }, 'published', null],
    [{ status: 'failed', error: 'not implemented in Step 2' }, 'failed', 'not implemented in Step 2'],
    [{ status: 'withdrawn' }, 'compiled_not_published', 'withdrawn'],
    [{ status: 'compiled', validation: { ok: false, errors: ['bad gtin'] } }, 'compiled_not_published', 'bad gtin'],
  ])('%o -> %s (%s)', (publication, state, reason) => {
    const result = publishStateOf(publication)
    expect(result.state).toBe(state)
    expect(result.reason).toBe(reason)
  })
})

// ─── summarize ───────────────────────────────────────────────────────

describe('summarize keeps the dimensions apart', () => {
  const cell = (publication, records, channel) => aggregateCell(
    publication, records,
    { channelSlug: channel, verificationSurface: SURFACE_BY_CHANNEL[channel] },
  )

  const cells = [
    cell(PUBLISHED, [probeClean(AFTER)], CHANNEL_PLAIN),
    cell(PUBLISHED, [probeDrift(AFTER, 3)], CHANNEL_PLAIN),
    cell(PUBLISHED, [gmcPending(AFTER)], CHANNEL_GMC),
    cell(PUBLISHED, [gmcDisapproved(AFTER)], CHANNEL_GMC),
    cell(PUBLISHED, [gmcGhost(AFTER)], CHANNEL_GMC),
    cell(PUBLISHED, [unparsed(AFTER)], CHANNEL_PLAIN),
    cell(PUBLISHED, [probeClean(BEFORE)], CHANNEL_PLAIN),
    cell(NEVER_PUBLISHED, [], CHANNEL_PLAIN),
    // A channel with no verification surface at all: counted in neither the
    // verified nor the drifting bucket, and not silently treated as unknown.
    cell(PUBLISHED, [], CHANNEL_NONE),
  ]
  const totals = summarize(cells)

  it('counts drift from probes only', () => {
    expect(totals.verifiedCells).toBe(1)      // the one fresh clean probe
    expect(totals.driftingCells).toBe(1)
    expect(totals.driftFindings).toBe(3)
  })

  it('counts issues from acceptance only — never from drift or unreadable', () => {
    expect(totals.issueCount).toBe(2)         // 1 pending + 1 disapproved
    expect(totals.pendingCells).toBe(1)
    expect(totals.disapprovedCells).toBe(1)
    expect(totals.notFoundCells).toBe(1)      // the ghost has no issues to count
  })

  it('counts cells where drift does not apply in neither drift bucket', () => {
    // The three GMC cells (acceptance) plus the one none cell. Dimension 2
    // does not apply to any of them, so none is verified and none is
    // drifting — and saying that is not the same as saying "unknown".
    expect(totals.driftNotApplicableCells).toBe(4)
    expect(totals.verifiedCells).toBe(1)
    expect(totals.driftingCells).toBe(1)
  })

  it('counts unreadable and stale in their own buckets', () => {
    expect(totals.unreadableCount).toBe(1)
    expect(totals.staleCount).toBe(1)
  })

  it('never lets acceptance or unreadable reach the drift numbers', () => {
    // 5 GMC/unreadable/stale cells contribute nothing to drift.
    expect(totals.verifiedCells + totals.driftingCells).toBe(2)
  })

  it('reports last-verified from fresh records only', () => {
    expect(totals.lastVerifiedAt).toBe(AFTER)
  })

  it('counts published cells regardless of any verification', () => {
    expect(totals.publishedCells).toBe(8)   // 9 cells, one never published
    expect(totals.totalCells).toBe(9)
  })
})
