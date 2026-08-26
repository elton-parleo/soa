/**
 * §2b of docs/verification-semantics.md — prospect drift, as a table.
 *
 * The same shape as verificationModel.test.js and for the same reason:
 * the failure mode is one fact leaking into another's count, and you
 * cannot catch that by asserting one fact at a time.
 *
 * Fixtures are the real production responses for Pampers, captured
 * 2026-08-25. Outcomes the live data does not yet contain
 * (`blocked_for_agents`, `robots_disallowed`, `parse_failed`,
 * `fetch_failed`, and any product with findings) are built here from the
 * schema the doc specifies, and flagged as such in the report.
 */
import { describe, it, expect } from 'vitest'

import DRIFT from '../__fixtures__/prospect-drift-pampers.json'
import PROSPECTS from '../__fixtures__/prospects.json'

import {
  classifyRecord, aggregateCell,
  classifySurface, surfaceOutcomeMeta, isSurfaceReadable,
  aggregateProspectProduct, summarizeProspect, normaliseProspectFinding,
  normaliseRobotsPolicy, ROBOTS_STATE, SURFACE_OUTCOME, PROSPECT_OUTCOME,
  METHOD_PROSPECT_FETCH,
} from '../verificationModel.js'

const surfaceOf = (outcome, transport = {}, extra = {}) => ({
  surface: 'example.com',
  url: 'https://example.com/p/1',
  outcome,
  error: null,
  summary: {},
  raw_jsonld: [],
  transport: { http_status: 200, bytes: 1000, attempts: 1, final_url: 'https://example.com/p/1', redirect_chain: [], ...transport },
  ...extra,
})

// ─── Prospect rows never touch a cell ────────────────────────────────

describe('a prospect record contributes to no cell dimension', () => {
  const PROSPECT_ROW = {
    id: 900, listing_id: null, record_ref: 'prospect:pampers:swaddlers',
    method: METHOD_PROSPECT_FETCH, created_at: '2026-08-25T23:00:00Z',
    drift: { outcome: 'drift_detected', findings: [{ field: 'price', surface_a: 'a', value_a: '1', surface_b: 'b', value_b: '2' }] },
  }

  it('classifies as its own kind, not as a probe', () => {
    const classified = classifyRecord(PROSPECT_ROW, null)
    expect(classified.kind).toBe('prospect')
    expect(classified.kind).not.toBe('probe')
  })

  // The cross-contamination the method name exists to prevent: a
  // surface-vs-surface observation must never answer a question about
  // one of our own listings.
  it('leaves drift unknown even though it carries findings', () => {
    const cell = aggregateCell(
      { status: 'published', published_at: '2026-08-25T22:00:00Z' },
      [PROSPECT_ROW],
      { channelSlug: 'schema_org', verificationSurface: 'fetch_probe' },
    )
    expect(cell.drift).toBeNull()
    expect(cell.badge.glyph).toBe('○')
  })

  it('is counted in no dimension at all — not even unreadable', () => {
    const cell = aggregateCell(
      { status: 'published', published_at: '2026-08-25T22:00:00Z' },
      [PROSPECT_ROW],
      { channelSlug: 'merchant_center' },
    )
    expect(cell.drift).toBeNull()
    expect(cell.acceptance).toBe('unknown')
    expect(cell.unreadableCount).toBe(0)
    expect(cell.staleCount).toBe(0)
    // Surfaced so it is not silently dropped, but in its own field.
    expect(cell.prospectRecordCount).toBe(1)
  })
})

// ─── THE SURFACE OUTCOME TABLE ───────────────────────────────────────
//
// Blocked ≠ absent ≠ disallowed-by-policy. Each row asserts the verdict,
// whether it counts as readable, and the tone it renders in — because
// collapsing any two of these into one badge is the bug this vocabulary
// exists to prevent.

