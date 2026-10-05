/**
 * The setup wizard against mocked writes: which call each step makes, with
 * what, and what the gate lets through. The feed preview is the 1B
 * validator's real output for an invented 10-SKU feed
 * (../__fixtures__/README.md) — 8 ready, 1 warning, 1 error, as the mock.
 */
import React from 'react'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import '@testing-library/jest-dom'

import CustomerSetupWizard, { stepsFor } from '../CustomerSetupWizard.jsx'
import { createCustomer, lookupDomain } from '../../../customersApi.js'
import { truesyncApi } from '../../../truesyncApi.js'
import PREVIEW from '../__fixtures__/feed-preview-acme-pets.json'

vi.mock('../../../customersApi.js', () => ({ createCustomer: vi.fn(), lookupDomain: vi.fn() }))
vi.mock('../../../truesyncApi.js', () => ({
  truesyncApi: {
    validateFeed: vi.fn(), commitFeed: vi.fn(), putOwnedIncentives: vi.fn(),
    getOwnedIncentives: vi.fn(), downloadTemplate: vi.fn(), getProvenance: vi.fn(),
  },
}))

const CREATED = {
  org_id: 31, org_name: 'Acme Pets', tenant_slug: 'acme-pets', created_account: true,
  merchant: { slug: 'acme-pets', name: 'Acme Pets', domain: 'acme-pets.test',
              kind: 'seller', hosting: 'external', has_record: false },
  retailers: { domains: ['acme-pets.test'] },
}
const CUSTOMERS = [{ org_id: 7, name: 'Wiggle & Snug', merchants: [] }]

// The same feed with its one error row removed: a clean upload.
const CLEAN = {
  ...PREVIEW,
  rows: PREVIEW.rows.filter((r) => r.status !== 'error'),
  summary: { ...PREVIEW.summary, rows: 9, error: 0 },
}

beforeEach(() => {
  vi.clearAllMocks()
  createCustomer.mockResolvedValue(CREATED)
  lookupDomain.mockResolvedValue({ status: 'unknown', domain: 'acme-pets.test' })
  truesyncApi.getProvenance.mockResolvedValue(null)
  truesyncApi.validateFeed.mockResolvedValue(PREVIEW)
  truesyncApi.commitFeed.mockResolvedValue({ version_number: 1 })
  truesyncApi.putOwnedIncentives.mockResolvedValue({ incentives: [] })
  truesyncApi.getOwnedIncentives.mockResolvedValue({ incentives: [] })
})

function renderWizard(props = {}) {
  const onDone = vi.fn()
  render(
    <CustomerSetupWizard open customers={CUSTOMERS} onClose={vi.fn()} onDone={onDone} {...props} />,
  )
  return { onDone }
}

const type = (label, value) => fireEvent.change(screen.getByLabelText(label), { target: { value } })
const next = () => fireEvent.click(screen.getByRole('button', { name: /^(Continue|Create customer|Save)$/ }))
const stepNames = () => [...document.querySelectorAll('.csw .step')].map((s) => s.textContent.replace(/^\d/, ''))

async function fillStep1({ hosting } = {}) {
  type('Account name', 'Acme Pets')
  type('Customer name', 'Acme Pets')
  type('Domain', 'acme-pets.test')
  fireEvent.blur(screen.getByLabelText('Domain'))
  if (hosting === 'parleo') fireEvent.click(screen.getByRole('button', { name: 'Parleo hosts them' }))
}

async function uploadFeed() {
  const file = new File(['gtin'], 'acme-pets-10-skus.csv', { type: 'text/csv' })
  fireEvent.change(screen.getByLabelText('Feed file'), { target: { files: [file] } })
  await screen.findByTestId('feed-preview')
  return file
}

