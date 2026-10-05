/**
 * The customer switcher (Step 1C), on its own and through the page.
 *
 * Two customers from fixtures: Wiggle & Snug (Parleo-hosted, the live
 * fixtures' merchant) and Acme Pets (customer-hosted, its record a SKU
 * feed). Selecting one must scope every read on the page to it — asserted
 * on the `customer` each read was made under, which is what the proxy turns
 * into that org's token.
 */
import React from 'react'
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import '@testing-library/jest-dom'

import channels from '../__fixtures__/channels.json'
import publications from '../__fixtures__/publications.json'
import spine from '../__fixtures__/merchant-schema-org.json'
import listings from '../__fixtures__/listings.json'

import CustomerSwitcher from '../CustomerSwitcher.jsx'
import MerchantCommandCenter from '../../MerchantCommandCenter.jsx'
import { truesyncApi, fetchAllVerifications } from '../../../truesyncApi.js'
import { listCustomers } from '../../../customersApi.js'
import { getSelection } from '../../../customerSelection.js'

vi.mock('../../../truesyncApi.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    truesyncApi: {
      getActiveBrand: vi.fn(), getChannels: vi.fn(), getPublications: vi.fn(),
      getMerchantSchemaOrg: vi.fn(), getListing: vi.fn(), getVerifications: vi.fn(),
      getProspects: vi.fn(), getProspectDrift: vi.fn(), getMerchantCatalog: vi.fn(),
    },
    fetchAllVerifications: vi.fn(),
  }
})
vi.mock('../../../customersApi.js', async (importOriginal) => ({
  ...(await importOriginal()),
  listCustomers: vi.fn(),
}))
vi.mock('../../../AuthContext.jsx', () => ({ useAuth: () => ({ signOut: vi.fn() }) }))
vi.mock('../../../api.js', () => ({
  api: {
    publishListing: vi.fn(), refreshGmcDiagnostics: vi.fn(), putSyncRule: vi.fn(),
    verifyListing: vi.fn(), verifyListingAcp: vi.fn(), verifyAll: vi.fn(),
  },
  apiAuthHeaders: () => ({}),
  expireSession: vi.fn(),
}))

const WS = { slug: 'wiggle-and-snug', name: 'Wiggle & Snug', domain: 'trueshopstore.com',
             kind: 'seller', hosting: 'parleo', has_record: true }
const ACME = { slug: 'acme-pets', name: 'Acme Pets', domain: 'acme-pets.test',
               kind: 'seller', hosting: 'external', has_record: true }
const CUSTOMERS = [
  { org_id: 31, name: 'Acme Pets', tenant_slug: 'acme-pets', error: null, merchants: [ACME] },
  { org_id: 7, name: 'Wiggle & Snug', tenant_slug: 'wiggle-and-snug', error: null, merchants: [WS] },
]
const PROSPECTS = [{ slug: 'pampers', prospect: 'Pampers', products_observed: 3, products_configured: 3 }]

// The feed-served catalog for Acme (supply 1B's catalog route shape).
const ACME_CATALOG = {
  merchant: 'acme-pets',
  listings: [
    { listing_id: 501, product_url: 'https://www.acme-pets.test/p/1', published_at: '2026-10-04T12:00:00Z',
      spec_version: 'sku-feed', title: 'Trailmix Adult Dog Food', brand: 'Trailmix',
      variants: [
        { variant_id: '00009900011005', gtin: '00009900011005', list_price: '74.98', currency: 'USD' },
        { variant_id: '00009900011012', gtin: '00009900011012', list_price: '46.98', currency: 'USD' },
      ] },
    { listing_id: 503, product_url: 'https://www.acme-pets.test/p/3', published_at: '2026-10-04T12:00:00Z',
      spec_version: 'sku-feed', title: 'Snugwalk Dog Harness', brand: 'Snugwalk',
      variants: [{ variant_id: '00009900011081', gtin: '00009900011081', list_price: '24.99', currency: 'USD' }] },
  ],
}

