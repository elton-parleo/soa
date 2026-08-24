/**
 * Derivation tests for the Merchant Command Center, run against
 * fixtures captured verbatim from the live TrueSync API on 2026-08-22
 * (see ../__fixtures__/README.md).
 *
 * The theme throughout: the matrix must never invent a state. Each
 * block below pins one way it could have.
 */
import { describe, it, expect } from 'vitest'

import channelsFixture from '../__fixtures__/channels.json'
import publicationsFixture from '../__fixtures__/publications.json'
import spineFixture from '../__fixtures__/merchant-schema-org.json'
import listingsFixture from '../__fixtures__/listings.json'

import {
  orderChannels, channelImplementation, isMutedImplementation,
  latestPublicationByCell, publicationHistoryForCell, buildCell,
  buildCatalogRows, summarize, driftFindings, verificationBadge,
  relativeTime, gmcDeepLink,
} from '../truesyncDerive.js'

const detailsById = Object.fromEntries(
  Object.entries(listingsFixture).map(([id, d]) => [Number(id), d]),
)

describe('orderChannels', () => {
  it('puts schema.org first and Merchant Center second', () => {
    const ordered = orderChannels(channelsFixture)
    expect(ordered.map((c) => c.slug).slice(0, 2)).toEqual(['schema_org', 'merchant_center'])
  })

  it('keeps every channel the API returned, in API order after the primaries', () => {
    const ordered = orderChannels(channelsFixture)
    expect(ordered).toHaveLength(channelsFixture.length)
    expect(ordered.slice(2).map((c) => c.slug))
      .toEqual(['acp', 'ucp_uip', 'deals_api', 'mcp', 'deal_directory'])
  })

  it('survives a missing primary rather than inventing a column', () => {
    const withoutGmc = channelsFixture.filter((c) => c.slug !== 'merchant_center')
    const ordered = orderChannels(withoutGmc)
    expect(ordered.map((c) => c.slug)).not.toContain('merchant_center')
    expect(ordered[0].slug).toBe('schema_org')
  })
})

describe('channelImplementation — the honest stub test', () => {
  it('reads channels with published rows as live', () => {
    for (const slug of ['schema_org', 'deals_api', 'mcp', 'deal_directory']) {
      expect(channelImplementation(slug, publicationsFixture)).toBe('live')
    }
  })

  // The live data's own verdict, and the reason this is derived rather
  // than hardcoded: GMC is the stub here, not ACP alone.
  it('reads channels whose every row failed "not implemented" as not_implemented', () => {
    for (const slug of ['merchant_center', 'acp', 'ucp_uip']) {
      expect(channelImplementation(slug, publicationsFixture)).toBe('not_implemented')
    }
  })

  it('reads a channel with no rows at all as no_data', () => {
    expect(channelImplementation('some_future_channel', publicationsFixture)).toBe('no_data')
  })

  it('distinguishes a genuinely broken channel from an unbuilt one', () => {
    const rows = [{ listing_id: 1, channel_slug: 'x', status: 'failed', error: 'connection reset' }]
    expect(channelImplementation('x', rows)).toBe('failing')
  })

  it('mutes exactly the unbuilt and the unknown', () => {
    expect(isMutedImplementation('not_implemented')).toBe(true)
    expect(isMutedImplementation('no_data')).toBe(true)
    expect(isMutedImplementation('live')).toBe(false)
    // A channel that is built but currently erroring must NOT be muted
    // — that is a red cell demanding attention, not a grey one.
    expect(isMutedImplementation('failing')).toBe(false)
  })
})

