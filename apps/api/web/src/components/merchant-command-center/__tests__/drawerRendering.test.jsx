/**
 * The drawer renders each dimension in its own section, from
 * `aggregateCell` output only.
 *
 * The classification rules themselves are tested in
 * verificationModel.test.js against the model's table; this file tests
 * that the UI shows what the model decided — and, in particular, that a
 * channel's acceptance verdict never appears as drift.
 */
import React from 'react'
import { render, screen, within, fireEvent } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import '@testing-library/jest-dom'

import REAL from '../__fixtures__/verification-records.json'
import channels from '../__fixtures__/channels.json'
import publications from '../__fixtures__/publications.json'
import spine from '../__fixtures__/merchant-schema-org.json'
import listings from '../__fixtures__/listings.json'

import ListingDrawer from '../ListingDrawer.jsx'
import {
  buildCatalogRows, latestPublicationByCell, orderChannels,
  gmcDeepLink, parseGmcRef, gmcExternalRefs, gmcAccountId, gmcOfferLink,
} from '../truesyncDerive.js'
import { aggregateCell, surfaceOf } from '../verificationModel.js'

const FRESH = '2099-01-01T00:00:00Z'   // newer than any fixture publish
const at = (t, record) => ({ ...record, created_at: t })

const PROBE_CLEAN = at(FRESH, REAL.fetch_probe_clean)
const PROBE_DRIFT = at(FRESH, {
  ...REAL.fetch_probe_clean,
  drift: {
    ...REAL.fetch_probe_clean.drift, integrity: false,
    findings: [{ variant: 'WS-SFD-1-96', field: 'price', expected: '17.99', observed: '18.99' }],
  },
})
const GMC_PENDING = at(FRESH, REAL.gmc_pending_review)
const GMC_GHOST = at(FRESH, REAL.gmc_not_found_ghost)
const GMC_UNAVAILABLE = at(FRESH, REAL.gmc_publish_failed)
const CORRUPT = at(FRESH, {
  id: 42, method: 'sidecar_audit', outcome: 'unknown',
  drift: { totallyUnexpected: 'payload' },
})

function drawerProps(overrides = {}) {
  const ordered = orderChannels(channels)
  const rows = buildCatalogRows(spine, Object.fromEntries(
    Object.entries(listings).map(([id, d]) => [Number(id), d])))

  const pubs = overrides.publications || publications
  const records = overrides.records || {}
  const byCell = latestPublicationByCell(pubs)

  const cellFor = (row, channel) => aggregateCell(
    byCell.get(`${row.listingId}:${channel.slug}`),
    records[`${row.listingId}:${channel.slug}`] || [],
    { channelSlug: channel.slug, verificationSurface: surfaceOf(channel) },
  )

  const { records: _r, ...rest } = overrides
  return {
    row: rows[0],
    channels: ordered,
    channelState: Object.fromEntries(ordered.map((c) => [c.slug, { implementation: 'live', muted: false }])),
    cellFor,
    publications: pubs,
    onClose: () => {}, onPublish: () => {}, publishPending: false,
    onVerify: () => {}, verifyPending: false,
    ...rest,
  }
}

const openGmc = () => fireEvent.click(screen.getByRole('tab', { name: /google merchant center/i }))

describe('drift section — dimension 2', () => {
  it('says drift is unknown when no probe exists', () => {
    render(<ListingDrawer {...drawerProps()} />)
    const section = screen.getByText(/Drift — master record vs\. surface/).closest('.mcc-section')
    expect(within(section).getByText(/drift is unknown/)).toBeInTheDocument()
    expect(screen.getByText('Drift: unknown')).toBeInTheDocument()
  })

  it('renders a clean probe as no drift', () => {
    render(<ListingDrawer {...drawerProps({ records: { '90:schema_org': [PROBE_CLEAN] } })} />)
    expect(screen.getByText('Structured data matches')).toBeInTheDocument()
    expect(screen.getByText('Newest verification recorded no drift.')).toBeInTheDocument()
    expect(screen.getByText('Drift: 0')).toBeInTheDocument()
  })

  it('renders findings as the master-vs-surface table', () => {
    render(<ListingDrawer {...drawerProps({ records: { '90:schema_org': [PROBE_DRIFT] } })} />)
    const table = screen.getByRole('table')
    expect(within(table).getByText('price')).toBeInTheDocument()
    expect(within(table).getByText('17.99')).toBeInTheDocument()
    expect(within(table).getByText('18.99')).toBeInTheDocument()
    expect(screen.getByText('Drift: 1')).toBeInTheDocument()
  })
})

