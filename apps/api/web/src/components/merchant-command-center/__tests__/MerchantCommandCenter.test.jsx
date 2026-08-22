/**
 * Render tests for the Merchant Command Center, driven by the same
 * live-captured fixtures the derive tests use
 * (../__fixtures__/README.md).
 *
 * What they pin, in order of how badly it would hurt to get wrong:
 *   1. a down API renders a banner, never a blank page or a spinner
 *      that never resolves
 *   2. stub channels render as stubs — muted, with their depth label —
 *      rather than empty or green
 *   3. nothing verified renders ○ and a zero drift count, not a guess
 *   4. the matrix itself renders from the API payloads
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

import MerchantCommandCenter from '../../MerchantCommandCenter.jsx'
import { truesyncApi, fetchAllVerifications, TrueSyncError } from '../../../truesyncApi.js'
import { api } from '../../../api.js'

// fetchAllVerifications is mocked alongside the client it wraps: it
// closes over the module's own `truesyncApi` binding, so mocking only
// the client object would leave it making real network calls.
vi.mock('../../../truesyncApi.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    truesyncApi: {
      getActiveBrand: vi.fn(),
      getChannels: vi.fn(),
      getPublications: vi.fn(),
      getMerchantSchemaOrg: vi.fn(),
      getListing: vi.fn(),
      getVerifications: vi.fn(),
    },
    fetchAllVerifications: vi.fn(),
  }
})

// Sidebar reads the auth context; the page under test never uses it.
vi.mock('../../../AuthContext.jsx', () => ({
  useAuth: () => ({ signOut: vi.fn() }),
}))
vi.mock('../../../api.js', () => ({
  api: { publishListing: vi.fn(), refreshGmcDiagnostics: vi.fn(), putSyncRule: vi.fn() },
}))

function mockHappyPath() {
  truesyncApi.getActiveBrand.mockResolvedValue(activeBrand)
  truesyncApi.getChannels.mockResolvedValue(channels)
  truesyncApi.getPublications.mockResolvedValue(publications)
  truesyncApi.getMerchantSchemaOrg.mockResolvedValue(spine)
  truesyncApi.getListing.mockImplementation((id) =>
    Promise.resolve(listings[String(id)]))
  truesyncApi.getVerifications.mockResolvedValue([])
  fetchAllVerifications.mockResolvedValue({})
}

beforeEach(() => { vi.clearAllMocks() })
afterEach(() => { vi.restoreAllMocks() })

describe('matrix renders from fixture API payloads', () => {
  beforeEach(mockHappyPath)

  it('renders one row per listing, with live names', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    for (const name of [
      'Snug-Fit Diapers', 'Snug-Fit Overnight Diapers',
      'Cloud Wipes 3-Pack', 'Bum Balm 4 oz', 'Snug-Fit Trial Pack',
    ]) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
  })

  it('renders a column per channel the API returned, real surfaces first', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    const headers = screen.getAllByRole('columnheader').map((th) => th.textContent)
    expect(headers[0]).toContain('Product')
    expect(headers[2]).toContain('Schema.org')
    expect(headers[3]).toContain('Google Merchant Center')
    // Every channel gets a column, stubs included.
    expect(headers).toHaveLength(2 + channels.length)
  })

  it('takes the brand name and accent colour from the active-brand API', async () => {
    const { container } = render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText(activeBrand.site.display_name)).toBeInTheDocument())

    // The accent drives the page's --brand-accent, not a hardcoded value.
    const root = container.querySelector('.mcc')
    expect(root.style.getPropertyValue('--brand-accent'))
      .toBe(activeBrand.site.primary_color)
  })

  it('shows real variant and GTIN counts, including a zero', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    expect(screen.getByText('12 variants')).toBeInTheDocument()
    expect(screen.getByText('4 with GTIN')).toBeInTheDocument()
    // Listings 91 and 94 genuinely have none — both must say so rather
    // than be omitted or rounded up.
    expect(screen.getAllByText('0 with GTIN')).toHaveLength(2)
  })

  it('counts published cells over the whole matrix', async () => {
    const { container } = render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    // 4 live channels x 5 listings out of 35 cells. Scoped to the stat
    // tile — the same numbers also appear in the header meta strip.
    const stat = [...container.querySelectorAll('.mcc-stat')]
      .find((el) => el.textContent.includes('Surface cells published'))
    expect(within(stat).getByText('20')).toBeInTheDocument()
    expect(within(stat).getByText('/ 35')).toBeInTheDocument()
  })
})

describe('stub channels render as stubs', () => {
  beforeEach(mockHappyPath)

  it('marks unbuilt channel columns muted and shows their depth label in-cell', async () => {
    const { container } = render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    const gmc = channels.find((c) => c.slug === 'merchant_center')
    const header = screen.getAllByRole('columnheader')
      .find((th) => th.textContent.includes(gmc.name))
    expect(header).toHaveClass('muted')

    // The depth label is in the cell itself, once per listing — an
    // honest cell, never an empty or a green one.
    const stubLabels = container.querySelectorAll('.mcc-stub-label')
    expect(stubLabels.length).toBeGreaterThan(0)
    expect([...stubLabels].some((el) => el.textContent === gmc.depth_label)).toBe(true)
  })

  it('leaves live channel columns unmuted', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    const header = screen.getAllByRole('columnheader')
      .find((th) => th.textContent.includes('Schema.org'))
    expect(header).not.toHaveClass('muted')
  })

  it('shows the channel depth label as the column tooltip', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    const acp = channels.find((c) => c.slug === 'acp')
    const header = screen.getAllByRole('columnheader')
      .find((th) => th.textContent.includes(acp.name))
    expect(header.getAttribute('title')).toContain(acp.depth_label)
  })
})

describe('no fabricated verification state', () => {
  beforeEach(mockHappyPath)

  it('renders ○ everywhere and a zero drift count when nothing is verified', async () => {
    const { container } = render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    const badges = container.querySelectorAll('.mcc-verify')
    expect(badges).toHaveLength(35)
    expect([...badges].every((b) => b.textContent === '○')).toBe(true)
    expect([...badges].some((b) => b.classList.contains('verified'))).toBe(false)

    expect(screen.getByText('No verification runs recorded')).toBeInTheDocument()
  })

  it('states last-verified as unavailable rather than borrowing a publish time', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    expect(screen.getByText('The verification API returns no timestamps')).toBeInTheDocument()
  })

  it('labels a failed cell as failed rather than showing a bare timestamp', async () => {
    const { container } = render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    const whens = [...container.querySelectorAll('.mcc-cell-when')].map((e) => e.textContent)
    // 3 unbuilt channels x 5 listings.
    expect(whens.filter((w) => w.startsWith('failed'))).toHaveLength(15)
  })
})

describe('API down', () => {
  it('renders a banner, not a blank page', async () => {
    truesyncApi.getActiveBrand.mockRejectedValue(new TrueSyncError('TrueSync did not respond within 15s', { timedOut: true }))
    truesyncApi.getChannels.mockRejectedValue(new TrueSyncError('TrueSync is unreachable'))
    truesyncApi.getPublications.mockRejectedValue(new TrueSyncError('TrueSync is unreachable'))
    truesyncApi.getMerchantSchemaOrg.mockRejectedValue(new TrueSyncError('TrueSync is unreachable'))

    render(<MerchantCommandCenter onNavigate={() => {}} />)

    const banner = await screen.findByRole('alert')
    expect(banner).toHaveTextContent('TrueSync could not be reached')
    expect(banner).toHaveTextContent('did not respond within 15s')
    expect(within(banner).getByRole('button', { name: /retry/i })).toBeInTheDocument()

    // And the spinner must be gone — a permanent "Loading…" is exactly
    // the failure mode the banner exists to prevent.
    await waitFor(() =>
      expect(screen.queryByText('Loading TrueSync catalog…')).not.toBeInTheDocument())
  })

  it('still renders the matrix when only a single listing detail fetch fails', async () => {
    mockHappyPath()
    truesyncApi.getListing.mockImplementation((id) =>
      id === 91
        ? Promise.reject(new TrueSyncError('boom'))
        : Promise.resolve(listings[String(id)]))

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    // The degraded row is still there, named from the spine.
    expect(screen.getByText('Snug-Fit Overnight Diapers')).toBeInTheDocument()
  })
})

describe('actions with no API behind them', () => {
  beforeEach(mockHappyPath)

  it('disables "Verify all" and says why, rather than stubbing a call', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    const verifyAll = screen.getByRole('button', { name: /verify all/i })
    expect(verifyAll).toBeDisabled()
    expect(verifyAll.getAttribute('title')).toMatch(/wire-up pending/i)
  })
})


describe('mutations go through the proxy and render what came back', () => {
  beforeEach(mockHappyPath)

  // "API errors verbatim in a toast" — the page must not paraphrase.
  it('shows an upstream error message word for word', async () => {
    const upstream = 'listing 90: merchant_center not implemented in Step 2'
    api.refreshGmcDiagnostics.mockRejectedValue(new Error(upstream))

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: /refresh google diagnostics/i }))

    const toast = await screen.findByText(upstream)
    expect(toast).toBeInTheDocument()
  })

  it('renders the sync-rule state the API returned, not the one clicked', async () => {
    // The upstream refuses to enable an unbuilt channel and echoes back
    // enabled:false. The toggle must follow the response, not the click
    // — that is the whole reason there are no optimistic updates.
    api.putSyncRule.mockResolvedValue({
      catalog_product_id: 27, channel_slug: 'acp', enabled: false, cadence: null,
    })

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Sync rules' }))

    const toggle = await screen.findByRole('switch', {
      name: /agentic commerce protocol sync for snug-fit diapers/i,
    })
    // Unknown before any write: there is no read endpoint to ask.
    expect(toggle).toHaveAttribute('aria-checked', 'mixed')

    fireEvent.click(toggle)

    await waitFor(() => expect(toggle).toHaveAttribute('aria-checked', 'false'))
    expect(api.putSyncRule).toHaveBeenCalledWith({
      catalog_product_id: 27, channel_slug: 'acp', enabled: true,
    })
  })

  it('keys sync-rule writes by catalog_product_id, never listing_id', async () => {
    api.putSyncRule.mockResolvedValue({ catalog_product_id: 29, channel_slug: 'mcp', enabled: true })

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Sync rules' }))

    fireEvent.click(await screen.findByRole('switch', {
      name: /model context protocol server sync for cloud wipes 3-pack/i,
    }))

    await waitFor(() => expect(api.putSyncRule).toHaveBeenCalled())
    const sent = api.putSyncRule.mock.calls[0][0]
    expect(sent.catalog_product_id).toBe(29)   // listing 92's catalog_product_id
    expect(sent).not.toHaveProperty('listing_id')
  })
})


describe('verification data drives the matrix badges', () => {
  beforeEach(mockHappyPath)

  it('renders ⚠ with a finding count where a run found drift', async () => {
    fetchAllVerifications.mockResolvedValue({
      '90:schema_org': [{
        id: 1, listing_id: 90, channel_slug: 'schema_org',
        phase: 'post_publish', method: 'live_fetch',
        drift: { findings: [
          { variant: 'WS-SFD-1-96', field: 'price', expected: '17.99', observed: '18.99' },
          { variant: 'WS-SFD-1-96', field: 'availability', expected: 'in_stock', observed: 'out_of_stock' },
        ] },
      }],
      '91:schema_org': [{
        id: 2, listing_id: 91, channel_slug: 'schema_org',
        phase: 'post_publish', method: 'live_fetch', drift: null,
      }],
      '92:schema_org': [{
        id: 3, listing_id: 92, channel_slug: 'schema_org',
        phase: 'fetch_failed', method: 'live_fetch', drift: null,
      }],
    })

    const { container } = render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() =>
      expect(container.querySelector('.mcc-verify.drift')).toBeInTheDocument())

    expect(container.querySelector('.mcc-verify.drift').textContent).toBe('⚠ 2')
    expect(container.querySelectorAll('.mcc-verify.verified')).toHaveLength(1)
    expect(container.querySelectorAll('.mcc-verify.failed')).toHaveLength(1)
    // The other 32 cells genuinely have no runs.
    expect(container.querySelectorAll('.mcc-verify.none')).toHaveLength(32)
  })

  it('rolls those into the header counts', async () => {
    fetchAllVerifications.mockResolvedValue({
      '90:schema_org': [{ id: 1, phase: 'post_publish', method: 'live_fetch', drift: { price: { expected: 1, observed: 2 } } }],
      '91:schema_org': [{ id: 2, phase: 'post_publish', method: 'live_fetch', drift: null }],
    })

    const { container } = render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() =>
      expect(container.querySelector('.mcc-verify.drift')).toBeInTheDocument())

    const drifting = [...container.querySelectorAll('.mcc-stat')]
      .find((el) => el.textContent.includes('Drifting'))
    expect(within(drifting).getByText('1')).toBeInTheDocument()
    expect(drifting).toHaveTextContent('1 verified clean')
  })

  it('shows the master-vs-surface comparison in the drawer', async () => {
    fetchAllVerifications.mockResolvedValue({
      '90:schema_org': [{
        id: 1, phase: 'post_publish', method: 'live_fetch',
        drift: { findings: [
          { variant: 'WS-SFD-1-96', field: 'price', expected: '17.99', observed: '18.99' },
        ] },
      }],
    })

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Snug-Fit Diapers'))

    expect(await screen.findByText('WS-SFD-1-96')).toBeInTheDocument()
    expect(screen.getByText('17.99')).toBeInTheDocument()
    expect(screen.getByText('18.99')).toBeInTheDocument()
    expect(screen.getByText('Drift · 1 field')).toBeInTheDocument()
  })
})
