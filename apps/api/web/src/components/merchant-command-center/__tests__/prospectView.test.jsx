/**
 * The prospect view renders the model's output — the switcher, the
 * three distinct surface outcomes, and the honest not-comparable state.
 *
 * Fixtures are the real Pampers production responses. No test here
 * fetches anything.
 */
import React from 'react'
import { render, screen, within, fireEvent, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import DRIFT from '../__fixtures__/prospect-drift-pampers.json'
import PROSPECTS from '../__fixtures__/prospects.json'
import activeBrand from '../__fixtures__/active-brand.json'
import channels from '../__fixtures__/channels.json'
import publications from '../__fixtures__/publications.json'
import spine from '../__fixtures__/merchant-schema-org.json'
import listings from '../__fixtures__/listings.json'

import ProspectView from '../ProspectView.jsx'
import CatalogSourceSwitcher from '../CatalogSourceSwitcher.jsx'
import MerchantCommandCenter from '../../MerchantCommandCenter.jsx'
import { truesyncApi, fetchAllVerifications } from '../../../truesyncApi.js'
import {
  aggregateProspectProduct, summarizeProspect, SURFACE_OUTCOME,
} from '../verificationModel.js'

vi.mock('../../../truesyncApi.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    truesyncApi: {
      getActiveBrand: vi.fn(), getChannels: vi.fn(), getPublications: vi.fn(),
      getMerchantSchemaOrg: vi.fn(), getListing: vi.fn(), getVerifications: vi.fn(),
      getProspects: vi.fn(), getProspectDrift: vi.fn(),
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

const products = () => DRIFT.products.map(aggregateProspectProduct)
const renderView = (list = products()) =>
  render(<ProspectView prospect={DRIFT} products={list} totals={summarizeProspect(list)} />)

function mockLive() {
  truesyncApi.getActiveBrand.mockResolvedValue(activeBrand)
  truesyncApi.getChannels.mockResolvedValue(channels)
  truesyncApi.getPublications.mockResolvedValue(publications)
  truesyncApi.getMerchantSchemaOrg.mockResolvedValue(spine)
  truesyncApi.getListing.mockImplementation((id) => Promise.resolve(listings[String(id)]))
  fetchAllVerifications.mockResolvedValue({})
  truesyncApi.getProspects.mockResolvedValue(PROSPECTS)
  truesyncApi.getProspectDrift.mockResolvedValue(DRIFT)
}

beforeEach(() => { vi.clearAllMocks() })

// ─── Banner and framing ──────────────────────────────────────────────

describe('prospect mode says what it is', () => {
  it('banners read-only observation, unmissably', () => {
    renderView()
    const banner = screen.getByRole('status')
    expect(banner).toHaveTextContent('Prospect mode')
    expect(banner).toHaveTextContent('read-only observation of public surfaces; nothing is published')
  })

  it('never renders a publish state, a sync matrix, or a publish control', () => {
    renderView()
    expect(screen.queryByText(/Syndication matrix/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /publish now/i })).not.toBeInTheDocument()
    expect(screen.queryByText(/Never published/)).not.toBeInTheDocument()
  })

  it('closes with the three-facts framing', () => {
    renderView()
    expect(screen.getByText(/three different facts/)).toBeInTheDocument()
  })
})

// ─── Surface outcomes render distinctly ──────────────────────────────

describe('the three facts are three different renderings', () => {
  it('renders ok and no_structured_data with different tones and labels', () => {
    const { container } = renderView()
    expect(screen.getAllByText('Read').length).toBe(2)
    expect(screen.getAllByText('No structured data').length).toBe(4)
    expect(container.querySelectorAll('.mcc-surface.tone-sync')).toHaveLength(2)
    expect(container.querySelectorAll('.mcc-surface.tone-drift')).toHaveLength(4)
  })

  it('shows the byte contrast that tells the wall from the real page', () => {
    renderView()
    // 15 KB Walmart stub vs 1.3 MB Target page — both no_structured_data,
    // and only the size distinguishes them.
    expect(screen.getByText('15 KB')).toBeInTheDocument()
    expect(screen.getByText('1.3 MB')).toBeInTheDocument()
  })

  it('surfaces the redirect that a no_structured_data badge alone would hide', () => {
    renderView()
    const redirects = screen.getAllByText(/Redirected to/)
    expect(redirects.length).toBeGreaterThan(0)
    expect(screen.getByText(/walmart\.com\/blocked/)).toBeInTheDocument()
  })

  it('renders blocked, disallowed and absent with three different tones', () => {
    const synthetic = aggregateProspectProduct({
      product_key: 'k', product_label: 'Three facts', observed: true,
      configured_surfaces: ['a', 'b', 'c'],
      drift: { outcome: 'insufficient_surfaces', findings: [], surfaces_read: 0, surfaces_total: 3 },
      surfaces: [
        { surface: 'a.com', url: 'https://a.com', outcome: SURFACE_OUTCOME.BLOCKED_FOR_AGENTS, transport: { bytes: 512, http_status: 403, attempts: 3 } },
        { surface: 'b.com', url: 'https://b.com', outcome: SURFACE_OUTCOME.ROBOTS_DISALLOWED, transport: {} },
        { surface: 'c.com', url: 'https://c.com', outcome: SURFACE_OUTCOME.NO_STRUCTURED_DATA, transport: { bytes: 900000, http_status: 200 } },
      ],
    })
    const { container } = renderView([synthetic])

    expect(screen.getByText('Blocked for agents')).toBeInTheDocument()
    expect(screen.getByText('Disallowed by robots')).toBeInTheDocument()
    expect(screen.getByText('No structured data')).toBeInTheDocument()
    expect(container.querySelectorAll('.mcc-surface.tone-fail')).toHaveLength(1)
    expect(container.querySelectorAll('.mcc-surface.tone-hold')).toHaveLength(1)
    expect(container.querySelectorAll('.mcc-surface.tone-drift')).toHaveLength(1)
    // The evidence behind the blocked row.
    expect(screen.getByText('3 attempts')).toBeInTheDocument()
    expect(screen.getByText('HTTP 403')).toBeInTheDocument()
  })
})

// ─── insufficient_surfaces ───────────────────────────────────────────

describe('insufficient_surfaces is its own state', () => {
  it('says how many surfaces were readable and that comparison was not possible', () => {
    renderView()
    const notices = screen.getAllByText(/cross-surface comparison not possible/i)
    expect(notices).toHaveLength(3)
    expect(screen.getAllByText(/Only 1 of 2 surfaces readable/).length).toBe(2)
    expect(screen.getByText(/Only 0 of 2 surfaces readable/)).toBeInTheDocument()
  })

  // The bug this whole state exists to prevent.
  it('never implies the surfaces agreed', () => {
    renderView()
    expect(screen.queryByText(/All readable surfaces agree/)).not.toBeInTheDocument()
    expect(screen.getAllByText(/not agreement between surfaces/).length).toBeGreaterThan(0)
  })

  it('explains the zero-readable case differently from the one-readable case', () => {
    renderView()
    expect(screen.getByText(/No surface returned machine-readable product data/)).toBeInTheDocument()
    expect(screen.getAllByText(/A single surface cannot disagree with itself/).length).toBe(2)
  })

  it('renders agreement only when the comparison actually ran', () => {
    const agreed = aggregateProspectProduct({
      product_key: 'k', product_label: 'Agreed', observed: true,
      drift: { outcome: 'ok', findings: [], surfaces_read: 2, surfaces_total: 2 },
      surfaces: [
        { surface: 'a.com', outcome: 'ok', transport: {} },
        { surface: 'b.com', outcome: 'ok', transport: {} },
      ],
    })
    renderView([agreed])
    expect(screen.getByText(/All readable surfaces agree/)).toBeInTheDocument()
  })
})

// ─── Findings table ──────────────────────────────────────────────────

describe('surface-vs-surface findings', () => {
  const drifting = aggregateProspectProduct({
    product_key: 'k', product_label: 'Disagreeing', observed: true,
    drift: {
      outcome: 'drift_detected', surfaces_read: 2, surfaces_total: 2,
      findings: [
        { variant_key: 'v', field: 'price', surface_a: 'pampers.com', value_a: '9.97', surface_b: 'target.com', value_b: '12.49' },
        { variant_key: 'v', field: 'gtin_missing', surface_a: 'pampers.com', value_a: '037000863403', surface_b: 'target.com', value_b: null },
      ],
    },
    surfaces: [
      { surface: 'pampers.com', outcome: 'ok', transport: {} },
      { surface: 'target.com', outcome: 'ok', transport: {} },
    ],
  })

  it('names both surfaces and styles neither as correct', () => {
    const { container } = renderView([drifting])
    const table = screen.getByRole('table')
    expect(within(table).getByText('9.97')).toBeInTheDocument()
    expect(within(table).getByText('12.49')).toBeInTheDocument()
    // No master here: both values carry the same neutral styling.
    expect(container.querySelectorAll('.mcc-val.neutral').length).toBe(4)
    expect(container.querySelectorAll('.mcc-val.good')).toHaveLength(0)
    expect(container.querySelectorAll('.mcc-val.bad')).toHaveLength(0)
  })

  it('calls out a missing identifier as its own kind of finding', () => {
    const { container } = renderView([drifting])
    expect(screen.getByText('identifier missing')).toBeInTheDocument()
    expect(container.querySelector('tr.finding-identifier')).toBeInTheDocument()
    expect(screen.getByText('missing')).toBeInTheDocument()
  })
})

// ─── Agent access ────────────────────────────────────────────────────

describe('agent access policy', () => {
  it('flags the domain closed to every agent without opening the table', () => {
    renderView()
    expect(screen.getAllByText(/closed to all 6/i).length).toBeGreaterThan(0)
  })

  it('expands into a per-agent table naming all six', () => {
    renderView()
    fireEvent.click(screen.getAllByRole('button', { name: /closed to all 6/i })[0])

    for (const agent of ['GPTBot', 'OAI-SearchBot', 'ChatGPT-User', 'ClaudeBot', 'PerplexityBot', 'Google-Extended']) {
      expect(screen.getByText(agent)).toBeInTheDocument()
    }
    expect(screen.getAllByText('blocked').length).toBeGreaterThanOrEqual(12)  // root + product pages
    expect(screen.getByText(/robots\.txt blocks GPTBot specifically/)).toBeInTheDocument()
  })

  it('reports the totals tile from the model, not from the DOM', () => {
    renderView()
    const tile = screen.getByText('Closed to agents').closest('.mcc-stat')
    expect(within(tile).getByText('1')).toBeInTheDocument()
    expect(tile).toHaveTextContent('www.amazon.com')
  })
})

// ─── Switcher ────────────────────────────────────────────────────────

describe('catalog source switcher', () => {
  it('offers the live merchant and each prospect with its counts', () => {
    render(
      <CatalogSourceSwitcher
        brandName="Wiggle & Snug" prospects={PROSPECTS.prospects}
        activeSlug={null} onSelect={() => {}}
      />)
    expect(screen.getByRole('tab', { name: /Wiggle & Snug/ })).toHaveAttribute('aria-selected', 'true')
    const prospectTab = screen.getByRole('tab', { name: /Pampers/ })
    expect(prospectTab).toHaveAttribute('aria-selected', 'false')
    expect(prospectTab).toHaveTextContent('3/3 products')
    expect(prospectTab).toHaveTextContent('Read-only')
  })

  it('reports the chosen slug, and null for the live merchant', () => {
    const onSelect = vi.fn()
    render(
      <CatalogSourceSwitcher
        brandName="Wiggle & Snug" prospects={PROSPECTS.prospects}
        activeSlug="pampers" onSelect={onSelect}
      />)
    fireEvent.click(screen.getByRole('tab', { name: /Wiggle & Snug/ }))
    expect(onSelect).toHaveBeenCalledWith(null)
    fireEvent.click(screen.getByRole('tab', { name: /Pampers/ }))
    expect(onSelect).toHaveBeenCalledWith('pampers')
  })
})

// ─── Integration through the page ────────────────────────────────────

describe('switching modes in the page', () => {
  beforeEach(mockLive)

  it('swaps the matrix for the prospect report and back', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())

    fireEvent.click(await screen.findByRole('tab', { name: /Pampers/ }))

    await waitFor(() => expect(screen.getByText(/Prospect mode/)).toBeInTheDocument())
    expect(screen.queryByText(/Syndication matrix/)).not.toBeInTheDocument()
    expect(screen.getByText('Pampers Swaddlers Diapers Size 1, 198 Count')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('tab', { name: /Wiggle & Snug/ }))
    await waitFor(() => expect(screen.getByText(/Syndication matrix/)).toBeInTheDocument())
    expect(screen.queryByText(/Prospect mode/)).not.toBeInTheDocument()
  })

  // Prospect data must never touch the live merchant's numbers.
  it('leaves the live merchant counts untouched by prospect data', async () => {
    const { container } = render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    const before = container.querySelector('.mcc-context-meta').textContent

    fireEvent.click(await screen.findByRole('tab', { name: /Pampers/ }))
    await waitFor(() => expect(screen.getByText(/Prospect mode/)).toBeInTheDocument())
    fireEvent.click(screen.getByRole('tab', { name: /Wiggle & Snug/ }))
    await waitFor(() => expect(screen.getByText(/Syndication matrix/)).toBeInTheDocument())

    expect(container.querySelector('.mcc-context-meta').textContent).toBe(before)
  })

  it('hides publish/verify controls in prospect mode — nothing here publishes', async () => {
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: /verify all/i })).toBeInTheDocument()

    fireEvent.click(await screen.findByRole('tab', { name: /Pampers/ }))
    await waitFor(() => expect(screen.getByText(/Prospect mode/)).toBeInTheDocument())

    expect(screen.queryByRole('button', { name: /verify all/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /refresh google diagnostics/i })).not.toBeInTheDocument()
  })

  it('renders a banner, not a blank page, when prospect drift fails', async () => {
    truesyncApi.getProspectDrift.mockRejectedValue(new Error('prospect ingest unavailable'))

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    fireEvent.click(await screen.findByRole('tab', { name: /Pampers/ }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Prospect observations could not be loaded')
    expect(alert).toHaveTextContent('prospect ingest unavailable')
  })

  // The prospect list failing must not take the live merchant down.
  it('still renders the matrix when the prospect list is unavailable', async () => {
    truesyncApi.getProspects.mockRejectedValue(new Error('down'))

    render(<MerchantCommandCenter onNavigate={() => {}} />)
    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    expect(screen.getByText(/Syndication matrix/)).toBeInTheDocument()
    expect(screen.queryByRole('tab', { name: /Pampers/ })).not.toBeInTheDocument()
  })
})
