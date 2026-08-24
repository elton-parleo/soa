/**
 * Verification records are read by the METHOD that produced them.
 *
 * The bug these pin: a gmc_diagnostics record has no `findings` key and
 * no {expected, observed} pairs, so the fetch_probe field parser
 * bottomed out at a synthetic "(unparsed drift record)" finding — and
 * every GMC row was then counted as one unit of catalog drift. A parse
 * failure was being reported as a problem with the merchant's data.
 *
 * The GMC fixture is a real production response (listing 90 /
 * merchant_center, 2026-08-24) — the exact payload that mis-parsed.
 */
import React from 'react'
import { render, screen, within } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import gmcEnvelope from '../__fixtures__/verifications-gmc.json'
import channels from '../__fixtures__/channels.json'
import publications from '../__fixtures__/publications.json'
import spine from '../__fixtures__/merchant-schema-org.json'
import listings from '../__fixtures__/listings.json'

import ListingDrawer from '../ListingDrawer.jsx'
import {
  parseVerification, parseGmcDiagnostics, fetchProbeFindings, driftFindings,
  verificationBadge, normaliseGmcIssue, summarize, buildCell, buildCatalogRows,
  latestPublicationByCell, orderChannels, isGmcDiagnostics, isFetchProbe,
} from '../truesyncDerive.js'

const GMC_ROWS = gmcEnvelope.verifications

// A fetch_probe record in the field-level shape.
const FETCH_PROBE_ROW = {
  id: 40, listing_id: 90, gtin: null, channel_slug: 'schema_org',
  phase: 'after', method: 'fetch_probe', created_at: '2026-08-24T22:00:00Z',
  observed: { price: '18.99' }, outcome: 'drift',
  drift: { findings: [
    { variant: 'WS-SFD-1-96', field: 'price', expected: '17.99', observed: '18.99' },
    { variant: 'WS-SFD-1-96', field: 'availability', expected: 'in_stock', observed: 'out_of_stock' },
  ] },
}

const CLEAN_FETCH_PROBE = {
  ...FETCH_PROBE_ROW, id: 41, drift: null, outcome: 'clean',
}

// Neither shape: the warning path.
const CORRUPT_ROW = {
  id: 42, listing_id: 90, channel_slug: 'schema_org',
  phase: 'after', method: 'sidecar_audit', created_at: '2026-08-24T22:05:00Z',
  observed: null, outcome: 'unknown',
  drift: { totallyUnexpected: 'payload', nested: { no: 'expected/observed pair' } },
}

// ─── method routing ──────────────────────────────────────────────────

describe('method routing', () => {
  it('recognises the API\'s own method names', () => {
    expect(isGmcDiagnostics(GMC_ROWS[0])).toBe(true)
    expect(isFetchProbe(FETCH_PROBE_ROW)).toBe(true)
    // The original spec called it live_fetch; accepted as an alias so a
    // rename cannot silently route records into the wrong parser.
    expect(isFetchProbe({ method: 'live_fetch' })).toBe(true)
    expect(isGmcDiagnostics(FETCH_PROBE_ROW)).toBe(false)
  })

  it('sends a GMC record to the GMC parser, never the field parser', () => {
    const parsed = parseVerification(GMC_ROWS[0])
    expect(parsed.kind).toBe('gmc')
    expect(parsed).toMatchObject({ approved: false, httpStatus: 404, issues: [] })
  })

  it('sends a fetch_probe record to the findings parser', () => {
    const parsed = parseVerification(FETCH_PROBE_ROW)
    expect(parsed.kind).toBe('findings')
    expect(parsed.findings).toHaveLength(2)
    expect(parsed.findings[0]).toEqual({
      variant: 'WS-SFD-1-96', field: 'price', expected: '17.99', observed: '18.99',
    })
  })

  it('sends anything it cannot read to the unparsed path, with a reason', () => {
    const parsed = parseVerification(CORRUPT_ROW)
    expect(parsed.kind).toBe('unparsed')
    expect(parsed.method).toBe('sidecar_audit')
    expect(parsed.reason).toMatch(/no parser for method "sidecar_audit"/)
  })

  // The regression itself.
  it('no longer manufactures a "(unparsed drift record)" finding', () => {
    for (const row of [...GMC_ROWS, CORRUPT_ROW]) {
      expect(driftFindings(row)).toEqual([])
    }
    expect(JSON.stringify(GMC_ROWS.map(parseVerification)))
      .not.toContain('unparsed drift record')
  })
})

// ─── the parsers ─────────────────────────────────────────────────────