const SURFACE_TABLE = [
  { name: 'ok — read and extracted',
    outcome: SURFACE_OUTCOME.OK, expect: { readable: true, tone: 'sync', label: 'Read' } },

  // The doc names this `fetched`; the live API emits `ok`. Both map to
  // the same readable state so a rename cannot silently break the view.
  { name: 'fetched — the doc\'s name for the same thing',
    outcome: 'fetched', expect: { readable: true, tone: 'sync', label: 'Read' } },

  { name: 'no_structured_data — their markup',
    outcome: SURFACE_OUTCOME.NO_STRUCTURED_DATA,
    expect: { readable: false, tone: 'drift', label: 'No structured data' } },

  { name: 'blocked_for_agents — their edge',
    outcome: SURFACE_OUTCOME.BLOCKED_FOR_AGENTS,
    expect: { readable: false, tone: 'fail', label: 'Blocked for agents' } },

  { name: 'robots_disallowed — their policy, not their behaviour',
    outcome: SURFACE_OUTCOME.ROBOTS_DISALLOWED,
    expect: { readable: false, tone: 'hold', label: 'Disallowed by robots' } },

  { name: 'parse_failed — their data',
    outcome: SURFACE_OUTCOME.PARSE_FAILED,
    expect: { readable: false, tone: 'drift', label: 'Parse failed' } },

  { name: 'fetch_failed — the network',
    outcome: SURFACE_OUTCOME.FETCH_FAILED,
    expect: { readable: false, tone: 'hold', label: 'Fetch failed' } },

  { name: 'an outcome newer than this build — named, never silently readable',
    outcome: 'quantum_entangled',
    expect: { readable: false, tone: 'hold', label: 'Unrecognised outcome' } },

  { name: 'a missing outcome is not readable',
    outcome: null, expect: { readable: false, tone: 'hold', label: 'Unrecognised outcome' } },
]

describe('surface outcome vocabulary', () => {
  it.each(SURFACE_TABLE.map((r) => [r.name, r]))('%s', (_n, row) => {
    const meta = surfaceOutcomeMeta(row.outcome)
    expect(meta.label).toBe(row.expect.label)
    expect(meta.tone).toBe(row.expect.tone)
    expect(isSurfaceReadable(row.outcome)).toBe(row.expect.readable)

    const classified = classifySurface(surfaceOf(row.outcome))
    expect(classified.readable).toBe(row.expect.readable)
    expect(classified.meta.tone).toBe(row.expect.tone)
  })

  it('gives the four unreadable-but-informative outcomes four different tones', () => {
    const tones = [
      SURFACE_OUTCOME.NO_STRUCTURED_DATA,
      SURFACE_OUTCOME.BLOCKED_FOR_AGENTS,
      SURFACE_OUTCOME.ROBOTS_DISALLOWED,
    ].map((o) => surfaceOutcomeMeta(o).tone)
    expect(new Set(tones).size).toBe(3)   // never one grey badge
  })

  it('covers every outcome the model defines', () => {
    const covered = new Set(SURFACE_TABLE.map((r) => r.outcome))
    for (const outcome of Object.values(SURFACE_OUTCOME)) {
      expect(covered.has(outcome)).toBe(true)
    }
  })
})

describe('transport evidence is preserved, and nothing is re-classified', () => {
  it('keeps status, bytes, attempts and the final url', () => {
    const s = classifySurface(surfaceOf(SURFACE_OUTCOME.BLOCKED_FOR_AGENTS, {
      http_status: 403, bytes: 512, attempts: 3, final_url: 'https://example.com/denied',
      redirect_chain: ['https://example.com/p/1'],
    }))
    expect(s.transport).toMatchObject({ httpStatus: 403, bytes: 512, attempts: 3 })
    expect(s.transport.finalUrl).toBe('https://example.com/denied')
    expect(s.redirected).toBe(true)
  })

  // The live Walmart row: classified `no_structured_data` by the
  // fetcher, but its final_url is a /blocked path. The view reports the
  // fetcher's verdict verbatim and surfaces the evidence beside it —
  // re-classifying here would invent a state the API never gave.
  it('does NOT upgrade a redirected 15KB body to blocked_for_agents', () => {
    const walmart = DRIFT.products[0].surfaces.find((s) => s.surface === 'walmart.com')
    const s = classifySurface(walmart)
    expect(s.outcome).toBe('no_structured_data')
    expect(s.readable).toBe(false)
    // …but the evidence that it was a wall is intact and renderable.
    expect(s.transport.bytes).toBe(15195)
    expect(s.transport.finalUrl).toContain('/blocked')
    expect(s.redirected).toBe(true)
  })

  it('does not call an unredirected fetch redirected', () => {
    expect(classifySurface(surfaceOf(SURFACE_OUTCOME.OK)).redirected).toBe(false)
  })
})

// ─── Product-level comparison ────────────────────────────────────────

const productOf = (outcome, surfaces, findings = [], extra = {}) => ({
  product_key: 'p1', product_label: 'Product One', observed: true,
  observed_at: '2026-08-25T21:00:00Z', gtin: '123',
  configured_surfaces: surfaces.map((s) => s.surface),
  drift: {
    outcome, findings, variant_key: 'p1',
    surfaces_read: surfaces.filter((s) => isSurfaceReadable(s.outcome)).length,
    surfaces_total: surfaces.length,
  },
  surfaces,
  ...extra,
})