describe('step 1 — account & customer', () => {
  it('writes the account, the merchant with both axes, and its retailer list', async () => {
    renderWizard()
    expect(stepNames()).toEqual(['Account & customer', 'Product feed', 'Customer-owned offers', 'Review'])
    await fillStep1()
    expect(screen.getByLabelText('Retailer 1')).toHaveValue('acme-pets.test')

    next()

    await screen.findByText('Drop a CSV or XLSX here, or choose a file')
    expect(createCustomer).toHaveBeenCalledWith({
      account: { name: 'Acme Pets' },
      merchant: { name: 'Acme Pets', domain: 'acme-pets.test', kind: 'seller', hosting: 'external' },
      retailers: ['acme-pets.test'],
      claim: false,
    })
  })

  it('adds to an existing account by id, creating no new one', async () => {
    renderWizard()
    fireEvent.change(screen.getByLabelText('Account choice'), { target: { value: '7' } })
    type('Customer name', 'Acme Pets')
    type('Domain', 'acme-pets.test')
    next()
    await waitFor(() => expect(createCustomer).toHaveBeenCalled())
    expect(createCustomer.mock.calls[0][0].account).toEqual({ org_id: 7 })
  })

  it('says the mock\'s brand-mode copy when the customer does not sell', () => {
    renderWizard()
    fireEvent.click(screen.getByRole('button', { name: 'No — a brand sold through retailers' }))
    expect(screen.getByText('Retailers that carry these products')).toBeInTheDocument()
    expect(screen.getByText(/AI-quoted prices will be checked against the retailer page/)).toBeInTheDocument()
    expect(screen.getByText(/reported as a fabricated claim/)).toBeInTheDocument()
  })

  it('a customer refused after its new account was made retries under that account', async () => {
    const err = Object.assign(new Error("merchant slug 'acme-pets' is not available"), { orgId: 44 })
    createCustomer.mockRejectedValueOnce(err)
    renderWizard({ customers: [...CUSTOMERS, { org_id: 44, name: 'Acme Pets', merchants: [] }] })
    await fillStep1()
    next()

    expect(await screen.findByRole('alert')).toHaveTextContent('The account was created, but the customer was not')
    expect(screen.getByLabelText('Account choice')).toHaveValue('44')
    next()
    await waitFor(() => expect(createCustomer).toHaveBeenCalledTimes(2))
    expect(createCustomer.mock.calls[1][0].account).toEqual({ org_id: 44 })
  })

  it('locks step 1 once it exists', async () => {
    renderWizard()
    await fillStep1()
    next()
    await screen.findByTestId('feed-drop')
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByLabelText('Customer name')).toBeDisabled()
    expect(screen.getByText(/Continue to load its products/)).toBeInTheDocument()
  })
})

describe('step 2 — the 1B feed: validate, preview, gate', () => {
  async function toFeed() {
    const utils = renderWizard()
    await fillStep1()
    next()
    await screen.findByTestId('feed-drop')
    return utils
  }

  it('validates under the new customer, and previews exactly what the validator said', async () => {
    await toFeed()
    const file = await uploadFeed()

    expect(truesyncApi.validateFeed).toHaveBeenCalledWith('acme-pets', [file], { customer: 31 })
    expect(screen.getByText('acme-pets-10-skus.csv · 10 rows')).toBeInTheDocument()
    expect(screen.getByText('8 ready')).toBeInTheDocument()
    expect(screen.getByText('1 warning')).toBeInTheDocument()
    expect(screen.getByText('1 error')).toBeInTheDocument()

    const rows = screen.getAllByRole('row').slice(1)
    expect(rows).toHaveLength(10)
    const bad = rows.find((r) => r.classList.contains('bad'))
    expect(within(bad).getByText('error')).toBeInTheDocument()
    expect(bad).toHaveTextContent(/check digit/)
    const warn = rows.find((r) => r.classList.contains('warn'))
    expect(warn).toHaveTextContent(/answered 404/)
  })

  it('filters by status with the chips', async () => {
    await toFeed()
    await uploadFeed()
    fireEvent.click(screen.getByRole('button', { name: 'Errors' }))
    expect(screen.getAllByRole('row').slice(1)).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Warnings' }))
    expect(screen.getAllByRole('row').slice(1)).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'All' }))
    expect(screen.getAllByRole('row').slice(1)).toHaveLength(10)
  })

  it('errors block until the operator chooses the valid rows; warnings pass', async () => {
    await toFeed()
    await uploadFeed()
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
    expect(screen.getByText(/1 row has an error/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'continue with the 9 valid rows' }))

    expect(screen.getByRole('button', { name: 'Continue' })).not.toBeDisabled()
    expect(screen.getByText(/9 products will be saved\. 1 row left out\. 1 warning kept/)).toBeInTheDocument()
  })

  it('commits all_valid_rows after "continue with the valid rows"', async () => {
    const { onDone } = await toFeed()
    await uploadFeed()
    fireEvent.click(screen.getByRole('button', { name: 'continue with the 9 valid rows' }))
    next()                                     // -> offers
    type('Offer 1 name', 'Vital Care Core')
    next()                                     // -> review
    expect(screen.getByText(
      'acme-pets-10-skus.csv · 9 products will be saved · 1 row left out (errors) · 1 warning kept',
    )).toBeInTheDocument()

    next()                                     // Create customer

    await waitFor(() => expect(onDone).toHaveBeenCalledWith({ orgId: 31, merchantSlug: 'acme-pets' }))
    expect(truesyncApi.commitFeed)
      .toHaveBeenCalledWith('acme-pets', 'upl_fixture_acme_1', 'all_valid_rows', { customer: 31 })
    expect(truesyncApi.putOwnedIncentives).toHaveBeenCalledWith('acme-pets', [
      { mechanic: 'loyalty_program', name: 'Vital Care Core', applies_to: 'all' },
    ], { customer: 31 })
  })

  it('commits require_clean when nothing is in error, warnings and all', async () => {
    truesyncApi.validateFeed.mockResolvedValue(CLEAN)
    const { onDone } = await toFeed()
    await uploadFeed()
    expect(screen.getByRole('button', { name: 'Continue' })).not.toBeDisabled()
    next(); next(); next()
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(truesyncApi.commitFeed.mock.calls[0][2]).toBe('require_clean')
  })
})