describe('parseGmcDiagnostics', () => {
  it('reads the real production payload', () => {
    expect(parseGmcDiagnostics({ issues: [], approved: false, httpStatus: 404 }))
      .toEqual({ kind: 'gmc', approved: false, httpStatus: 404, issues: [] })
  })

  it('reads an approved item with issues', () => {
    const parsed = parseGmcDiagnostics({
      approved: true, httpStatus: 200,
      issues: ['image_link_pending_crawl', 'pending_initial_policy_review_free_listings'],
    })
    expect(parsed.approved).toBe(true)
    expect(parsed.issues.map((i) => i.severity)).toEqual(['pending', 'pending'])
  })

  it('is null for a payload that is not GMC-shaped, so routing can fall through', () => {
    expect(parseGmcDiagnostics({ findings: [] })).toBeNull()
    expect(parseGmcDiagnostics(null)).toBeNull()
    expect(parseGmcDiagnostics([])).toBeNull()
  })
})

describe('normaliseGmcIssue', () => {
  it('derives severity from the code when none is declared', () => {
    expect(normaliseGmcIssue('image_link_pending_crawl').severity).toBe('pending')
    expect(normaliseGmcIssue('missing_required_gtin').severity).toBe('error')
    expect(normaliseGmcIssue('some_suggestion').severity).toBe('warning')
    // Nothing recognisable is 'info', never an invented error.
    expect(normaliseGmcIssue('mystery_code').severity).toBe('info')
  })

  it('prefers a declared severity', () => {
    expect(normaliseGmcIssue({ code: 'pending_review', severity: 'error' }).severity).toBe('error')
  })

  it('reads object issues with their descriptions', () => {
    expect(normaliseGmcIssue({
      code: 'image_link_pending_crawl', description: 'Image is being crawled',
    })).toMatchObject({ code: 'image_link_pending_crawl', description: 'Image is being crawled' })
  })
})

describe('fetchProbeFindings', () => {
  it('returns [] for "ran, found nothing" and null for "cannot read"', () => {
    // The distinction the old parser collapsed.
    expect(fetchProbeFindings(null)).toEqual([])
    expect(fetchProbeFindings({})).toEqual([])
    expect(fetchProbeFindings({ issues: [], approved: false, httpStatus: 404 })).toBeNull()
    expect(fetchProbeFindings('nonsense')).toBeNull()
  })

  it('reads both field-level shapes', () => {
    expect(fetchProbeFindings({ findings: [{ field: 'price', expected: 1, observed: 2 }] }))
      .toHaveLength(1)
    expect(fetchProbeFindings({ price: { expected: 1, observed: 2 } }))
      .toEqual([{ variant: null, field: 'price', expected: 1, observed: 2 }])
  })
})

// ─── badge math ──────────────────────────────────────────────────────

describe('badge math excludes unparseable rows', () => {
  it('gives an unreadable record its own kind, never drift', () => {
    const badge = verificationBadge([CORRUPT_ROW])
    expect(badge.kind).toBe('unparsed')
    expect(badge.findingCount).toBe(0)
    expect(badge.reason).toBeTruthy()
  })

  it('counts real fetch_probe findings', () => {
    expect(verificationBadge([FETCH_PROBE_ROW])).toMatchObject({ kind: 'drift', findingCount: 2 })
  })

  it('reads a clean fetch_probe as verified', () => {
    expect(verificationBadge([CLEAN_FETCH_PROBE])).toMatchObject({ kind: 'verified', findingCount: 0 })
  })

  // The exact production case: 12 GMC rows, not approved, zero issues.
  // Previously each parsed as one drift finding.
  it('reads a not-approved GMC record as drift with its real issue count', () => {
    expect(verificationBadge(GMC_ROWS)).toMatchObject({ kind: 'drift', findingCount: 0, gmc: true })
  })

  it('reads an approved GMC record as verified', () => {
    const approved = { ...GMC_ROWS[0], drift: { approved: true, issues: [], httpStatus: 200 } }
    expect(verificationBadge([approved])).toMatchObject({ kind: 'verified', findingCount: 0 })
  })

  it('counts GMC item issues, not synthetic ones', () => {
    const withIssues = { ...GMC_ROWS[0], drift: {
      approved: false, httpStatus: 200,
      issues: ['image_link_pending_crawl', 'pending_initial_policy_review_free_listings'],
    } }
    expect(verificationBadge([withIssues])).toMatchObject({ kind: 'drift', findingCount: 2 })
  })
})

describe('summarize separates unreadable from drifting', () => {
  const ordered = orderChannels(channels)
  const rows = buildCatalogRows(spine, Object.fromEntries(
    Object.entries(listings).map(([id, d]) => [Number(id), d])))
  const byCell = latestPublicationByCell(publications)

  function statsWith(verificationsByCell) {
    const cellFor = (row, channel) => buildCell({
      publication: byCell.get(`${row.listingId}:${channel.slug}`),
      verifications: verificationsByCell[`${row.listingId}:${channel.slug}`] || [],
      implementation: 'live',
    })
    return summarize(rows, ordered, cellFor)
  }

  it('keeps unreadable records out of the drift count entirely', () => {
    const stats = statsWith({
      '90:schema_org': [CORRUPT_ROW],
      '91:schema_org': [CORRUPT_ROW],
      '92:schema_org': [FETCH_PROBE_ROW],
    })
    expect(stats.unreadableCells).toBe(2)
    expect(stats.driftCells).toBe(1)      // only the real one
    expect(stats.verifiedCells).toBe(0)
  })

  it('reports last-verified from created_at, which the API now sends', () => {
    const stats = statsWith({
      '90:merchant_center': GMC_ROWS,
      '92:schema_org': [FETCH_PROBE_ROW],
    })
    expect(stats.lastVerifiedAt).toBe(FETCH_PROBE_ROW.created_at)   // the newer of the two
  })
})