const FINDING = {
  variant_key: 'p1', field: 'price',
  surface_a: 'a.com', value_a: '9.97', surface_b: 'b.com', value_b: '12.49',
}

const PRODUCT_TABLE = [
  { name: 'insufficient_surfaces — findings null, never 0',
    product: productOf(PROSPECT_OUTCOME.INSUFFICIENT_SURFACES,
      [surfaceOf(SURFACE_OUTCOME.OK), surfaceOf(SURFACE_OUTCOME.NO_STRUCTURED_DATA)]),
    expect: { outcome: 'insufficient_surfaces', findingCount: null, insufficient: true, read: 1, total: 2, tone: 'hold' } },

  { name: 'no readable surface at all — still insufficient, not agreement',
    product: productOf(PROSPECT_OUTCOME.INSUFFICIENT_SURFACES,
      [surfaceOf(SURFACE_OUTCOME.NO_STRUCTURED_DATA), surfaceOf(SURFACE_OUTCOME.BLOCKED_FOR_AGENTS)]),
    expect: { outcome: 'insufficient_surfaces', findingCount: null, insufficient: true, read: 0, total: 2, tone: 'hold' } },

  { name: 'ok — two readable surfaces that agree',
    product: productOf(PROSPECT_OUTCOME.OK, [surfaceOf(SURFACE_OUTCOME.OK), surfaceOf(SURFACE_OUTCOME.OK)]),
    expect: { outcome: 'ok', findingCount: 0, insufficient: false, read: 2, total: 2, tone: 'sync' } },

  { name: 'drift_detected — surfaces disagree',
    product: productOf(PROSPECT_OUTCOME.DRIFT_DETECTED,
      [surfaceOf(SURFACE_OUTCOME.OK), surfaceOf(SURFACE_OUTCOME.OK)], [FINDING]),
    expect: { outcome: 'drift_detected', findingCount: 1, insufficient: false, read: 2, total: 2, tone: 'drift' } },

  { name: 'robots_disallowed counts against readability like any other unreadable outcome',
    product: productOf(PROSPECT_OUTCOME.INSUFFICIENT_SURFACES,
      [surfaceOf(SURFACE_OUTCOME.OK), surfaceOf(SURFACE_OUTCOME.ROBOTS_DISALLOWED)]),
    expect: { outcome: 'insufficient_surfaces', findingCount: null, insufficient: true, read: 1, total: 2, tone: 'hold' } },
]

describe('prospect product comparison', () => {
  it.each(PRODUCT_TABLE.map((r) => [r.name, r]))('%s', (_n, row) => {
    const p = aggregateProspectProduct(row.product)
    expect(p.outcome).toBe(row.expect.outcome)
    expect(p.findingCount).toBe(row.expect.findingCount)
    expect(p.insufficient).toBe(row.expect.insufficient)
    expect(p.surfacesRead).toBe(row.expect.read)
    expect(p.surfacesTotal).toBe(row.expect.total)
    expect(p.outcomeMeta.tone).toBe(row.expect.tone)
  })

  it('covers every comparison outcome the model defines', () => {
    const covered = new Set(PRODUCT_TABLE.map((r) => r.expect.outcome))
    expect(covered).toEqual(new Set(Object.values(PROSPECT_OUTCOME)))
  })

  it('an unobserved product claims nothing', () => {
    const p = aggregateProspectProduct({
      product_key: 'p9', product_label: 'Never fetched',
      observed: false, configured_surfaces: ['a.com', 'b.com'], surfaces: [], drift: null,
    })
    expect(p.observed).toBe(false)
    expect(p.outcome).toBeNull()
    expect(p.findingCount).toBe(0)
    expect(p.surfaces).toEqual([])
  })
})

describe('prospect findings mirror dimension 2 with neither side authoritative', () => {
  it('normalises the surface_a/value_a/surface_b/value_b schema', () => {
    expect(normaliseProspectFinding(FINDING)).toEqual({
      variantKey: 'p1', field: 'price',
      surfaceA: 'a.com', valueA: '9.97', surfaceB: 'b.com', valueB: '12.49',
      missingIdentifier: false, severity: null,
    })
  })

  it('marks gtin_missing as a first-class identifier finding', () => {
    const f = normaliseProspectFinding({ ...FINDING, field: 'gtin_missing', value_b: null })
    expect(f.missingIdentifier).toBe(true)
    expect(f.valueB).toBeNull()
  })

  it('survives a finding with nothing in it', () => {
    expect(() => normaliseProspectFinding(null)).not.toThrow()
    expect(normaliseProspectFinding({}).field).toBeNull()
  })
})

