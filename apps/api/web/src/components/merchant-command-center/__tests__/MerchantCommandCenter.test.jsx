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
import gmcEnvelope from '../__fixtures__/verifications-gmc.json'
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
      // Added with the prospect view; the page loads the list alongside
      // the live merchant, so every page-level test needs it stubbed.
      getProspects: vi.fn(),
      getProspectDrift: vi.fn(),
    },
    fetchAllVerifications: vi.fn(),
  }
})

// Sidebar reads the auth context; the page under test never uses it.
vi.mock('../../../AuthContext.jsx', () => ({
  useAuth: () => ({ signOut: vi.fn() }),
}))
vi.mock('../../../api.js', () => ({
  api: {
    publishListing: vi.fn(), refreshGmcDiagnostics: vi.fn(), putSyncRule: vi.fn(),
    verifyListing: vi.fn(), verifyListingAcp: vi.fn(), verifyAll: vi.fn(),
  },
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
  truesyncApi.getProspects.mockResolvedValue({ prospects: [] })
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

    // Scoped to tbody: the legend now carries a '?' marker with the
    // same class, and this assertion is about cells.
    const badges = container.querySelectorAll('.mcc-matrix tbody .mcc-verify')
    expect(badges).toHaveLength(35)
    expect([...badges].every((b) => b.textContent === '○')).toBe(true)
    expect([...badges].some((b) => b.classList.contains('clean'))).toBe(false)

    expect(screen.getByText('No fresh verification runs')).toBeInTheDocument()
  })

  it('states last-verified as unavailable rather than borrowing a publish time', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    expect(screen.getByText('No fresh verification run')).toBeInTheDocument()
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

describe('verify runs through the proxy', () => {
  beforeEach(mockHappyPath)

  it('enables "Verify all" and calls the proxied endpoint', async () => {
    api.verifyAll.mockResolvedValue({ verified: 5 })

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    const verifyAll = screen.getByRole('button', { name: /verify all/i })
    expect(verifyAll).not.toBeDisabled()

    fireEvent.click(verifyAll)

    await waitFor(() => expect(api.verifyAll).toHaveBeenCalled())
    expect(await screen.findByText('Verified 5 listings')).toBeInTheDocument()
  })

  it('shows a spinner while a verify-all is in flight and re-reads afterwards', async () => {
    let resolve
    api.verifyAll.mockReturnValue(new Promise((r) => { resolve = r }))

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fetchAllVerifications.mockClear()

    fireEvent.click(screen.getByRole('button', { name: /verify all/i }))

    expect(await screen.findByText('Verifying…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /verifying/i })).toBeDisabled()

    resolve({ verified: 5 })
    // No optimistic update: the badges come from a fresh read.
    await waitFor(() => expect(fetchAllVerifications).toHaveBeenCalled())
  })

  it('surfaces a verify-all failure verbatim', async () => {
    const upstream = 'missing or invalid X-TrueSync-Key'
    api.verifyAll.mockRejectedValue(new Error(upstream))

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: /verify all/i }))

    expect(await screen.findByText(upstream)).toBeInTheDocument()
  })

  it('verifies one listing from the drawer, with a per-listing spinner', async () => {
    let resolve
    api.verifyListing.mockReturnValue(new Promise((r) => { resolve = r }))

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Snug-Fit Diapers'))

    const verifyNow = await screen.findByRole('button', { name: /verify now/i })
    expect(verifyNow).not.toBeDisabled()
    fireEvent.click(verifyNow)

    // Scoped to this listing: the header's Verify all stays available.
    expect(await screen.findByRole('button', { name: /verifying…/i })).toBeInTheDocument()
    expect(api.verifyListing).toHaveBeenCalledWith(90)

    resolve({ outcome: 'ok', integrity: true, findings: [] })
    expect(await screen.findByText('Verified Snug-Fit Diapers · schema_org — no drift')).toBeInTheDocument()
  })

  // The bug this suite missed: the drawer's Verify button dropped the channel
  // and always ran the schema.org probe. Verifying the ACP cell reported
  // success, wrote a schema_org row, and left ACP at "Unverified" — which the
  // live API showed as 4 rows for ?channel=schema_org and [] for ?channel=acp.
  it('verifies the ACP cell against the ACP probe, not the schema.org one', async () => {
    api.verifyListingAcp.mockResolvedValue({ outcome: 'ok', integrity: true, findings: [] })

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Snug-Fit Diapers'))

    // The drawer shows one channel at a time, so select ACP's tab first.
    fireEvent.click(await screen.findByRole('tab', { name: /agentic commerce protocol/i }))
    fireEvent.click(await screen.findByRole('button', { name: /verify feed/i }))

    expect(api.verifyListingAcp).toHaveBeenCalledWith(90)
    expect(api.verifyListing).not.toHaveBeenCalled()
    expect(await screen.findByText('Verified Snug-Fit Diapers · acp — no drift'))
      .toBeInTheDocument()
  })

  it('refetches verifications after an ACP verify, so the cell updates', async () => {
    api.verifyListingAcp.mockResolvedValue({ outcome: 'ok', integrity: true, findings: [] })

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Snug-Fit Diapers'))

    fireEvent.click(await screen.findByRole('tab', { name: /agentic commerce protocol/i }))
    fetchAllVerifications.mockClear()
    fireEvent.click(await screen.findByRole('button', { name: /verify feed/i }))

    // A toast is not a refresh. Without this the badge stays stale until
    // someone reloads the page by hand.
    await waitFor(() => expect(fetchAllVerifications).toHaveBeenCalled())
  })

  it('offers no verify button on a channel with no probe', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Snug-Fit Diapers'))

    // schema.org has a storefront to fetch.
    expect(await screen.findByRole('button', { name: /verify now/i })).toBeInTheDocument()

    // The MCP server has no fetchable surface. It used to show "Verify now"
    // anyway, and clicking it ran the schema.org probe.
    fireEvent.click(await screen.findByRole('tab', { name: /model context protocol/i }))
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /^verify (now|feed)$/i })).toBeNull()
    })
  })

  it('reports findings from a verify rather than claiming success', async () => {
    api.verifyListing.mockResolvedValue({
      outcome: 'ok', integrity: false,
      findings: [{ field: 'price' }, { field: 'availability' }],
    })

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Snug-Fit Diapers'))
    fireEvent.click(await screen.findByRole('button', { name: /verify now/i }))

    expect(await screen.findByText('Verified Snug-Fit Diapers · schema_org — 2 findings')).toBeInTheDocument()
  })

  // A probe that could not read the page is not a success, even though
  // the HTTP call succeeded and it returned zero findings.
  it('treats a non-ok probe outcome as a failure, not "no drift"', async () => {
    api.verifyListing.mockResolvedValue({
      outcome: 'fetch_failed', integrity: null, findings: [], error: 'connection reset',
    })

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Snug-Fit Diapers'))
    fireEvent.click(await screen.findByRole('button', { name: /verify now/i }))

    const toast = await screen.findByText('Snug-Fit Diapers: connection reset')
    expect(toast.closest('.mcc-toast')).toHaveClass('err')
  })
})