beforeEach(() => {
  vi.clearAllMocks()
  window.sessionStorage.clear()
  truesyncApi.getChannels.mockResolvedValue(channels)
  truesyncApi.getPublications.mockResolvedValue(publications)
  truesyncApi.getMerchantSchemaOrg.mockResolvedValue(spine)
  truesyncApi.getListing.mockImplementation((id) => Promise.resolve(listings[String(id)]))
  truesyncApi.getProspects.mockResolvedValue({ prospects: [] })
  truesyncApi.getMerchantCatalog.mockResolvedValue(ACME_CATALOG)
  fetchAllVerifications.mockResolvedValue({})
})

// ─── The control ────────────────────────────────────────────────────

describe('the switcher lists customers, each expanding to its merchants', () => {
  function open(props = {}) {
    const onSelect = vi.fn()
    const onNewCustomer = vi.fn()
    render(
      <CustomerSwitcher
        customers={CUSTOMERS} isOperator={false} prospects={[]}
        selection={{ orgId: 7, merchantSlug: 'wiggle-and-snug', prospectSlug: null }}
        onSelect={onSelect} onNewCustomer={onNewCustomer} {...props}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Customer' }))
    return { onSelect, onNewCustomer }
  }

  it('shows every customer with its merchants: name, kind, hosting', () => {
    open()
    const acme = screen.getByRole('group', { name: 'Acme Pets' })
    const ws = screen.getByRole('group', { name: 'Wiggle & Snug' })
    expect(within(acme).getByRole('menuitemradio', { name: /Acme Pets/ }))
      .toHaveTextContent('acme-pets.testSellerCustomer-hosted')
    expect(within(ws).getByRole('menuitemradio', { name: /Wiggle & Snug/ }))
      .toHaveTextContent('SellerParleo-hosted')
    expect(within(ws).getByRole('menuitemradio', { name: /Wiggle & Snug/ }))
      .toHaveAttribute('aria-checked', 'true')
  })

  it('reports the chosen org and merchant', () => {
    const { onSelect } = open()
    fireEvent.click(screen.getByRole('menuitemradio', { name: /Acme Pets/ }))
    expect(onSelect).toHaveBeenCalledWith({ orgId: 31, merchantSlug: 'acme-pets', prospectSlug: null })
  })

  it('offers prospects as a read-only mode of the SELECTED customer only', () => {
    const { onSelect } = open({ prospects: PROSPECTS })
    const ws = screen.getByRole('group', { name: 'Wiggle & Snug' })
    const pampers = within(ws).getByRole('menuitemradio', { name: /Pampers/ })
    expect(within(screen.getByRole('group', { name: 'Acme Pets' }))
      .queryByRole('menuitemradio', { name: /Pampers/ })).not.toBeInTheDocument()
    fireEvent.click(pampers)
    expect(onSelect).toHaveBeenCalledWith({ orgId: 7, merchantSlug: 'wiggle-and-snug', prospectSlug: 'pampers' })
  })

  it('offers "New customer" to operators only', () => {
    open()
    expect(screen.queryByRole('button', { name: '+ New customer' })).not.toBeInTheDocument()
  })

  it('an operator\'s footer opens the wizard', () => {
    const { onNewCustomer } = open({ isOperator: true })
    fireEvent.click(screen.getByRole('button', { name: '+ New customer' }))
    expect(onNewCustomer).toHaveBeenCalled()
  })

  it('keeps a refused customer listed, saying why', () => {
    open({ customers: [{ ...CUSTOMERS[0], merchants: [], error: 'Not authorized for this customer — no' }] })
    expect(screen.getByText('Not authorized for this customer — no')).toBeInTheDocument()
  })
})

// ─── Through the page ───────────────────────────────────────────────

describe('selecting a customer scopes the page', () => {
  async function choose(name) {
    fireEvent.click(await screen.findByRole('button', { name: 'Customer' }))
    fireEvent.click(await screen.findByRole('menuitemradio', { name }))
  }

  it('reads the selected customer\'s data, under its org, and persists the choice', async () => {
    listCustomers.mockResolvedValue({ is_operator: false, customers: CUSTOMERS })
    window.sessionStorage.setItem('parleo.customerSelection',
      JSON.stringify({ orgId: 7, merchantSlug: 'wiggle-and-snug', prospectSlug: null }))
    render(<MerchantCommandCenter onNavigate={() => {}} />)

    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    expect(truesyncApi.getChannels).toHaveBeenLastCalledWith(expect.objectContaining({ customer: 7 }))
    expect(truesyncApi.getPublications).toHaveBeenLastCalledWith(expect.objectContaining({ customer: 7 }))
    // Verifications load in bulk, by merchant — not one call per cell.
    expect(fetchAllVerifications).toHaveBeenCalledWith(
      'wiggle-and-snug', expect.any(Array), expect.any(Array), expect.anything())

    await choose(/Acme Pets/)

    await waitFor(() => expect(screen.getByText('Trailmix Adult Dog Food')).toBeInTheDocument())
    expect(truesyncApi.getMerchantCatalog).toHaveBeenCalledWith('acme-pets', expect.objectContaining({ customer: 31 }))
    expect(truesyncApi.getChannels).toHaveBeenLastCalledWith(expect.objectContaining({ customer: 31 }))
    expect(screen.queryByText('Snug-Fit Diapers')).not.toBeInTheDocument()
    expect(getSelection()).toEqual({ orgId: 31, merchantSlug: 'acme-pets', prospectSlug: null })
  })

  it('a customer-hosted merchant: feed rows, every column not connected, nothing to publish', async () => {
    listCustomers.mockResolvedValue({ is_operator: true, customers: CUSTOMERS })
    render(<MerchantCommandCenter onNavigate={() => {}} />)   // first customer: Acme

    await waitFor(() => expect(screen.getByText('Trailmix Adult Dog Food')).toBeInTheDocument())
    expect(truesyncApi.getMerchantSchemaOrg).not.toHaveBeenCalled()
    expect(truesyncApi.getPublications).not.toHaveBeenCalled()

    const headers = screen.getAllByRole('columnheader').slice(2)
    expect(headers).toHaveLength(channels.length)
    for (const th of headers) expect(th).toHaveTextContent('not connected')
    expect(screen.getAllByText('not connected', { selector: '.mcc-cell-when' }))
      .toHaveLength(channels.length * ACME_CATALOG.listings.length)
    expect(screen.queryByText('never published')).not.toBeInTheDocument()

    expect(screen.getByText('2 variants')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /verify all/i })).not.toBeInTheDocument()
    // Re-entry, for operators: a new feed version, or the offers.
    expect(screen.getByRole('button', { name: 'Upload new feed' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit offers' })).toBeInTheDocument()
  })

  it('a customer-hosted merchant with no feed yet says so, not "no publications"', async () => {
    listCustomers.mockResolvedValue({ is_operator: true, customers: CUSTOMERS })
    const missing = Object.assign(new Error('merchant has no committed feed'), { status: 404 })
    truesyncApi.getMerchantCatalog.mockRejectedValue(missing)
    render(<MerchantCommandCenter onNavigate={() => {}} />)

    expect(await screen.findByText('No product feed yet')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('a stored selection this login cannot use is replaced, not sent on', async () => {
    window.sessionStorage.setItem('parleo.customerSelection',
      JSON.stringify({ orgId: 999, merchantSlug: 'someone-else', prospectSlug: null }))
    listCustomers.mockResolvedValue({ is_operator: false, customers: [CUSTOMERS[1]] })
    render(<MerchantCommandCenter onNavigate={() => {}} />)

    await waitFor(() => expect(screen.getByText('Snug-Fit Diapers')).toBeInTheDocument())
    expect(getSelection()).toEqual({ orgId: 7, merchantSlug: 'wiggle-and-snug', prospectSlug: null })
    for (const call of truesyncApi.getChannels.mock.calls) {
      expect(call[0].customer).toBe(7)
    }
  })

  it('a login with no customer says so, and an operator is offered New customer', async () => {
    listCustomers.mockResolvedValue({ is_operator: true, customers: [] })
    render(<MerchantCommandCenter onNavigate={() => {}} />)
    expect(await screen.findByText('No customer account is linked to your login')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'New customer' }))
    expect(await screen.findByRole('dialog', { name: 'New customer' })).toBeInTheDocument()
  })
})