describe('latestPublicationByCell', () => {
  it('covers every listing x channel pair present in the data', () => {
    const byCell = latestPublicationByCell(publicationsFixture)
    expect(byCell.size).toBe(35)   // 5 listings x 7 channels
  })

  it('takes the newest row when a cell has history', () => {
    const byCell = latestPublicationByCell(publicationsFixture)
    const cell = byCell.get('90:schema_org')
    const allForCell = publicationsFixture.filter(
      (p) => p.listing_id === 90 && p.channel_slug === 'schema_org',
    )
    expect(allForCell.length).toBeGreaterThan(1)
    expect(cell.id).toBe(Math.max(...allForCell.map((p) => p.id)))
  })

  it('does not depend on the API returning rows newest-first', () => {
    const reversed = [...publicationsFixture].reverse()
    expect(latestPublicationByCell(reversed).get('90:schema_org').id)
      .toBe(latestPublicationByCell(publicationsFixture).get('90:schema_org').id)
  })

  it('ignores rows with no listing_id rather than keying on null', () => {
    const byCell = latestPublicationByCell([
      ...publicationsFixture,
      { listing_id: null, channel_slug: 'schema_org', status: 'published' },
    ])
    expect(byCell.has('null:schema_org')).toBe(false)
  })
})

describe('publicationHistoryForCell', () => {
  it('returns that cell only, newest first', () => {
    const history = publicationHistoryForCell(publicationsFixture, 90, 'schema_org')
    expect(history.length).toBeGreaterThan(1)
    expect(history.every((p) => p.listing_id === 90 && p.channel_slug === 'schema_org')).toBe(true)
    const ids = history.map((p) => p.id)
    expect(ids).toEqual([...ids].sort((a, b) => b - a))
  })

  it('is empty, not undefined, for a cell with no events', () => {
    expect(publicationHistoryForCell(publicationsFixture, 90, 'nope')).toEqual([])
  })
})

describe('buildCell', () => {
  const byCell = latestPublicationByCell(publicationsFixture)

  it('reads a published row as published, with its publish time', () => {
    const cell = buildCell({
      publication: byCell.get('90:schema_org'), verifications: [], implementation: 'live',
    })
    expect(cell.publishState).toBe('published')
    expect(cell.isPublished).toBe(true)
    expect(cell.at).toBe(byCell.get('90:schema_org').published_at)
  })

  it('reads a failed row as failed and keeps the upstream error', () => {
    const cell = buildCell({
      publication: byCell.get('90:merchant_center'),
      verifications: [], implementation: 'not_implemented',
    })
    expect(cell.publishState).toBe('failed')
    expect(cell.isPublished).toBe(false)
    expect(cell.error).toMatch(/not implemented/i)
    expect(cell.muted).toBe(true)
  })

  // The non-negotiable: absence is "never published", never a blank
  // and never an optimistic green.
  it('reads a missing row as never published', () => {
    const cell = buildCell({ publication: undefined, verifications: [], implementation: 'no_data' })
    expect(cell.publishState).toBe('never')
    expect(cell.publishLabel).toBe('Never published')
    expect(cell.isPublished).toBe(false)
    expect(cell.at).toBeNull()
  })

  it('falls back to compiled_at for freshness when a row never published', () => {
    const cell = buildCell({
      publication: byCell.get('90:acp'), verifications: [], implementation: 'not_implemented',
    })
    expect(cell.at).toBe(byCell.get('90:acp').compiled_at)
  })

  it('treats compiled/validated as compiled-not-published', () => {
    for (const status of ['compiled', 'validated', 'compiled_not_published']) {
      const cell = buildCell({
        publication: { status, compiled_at: '2026-08-21T00:00:00Z' },
        verifications: [], implementation: 'live',
      })
      expect(cell.publishState).toBe('compiled_not_published')
    }
  })

  // Real expressiveness data off the live rows — the drawer's side card
  // is built from it, so an empty array here would empty that card.
  it('carries the channel expressiveness flags through', () => {
    const cell = buildCell({
      publication: byCell.get('90:merchant_center'), verifications: [], implementation: 'not_implemented',
    })
    expect(cell.expressiveness.length).toBeGreaterThan(0)
    expect(cell.expressiveness[0]).toHaveProperty('severity')
    expect(cell.expressiveness[0]).toHaveProperty('note')
  })
})

