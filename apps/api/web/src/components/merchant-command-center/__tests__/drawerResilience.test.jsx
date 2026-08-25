/**
 * Regression tests for the "dead click": selecting a matrix row must
 * always put something visible on screen.
 *
 * The original defect was not an exception — the drawer rendered
 * correctly, below the fold, with nothing scrolling it into view
 * (measured: drawer top at viewport y=1057 on a 900px viewport, five
 * listings, scrollY=0). Nothing in the console, nothing on screen, and
 * a second click toggled it shut. These tests pin the fix and the
 * hardening that went with it.
 */
import React from 'react'
import { render, screen, waitFor, within, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import '@testing-library/jest-dom'

import activeBrand from '../__fixtures__/active-brand.json'
import channels from '../__fixtures__/channels.json'
import publications from '../__fixtures__/publications.json'
import spine from '../__fixtures__/merchant-schema-org.json'
import listings from '../__fixtures__/listings.json'
import verificationEnvelope from '../__fixtures__/verifications-envelope.json'

import MerchantCommandCenter from '../../MerchantCommandCenter.jsx'
import ListingDrawer from '../ListingDrawer.jsx'
import DrawerErrorBoundary from '../DrawerErrorBoundary.jsx'
import { unwrapVerifications } from '../../../truesyncApi.js'
import { truesyncApi, fetchAllVerifications } from '../../../truesyncApi.js'
import { buildCatalogRows, latestPublicationByCell, orderChannels } from '../truesyncDerive.js'
import { aggregateCell } from '../verificationModel.js'

vi.mock('../../../truesyncApi.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    truesyncApi: {
      getActiveBrand: vi.fn(), getChannels: vi.fn(), getPublications: vi.fn(),
      getMerchantSchemaOrg: vi.fn(), getListing: vi.fn(), getVerifications: vi.fn(),
    },
    fetchAllVerifications: vi.fn(),
  }
})
vi.mock('../../../AuthContext.jsx', () => ({ useAuth: () => ({ signOut: vi.fn() }) }))
vi.mock('../../../api.js', () => ({
  api: {
    publishListing: vi.fn(), refreshGmcDiagnostics: vi.fn(), putSyncRule: vi.fn(),
    verifyListing: vi.fn(), verifyAll: vi.fn(),
  },
}))

function mockHappyPath(verifications = {}) {
  truesyncApi.getActiveBrand.mockResolvedValue(activeBrand)
  truesyncApi.getChannels.mockResolvedValue(channels)
  truesyncApi.getPublications.mockResolvedValue(publications)
  truesyncApi.getMerchantSchemaOrg.mockResolvedValue(spine)
  truesyncApi.getListing.mockImplementation((id) => Promise.resolve(listings[String(id)]))
  fetchAllVerifications.mockResolvedValue(verifications)
}