// ─── Agent access policy ─────────────────────────────────────────────

describe('robots policy is an independent question', () => {
  const amazon = DRIFT.products[1].surfaces.find((s) => s.surface === 'amazon.com')

  it('reads the real Amazon block: all six agents, explicitly', () => {
    const policy = normaliseRobotsPolicy(amazon.robots_policy)
    expect(policy.agentCount).toBe(6)
    expect(policy.blockedCount).toBe(6)
    expect(policy.closedToAllAgents).toBe(true)
    expect(policy.agents.every((a) => a.productPages === ROBOTS_STATE.BLOCKED)).toBe(true)
    expect(policy.divergence.length).toBeGreaterThan(0)
  })

  it('reads an open domain as open', () => {
    const pampers = DRIFT.products[0].surfaces.find((s) => s.surface === 'pampers.com')
    const policy = normaliseRobotsPolicy(pampers.robots_policy)
    expect(policy.blockedCount).toBe(0)
    expect(policy.closedToAllAgents).toBe(false)
  })

  // A surface can serve us perfectly and still be closed to every agent
  // a shopper uses — which is why this is not folded into the outcome.
  it('is independent of the surface outcome', () => {
    const s = classifySurface(surfaceOf(SURFACE_OUTCOME.OK, {}, { robots_policy: amazon.robots_policy }))
    expect(s.readable).toBe(true)
    expect(s.robotsPolicy.closedToAllAgents).toBe(true)
  })

  it('never guesses when robots.txt could not be read', () => {
    const policy = normaliseRobotsPolicy({ domain: 'x.com', robots_readable: false, agents: [] })
    expect(policy.readable).toBe(false)
    expect(policy.closedToAllAgents).toBe(false)   // unreadable is not "open"
  })

  it('maps an unrecognised state to unknown rather than assuming', () => {
    const policy = normaliseRobotsPolicy({
      robots_readable: true, agents: [{ agent: 'X', root: 'maybe', product_pages: null }],
    })
    expect(policy.agents[0].root).toBe(ROBOTS_STATE.UNKNOWN)
    expect(policy.agents[0].productPages).toBe(ROBOTS_STATE.UNKNOWN)
  })

  it('is null when absent, rather than an empty table', () => {
    expect(normaliseRobotsPolicy(null)).toBeNull()
    expect(classifySurface(surfaceOf(SURFACE_OUTCOME.OK)).robotsPolicy).toBeNull()
  })
})

// ─── The real Pampers payload ────────────────────────────────────────

describe('the live Pampers report', () => {
  const products = DRIFT.products.map(aggregateProspectProduct)
  const totals = summarizeProspect(products)

  it('reads all three products as not comparable', () => {
    expect(products).toHaveLength(3)
    expect(products.every((p) => p.insufficient)).toBe(true)
    expect(products.every((p) => p.findingCount === null)).toBe(true)
  })

  it('preserves the byte contrast that carries the story', () => {
    const bytes = {}
    for (const p of products) for (const s of p.surfaces) bytes[s.surface] = s.transport.bytes
    expect(bytes['walmart.com']).toBe(15195)      // a wall
    expect(bytes['target.com']).toBe(1312508)     // a real page with no JSON-LD
    // Both are `no_structured_data`; only the size tells them apart.
    expect(bytes['target.com'] / bytes['walmart.com']).toBeGreaterThan(50)
  })

  it('counts surfaces and outcomes without inventing agreement', () => {
    expect(totals).toMatchObject({
      products: 3, observed: 3, notComparable: 3, comparable: 0,
      surfaces: 6, surfacesReadable: 2, findingsTotal: 0, withDrift: 0,
    })
    expect(totals.outcomeCounts).toEqual({ ok: 2, no_structured_data: 4 })
  })

  it('flags the one domain closed to every agent', () => {
    expect(totals.agentBlockedDomains).toEqual(['www.amazon.com'])
  })

  it('matches the list payload it came from', () => {
    const listed = PROSPECTS.prospects.find((p) => p.slug === DRIFT.slug)
    expect(listed.products_configured).toBe(products.length)
    expect(listed.products_observed).toBe(totals.observed)
  })
})

describe('summarizeProspect on an empty prospect', () => {
  it('claims nothing', () => {
    const totals = summarizeProspect([])
    expect(totals).toMatchObject({
      products: 0, observed: 0, surfaces: 0, surfacesReadable: 0, findingsTotal: 0,
    })
    expect(totals.lastObservedAt).toBeNull()
    expect(totals.agentBlockedDomains).toEqual([])
  })
})