describe('verificationBadge — drift badge math', () => {
  it('is ○ when nothing has been verified', () => {
    expect(verificationBadge([])).toEqual({ kind: 'none', findingCount: 0 })
    expect(verificationBadge(undefined)).toEqual({ kind: 'none', findingCount: 0 })
  })

  it('is ✓ when the newest run found no drift', () => {
    expect(verificationBadge([{ id: 1, phase: 'post_publish', method: 'live_fetch', drift: null }]))
      .toEqual({ kind: 'verified', findingCount: 0 })
    expect(verificationBadge([{ id: 1, phase: 'post_publish', method: 'live_fetch', drift: {} }]).kind)
      .toBe('verified')
  })

  it('counts findings from a {findings:[...]} drift record', () => {
    const badge = verificationBadge([{
      id: 2, phase: 'post_publish', method: 'live_fetch',
      drift: { findings: [
        { field: 'price', expected: '17.99', observed: '18.99' },
        { field: 'count', expected: 96, observed: 84 },
        { field: 'availability', expected: 'in_stock', observed: 'out_of_stock' },
      ] },
    }])
    expect(badge).toEqual({ kind: 'drift', findingCount: 3 })
  })

  it('counts findings from a {field:{expected,observed}} drift record', () => {
    // method matters now: field-level drift belongs to fetch_probe. The
    // same payload under method: 'gmc_diagnostics' is a contradiction
    // and routes to the warning path instead — see the case below.
    const badge = verificationBadge([{
      id: 3, phase: 'post_publish', method: 'fetch_probe',
      drift: { price: { expected: '17.99', observed: '18.99' }, gtin: { expected: 'x', observed: null } },
    }])
    expect(badge).toEqual({ kind: 'drift', findingCount: 2 })
  })

  it('refuses to read field-level drift out of a gmc_diagnostics record', () => {
    const badge = verificationBadge([{
      id: 3, phase: 'post_publish', method: 'gmc_diagnostics',
      drift: { price: { expected: '17.99', observed: '18.99' } },
    }])
    expect(badge.kind).toBe('unparsed')
    expect(badge.findingCount).toBe(0)
  })

  it('is ✕ when the check itself failed', () => {
    expect(verificationBadge([{ id: 4, phase: 'fetch_failed', method: 'live_fetch', drift: null }]).kind)
      .toBe('failed')
  })

  it('reads only the newest run, not the whole history', () => {
    const badge = verificationBadge([
      { id: 9, phase: 'post_publish', method: 'live_fetch', drift: null },
      { id: 8, phase: 'post_publish', method: 'live_fetch', drift: { findings: [{ field: 'price' }] } },
    ])
    expect(badge.kind).toBe('verified')
  })

  // An unreadable record must never read as verified — that would turn
  // a warning green. It must not read as drift either: it is a gap in
  // this page, not a finding about the catalog. Hence its own kind.
  it('never downgrades an unrecognised drift shape to verified', () => {
    const badge = verificationBadge([{ id: 5, phase: 'post_publish', method: 'live_fetch', drift: { weird: 'shape' } }])
    expect(badge.kind).toBe('unparsed')
    expect(badge.kind).not.toBe('verified')
    expect(badge.findingCount).toBe(0)
  })
})

describe('driftFindings', () => {
  it('normalises both shapes to {variant, field, expected, observed}', () => {
    expect(driftFindings({ drift: { findings: [{ sku: 'WS-1', field: 'price', master: '1', surface: '2' }] } }))
      .toEqual([{ variant: 'WS-1', field: 'price', expected: '1', observed: '2' }])
    expect(driftFindings({ drift: { price: { expected: '1', actual: '2' } } }))
      .toEqual([{ variant: null, field: 'price', expected: '1', observed: '2' }])
  })

  it('is empty for no drift', () => {
    expect(driftFindings({ drift: null })).toEqual([])
    expect(driftFindings({})).toEqual([])
    expect(driftFindings(null)).toEqual([])
  })
})