describe('a Parleo-hosted customer', () => {
  it('has no feed step, and nothing is validated or committed', async () => {
    const { onDone } = renderWizard()
    await fillStep1({ hosting: 'parleo' })
    expect(stepNames()).toEqual(['Account & customer', 'Customer-owned offers', 'Review'])
    createCustomer.mockResolvedValue({ ...CREATED, merchant: { ...CREATED.merchant, hosting: 'parleo' } })

    next()
    await screen.findByText('Programs and offers this customer owns')
    next(); next()

    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(truesyncApi.validateFeed).not.toHaveBeenCalled()
    expect(truesyncApi.commitFeed).not.toHaveBeenCalled()
    expect(createCustomer.mock.calls[0][0].merchant.hosting).toBe('parleo')
  })

  it('stepsFor says the same', () => {
    expect(stepsFor('new', 'parleo')).toEqual(['account', 'offers', 'review'])
    expect(stepsFor('new', 'external')).toEqual(['account', 'feed', 'offers', 'review'])
  })
})

describe('step 3 — owned offers', () => {
  it('an offer the grammar cannot read stops Continue, on that row', async () => {
    renderWizard({ mode: 'offers', existing: { orgId: 31, orgName: 'Acme Pets', merchant: CREATED.merchant } })
    await waitFor(() => expect(truesyncApi.getOwnedIncentives).toHaveBeenCalled())
    fireEvent.change(screen.getByLabelText('Offer 1 kind'), { target: { value: 'subscription_discount' } })
    type('Offer 1 name', 'Repeat Delivery')
    type('Offer 1 value', '35% off first, 5% ongoing')
    next()
    expect(await screen.findByRole('alert')).toHaveTextContent(/two-part rule is two offers/)
    expect(screen.getByText('Programs and offers this customer owns')).toBeInTheDocument()
  })
})

describe('re-entry from the Command Center', () => {
  const existing = { orgId: 31, orgName: 'Acme Pets', merchant: { ...CREATED.merchant, has_record: true } }

  it('a new feed version: feed and review only, no account writes, offers untouched', async () => {
    const { onDone } = renderWizard({ mode: 'feed', existing })
    expect(stepNames()).toEqual(['Product feed', 'Review'])
    await uploadFeed()
    fireEvent.click(screen.getByRole('button', { name: 'continue with the 9 valid rows' }))
    next(); next()
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(createCustomer).not.toHaveBeenCalled()
    expect(truesyncApi.commitFeed).toHaveBeenCalled()
    expect(truesyncApi.putOwnedIncentives).not.toHaveBeenCalled()
  })

  it('editing offers loads the stored ones and replaces them', async () => {
    truesyncApi.getOwnedIncentives.mockResolvedValue({ incentives: [
      { mechanic: 'coupon_code', name: 'WELCOME10', code: 'WELCOME10', discount_percent: '10', applies_to: 'all' },
    ] })
    const { onDone } = renderWizard({ mode: 'offers', existing })
    await waitFor(() => expect(screen.getByLabelText('Offer 1 name')).toHaveValue('WELCOME10'))
    expect(screen.getByLabelText('Offer 1 value')).toHaveValue('10%')
    next(); next()
    await waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(truesyncApi.putOwnedIncentives).toHaveBeenCalledWith('acme-pets', [
      { mechanic: 'coupon_code', name: 'WELCOME10', code: 'WELCOME10', applies_to: 'all', discount_percent: '10' },
    ], { customer: 31 })
  })
})

// ─── Step 2A-0: the domain is looked up, and a known one is claimed ──────