beforeEach(() => { vi.clearAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

// Props for rendering ListingDrawer on its own, so a single bad record
// can be aimed straight at it.
function drawerProps(overrides = {}) {
  const ordered = orderChannels(channels)
  const rows = buildCatalogRows(spine, Object.fromEntries(
    Object.entries(listings).map(([id, d]) => [Number(id), d])))
  const pubs = overrides.publications || publications
  const records = overrides.verificationsByCell || {}
  const byCell = latestPublicationByCell(pubs)

  // The drawer consumes aggregateCell output and counts nothing itself
  // — see docs/verification-semantics.md.
  const cellFor = (row, channel) => aggregateCell(
    byCell.get(`${row.listingId}:${channel.slug}`),
    records[`${row.listingId}:${channel.slug}`] || [],
    { channelSlug: channel.slug },
  )

  const { verificationsByCell, ...rest } = overrides
  return {
    row: rows[0],
    channels: ordered,
    channelState: Object.fromEntries(ordered.map((c) => [c.slug, { implementation: 'live', muted: false }])),
    cellFor,
    publications: pubs,
    onClose: () => {},
    onPublish: () => {},
    publishPending: false,
    onVerify: () => {},
    verifyPending: false,
    ...rest,
  }
}

// ─── the root cause ──────────────────────────────────────────────────

describe('selecting a row is never a dead click', () => {
  beforeEach(() => mockHappyPath())

  it('scrolls the drawer into view when a row is selected', async () => {
    const scrollIntoView = vi.fn()
    // jsdom has no scrollIntoView at all; installing a spy is both the
    // stub and the assertion.
    window.HTMLElement.prototype.scrollIntoView = scrollIntoView

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Snug-Fit Diapers'))

    await waitFor(() => expect(scrollIntoView).toHaveBeenCalled())
    expect(scrollIntoView.mock.calls[0][0]).toMatchObject({ block: 'nearest' })
  })

  it('still opens the drawer when scrollIntoView does not exist', async () => {
    delete window.HTMLElement.prototype.scrollIntoView

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Snug-Fit Diapers'))

    expect(await screen.findByText(/Snug-Fit Diapers — Schema\.org/)).toBeInTheDocument()
  })

  it('renders a visible panel rather than nothing when there are no channels', () => {
    render(<ListingDrawer {...drawerProps({ channels: [], channelState: {} })} />)

    expect(screen.getByRole('alert')).toHaveTextContent('no channel to show')
  })
})

// ─── resilience to the records the API actually returns ──────────────

describe('drawer renders from records with missing fields', () => {
  // The real VerificationResponse has no created_at and no outcome —
  // confirmed against the live OpenAPI schema. Everything optional is
  // null here as well.
  const NULL_RECORD = {
    id: null, listing_id: 90, gtin: null, channel_slug: 'schema_org',
    phase: null, method: null, observed: null, drift: null,
    created_at: null, outcome: null,
  }

  it('renders a verification with null created_at/outcome as "—", not a crash', () => {
    render(<ListingDrawer {...drawerProps({
      verificationsByCell: { '90:schema_org': [NULL_RECORD] },
    })} />)

    // A record with no created_at is stale by the freshness rule, so it
    // lands in the superseded section and counts for nothing.
    const stale = screen.getByText(/Superseded verification records/).closest('.mcc-section')
    expect(within(stale).getAllByText(/pre-dates latest publish/).length).toBeGreaterThan(0)
    // Drift is unknown, because nothing fresh has run.
    expect(screen.getByText('Drift: unknown')).toBeInTheDocument()
    // And the panel as a whole survived.
    expect(screen.getByText(/Snug-Fit Diapers — Schema\.org/)).toBeInTheDocument()
  })

  it('renders drift findings whose every field is null', () => {
    // Must be a fresh fetch_probe to reach the comparison table at all:
    // a record with no method is unreadable, and one with no created_at
    // is stale. Both are correct under the model — this test is about
    // what the table does with null FIELDS, not null metadata.
    render(<ListingDrawer {...drawerProps({
      verificationsByCell: { '90:schema_org': [{
        ...NULL_RECORD,
        method: 'fetch_probe',
        created_at: '2099-01-01T00:00:00Z',
        drift: { findings: [{ variant: null, field: null, expected: null, observed: null }] },
      }] },
    })} />)

    const comparison = screen.getByText(/Drift — master record vs\. surface/).closest('.mcc-section')
    expect(within(comparison).getByText('missing')).toBeInTheDocument()
    // Null field names render as the em-dash placeholder, not a crash.
    expect(within(comparison).getAllByText('—').length).toBeGreaterThan(0)
  })

  it('survives a record whose fields are objects where strings were expected', () => {
    // React throws "Objects are not valid as a React child" on this
    // unless every scalar goes through text().
    render(<ListingDrawer {...drawerProps({
      verificationsByCell: { '90:schema_org': [{
        ...NULL_RECORD, phase: { nested: 'object' }, method: ['an', 'array'],
      }] },
    })} />)

    // Survives; the record is unreadable (unknown method shape), which
    // is its own dimension and not a drift finding.
    expect(screen.getByText(/Snug-Fit Diapers — Schema\.org/)).toBeInTheDocument()
  })

  it('survives a publication row with a null status and no timestamps', () => {
    render(<ListingDrawer {...drawerProps({
      publications: [{
        id: 1, record_ref: 'listing:90', listing_id: 90, channel_slug: 'schema_org',
        payload: null, validation: null, expressiveness: null, spec_version: null,
        status: null, external_ref: null, compiled_at: null, published_at: null, error: null,
      }],
    })} />)

    expect(screen.getByText('unknown status')).toBeInTheDocument()
    expect(screen.getByText(/Snug-Fit Diapers — Schema\.org/)).toBeInTheDocument()
  })
})

// ─── the boundary ────────────────────────────────────────────────────

describe('error boundary', () => {
  let consoleError
  beforeEach(() => { consoleError = vi.spyOn(console, 'error').mockImplementation(() => {}) })

  function Boom() { throw new Error('corrupt verification record') }

  it('shows a visible panel naming the failure instead of failing silently', () => {
    render(
      <DrawerErrorBoundary resetKey={90} onClose={() => {}} context="listing_id 90">
        <Boom />
      </DrawerErrorBoundary>,
    )

    const panel = screen.getByRole('alert')
    expect(panel).toHaveTextContent('Couldn’t render details: corrupt verification record')
    expect(within(panel).getByRole('button', { name: /close/i })).toBeInTheDocument()
    expect(consoleError).toHaveBeenCalled()
  })

  it('catches a genuinely corrupt fixture rather than unmounting the page', () => {
    // A drift record shaped so that driftFindings returns something the
    // renderer cannot handle: a getter that throws when read.
    const corrupt = {
      id: 1, phase: 'post_publish', method: 'live_fetch',
      get drift() { throw new Error('unreadable drift blob') },
    }

    render(
      <DrawerErrorBoundary resetKey={90} onClose={() => {}}>
        <ListingDrawer {...drawerProps({ verificationsByCell: { '90:schema_org': [corrupt] } })} />
      </DrawerErrorBoundary>,
    )

    expect(screen.getByRole('alert')).toHaveTextContent('unreadable drift blob')
  })

  it('clears the error when a different row is selected', () => {
    const { rerender } = render(
      <DrawerErrorBoundary resetKey={90}><Boom /></DrawerErrorBoundary>,
    )
    expect(screen.getByRole('alert')).toBeInTheDocument()

    rerender(
      <DrawerErrorBoundary resetKey={91}><div>recovered</div></DrawerErrorBoundary>,
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText('recovered')).toBeInTheDocument()
  })
})

// ─── the API envelope that changed under us ──────────────────────────

describe('verifications endpoint envelope', () => {
  it('unwraps the 2026-08-24 envelope', () => {
    expect(unwrapVerifications(verificationEnvelope)).toEqual(verificationEnvelope.verifications)
  })

  it('still accepts the older bare array', () => {
    const rows = [{ id: 1, phase: 'post_publish', method: 'live_fetch' }]
    expect(unwrapVerifications(rows)).toBe(rows)
  })

  it('resolves anything unrecognised to [] rather than throwing', () => {
    expect(unwrapVerifications(null)).toEqual([])
    expect(unwrapVerifications({ unexpected: true })).toEqual([])
    expect(unwrapVerifications('nonsense')).toEqual([])
  })
})