describe('sync rules ask before the first real write of a session', () => {
  beforeEach(mockHappyPath)

  async function openRules() {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(screen.getByRole('button', { name: 'Sync rules' }))
  }

  const acpToggle = () => screen.getByRole('switch', {
    name: /agentic commerce protocol sync for snug-fit diapers/i,
  })

  it('shows a confirm naming the channel and direction, and writes nothing yet', async () => {
    await openRules()

    fireEvent.click(acpToggle())

    const confirm = await screen.findByRole('alertdialog')
    expect(confirm).toHaveTextContent(
      'This is a real write — Agentic Commerce Protocol will be enabled for future publishes')
    expect(confirm).toHaveTextContent('Snug-Fit Diapers')
    expect(confirm).toHaveTextContent('catalog_product_id 27')
    // Nothing has been sent while the operator is still deciding.
    expect(api.putSyncRule).not.toHaveBeenCalled()
  })

  it('performs the write only after confirming', async () => {
    api.putSyncRule.mockResolvedValue({ catalog_product_id: 27, channel_slug: 'acp', enabled: true })
    await openRules()
    fireEvent.click(acpToggle())

    fireEvent.click(within(await screen.findByRole('alertdialog'))
      .getByRole('button', { name: /^enable/i }))

    await waitFor(() => expect(api.putSyncRule).toHaveBeenCalledWith({
      catalog_product_id: 27, channel_slug: 'acp', enabled: true,
    }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('sends nothing when the confirm is cancelled', async () => {
    await openRules()
    fireEvent.click(acpToggle())

    fireEvent.click(within(await screen.findByRole('alertdialog'))
      .getByRole('button', { name: /cancel/i }))

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(api.putSyncRule).not.toHaveBeenCalled()
    // And the toggle is untouched — still unknown, because nothing was written.
    expect(acpToggle()).toHaveAttribute('aria-checked', 'mixed')
  })

  // The point of "once per session": enough to establish that these are
  // real writes, not so much that it becomes reflex to dismiss.
  it('asks once — later toggles apply immediately', async () => {
    api.putSyncRule.mockResolvedValue({ catalog_product_id: 27, channel_slug: 'acp', enabled: true })
    await openRules()

    fireEvent.click(acpToggle())
    fireEvent.click(within(await screen.findByRole('alertdialog'))
      .getByRole('button', { name: /^enable/i }))
    await waitFor(() => expect(api.putSyncRule).toHaveBeenCalledTimes(1))

    api.putSyncRule.mockResolvedValue({ catalog_product_id: 27, channel_slug: 'mcp', enabled: true })
    fireEvent.click(screen.getByRole('switch', {
      name: /model context protocol server sync for snug-fit diapers/i,
    }))

    await waitFor(() => expect(api.putSyncRule).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })
})


/**
 * The page rendered against real, timestamped verification records.
 *
 * This block exists because its absence let a bug through: every
 * page-level test ran with `fetchAllVerifications` resolving to {}, so
 * `stats.lastVerifiedAt` was always null and the branches that format a
 * real timestamp never executed. A missing `absoluteTime` import
 * therefore passed the whole suite and only surfaced in a browser.
 */
describe('page rendered with real verification records', () => {
  const GMC_ROWS = gmcEnvelope.verifications

  beforeEach(() => {
    mockHappyPath()
    fetchAllVerifications.mockResolvedValue({ '90:merchant_center': GMC_ROWS })
  })

  it('formats last-verified from created_at instead of saying n/a', async () => {
    const { container } = render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() =>
      expect(container.querySelector('.mcc-verify.drift')).toBeInTheDocument())

    const tile = [...container.querySelectorAll('.mcc-stat')]
      .find((el) => el.textContent.includes('Last verified'))
    expect(tile).not.toHaveTextContent('n/a')
    expect(tile).not.toHaveTextContent('No verification run has recorded a timestamp')
    // Both the relative and the absolute rendering are exercised here.
    expect(tile.textContent).toMatch(/ago/)
  })

  it('counts the GMC ghost as acceptance, never as drift', async () => {
    const { container } = render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() =>
      expect(container.querySelector('.mcc-verify.drift')).toBeInTheDocument())

    // The production case: not approved, zero itemised issues. Under
    // the model this is ACCEPTANCE, not drift — the whole rebuild.
    expect(container.querySelectorAll('.mcc-matrix tbody .mcc-verify.unreadable')).toHaveLength(0)
    const drifting = [...container.querySelectorAll('.mcc-stat')]
      .find((el) => el.textContent.includes('Drifting'))
    expect(within(drifting).getByText('0')).toBeInTheDocument()
    // It shows up as "not in feed" instead (the 404 ghost).
    expect(screen.getByText('not in feed')).toBeInTheDocument()
  })

  it('shows the unreadable indicator separately when a record cannot be parsed', async () => {
    fetchAllVerifications.mockResolvedValue({
      '90:merchant_center': GMC_ROWS,
      '91:schema_org': [{
        id: 99, phase: 'after', method: 'sidecar_audit',
        created_at: '2026-08-24T22:10:00Z', drift: { nothing: 'recognisable' },
      }],
    })

    const { container } = render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() =>
      expect(container.querySelector('.mcc-verify.unreadable')).toBeInTheDocument())

    // Its own indicator, and drift is untouched by it.
    expect(screen.getByText('unreadable')).toBeInTheDocument()
    const drifting = [...container.querySelectorAll('.mcc-stat')]
      .find((el) => el.textContent.includes('Drifting'))
    expect(within(drifting).getByText('0')).toBeInTheDocument()
  })

  it('opens the GMC drawer on the Merchant Center channel', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Snug-Fit Diapers'))
    fireEvent.click(await screen.findByRole('tab', { name: /google merchant center/i }))

    expect(await screen.findByText(/Surface acceptance/)).toBeInTheDocument()
    const section = screen.getByText(/Surface acceptance/).closest('.mcc-section')
    expect(within(section).getByText('Not in feed')).toBeInTheDocument()
    expect(screen.getByText('Drift: unknown')).toBeInTheDocument()
  })
})