describe('buildCatalogRows', () => {
  const rows = buildCatalogRows(spineFixture, detailsById)

  it('builds one row per listing in the spine', () => {
    expect(rows).toHaveLength(5)
    expect(rows.map((r) => r.listingId)).toEqual([90, 91, 92, 93, 94])
  })

  it('carries the catalog_product_id the sync-rule API is keyed by', () => {
    expect(rows.find((r) => r.listingId === 90).catalogProductId).toBe(27)
  })

  it('counts variants and GTIN coverage from the canonical record', () => {
    const diapers = rows.find((r) => r.listingId === 90)
    expect(diapers.variantCount).toBe(12)
    expect(diapers.gtinCount).toBe(4)

    const overnight = rows.find((r) => r.listingId === 91)
    expect(overnight.variantCount).toBe(4)
    expect(overnight.gtinCount).toBe(0)   // real, and a finding in itself
  })

  // A multi-variant product has no product-level GTIN; borrowing one
  // variant's code would read as the product's identifier.
  it('shows a product-level GTIN only where one exists', () => {
    expect(rows.find((r) => r.listingId === 90).gtin).toBeNull()
    expect(rows.find((r) => r.listingId === 92).gtin).toBe('884400676641')
  })

  it('keeps a row whose detail fetch failed, with nulls rather than dropping it', () => {
    const partial = buildCatalogRows(spineFixture, { 90: detailsById[90] })
    expect(partial).toHaveLength(5)
    const missing = partial.find((r) => r.listingId === 91)
    expect(missing.detailAvailable).toBe(false)
    expect(missing.catalogProductId).toBeNull()
    expect(missing.variantCount).toBe(0)
    // Still nameable, from the spine's own payload.
    expect(missing.name).toBe('Snug-Fit Overnight Diapers')
  })
})

describe('summarize', () => {
  const channels = orderChannels(channelsFixture)
  const rows = buildCatalogRows(spineFixture, detailsById)
  const byCell = latestPublicationByCell(publicationsFixture)
  const cellFor = (row, channel) => buildCell({
    publication: byCell.get(`${row.listingId}:${channel.slug}`),
    verifications: [],
    implementation: channelImplementation(channel.slug, publicationsFixture),
  })

  it('counts published cells across the whole matrix', () => {
    const stats = summarize(rows, channels, cellFor)
    expect(stats.totalCells).toBe(35)
    // 4 live channels x 5 listings; the other 3 have never published.
    expect(stats.publishedCells).toBe(20)
  })

  it('reports zero verified and zero drifting when nothing has been verified', () => {
    const stats = summarize(rows, channels, cellFor)
    expect(stats.verifiedCells).toBe(0)
    expect(stats.driftCells).toBe(0)
  })
})

describe('relativeTime', () => {
  const now = Date.parse('2026-08-22T12:00:00Z')

  it('formats across the scale', () => {
    expect(relativeTime('2026-08-22T11:59:30Z', now)).toBe('30s ago')
    expect(relativeTime('2026-08-22T11:30:00Z', now)).toBe('30m ago')
    expect(relativeTime('2026-08-22T06:00:00Z', now)).toBe('6h ago')
    expect(relativeTime('2026-08-19T12:00:00Z', now)).toBe('3d ago')
    expect(relativeTime('2026-06-22T12:00:00Z', now)).toBe('2mo ago')
    expect(relativeTime('2024-08-22T12:00:00Z', now)).toBe('2y ago')
  })

  it('returns null for absent or unparseable input, so callers decide', () => {
    expect(relativeTime(null)).toBeNull()
    expect(relativeTime(undefined)).toBeNull()
    expect(relativeTime('not a date')).toBeNull()
  })
})

describe('gmcDeepLink', () => {
  it('links a real Merchant Center resource name', () => {
    expect(gmcDeepLink('accounts/12345/products/online:en:US:sku-1'))
      .toContain('merchants.google.com')
  })

  // Every external_ref in the live data is of the form
  // "deals_api:listing:90" — not a GMC resource name. Building a link
  // out of one would land the operator on an error page.
  it('returns null for refs that are not resource names', () => {
    expect(gmcDeepLink('deal_directory:listing:90')).toBeNull()
    expect(gmcDeepLink(null)).toBeNull()
    expect(gmcDeepLink('')).toBeNull()
  })
})
