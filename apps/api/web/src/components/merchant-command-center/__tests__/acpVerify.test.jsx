/**
 * ACP verification: the cell must get its own badge.
 *
 * The bug: the drawer's "Verify now" button dropped the channel and always
 * called the schema.org probe. Clicking it on the ACP cell returned success,
 * wrote a `schema_org` verification row, and left ACP at ○ Unverified. The
 * live API showed it plainly — 4 rows for `?channel=schema_org`, and
 * `"verifications": []` for `?channel=acp`, against a published ACP row.
 *
 * The fixtures below are the real payloads from listing 90 on 2026-08-26,
 * with the ACP row shaped exactly as the upstream writer produces it.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import {
  classifyRecord, aggregateCell, canVerify, SURFACE, extensionStatusOf,
} from '../verificationModel.js'

// The ACP publication this listing actually has. Freshness is measured
// against published_at, so the fixture rows sit on either side of it.
const ACP_PUBLISHED_AT = '2026-08-26T15:46:09.160585+00:00'

// The publication as the page holds it, from the same live response.
const PUBLICATION = {
  publication_id: 361,
  status: 'published',
  published_at: ACP_PUBLISHED_AT,
  spec_version: 'acp-feed-stable-2026-08-18',
}

// What verify-acp writes: same phase/method/shape as the schema.org probe,
// differing only in channel_slug and the URL it fetched.
const ACP_ROW_FRESH = {
  id: 106,
  listing_id: 90,
  gtin: null,
  channel_slug: 'acp',
  phase: 'after',
  method: 'fetch_probe',
  created_at: '2026-08-26T15:52:03.114220Z',
  drift: {
    url: 'https://api.parleo.io/api/truesync/listings/90/acp',
    error: null,
    outcome: 'ok',
    findings: [],
    integrity: true,
    bytes_identical: true,
  },
  outcome: 'ok',
}

const ACP_ROW_WITH_DRIFT = {
  ...ACP_ROW_FRESH,
  id: 107,
  created_at: '2026-08-26T15:53:00.000000Z',
  drift: {
    ...ACP_ROW_FRESH.drift,
    outcome: 'drift_detected',
    integrity: false,
    bytes_identical: false,
    findings: [
      {
        variant_key: '90:snug-fit-diapers-s3-small',
        field: 'price',
        expected: '22.99 USD',
        observed: '19.99 USD',
      },
    ],
  },
  outcome: 'drift_detected',
}

// Older than the publication it claims to verify: a probe of a feed that has
// since been republished says nothing about what is served now.
const ACP_ROW_STALE = {
  ...ACP_ROW_FRESH,
  id: 100,
  created_at: '2026-08-25T09:00:00.000000Z',
}

describe('ACP verification rows classify like any other fetch_probe', () => {
  it('a fresh clean probe is a fresh probe, not unreadable', () => {
    const verdict = classifyRecord(ACP_ROW_FRESH, ACP_PUBLISHED_AT)
    expect(verdict.method).toBe('fetch_probe')
    expect(verdict.kind).toBe('probe')
    expect(verdict.fresh).toBe(true)
    expect(verdict.findings).toHaveLength(0)
  })

  it('a fresh probe with findings carries them', () => {
    const verdict = classifyRecord(ACP_ROW_WITH_DRIFT, ACP_PUBLISHED_AT)
    expect(verdict.kind).toBe('probe')
    expect(verdict.findings).toHaveLength(1)
  })

  it('the cell aggregates a fresh ACP probe into a real drift number', () => {
    const cell = aggregateCell(PUBLICATION, [ACP_ROW_FRESH], { channelSlug: 'acp', verificationSurface: SURFACE.FETCH_PROBE })
    expect(cell.drift).toBe(0)
    expect(cell.drift).not.toBeNull()
  })

  it('drift findings reach the cell', () => {
    const cell = aggregateCell(PUBLICATION, [ACP_ROW_WITH_DRIFT], { channelSlug: 'acp', verificationSurface: SURFACE.FETCH_PROBE })
    expect(cell.drift).toBe(1)
  })

  it('a probe older than the publication stays unknown, not zero', () => {
    const cell = aggregateCell(PUBLICATION, [ACP_ROW_STALE], { channelSlug: 'acp', verificationSurface: SURFACE.FETCH_PROBE })
    expect(cell.drift).toBeNull()
  })

  it('no verifications at all is unknown — the state the bug left ACP in', () => {
    const cell = aggregateCell(PUBLICATION, [], { channelSlug: 'acp', verificationSurface: SURFACE.FETCH_PROBE })
    expect(cell.drift).toBeNull()
  })
})

describe('the channel decides whether it can be verified', () => {
  it('a fetch_probe surface can be verified', () => {
    expect(canVerify(SURFACE.FETCH_PROBE)).toBe(true)
    expect(canVerify({ verification_surface: 'fetch_probe' })).toBe(true)
  })

  it('acceptance and none surfaces cannot', () => {
    expect(canVerify(SURFACE.ACCEPTANCE)).toBe(false)
    expect(canVerify(SURFACE.NONE)).toBe(false)
  })

  it('an undeclared channel cannot — never a probe by default', () => {
    expect(canVerify(undefined)).toBe(false)
    expect(canVerify({})).toBe(false)
  })
})


// ---------------------------------------------------------------------------
// the three surface kinds, end to end through the matrix
// ---------------------------------------------------------------------------

describe('the glyph follows the channel\'s declared surface', () => {
  const PUB = { status: 'published', published_at: ACP_PUBLISHED_AT }

  it('fetch_probe with no probe yet is ○ — a prompt somebody can answer', () => {
    const cell = aggregateCell(PUB, [], {
      channelSlug: 'acp', verificationSurface: SURFACE.FETCH_PROBE,
    })
    expect(cell.driftApplies).toBe(true)
    expect(cell.badge.glyph).toBe('○')
  })

  it('acceptance renders the muted dash, never ○', () => {
    const cell = aggregateCell(PUB, [], {
      channelSlug: 'merchant_center', verificationSurface: SURFACE.ACCEPTANCE,
    })
    expect(cell.driftApplies).toBe(false)
    expect(cell.drift).toBeNull()
    expect(cell.badge.glyph).toBe('–')
    expect(cell.badge.kind).toBe('not_applicable')
    expect(cell.badge.label).toMatch(/no independent verification surface/i)
    // Dimension 3 still carries this cell.
    expect(cell.hasAcceptanceAuthority).toBe(true)
  })

  it('none renders the muted dash and has no acceptance authority either', () => {
    const cell = aggregateCell(PUB, [], {
      channelSlug: 'mcp', verificationSurface: SURFACE.NONE,
    })
    expect(cell.badge.glyph).toBe('–')
    expect(cell.hasAcceptanceAuthority).toBe(false)
  })

  it('an undeclared channel gets the dash, not a probe it cannot run', () => {
    const cell = aggregateCell(PUB, [], { channelSlug: 'something_new' })
    expect(cell.driftApplies).toBe(false)
    expect(cell.badge.glyph).toBe('–')
  })

  it('a channel that GAINS a probe needs no change here', () => {
    // ucp_uip is `none` today. When it goes live the API says fetch_probe and
    // this side starts rendering ○ with nothing edited — which is the whole
    // point of the field being the truth.
    const before = aggregateCell(PUB, [], {
      channelSlug: 'ucp_uip', verificationSurface: SURFACE.NONE,
    })
    const after = aggregateCell(PUB, [], {
      channelSlug: 'ucp_uip', verificationSurface: SURFACE.FETCH_PROBE,
    })
    expect(before.badge.glyph).toBe('–')
    expect(after.badge.glyph).toBe('○')
  })
})


// ---------------------------------------------------------------------------
// extension status — four values, one of them not a warning
// ---------------------------------------------------------------------------

describe('extension status renders what it means', () => {
  it('not_applicable is neutral — nothing is wrong when it is set', () => {
    const channel = {
      slug: 'ucp_uip',
      extension_status: 'not_applicable',
      extension_status_reason:
        'loyalty extension carries buyer-resolved eligibility claims (membership id); '
        + 'a static catalog artifact cannot populate them without fabricating a buyer; '
        + 'separately, the standard carries no member-price field',
    }
    const status = extensionStatusOf(channel)
    expect(status.status).toBe('not_applicable')
    expect(status.tone).toBe('neutral')
    // Emphatically not the tones that mean "chase this".
    expect(status.tone).not.toBe('warn')
    expect(status.tone).not.toBe('bad')
    expect(status.reason).toContain('fabricating a buyer')
  })

  it('insufficient_spec is the one worth chasing', () => {
    expect(extensionStatusOf({
      slug: 'x', extension_status: 'insufficient_spec', extension_status_reason: 'r',
    }).tone).toBe('bad')
  })

  it('deferred reads as outstanding work, not as a defect', () => {
    expect(extensionStatusOf({
      slug: 'acp', extension_status: 'deferred', extension_status_reason: 'r',
    }).tone).toBe('warn')
  })

  it('populated is good news', () => {
    expect(extensionStatusOf({
      slug: 'x', extension_status: 'populated',
    }).tone).toBe('ok')
  })

  it('a channel with no extension facet declares nothing at all', () => {
    // Absent is not the same as "has one that cannot be filled", so it must
    // not render a row that implies a facet exists.
    expect(extensionStatusOf({ slug: 'schema_org' })).toBeNull()
    expect(extensionStatusOf({ slug: 'x', extension_status: null })).toBeNull()
    expect(extensionStatusOf(undefined)).toBeNull()
  })

  it('an unfamiliar status still renders, with its own name', () => {
    const status = extensionStatusOf({ slug: 'x', extension_status: 'something_new' })
    expect(status.label).toContain('something_new')
    expect(status.tone).toBe('warn')
  })

  it('it contributes to no cell dimension', () => {
    // Metadata, not a measurement: a channel carrying not_applicable must not
    // acquire drift, acceptance or unreadable counts from it.
    const cell = aggregateCell(
      { status: 'published', published_at: ACP_PUBLISHED_AT }, [],
      { channelSlug: 'ucp_uip', verificationSurface: SURFACE.FETCH_PROBE },
    )
    expect(cell.drift).toBeNull()
    expect(cell.unreadableCount).toBe(0)
    expect(cell.issueCount).toBe(0)
  })
})
