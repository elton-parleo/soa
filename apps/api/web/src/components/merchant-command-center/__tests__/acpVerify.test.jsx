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
import { classifyRecord, aggregateCell, VERIFY_BY_CHANNEL } from '../verificationModel.js'

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
    const cell = aggregateCell(PUBLICATION, [ACP_ROW_FRESH], { channelSlug: 'acp' })
    expect(cell.drift).toBe(0)
    expect(cell.drift).not.toBeNull()
  })

  it('drift findings reach the cell', () => {
    const cell = aggregateCell(PUBLICATION, [ACP_ROW_WITH_DRIFT], { channelSlug: 'acp' })
    expect(cell.drift).toBe(1)
  })

  it('a probe older than the publication stays unknown, not zero', () => {
    const cell = aggregateCell(PUBLICATION, [ACP_ROW_STALE], { channelSlug: 'acp' })
    expect(cell.drift).toBeNull()
  })

  it('no verifications at all is unknown — the state the bug left ACP in', () => {
    const cell = aggregateCell(PUBLICATION, [], { channelSlug: 'acp' })
    expect(cell.drift).toBeNull()
  })
})

describe('every verifiable channel routes somewhere', () => {
  it('acp and schema_org are the probe-capable channels', () => {
    expect(Object.keys(VERIFY_BY_CHANNEL).sort()).toEqual(['acp', 'schema_org'])
  })

  it('channels with no fetchable surface offer no probe', () => {
    for (const slug of ['merchant_center', 'ucp_uip', 'mcp', 'deals_api', 'deal_directory']) {
      expect(VERIFY_BY_CHANNEL[slug]).toBeUndefined()
    }
  })
})