describe('step 1 looks the domain up — claim, not create', () => {
  const UNCLAIMED = {
    status: 'unclaimed', domain: 'petco.com',
    merchant: { slug: 'petco', display_name: 'Petco', domain: 'petco.com',
                scraped_deals: 3, scraped_listings: 1, last_seen_at: '2026-10-04T12:00:00Z' },
  }

  async function enterPetco() {
    type('Account name', 'Petco')
    type('Customer name', 'Petco')
    type('Domain', 'https://www.petco.com/')
  }

  it('unclaimed: says what is on file, and Continue becomes Claim and continue', async () => {
    lookupDomain.mockResolvedValue(UNCLAIMED)
    createCustomer.mockResolvedValue({
      ...CREATED, org_name: 'Petco', merchant_action: 'claimed',
      merchant: { ...CREATED.merchant, slug: 'petco', name: 'Petco', domain: 'petco.com' },
      provenance: { deals: { scrape: 3, published: 0 }, listings: { scrape: 1, published: 0 } },
    })
    renderWizard()
    await enterPetco()

    const card = await screen.findByTestId('claim-card')
    expect(card).toHaveTextContent('petco.com is already known')
    expect(card).toHaveTextContent('3 scraped deals on file, 1 listing, last seen Oct 4, 2026')
    expect(lookupDomain).toHaveBeenLastCalledWith('petco.com', expect.objectContaining({ orgId: null }))

    fireEvent.click(screen.getByRole('button', { name: 'Claim and continue' }))

    await screen.findByTestId('feed-drop')
    expect(createCustomer.mock.calls[0][0].claim).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))
    expect(screen.getByText(/It brought 3 scraped deals and 1 scraped listing with it/)).toBeInTheDocument()
  })

  it('mine: says so and continues', async () => {
    lookupDomain.mockResolvedValue({ status: 'mine', domain: 'petco.com', slug: 'petco' })
    renderWizard()
    fireEvent.change(screen.getByLabelText('Account choice'), { target: { value: '7' } })
    type('Customer name', 'Petco')
    type('Domain', 'petco.com')

    expect(await screen.findByTestId('claim-card')).toHaveTextContent("petco.com is already this account's")
    await waitFor(() => expect(lookupDomain).toHaveBeenLastCalledWith('petco.com', expect.objectContaining({ orgId: 7 })))
    expect(screen.getByRole('button', { name: 'Continue' })).not.toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Claim and continue' })).not.toBeInTheDocument()
  })

  it('unavailable: says only that, and Continue is off', async () => {
    lookupDomain.mockResolvedValue({ status: 'unavailable', domain: 'petco.com' })
    renderWizard()
    await enterPetco()

    const card = await screen.findByTestId('claim-card')
    expect(card.textContent).toBe('petco.com is not available')
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled()
  })

  it('unknown: no card, and the customer is created', async () => {
    lookupDomain.mockResolvedValue({ status: 'unknown', domain: 'petco.com' })
    renderWizard()
    await enterPetco()
    await waitFor(() => expect(lookupDomain).toHaveBeenCalled())
    expect(screen.queryByTestId('claim-card')).not.toBeInTheDocument()

    next()
    await waitFor(() => expect(createCustomer).toHaveBeenCalled())
    expect(createCustomer.mock.calls[0][0].claim).toBe(false)
  })

  it('a retry after a failure goes again with the same request, and the server reuses the account', async () => {
    lookupDomain.mockResolvedValue({ status: 'unknown', domain: 'petco.com' })
    createCustomer.mockRejectedValueOnce(new Error('This app could not be reached'))
    renderWizard()
    await enterPetco()
    await waitFor(() => expect(lookupDomain).toHaveBeenCalled())

    next()
    expect(await screen.findByRole('alert')).toHaveTextContent('This app could not be reached')
    next()

    await screen.findByTestId('feed-drop')
    expect(createCustomer).toHaveBeenCalledTimes(2)
    expect(createCustomer.mock.calls[1][0]).toEqual(createCustomer.mock.calls[0][0])
    expect(createCustomer.mock.calls[1][0].account).toEqual({ name: 'Petco' })
  })
})

describe('re-entry shows what the merchant holds, by provenance', () => {
  it('lists scraped and published rows, and when it was claimed', async () => {
    truesyncApi.getProvenance.mockResolvedValue({
      merchant_source: 'scrape',
      deals: { scrape: 3, published: 1 }, listings: { scrape: 1, published: 9 },
      journal: [{ action: 'claim', at: '2026-10-05T09:00:00Z' }],
    })
    renderWizard({ mode: 'feed', existing: { orgId: 31, orgName: 'Petco', merchant: { ...CREATED.merchant, slug: 'petco' } } })

    const note = await screen.findByTestId('provenance')
    expect(truesyncApi.getProvenance).toHaveBeenCalledWith('petco', { customer: 31 })
    expect(note).toHaveTextContent(
      '3 scraped deals and 1 scraped listing (public), 1 published deal and 9 published listings')
    expect(note).toHaveTextContent('Claimed Oct 5, 2026')
  })
})