// ─── rendering ───────────────────────────────────────────────────────

function drawerProps(overrides = {}) {
  const ordered = orderChannels(channels)
  const rows = buildCatalogRows(spine, Object.fromEntries(
    Object.entries(listings).map(([id, d]) => [Number(id), d])))
  const byCell = latestPublicationByCell(publications)
  return {
    row: rows[0],
    channels: ordered,
    channelState: Object.fromEntries(ordered.map((c) => [c.slug, { implementation: 'live', muted: false }])),
    cellFor: (row, channel) => buildCell({
      publication: byCell.get(`${row.listingId}:${channel.slug}`),
      verifications: overrides.verificationsByCell?.[`${row.listingId}:${channel.slug}`] || [],
      implementation: 'live',
    }),
    publications,
    verificationsByCell: {},
    onClose: () => {}, onPublish: () => {}, publishPending: false,
    ...overrides,
  }
}

describe('drawer renders each shape with its own renderer', () => {
  it('renders a GMC record as the Merchant Center status, not a comparison table', () => {
    render(<ListingDrawer {...drawerProps({
      verificationsByCell: { '90:schema_org': GMC_ROWS },
    })} />)

    expect(screen.getByText(/Merchant Center status/)).toBeInTheDocument()
    expect(screen.queryByText('Master record vs. surface')).not.toBeInTheDocument()
    expect(screen.getByText('Not approved')).toBeInTheDocument()
    expect(screen.getByText('HTTP 404')).toBeInTheDocument()
    expect(screen.getByText(/has not approved this item and reported no itemised issues/))
      .toBeInTheDocument()
    // And crucially, no invented finding anywhere on screen.
    expect(screen.queryByText(/unparsed drift record/)).not.toBeInTheDocument()
  })

  it('renders GMC item issues severity-coloured', () => {
    const withIssues = [{ ...GMC_ROWS[0], drift: {
      approved: false, httpStatus: 200,
      issues: [
        { code: 'pending_initial_policy_review_free_listings', description: 'Awaiting review' },
        { code: 'image_link_pending_crawl' },
        { code: 'missing_required_gtin' },
      ],
    } }]

    const { container } = render(<ListingDrawer {...drawerProps({
      verificationsByCell: { '90:schema_org': withIssues },
    })} />)

    expect(screen.getAllByText('pending_initial_policy_review_free_listings').length).toBeGreaterThan(0)
    expect(screen.getByText('Awaiting review')).toBeInTheDocument()
    expect(container.querySelector('.mcc-gmc-issues li.sev-pending')).toBeInTheDocument()
    expect(container.querySelector('.mcc-gmc-issues li.sev-error')).toBeInTheDocument()
  })

  it('renders a fetch_probe record as the master-vs-surface table', () => {
    render(<ListingDrawer {...drawerProps({
      verificationsByCell: { '90:schema_org': [FETCH_PROBE_ROW] },
    })} />)

    expect(screen.getByText(/Master record vs\. surface/)).toBeInTheDocument()
    expect(screen.queryByText(/Merchant Center status/)).not.toBeInTheDocument()
    const table = screen.getByRole('table')
    expect(within(table).getByText('price')).toBeInTheDocument()
    expect(within(table).getByText('17.99')).toBeInTheDocument()
    expect(within(table).getByText('18.99')).toBeInTheDocument()
  })

  it('renders a corrupt record as a visible warning panel naming the method', () => {
    render(<ListingDrawer {...drawerProps({
      verificationsByCell: { '90:schema_org': [CORRUPT_ROW] },
    })} />)

    expect(screen.getByText(/Couldn’t parse verification record \(method: sidecar_audit\)/))
      .toBeInTheDocument()
    expect(screen.getByText(/Not counted as drift/)).toBeInTheDocument()
    // The raw payload is offered so the gap can be diagnosed.
    expect(screen.getByText('Show the raw drift payload')).toBeInTheDocument()
  })

  it('names the method with no parser when the record carries none', () => {
    render(<ListingDrawer {...drawerProps({
      verificationsByCell: { '90:schema_org': [{ ...CORRUPT_ROW, method: null }] },
    })} />)

    expect(screen.getByText(/method: none given/)).toBeInTheDocument()
  })
})