describe('acceptance section — dimension 3', () => {
  it('renders pending review amber, and drift stays unknown', () => {
    render(<ListingDrawer {...drawerProps({ records: { '90:merchant_center': [GMC_PENDING] } })} />)
    openGmc()

    const section = screen.getByText(/Surface acceptance/).closest('.mcc-section')
    expect(within(section).getByText('Pending review')).toBeInTheDocument()
    expect(within(section).getByText('pending_initial_policy_review_free_listings')).toBeInTheDocument()
    expect(within(section).getByText('pending review')).toBeInTheDocument()

    // The whole point: an acceptance verdict is not drift.
    expect(screen.getByText('Drift: unknown')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('says openly that it overrode the channel’s severity', () => {
    render(<ListingDrawer {...drawerProps({ records: { '90:merchant_center': [GMC_PENDING] } })} />)
    openGmc()
    expect(screen.getByText(/shown as pending because this is a lifecycle code/))
      .toBeInTheDocument()
    expect(screen.getByText('DISAPPROVED')).toBeInTheDocument()
  })

  it('renders the 404 ghost as not in feed', () => {
    render(<ListingDrawer {...drawerProps({ records: { '90:merchant_center': [GMC_GHOST] } })} />)
    openGmc()
    // The label appears twice by design — once as a header chip, once
    // in the section — so scope to the section.
    const section = screen.getByText(/Surface acceptance/).closest('.mcc-section')
    expect(within(section).getByText('Not in feed')).toBeInTheDocument()
    expect(within(section).getByText('HTTP 404')).toBeInTheDocument()
    expect(within(section).getByText(/not found in the account/)).toBeInTheDocument()
  })

  it('renders publish_failed as no opinion available, blaming nobody', () => {
    render(<ListingDrawer {...drawerProps({ records: { '90:merchant_center': [GMC_UNAVAILABLE] } })} />)
    openGmc()
    const section = screen.getByText(/Surface acceptance/).closest('.mcc-section')
    expect(within(section).getByText('No opinion available')).toBeInTheDocument()
    expect(within(section).getByText(/not implemented in Step 2/)).toBeInTheDocument()
    expect(within(section).getByText(/Nothing is counted for this cell/)).toBeInTheDocument()
  })

  it('renders a genuine rejection red and a lifecycle code amber, together', () => {
    const mixed = at(FRESH, {
      ...REAL.gmc_pending_review,
      drift: { approved: false, issues: [
        { code: 'image_link_pending_crawl', severity: 'DISAPPROVED' },
        { code: 'policy_violation_adult', severity: 'DISAPPROVED' },
      ] },
    })
    const { container } = render(
      <ListingDrawer {...drawerProps({ records: { '90:merchant_center': [mixed] } })} />)
    openGmc()

    expect(screen.getByText('pending review')).toBeInTheDocument()
    expect(screen.getByText('action needed')).toBeInTheDocument()
    expect(container.querySelector('.mcc-gmc-issues li.sev-pending')).toBeInTheDocument()
    expect(container.querySelector('.mcc-gmc-issues li.sev-error')).toBeInTheDocument()
  })

  it('shows no acceptance section on a channel with no acceptance authority', () => {
    render(<ListingDrawer {...drawerProps({ records: { '90:schema_org': [PROBE_CLEAN] } })} />)
    expect(screen.queryByText(/Surface acceptance/)).not.toBeInTheDocument()
  })
})

describe('unreadable section — dimension 4', () => {
  it('names the method and disclaims both other dimensions', () => {
    render(<ListingDrawer {...drawerProps({ records: { '90:schema_org': [CORRUPT] } })} />)
    expect(screen.getByText(/Couldn’t parse verification record \(method: sidecar_audit\)/))
      .toBeInTheDocument()
    expect(screen.getByText(/Not counted as drift and not counted as a surface issue/))
      .toBeInTheDocument()
    expect(screen.getByText('Drift: unknown')).toBeInTheDocument()
  })
})

describe('stale records — the freshness rule', () => {
  // Older than every publish in the fixture set.
  const STALE_PROBE = at('2020-01-01T00:00:00Z', REAL.fetch_probe_clean)

  it('puts a superseded record in its own greyed section and counts it nowhere', () => {
    render(<ListingDrawer {...drawerProps({ records: { '90:schema_org': [STALE_PROBE] } })} />)

    expect(screen.getByText(/Superseded verification records \(1\)/)).toBeInTheDocument()
    expect(screen.getAllByText(/pre-dates latest publish/).length).toBeGreaterThan(0)
    // Drift is unknown again — the clean run verified an artifact we
    // have since replaced.
    expect(screen.getByText('Drift: unknown')).toBeInTheDocument()
    // The drift section explains why it is unknown.
    const drift = screen.getByText(/Drift — master record vs\. surface/).closest('.mcc-section')
    expect(within(drift).getByText(/drift stays unknown until a fresh run/)).toBeInTheDocument()
  })

  it('a fresh record alongside a stale one still reports', () => {
    render(<ListingDrawer {...drawerProps({
      records: { '90:schema_org': [PROBE_CLEAN, STALE_PROBE] },
    })} />)
    expect(screen.getByText('Drift: 0')).toBeInTheDocument()
    expect(screen.getByText(/Superseded verification records \(1\)/)).toBeInTheDocument()
  })
})

describe('gmc deep links', () => {
  const REAL_REF = 'accounts/5841611055/productInputs/en~US~90:snug-fit-diapers-s3-small'
  const REAL_LIST = [
    REAL_REF,
    'accounts/5841611055/productInputs/en~US~90:snug-fit-diapers-s3-big',
  ].join(';')

  it('maps a productInputs resource name by offerId', () => {
    const parsed = parseGmcRef(REAL_REF)
    expect(parsed).toMatchObject({
      account: '5841611055', offerId: '90:snug-fit-diapers-s3-small', language: 'en', country: 'US',
    })
    expect(parsed.url).toContain('merchants.google.com/mc/items/details')
  })

  it('splits the semicolon-joined list into one entry per variant', () => {
    const entries = gmcExternalRefs(REAL_LIST)
    expect(entries.map((e) => e.offerId))
      .toEqual(['90:snug-fit-diapers-s3-small', '90:snug-fit-diapers-s3-big'])
    expect(entries.every((e) => e.url)).toBe(true)
  })

  it('keeps an unmappable ref visible but unlinked', () => {
    const entries = gmcExternalRefs('accounts/1/productInputs/en~US~ok;something-else')
    expect(entries[0].url).toBeTruthy()
    expect(entries[1]).toMatchObject({ ref: 'something-else', url: null })
  })

  it('keeps the null fallback for refs that are not resource names', () => {
    expect(gmcDeepLink('deals_api:listing:90')).toBeNull()
    expect(gmcDeepLink(null)).toBeNull()
    expect(parseGmcRef('nonsense')).toBeNull()
  })

  it('still maps the older products/ form', () => {
    expect(gmcDeepLink('accounts/12345/products/online:en:US:sku-1')).toContain('a=12345')
  })

  it('links a diagnostics record’s own offer from the publication account', () => {
    expect(gmcAccountId(REAL_LIST)).toBe('5841611055')
    expect(gmcOfferLink('5841611055', '90:x')).toContain(encodeURIComponent('90:x'))
    expect(gmcOfferLink(null, 'x')).toBeNull()
    expect(gmcOfferLink('123', null)).toBeNull()
  })

  it('renders one link per variant in the drawer', () => {
    const withRefs = publications.map((p) =>
      p.listing_id === 90 && p.channel_slug === 'merchant_center'
        ? { ...p, status: 'published', external_ref: REAL_LIST, published_at: '2026-08-24T21:07:36Z' }
        : p)

    render(<ListingDrawer {...drawerProps({ publications: withRefs })} />)
    openGmc()

    expect(screen.getByText('Merchant Center items (2):')).toBeInTheDocument()
    const links = screen.getAllByRole('link', { name: /snug-fit-diapers-s3/ })
    expect(links).toHaveLength(2)
    expect(links[0].getAttribute('href')).toContain('merchants.google.com/mc/items/details')
  })
})
